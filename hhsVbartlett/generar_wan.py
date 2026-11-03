"""Render acts with Wan 2.2 14B through the ComfyUI API, then join them.

Uses the same prompts JSON as generar_h3.py ("output", "style", "acts"), minus "refs".
An act (or the whole spec) may set "start_image" and/or "end_image" to pin the first/last
frame; those acts use the I2V models (first-last-frame), the rest use T2V.
Images are padded with black to the video aspect, since ComfyUI center-crops them.
Wan has no audio, so the final video is silent.

Models (the ComfyUI "Wan 2.2 14B Text to Video" / "Image to Video" templates download them):
  diffusion_models/wan2.2_{t2v,i2v}_{high,low}_noise_14B_fp8_scaled.safetensors
  text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors
  vae/wan_2.1_vae.safetensors
  loras/wan2.2_t2v_lightx2v_4steps_lora_v1.1_{high,low}_noise.safetensors   (turbo, default)
  loras/wan2.2_i2v_lightx2v_4steps_lora_v1_{high,low}_noise.safetensors

Run with ComfyUI's own Python (it already has PyAV):
  D:\\Comfy-Desktop\\ComfyUI-Installs\\ComfyUI\\standalone-env\\python.exe generar_wan.py --prompts x.json
  ... generar_wan.py --prompts x.json --acts act2 --seed 123   # re-render a single act
  ... generar_wan.py --prompts x.json --no-turbo                # 20 steps, cfg 3.5 (slower)
  ... generar_wan.py --prompts x.json --join-only               # just rebuild the final video
"""
import argparse
import json
import random
from fractions import Fraction
from pathlib import Path

import av

from generar_h3 import render, upload_padded

HERE = Path(__file__).resolve().parent
FPS = 16

# default negative prompt from the official Wan 2.2 template
NEGATIVE = ("色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，"
            "JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，"
            "形态畸形的肢体，手指融合，静止不动的画面，杂乱的背景，三条腿，背景人多，倒着走")


def frame_count(seconds):
    # Wan needs 4k+1 frames
    n = max(5, round(seconds * FPS))
    return n + (1 - n % 4) % 4


