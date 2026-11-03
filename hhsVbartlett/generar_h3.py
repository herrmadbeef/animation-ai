"""Render the HHS vs Bartlett acts with MiniMax H3 (Ref2VA) through the ComfyUI API, then join them.

An act (or the whole spec) may set "first_frame" and/or "last_frame" instead of "refs":
those acts use the FL2VA model to pin the first/last frame (padded with black to the video aspect).

Run with ComfyUI's own Python (it already has PyAV):
  D:\\Comfy-Desktop\\ComfyUI-Installs\\ComfyUI\\standalone-env\\python.exe generar_h3.py
  ... generar_h3.py --acts act2 --seed 123      # re-render a single act
  ... generar_h3.py --join-only                  # just rebuild the final video
"""
import argparse
import json
import random
import tempfile
import time
import urllib.request
import uuid
from fractions import Fraction
from pathlib import Path

import av
from PIL import Image

HERE = Path(__file__).resolve().parent
OUTPUT_ROOT = Path(r"D:\Comfy-Desktop\ComfyUI-Shared\output")


def api(server, path, data=None, headers=None):
    req = urllib.request.Request(server + path, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or b"null")


def upload_image(server, path):
    boundary = uuid.uuid4().hex
    body = b"".join([
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n".encode(),
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{path.name}\"\r\n"
        f"Content-Type: image/png\r\n\r\n".encode(),
        path.read_bytes(),
        f"\r\n--{boundary}--\r\n".encode(),
    ])
    return api(server, "/upload/image", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})["name"]


def upload_padded(server, path, width, height):
    """Pad the image with black to the video aspect (ComfyUI would crop it) and upload it."""
    img = Image.open(path).convert("RGB")
    w, h = img.size
    if w * height > h * width:
        canvas = Image.new("RGB", (w, round(w * height / width)))
    else:
        canvas = Image.new("RGB", (round(h * width / height), h))
    canvas.paste(img, ((canvas.width - w) // 2, (canvas.height - h) // 2))
    with tempfile.TemporaryDirectory() as tmp:
        padded = Path(tmp) / f"{path.stem}_{width}x{height}.png"
        canvas.save(padded)
        return upload_image(server, padded)


def frame_count(seconds):
    # H3 needs 17k+5 frames at 24 fps (same expression as the official template)
    n = max(5, round(seconds * 24))
    return n + (5 - n % 17) % 17


def build_graph(prompt, refs, width, height, length, seed, steps, turbo, prefix, keyframes=None):
    g = {
        "unet": {"class_type": "UNETLoader", "inputs": {
            "unet_name": f"minimax_h3_{'fl2va' if keyframes else 'ref2va'}_pruned_int8_convrot.safetensors",
            "weight_dtype": "default"}},
        "clip": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", "type": "minimax", "device": "default"}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_video_vae_int8_convrot.safetensors"}},
        "avae": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_audio_vae_fp32.safetensors"}},
        "cond": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {
            "clip": ["clip", 0], "vae": ["vae", 0], "audio_vae": ["avae", 0], "prompt": prompt,
            "width": width, "height": height, "length": length, "ref_image_size": "match"}},
        "noise": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "sampler": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}},
        "sched": {"class_type": "BasicScheduler", "inputs": {
            "model": ["unet", 0], "scheduler": "simple", "steps": steps, "denoise": 1.0}},
        "guider": {"class_type": "BasicGuider", "inputs": {"model": ["model", 0], "conditioning": ["cond", 0]}},
        "sample": {"class_type": "SamplerCustomAdvanced", "inputs": {
            "noise": ["noise", 0], "guider": ["guider", 0], "sampler": ["sampler", 0],
            "sigmas": ["sched", 0], "latent_image": ["cond", 1]}},
        "dec": {"class_type": "VAEDecode", "inputs": {"samples": ["sample", 0], "vae": ["vae", 0]}},
        "adec": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["sample", 0], "vae": ["avae", 0]}},
        "video": {"class_type": "CreateVideo", "inputs": {
            "images": ["dec", 0], "audio": ["adec", 0], "fps": 24.0, "bit_depth": 8,
            "color_space": "sRGB", "codec": "none"}},
        "save": {"class_type": "SaveVideo", "inputs": {
            "video": ["video", 0], "filename_prefix": prefix, "format": "auto", "codec": "auto"}},
    }
    if turbo:
        lora = ("minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors" if keyframes
                else "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors")
        g["model"] = {"class_type": "LoraLoaderModelOnly", "inputs": {
            "model": ["unet", 0], "lora_name": lora, "strength_model": 1.0}}
    else:
        g["guider"]["inputs"]["model"] = ["unet", 0]
    if keyframes:
        # FL2VA: same sampler chain, keyframe conditioning instead of reference images
        g["cond"] = {"class_type": "MiniMaxH3ImageToVideo", "inputs": {
            "clip": ["clip", 0], "vae": ["vae", 0], "prompt": prompt,
            "width": width, "height": height, "length": length}}
        for key, name in keyframes.items():
            g[key] = {"class_type": "LoadImage", "inputs": {"image": name}}
            g["cond"]["inputs"][key] = [key, 0]
        return g
    for i, name in enumerate(refs):
        g[f"ref{i}"] = {"class_type": "LoadImage", "inputs": {"image": name}}
        g["cond"]["inputs"][f"ref_images.ref_image_{i}"] = [f"ref{i}", 0]
    return g


