"""Quality checks for a rendered episode: lengths, dead air and a frame grid to look at.

  D:\\Comfy-Desktop\\ComfyUI-Installs\\ComfyUI\\standalone-env\\python.exe qa_episodio.py ep01-ip-address.json

Prints per-shot "quiet" seconds at the shot's start/end (narration starting late or ending early)
and writes output/epNN[/lang]/qa_grid.png: one column per shot, four frames spread across it, to
spot camera moves, morphing scenery, location jumps, off-model characters and gibberish lettering
(those need eyes; frame-difference numbers missed them in testing).
"""
import json
import sys
from pathlib import Path

import av
import numpy as np
from PIL import Image, ImageDraw

from generar_episodio import HERE, OUTPUT, shot_seconds

FPS, RATE = 24, 48000
QUIET_RMS = 0.05     # half-seconds below this loudness count as near-silent
ROWS = 4             # frames per shot in the grid


def main():
    ep_path = Path(sys.argv[1])
    if not ep_path.is_absolute():
        ep_path = HERE / ep_path
    ep = json.loads(ep_path.read_text(encoding="utf-8"))
    lang = ep.get("language", "en")
    ep_dir = OUTPUT / f"ep{ep['episode']:02d}"
    if lang != "en":
        ep_dir = ep_dir / lang
    final = ep_dir / f"{ep_path.stem.removesuffix('.' + lang)}{'' if lang == 'en' else '-' + lang}.mp4"

    with av.open(str(final)) as c:
        frames = [f.to_image() for f in c.decode(video=0)]
    with av.open(str(final)) as c:
        audio = np.concatenate([f.to_ndarray().reshape(2, -1) for f in c.decode(audio=0)], axis=1)
    print(f"{final.name}: video {len(frames) / FPS:.1f}s, audio {audio.shape[1] / RATE:.1f}s, "
          f"{frames[0].width}x{frames[0].height}")

    tile_w, tile_h = 216, 384
    grid = Image.new("RGB", (tile_w * len(ep["shots"]), 30 + tile_h * ROWS), "white")
    draw = ImageDraw.Draw(grid)
    start = 0.0
    for col, shot in enumerate(ep["shots"]):
        secs = shot_seconds(shot)
        rms = [float(np.sqrt((audio[:, int((start + t) * RATE):int((start + t + 0.5) * RATE)] ** 2).mean()))
               for t in np.arange(0, secs - 0.25, 0.5)]
        lead = next((i for i, v in enumerate(rms) if v > QUIET_RMS), len(rms)) * 0.5
        tail = next((i for i, v in enumerate(reversed(rms)) if v > QUIET_RMS), len(rms)) * 0.5
        print(f"shot {shot['shot']}: {start:.1f}-{start + secs:.1f}s, quiet start {lead:.1f}s / end {tail:.1f}s")
        a, b = int(start * FPS), min(int((start + secs) * FPS), len(frames)) - 1
        for row in range(ROWS):
            i = a + (b - a) * (2 * row + 1) // (2 * ROWS)
            grid.paste(frames[i].resize((tile_w, tile_h)), (col * tile_w, 30 + row * tile_h))
        draw.text((col * tile_w + 6, 8), f"shot {shot['shot']}  {start:.1f}-{start + secs:.1f}s", fill="black")
        start += secs
    dest = ep_dir / "qa_grid.png"
    grid.save(dest)
    print(f"grid: {dest}")


if __name__ == "__main__":
    main()