def build_graph(prompt, negative, width, height, length, seed, turbo, prefix, start_image=None, end_image=None):
    steps, cfg = (4, 1.0) if turbo else (20, 3.5)
    i2v = bool(start_image or end_image)
    kind = "i2v" if i2v else "t2v"
    g = {
        "unet_high": {"class_type": "UNETLoader", "inputs": {
            "unet_name": f"wan2.2_{kind}_high_noise_14B_fp8_scaled.safetensors", "weight_dtype": "default"}},
        "unet_low": {"class_type": "UNETLoader", "inputs": {
            "unet_name": f"wan2.2_{kind}_low_noise_14B_fp8_scaled.safetensors", "weight_dtype": "default"}},
        "clip": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "type": "wan", "device": "default"}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": "wan_2.1_vae.safetensors"}},
        "pos": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": prompt}},
        "neg": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": negative}},
        "latent": {"class_type": "EmptyHunyuanLatentVideo", "inputs": {
            "width": width, "height": height, "length": length, "batch_size": 1}},
        "shift_high": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["unet_high", 0], "shift": 8.0}},
        "shift_low": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["unet_low", 0], "shift": 8.0}},
        # high-noise expert does the first half of the steps, low-noise expert finishes
        "sample_high": {"class_type": "KSamplerAdvanced", "inputs": {
            "model": ["shift_high", 0], "positive": ["pos", 0], "negative": ["neg", 0],
            "latent_image": ["latent", 0], "add_noise": "enable", "noise_seed": seed,
            "steps": steps, "cfg": cfg, "sampler_name": "euler", "scheduler": "simple",
            "start_at_step": 0, "end_at_step": steps // 2, "return_with_leftover_noise": "enable"}},
        "sample_low": {"class_type": "KSamplerAdvanced", "inputs": {
            "model": ["shift_low", 0], "positive": ["pos", 0], "negative": ["neg", 0],
            "latent_image": ["sample_high", 0], "add_noise": "disable", "noise_seed": 0,
            "steps": steps, "cfg": cfg, "sampler_name": "euler", "scheduler": "simple",
            "start_at_step": steps // 2, "end_at_step": 10000, "return_with_leftover_noise": "disable"}},
        "dec": {"class_type": "VAEDecode", "inputs": {"samples": ["sample_low", 0], "vae": ["vae", 0]}},
        "video": {"class_type": "CreateVideo", "inputs": {"images": ["dec", 0], "fps": float(FPS)}},
        "save": {"class_type": "SaveVideo", "inputs": {
            "video": ["video", 0], "filename_prefix": prefix, "format": "auto", "codec": "auto"}},
    }
    if i2v:
        # the first-last-frame node replaces the empty latent and wraps the conditioning
        g["latent"] = {"class_type": "WanFirstLastFrameToVideo", "inputs": {
            "positive": ["pos", 0], "negative": ["neg", 0], "vae": ["vae", 0],
            "width": width, "height": height, "length": length, "batch_size": 1}}
        for key, name in (("start_image", start_image), ("end_image", end_image)):
            if name:
                g[key] = {"class_type": "LoadImage", "inputs": {"image": name}}
                g["latent"]["inputs"][key] = [key, 0]
        for stage in ("high", "low"):
            g[f"sample_{stage}"]["inputs"]["positive"] = ["latent", 0]
            g[f"sample_{stage}"]["inputs"]["negative"] = ["latent", 1]
        g["sample_high"]["inputs"]["latent_image"] = ["latent", 2]
    if turbo:
        lora_version = "v1" if i2v else "v1.1"
        for stage in ("high", "low"):
            g[f"lora_{stage}"] = {"class_type": "LoraLoaderModelOnly", "inputs": {
                "model": [f"unet_{stage}", 0],
                "lora_name": f"wan2.2_{kind}_lightx2v_4steps_lora_{lora_version}_{stage}_noise.safetensors",
                "strength_model": 1.0}}
            g[f"shift_{stage}"]["inputs"]["model"] = [f"lora_{stage}", 0]
    return g


def join(clips, dest):
    """Re-encode the act clips into one silent H.264 mp4."""
    with av.open(str(dest), "w") as out:
        vs = None
        pts = 0
        for clip in clips:
            with av.open(str(clip)) as inp:
                src_v = inp.streams.video[0]
                if vs is None:
                    vs = out.add_stream("libx264", rate=Fraction(FPS))
                    vs.width, vs.height, vs.pix_fmt = src_v.width, src_v.height, "yuv420p"
                    vs.options = {"crf": "18"}
                for frame in inp.decode(src_v):
                    f = frame.reformat(vs.width, vs.height, "yuv420p")
                    f.pts, f.time_base = pts, Fraction(1, FPS)
                    pts += 1
                    out.mux(vs.encode(f))
        out.mux(vs.encode())


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--server", default="http://127.0.0.1:8188")
    p.add_argument("--prompts", required=True)
    p.add_argument("--acts", nargs="*", help="act names to render (default: all)")
    p.add_argument("--width", type=int, default=832)
    p.add_argument("--height", type=int, default=480)
    p.add_argument("--seed", type=int)
    p.add_argument("--no-turbo", action="store_true", help="20 steps without the lightx2v LoRAs (slower, sometimes better)")
    p.add_argument("--join-only", action="store_true")
    args = p.parse_args()

    spec = json.loads(Path(args.prompts).read_text(encoding="utf-8"))
    name = spec["output"]
    negative = spec.get("negative", NEGATIVE)
    out_dir = HERE / "renders" / name
    out_dir.mkdir(parents=True, exist_ok=True)

    if not args.join_only:
        for act in spec["acts"]:
            if args.acts and act["name"] not in args.acts:
                continue
            seed = args.seed if args.seed is not None else random.randrange(2**48)
            length = frame_count(act["seconds"])
            print(f"[{act['name']}] {act['seconds']}s ({length} frames), {args.width}x{args.height}, "
                  f"{'20' if args.no_turbo else '4'} steps, seed {seed}")
            prompt = (spec.get("style", "") + "\n" + act["prompt"]).strip()
            frames = {}
            for key in ("start_image", "end_image"):
                path = act.get(key, spec.get(key))
                if path:
                    frames[key] = upload_padded(args.server, HERE / path, args.width, args.height)
            graph = build_graph(prompt, negative, args.width, args.height, length, seed,
                                not args.no_turbo, f"video/{name}_{act['name']}", **frames)
            src = render(args.server, graph)
            dest = out_dir / f"{act['name']}.mp4"
            dest.write_bytes(src.read_bytes())
            print(f"  -> {dest}")

    clips = [out_dir / f"{a['name']}.mp4" for a in spec["acts"]]
    missing = [c.name for c in clips if not c.exists()]
    if missing:
        print("not joining yet, missing:", ", ".join(missing))
        return
    final = HERE / f"{name}.mp4"
    join(clips, final)
    print(f"final video: {final}")


if __name__ == "__main__":
    main()
