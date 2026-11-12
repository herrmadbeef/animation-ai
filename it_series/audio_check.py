"""Narration checks on each rendered shot (output/epNN[/lang]/shots/shotNN.mp4), before or after a join.

  D:\\Comfy-Desktop\\ComfyUI-Installs\\ComfyUI\\standalone-env\\python.exe audio_check.py ep02-dns.json [--shots 2,5]

Measures speech-band (300-3400 Hz) loudness in 50 ms windows and prints, per shot, where speech
starts and ends in the raw render compared with the part the join keeps (trim_start_sec ..
trim_start_sec + shot length). It is a loudness measure, not speech recognition: music sits under the
voice, so treat the flags as strong hints and still ask the user to listen.

Flags:
  REPEAT?  speech lasts much longer than one reading of the line (H3 tends to say a short line twice)
  CUT      speech-level audio continues past the trim point (last words lost in the join)
  LATE     speech starts more than 2 s into the kept part
  NO-TAIL  last shot ends less than 0.5 s after the last word (closing line may sound clipped)
"""
import json
import sys
from pathlib import Path

import av
import numpy as np

from generar_episodio import HERE, OUTPUT, shot_seconds

WIN = 0.05            # analysis window, seconds
SPEECH_DB = -6        # windows within this many dB of the 95th percentile count as speech
READ_WPS = 2.7        # measured H3 narration pace, words per second
REPEAT_RATIO = 1.6    # speech span above this x one reading -> likely said twice


def speech_db(clip):
    with av.open(str(clip)) as c:
        s = c.streams.audio[0]
        sr = s.rate
        x = np.concatenate([(a.mean(0) if a.shape[0] > 1 else a[0])
                            for a in (f.to_ndarray() for f in c.decode(s))]).astype(np.float32)
    w = int(sr * WIN)
    f = np.fft.rfftfreq(w, 1 / sr)
    band = (f > 300) & (f < 3400)
    win = np.hanning(w)
    db = np.array([10 * np.log10((np.abs(np.fft.rfft(x[i:i + w] * win)) ** 2)[band].sum() + 1e-9)
                   for i in range(0, len(x) - w + 1, w)])
    return db - np.percentile(db, 95), len(x) / sr


def main():
    args = sys.argv[1:]
    ep_path = Path(args[0])
    if not ep_path.is_absolute():
        ep_path = HERE / ep_path
    only = None
    if "--shots" in args:
        only = {int(n) for n in args[args.index("--shots") + 1].split(",")}
    ep = json.loads(ep_path.read_text(encoding="utf-8"))
    lang = ep.get("language", "en")
    ep_dir = OUTPUT / f"ep{ep['episode']:02d}"
    if lang != "en":
        ep_dir = ep_dir / lang
    last_shot = ep["shots"][-1]["shot"]

    for shot in ep["shots"]:
        n = shot["shot"]
        if only and n not in only:
            continue
        clip = ep_dir / "shots" / f"shot{n:02d}.mp4"
        if not clip.exists():
            print(f"shot {n}: no render at {clip}")
            continue
        db, raw = speech_db(clip)
        skip = shot.get("trim_start_sec", 0)
        end = skip + shot_seconds(shot)
        loud = np.nonzero(db > SPEECH_DB)[0]
        if not len(loud):
            print(f"shot {n}: no speech found (raw {raw:.2f}s)  FLAG: NO-SPEECH")
            continue
        first, last = loud[0] * WIN, (loud[-1] + 1) * WIN
        words = len(shot.get("voiceover", "").split())
        one_read = words / READ_WPS
        span = last - first
        flags = []
        if span > REPEAT_RATIO * one_read + 0.5:
            flags.append("REPEAT?")
        if last > end + WIN:
            flags.append("CUT")
        if first - skip > 2.0:
            flags.append("LATE")
        if n == last_shot and end - last < 0.5:
            flags.append("NO-TAIL")
        print(f"shot {n}: kept {skip:.2f}-{end:.2f}s of {raw:.2f}s raw | speech {first:.2f}-{last:.2f}s "
              f"({span:.1f}s; one reading of {words} words ~{one_read:.1f}s)"
              + (f"  FLAG: {' '.join(flags)}" if flags else "  OK"))


if __name__ == "__main__":
    main()
