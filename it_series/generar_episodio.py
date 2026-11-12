"""Render an "IT in 30 Seconds" episode JSON with MiniMax H3 through the ComfyUI API.

Each shot is rendered with its narration line and the music cue as H3 audio. Every character named
in a shot's prompt gets its reference image from characters/<Name>.png as <Picture N>, so the cast
looks the same across shots, episodes and languages (--make-character renders a missing one).
Shots are stretched past their planned duration when the narration needs more time, the on-screen
text is drawn on afterwards (crisp lettering, H3 is told to render none) and everything is joined
and scaled to the episode resolution.

Output: output/epNN/<episode>.mp4 with the shots in output/epNN/shots/;
other languages ("language" in the JSON) go to output/epNN/<lang>/.

Run with ComfyUI's own Python (it already has PyAV and Pillow):
  D:\\Comfy-Desktop\\ComfyUI-Installs\\ComfyUI\\standalone-env\\python.exe generar_episodio.py ep01-ip-address.json
  ... generar_episodio.py ep02-dns.json --make-character Alex          # create characters/Alex.png
  ... generar_episodio.py ep01-ip-address.json --shots 3 --seed 123   # re-render a single shot
  ... generar_episodio.py ep01-ip-address.json --join-only             # just rebuild the final video
"""
import argparse
import json
import os
import random
import sys
import textwrap
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
CHARACTERS = HERE / "characters"
# smoke tests point this elsewhere so they don't mix with real episodes
OUTPUT = Path(os.environ.get("IT_SERIES_OUTPUT", HERE / "output"))
sys.path.insert(0, str(HERE.parent / "hhsVbartlett"))
from generar_h3 import build_graph, frame_count, render, upload_image  # noqa: E402

FPS = 24
RATE = 48000
FONT = "C:/Windows/Fonts/segoeuib.ttf"
WORDS_PER_SEC = 2.5   # relaxed narration pace
TAIL_SEC = 1.0        # breathing room after the last word
MAX_EXTRA_SEC = 10    # episodes may run this much past total_duration_sec


def shot_seconds(shot):
    """Shot length: its planned duration, stretched when the narration needs more time."""
    words = len(shot.get("voiceover", "").split())
    return max(shot["duration_sec"], round(words / WORDS_PER_SEC + TAIL_SEC, 1))


def shot_cast(ep, shot):
    """Characters that appear in the shot (named in its prompt), in the episode's order."""
    return [name for name in ep["characters"] if name in shot["prompt"]]


def shot_prompt(ep, shot, ref_names):
    parts = []
    for i, name in enumerate(ref_names, 1):
        parts.append(f"<Picture {i}> is {name}: {ep['characters'][name]}. Use <Picture {i}> only for "
                     f"{name}'s look; do not copy its background, setting or pose, the setting is described below.")
    parts.append(shot["prompt"])
    parts.append("The camera moves smoothly and steadily with no shaking or jitter. Buildings, houses and "
                 "scenery keep exactly the same shape, size and position for the whole shot; only the "
                 "characters move.")
    if shot.get("voiceover"):
        narrator = ep.get("narrator", "a warm, friendly narrator voice")
        parts.append(f'Audio: right from the first second, {narrator} says clearly, at a '
                     f'relaxed pace, finishing the whole sentence: "{shot["voiceover"]}" '
                     f'Background music: {ep["music"]}.')
    parts.append("No on-screen text, no subtitles, no letters or numbers anywhere in the image.")
    return "\n".join(parts)


