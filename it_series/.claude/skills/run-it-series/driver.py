"""Smoke driver for the it_series render pipeline (generar_episodio.py + qa_episodio.py on ComfyUI).

Run with ComfyUI's Python from it_series/:
  D:\\Comfy-Desktop\\ComfyUI-Installs\\ComfyUI\\standalone-env\\python.exe .claude/skills/run-it-series/driver.py <cmd>

  status    is the ComfyUI backend up, are the H3 models installed
  start     launch ComfyUI Desktop if needed and wait (up to 5 min) for the backend
  selftest  offline check of join/trim/silence-padding/captions with synthetic clips (no ComfyUI)
  smoke     render a real 1-shot episode (Bit + caption, 320x576) end to end, then QA it

Everything the driver writes goes to %TEMP%/it_series_smoke, never to it_series/output.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

UNIT = Path(__file__).resolve().parents[3]          # it_series/
PY = r"D:\Comfy-Desktop\ComfyUI-Installs\ComfyUI\standalone-env\python.exe"
DESKTOP = r"D:\Comfy-Desktop\Comfy Desktop\Comfy Desktop.exe"
SERVER = "http://127.0.0.1:8188"
WORK = Path(tempfile.gettempdir()) / "it_series_smoke"
H3_MODELS = ["minimax_h3_fl2va_pruned_int8_convrot.safetensors", "minimax_h3_ref2va_pruned_int8_convrot.safetensors"]


def get(path):
    with urllib.request.urlopen(SERVER + path, timeout=3) as r:
        return json.loads(r.read())


def up():
    try:
        get("/system_stats")
        return True
    except OSError:
        return False


def status():
    if not up():
        print(f"ComfyUI: DOWN ({SERVER})")
        return 1
    models = get("/models/diffusion_models")
    print(f"ComfyUI: up ({SERVER})")
    for m in H3_MODELS:
        print(f"  {'ok     ' if m in models else 'MISSING'} {m}")
    bit = UNIT / "characters" / "Bit.png"
    print(f"  {'ok     ' if bit.exists() else 'MISSING'} characters/Bit.png")
    return 0 if all(m in models for m in H3_MODELS) else 1


def start():
    if up():
        print("ComfyUI already up")
        return 0
    print("launching ComfyUI Desktop ...")
    subprocess.Popen([DESKTOP], creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    t0 = time.time()
    while time.time() - t0 < 300:
        if up():
            print(f"ComfyUI up after {time.time() - t0:.0f}s")
            return 0
        time.sleep(5)
    print("ComfyUI Desktop is open but the backend never answered on 8188: it is waiting on a dialog "
          "(update / maintenance / error) in its window. Someone has to click through it.")
    return 1


def selftest():
    """Join synthetic clips (too long, too short, 44.1 kHz audio) and check the result."""
    import av
    import numpy as np
    sys.path.insert(0, str(UNIT))
    import generar_episodio as g

    WORK.mkdir(parents=True, exist_ok=True)
    ep = json.loads((UNIT / "ep01-ip-address.json").read_text(encoding="utf-8"))
    specs = [(3.04, 48000), (6.5, 44100), (7.7, 48000), (9.9, 48000), (4.0, 48000)]
    clips = []
    for i, (secs, rate) in enumerate(specs):
        path = WORK / f"synthetic{i}.mp4"
        with av.open(str(path), "w") as o:
            v = o.add_stream("libx264", rate=24)
            v.width, v.height, v.pix_fmt = 576, 1024, "yuv420p"
            a = o.add_stream("aac", rate=rate, layout="stereo")
            for n in range(round(secs * 24)):
                f = av.VideoFrame.from_ndarray(np.full((1024, 576, 3), 60 * i, np.uint8), format="rgb24")
                f.pts = n
                o.mux(v.encode(f))
            x = (np.sin(2 * np.pi * 440 * np.arange(round(secs * rate)) / rate) * 0.2).astype(np.float32)
            for s in range(0, len(x), 1024):
                af = av.AudioFrame.from_ndarray(np.stack([x[s:s + 1024]] * 2), format="fltp", layout="stereo")
                af.sample_rate, af.pts = rate, s
                o.mux(a.encode(af))
            o.mux(v.encode())
            o.mux(a.encode())
        clips.append(path)
    dest = WORK / "selftest.mp4"
    g.join(ep, clips, dest, 1080, 1920)
    want = sum(g.shot_seconds(s) for s in ep["shots"])
    with av.open(str(dest)) as c:
        nv, size = sum(1 for _ in c.decode(video=0)), (c.streams.video[0].width, c.streams.video[0].height)
    with av.open(str(dest)) as c:
        na = sum(f.samples for f in c.decode(audio=0))
    ok = abs(nv / 24 - want) < 0.05 and abs(na / 48000 - want) < 0.05 and size == (1080, 1920)
    print(f"selftest {'PASS' if ok else 'FAIL'}: video {nv / 24:.2f}s, audio {na / 48000:.2f}s, "
          f"expected {want:.2f}s, {size[0]}x{size[1]} -> {dest}")
    return 0 if ok else 1


def smoke():
    if not up():
        print("ComfyUI is down: run `driver.py start` first")
        return 1
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    ep = json.loads((UNIT / "ep01-ip-address.json").read_text(encoding="utf-8"))
    ep["episode"], ep["title"], ep["total_duration_sec"] = 99, "Smoke test", 3
    ep["shots"] = [dict(ep["shots"][0], voiceover="Every device has a home address.",
                        on_screen_text="Smoke test", duration_sec=3, end_sec=3)]
    spec = WORK / "ep99-smoke.json"
    spec.write_text(json.dumps(ep, indent=2), encoding="utf-8")
    env = dict(os.environ, IT_SERIES_OUTPUT=str(WORK / "output"), PYTHONIOENCODING="utf-8")
    t0 = time.time()
    for cmd in ([PY, "-u", "generar_episodio.py", str(spec), "--width", "320", "--height", "576"],
                [PY, "qa_episodio.py", str(spec)]):
        r = subprocess.run(cmd, cwd=UNIT, env=env)
        if r.returncode:
            print(f"smoke FAIL: {' '.join(cmd[1:3])} exited {r.returncode}")
            return 1
    print(f"smoke PASS in {time.time() - t0:.0f}s: look at {WORK / 'output' / 'ep99' / 'qa_grid.png'}")
    return 0


if __name__ == "__main__":
    cmds = {"status": status, "start": start, "selftest": selftest, "smoke": smoke}
    if len(sys.argv) != 2 or sys.argv[1] not in cmds:
        print(__doc__)
        sys.exit(2)
    sys.exit(cmds[sys.argv[1]]())