def render(server, graph):
    client_id = uuid.uuid4().hex
    pid = api(server, "/prompt", json.dumps({"prompt": graph, "client_id": client_id}).encode(),
              {"Content-Type": "application/json"})["prompt_id"]
    start = time.time()
    while True:
        time.sleep(5)
        hist = api(server, f"/history/{pid}").get(pid)
        if hist:
            status = hist.get("status", {})
            if status.get("status_str") == "error":
                raise RuntimeError(json.dumps(status.get("messages"), ensure_ascii=False)[:2000])
            for out in hist["outputs"].values():
                for item in out.get("images", []) + out.get("videos", []):
                    if item.get("filename", "").endswith(".mp4"):
                        print(f"  done in {time.time() - start:.0f}s")
                        return OUTPUT_ROOT / item.get("subfolder", "") / item["filename"]
            raise RuntimeError(f"no video in outputs: {hist['outputs']}")
        print(f"  ... {time.time() - start:.0f}s", end="\r")


def join(clips, dest):
    """Re-encode the act clips into one H.264/AAC mp4."""
    with av.open(str(dest), "w") as out:
        vs = as_ = None
        resampler = av.AudioResampler(format="fltp", layout="stereo", rate=48000)
        v_pts = a_pts = 0
        for clip in clips:
            with av.open(str(clip)) as inp:
                src_v = inp.streams.video[0]
                if vs is None:
                    vs = out.add_stream("libx264", rate=Fraction(24))
                    vs.width, vs.height, vs.pix_fmt = src_v.width, src_v.height, "yuv420p"
                    vs.options = {"crf": "18"}
                    as_ = out.add_stream("aac", rate=48000, layout="stereo")
                streams = [src_v] + list(inp.streams.audio[:1])
                for frame in inp.decode(*streams):
                    if isinstance(frame, av.VideoFrame):
                        f = frame.reformat(vs.width, vs.height, "yuv420p")
                        f.pts, f.time_base = v_pts, Fraction(1, 24)
                        v_pts += 1
                        out.mux(vs.encode(f))
                    else:
                        for rf in resampler.resample(frame):
                            rf.pts, rf.time_base = a_pts, Fraction(1, 48000)
                            a_pts += rf.samples
                            out.mux(as_.encode(rf))
            # keep audio aligned with video at every act boundary
            a_pts = max(a_pts, v_pts * 2000)
        out.mux(vs.encode())
        out.mux(as_.encode())


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--server", default="http://127.0.0.1:8000")
    p.add_argument("--prompts", default=str(HERE / "HHSvBartlett_h3_prompts.json"))
    p.add_argument("--acts", nargs="*", help="act names to render (default: all)")
    p.add_argument("--width", type=int, default=736)
    p.add_argument("--height", type=int, default=416)
    p.add_argument("--seed", type=int)
    p.add_argument("--no-turbo", action="store_true", help="20 steps without the 4-step LoRA (slower, sometimes better)")
    p.add_argument("--join-only", action="store_true")
    args = p.parse_args()

    spec = json.loads(Path(args.prompts).read_text(encoding="utf-8"))
    # an "output" name keeps each script's renders and final video separate
    name = spec.get("output", "HHSvBartlett_H3")
    out_dir = HERE / "renders" / name if "output" in spec else HERE / "renders"
    out_dir.mkdir(parents=True, exist_ok=True)

    if not args.join_only:
        refs = [upload_image(args.server, HERE / ref) for ref in spec.get("refs", [])]
        for act in spec["acts"]:
            if args.acts and act["name"] not in args.acts:
                continue
            keyframes = {}
            for key in ("first_frame", "last_frame"):
                path = act.get(key, spec.get(key))
                if path:
                    keyframes[key] = upload_padded(args.server, HERE / path, args.width, args.height)
            seed = args.seed if args.seed is not None else random.randrange(2**48)
            # the FL2VA turbo LoRA runs 6 steps in the official template, the Ref2VA one 4
            steps = 20 if args.no_turbo else (6 if keyframes else 4)
            print(f"[{act['name']}] {act['seconds']}s, {args.width}x{args.height}, {steps} steps, seed {seed}")
            graph = build_graph(spec["style"] + "\n" + act["prompt"], refs, args.width, args.height,
                                frame_count(act["seconds"]), seed, steps, not args.no_turbo,
                                f"video/{name}_{act['name']}", keyframes)
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