def make_character(ep, name, args):
    """Render a short character-sheet clip on a plain background and keep its middle frame."""
    look = ep["characters"][name]
    # the series style names a landscape, which beats "plain background", so only its drawing style is used
    prompt = (f"Character model sheet: {look}. Full body, standing in a neutral pose facing the viewer, "
              f"centered, alone on a completely flat plain cream-colored studio backdrop: no landscape, no sky, "
              f"no ground, no houses, nothing else in the frame. Static camera, the character only blinks and "
              f"breathes. Style: hand-drawn 2D anime character design in the style of classic Studio Ghibli "
              f"films, clean linework, soft pastel colors. No text, no letters or numbers anywhere in the image.")
    seed = args.seed if args.seed is not None else random.randrange(2**48)
    print(f"[character {name}] seed {seed}")
    graph = build_graph(prompt, [], args.width, args.height, frame_count(3), seed,
                        20 if args.no_turbo else 6, not args.no_turbo, f"video/character_{name}")
    clip = render(args.server, graph)
    with av.open(str(clip)) as inp:
        frames = [f for f in inp.decode(video=0)]
    CHARACTERS.mkdir(exist_ok=True)
    dest = CHARACTERS / f"{name}.png"
    frames[len(frames) // 2].to_image().save(dest)
    print(f"  -> {dest}")


def text_overlay(text, width, height):
    """RGBA layer with the on-screen text in a rounded dark pill, upper third of the frame."""
    layer = Image.new("RGBA", (width, height))
    if not text:
        return layer
    draw = ImageDraw.Draw(layer)
    size = round(width * 0.062)
    font = ImageFont.truetype(FONT, size)
    lines = textwrap.wrap(text, width=22) or [text]
    boxes = [draw.textbbox((0, 0), line, font=font) for line in lines]
    line_h = max(b[3] - b[1] for b in boxes)
    gap = round(size * 0.25)
    text_w = max(b[2] - b[0] for b in boxes)
    text_h = line_h * len(lines) + gap * (len(lines) - 1)
    pad_x, pad_y = round(size * 0.7), round(size * 0.45)
    x0 = (width - text_w) // 2 - pad_x
    y0 = round(height * 0.13)
    draw.rounded_rectangle((x0, y0, x0 + text_w + 2 * pad_x, y0 + text_h + 2 * pad_y),
                           radius=round(size * 0.5), fill=(20, 24, 32, 170))
    y = y0 + pad_y
    for line, b in zip(lines, boxes):
        draw.text(((width - (b[2] - b[0])) // 2 - b[0], y - b[1]), line, font=font, fill=(255, 255, 255, 255))
        y += line_h + gap
    return layer


def _clip_audio(clip):
    """All of a clip's audio as a (2, samples) float32 array at RATE."""
    resampler = av.AudioResampler(format="fltp", layout="stereo", rate=RATE)
    parts = []
    with av.open(str(clip)) as inp:
        if inp.streams.audio:
            for frame in inp.decode(audio=0):
                parts += [rf.to_ndarray() for rf in resampler.resample(frame)]
    return np.concatenate(parts, axis=1).astype(np.float32) if parts else np.zeros((2, 0), np.float32)


def join(ep, clips, dest, width, height):
    """Trim each shot to its duration, draw its on-screen text, scale and join into one mp4.

    A shot may have "transition_in": {"video_dissolve_sec": s, "audio_crossfade_sec": s} to soften
    the join with the previous shot without moving it or shortening the episode: the previous
    shot's spare rendered frames/audio past its trim point fade out over this shot's first frames
    and samples. Size audio_crossfade_sec to the quiet gap so no narration overlaps.
    A shot may also have "trim_start_sec": s to skip the first s seconds of its render (dead air
    before the narration); the shot then uses the render from s to s + its duration.
    """
    with av.open(str(dest), "w") as out:
        vs = out.add_stream("libx264", rate=Fraction(FPS))
        vs.width, vs.height, vs.pix_fmt = width, height, "yuv420p"
        vs.options = {"crf": "18"}
        as_ = out.add_stream("aac", rate=RATE, layout="stereo")
        v_pts = a_pts = 0
        shots = ep["shots"]
        tail_frames, tail_audio = [], np.zeros((2, 0), np.float32)
        for k, (shot, clip) in enumerate(zip(shots, clips)):
            n_frames = round(shot_seconds(shot) * FPS)
            n_samples = round(shot_seconds(shot) * RATE)
            nxt = (shots[k + 1].get("transition_in") or {}) if k + 1 < len(shots) else {}
            keep_v = round(nxt.get("video_dissolve_sec", 0) * FPS)
            keep_a = round(nxt.get("audio_crossfade_sec", 0) * RATE)
            trans = shot.get("transition_in") or {}
            mix_v = min(round(trans.get("video_dissolve_sec", 0) * FPS), len(tail_frames))
            overlay = text_overlay(shot.get("on_screen_text", ""), width, height)
            new_tail = []
            skip = shot.get("trim_start_sec", 0)    # drop dead air at the start of the render
            skip_v, skip_a = round(skip * FPS), round(skip * RATE)
            with av.open(str(clip)) as inp:
                last = None
                i = -1
                for i, frame in enumerate(f for n, f in enumerate(inp.decode(video=0)) if n >= skip_v):
                    if i >= n_frames + keep_v:
                        break
                    img = frame.to_image().convert("RGB").resize((width, height), Image.LANCZOS)
                    img.paste(overlay, (0, 0), overlay)
                    if i >= n_frames:          # spare frames past the trim: next shot's dissolve
                        new_tail.append(img)
                        continue
                    if i < mix_v:              # dissolve in from the previous shot's spare frames
                        img = Image.blend(tail_frames[i], img, (i + 1) / (mix_v + 1))
                    last = img
                    f = av.VideoFrame.from_image(img).reformat(format="yuv420p")
                    f.pts, f.time_base = v_pts, Fraction(1, FPS)
                    v_pts += 1
                    out.mux(vs.encode(f))
                # hold the last frame if the render came out short
                for _ in range(min(i + 1, n_frames), n_frames):
                    f = av.VideoFrame.from_image(last).reformat(format="yuv420p")
                    f.pts, f.time_base = v_pts, Fraction(1, FPS)
                    v_pts += 1
                    out.mux(vs.encode(f))
            while keep_v and len(new_tail) < keep_v:   # render too short for the whole dissolve
                new_tail.append(new_tail[-1] if new_tail else last)
            tail_frames = new_tail
            # audio: trim/pad to the shot length, equal-power crossfade with the previous spare tail
            audio = _clip_audio(clip)[:, skip_a:]
            body =np.zeros((2, n_samples), np.float32)
            body[:, :min(n_samples, audio.shape[1])] = audio[:, :n_samples]
            mix_a = min(round(trans.get("audio_crossfade_sec", 0) * RATE), tail_audio.shape[1], n_samples)
            if mix_a:
                t = (np.arange(mix_a, dtype=np.float32) + 0.5) / mix_a
                body[:, :mix_a] = (body[:, :mix_a] * np.sin(t * np.pi / 2)
                                   + tail_audio[:, :mix_a] * np.cos(t * np.pi / 2))
            tail_audio = np.zeros((2, keep_a), np.float32)
            spare = audio[:, n_samples:n_samples + keep_a]
            tail_audio[:, :spare.shape[1]] = spare
            for s0 in range(0, n_samples, 1024):
                chunk = np.ascontiguousarray(body[:, s0:s0 + 1024])
                rf = av.AudioFrame.from_ndarray(chunk, format="fltp", layout="stereo")
                rf.sample_rate = RATE
                rf.pts, rf.time_base = a_pts, Fraction(1, RATE)
                a_pts += chunk.shape[1]
                out.mux(as_.encode(rf))
        out.mux(vs.encode())
        out.mux(as_.encode())


def main():
    p = argparse.ArgumentParser()
    p.add_argument("episode", help="episode JSON, e.g. ep01-ip-address.json")
    p.add_argument("--server", default="http://127.0.0.1:8188")
    p.add_argument("--shots", nargs="*", type=int, help="shot numbers to render (default: all)")
    p.add_argument("--width", type=int, default=576, help="render width (multiple of 32)")
    p.add_argument("--height", type=int, default=1024, help="render height (multiple of 32)")
    p.add_argument("--seed", type=int)
    p.add_argument("--make-character", metavar="NAME",
                   help="render characters/NAME.png from the episode's character description, then stop")
    p.add_argument("--no-turbo", action="store_true", help="20 steps without the turbo LoRAs (slower, sometimes better)")
    p.add_argument("--join-only", action="store_true")
    args = p.parse_args()

    ep_path = Path(args.episode)
    if not ep_path.is_absolute():
        ep_path = HERE / ep_path
    ep = json.loads(ep_path.read_text(encoding="utf-8"))
    if args.make_character:
        make_character(ep, args.make_character, args)
        return
    name = f"ep{ep['episode']:02d}"
    # output/epNN/epNN-<slug>.mp4 is the episode, output/epNN/shots/ holds the shots;
    # other languages ("language" in the JSON) go to output/epNN/<lang>/
    lang = ep.get("language", "en")
    ep_dir = OUTPUT / name
    if lang != "en":
        ep_dir = ep_dir / lang
    shots_dir = ep_dir / "shots"
    shots_dir.mkdir(parents=True, exist_ok=True)
    clips = [shots_dir / f"shot{s['shot']:02d}.mp4" for s in ep["shots"]]

    missing_cast = sorted({n for s in ep["shots"] for n in shot_cast(ep, s)
                           if not (CHARACTERS / f"{n}.png").exists()})
    if missing_cast and not args.join_only:
        sys.exit(f"missing character references: {', '.join(missing_cast)} "
                 f"(create them with --make-character NAME)")

    total = sum(shot_seconds(s) for s in ep["shots"])
    planned = ep.get("total_duration_sec", total)
    print(f"{name}: {total:.1f}s with narration room (planned {planned}s)")
    if total > planned + MAX_EXTRA_SEC:
        print(f"  warning: more than {MAX_EXTRA_SEC}s over plan, consider shortening the voiceover")

    if not args.join_only:
        for shot, dest in zip(ep["shots"], clips):
            if args.shots and shot["shot"] not in args.shots:
                continue
            cast = shot_cast(ep, shot)
            refs = [upload_image(args.server, CHARACTERS / f"{n}.png") for n in cast]
            seed = args.seed if args.seed is not None else random.randrange(2**48)
            steps = 20 if args.no_turbo else (4 if refs else 6)
            seconds = shot_seconds(shot)
            length = frame_count(seconds)
            print(f"[shot {shot['shot']}] {seconds}s ({length} frames), {args.width}x{args.height}, "
                  f"{steps} steps, refs {cast or 'none (t2v)'}, seed {seed}")
            graph = build_graph(shot_prompt(ep, shot, cast), refs, args.width, args.height, length,
                                seed, steps, not args.no_turbo, f"video/{name}_shot{shot['shot']:02d}")
            dest.write_bytes(render(args.server, graph).read_bytes())
            print(f"  -> {dest}")

    missing = [c.name for c in clips if not c.exists()]
    if missing:
        print("not joining yet, missing:", ", ".join(missing))
        return
    width, height = (int(v) for v in ep.get("resolution", "1080x1920").split("x"))
    final = ep_dir / f"{ep_path.stem.removesuffix('.' + lang)}{'' if lang == 'en' else '-' + lang}.mp4"
    join(ep, clips, final, width, height)
    print(f"final video: {final}")


if __name__ == "__main__":
    main()
