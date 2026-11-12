---
name: run-it-series
description: Run, smoke-test and drive the "IT in 30 Seconds" video pipeline (generar_episodio.py + qa_episodio.py on local ComfyUI / MiniMax H3). Use when asked to start ComfyUI, render or re-render an episode or a shot, create a character reference, join/caption an episode, check or screenshot (QA grid) a rendered episode, or verify the pipeline works.
---

The pipeline turns an episode JSON (`epNN-<slug>.json`) into a narrated, captioned 1080x1920
video by rendering each shot with MiniMax H3 on the local ComfyUI server (`http://127.0.0.1:8188`).
Drive it with `.claude/skills/run-it-series/driver.py` (status / start / offline selftest /
end-to-end smoke render). The "screenshot" is the QA grid PNG, which you `Read` and look at.

All paths below are relative to `it_series/`. This is a **Windows** machine (Git Bash); there is
no Linux/container path: H3 needs the local RTX 4070 Ti SUPER and the ComfyUI Desktop install.

## Prerequisites

- ComfyUI Desktop at `D:\Comfy-Desktop\Comfy Desktop\Comfy Desktop.exe`, models in
  `D:\Comfy-Desktop\ComfyUI-Shared\models\` (H3 `fl2va` + `ref2va`, turbo LoRAs, H3 VAEs, Qwen3-VL
  text encoder). `driver.py status` checks the two H3 diffusion models.
- Always use ComfyUI's bundled Python (has PyAV, Pillow, numpy; nothing to install):

```bash
PY="D:/Comfy-Desktop/ComfyUI-Installs/ComfyUI/standalone-env/python.exe"
```

- `generar_episodio.py` imports `build_graph`/`render` from `../hhsVbartlett/generar_h3.py`.

## Run (agent path)

```bash
$PY .claude/skills/run-it-series/driver.py status     # ComfyUI up? H3 models + characters/Bit.png present?
$PY .claude/skills/run-it-series/driver.py start      # launches ComfyUI Desktop if down, waits up to 5 min
$PY .claude/skills/run-it-series/driver.py selftest   # offline: join/trim/padding/captions, ~10 s, no GPU
$PY .claude/skills/run-it-series/driver.py smoke      # real 1-shot render + join + QA, ~30 s when warm
```

Expected: `selftest PASS: video 35.00s, audio 35.00s, expected 35.00s, 1080x1920` and
`smoke PASS in 31s: look at C:\Users\herrm\AppData\Local\Temp\it_series_smoke\output\ep99\qa_grid.png`.
Then `Read` that PNG: Bit (orange fox, blue scarf, satchel, envelope) on a hilltop with a
"Smoke test" caption. Driver output all goes to `%TEMP%\it_series_smoke`, never to `output/`.

Real episodes: render one shot per command (each takes 1–4 min, keep Bash timeout at 600000 ms),
then join and QA:

```bash
PYTHONIOENCODING=utf-8 $PY -u generar_episodio.py ep01-ip-address.json --shots 4 5   # overwrites those shots!
PYTHONIOENCODING=utf-8 $PY generar_episodio.py ep01-ip-address.json --join-only
PYTHONIOENCODING=utf-8 $PY qa_episodio.py ep01-ip-address.json
PYTHONIOENCODING=utf-8 $PY -u generar_episodio.py ep02-dns.json --make-character Alex
```

- Output: `output/epNN/<slug>.mp4`, shots in `output/epNN/shots/shotNN.mp4`, QA grid
  `output/epNN/qa_grid.png` (4 frames per shot). Translations (`epNN-<slug>.<lang>.json` with
  `"language"`) go to `output/epNN/<lang>/`.
- `qa_episodio.py` prints `quiet start Xs / end Ys` per shot (dead air); look at the grid for camera
  moves, morphing houses, location jumps, gibberish lettering, off-model characters.
- `audio_check.py epNN-x.json [--shots 2,5]` checks narration in the raw shot renders and flags
  `REPEAT?` (line said twice), `CUT` (speech past the join trim), `LATE` (starts >2 s in) and
  `NO-TAIL` (last shot ends <0.5 s after the last word). Loudness-based, so the user still listens.
- Before a multi-shot render, check free RAM: under ~15 GB, H3 slows ~5x and a batch was killed.
- `--make-character NAME` writes `characters/NAME.png` (~55 s); look at it before rendering.
- For writing episode JSONs and the full QA/retry loop, use the `it-video-producer` agent
  (`../.claude/agents/it-video-producer.md`).

## Run (human path)

Open ComfyUI Desktop, then `$PY generar_episodio.py epNN-x.json` (all shots + join, ~10 min).

## Gotchas

- **ComfyUI is on port 8188, not 8000.** `../hhsVbartlett/generar_h3.py` still defaults to 8000;
  pass `--server http://127.0.0.1:8188` there. `generar_episodio.py` and the driver default to 8188.
- **Desktop window open ≠ server up.** After a reboot the app can sit on an update/maintenance
  dialog with no Python process and nothing on 8188 (`comfyui.log` not even written). `driver.py
  start` times out after 5 min; a human has to click through the window.
- **Spanish text crashes prints** with `UnicodeEncodeError: 'charmap'` (cp1252 console) unless
  `PYTHONIOENCODING=utf-8` is set.
- **Character refs leak their background.** A reference frame taken from a scene made H3 jump
  back to that scene mid-shot; refs must be the character alone. `characters/Bit.png` is a tight
  crop. `--make-character` must not use the series `style` text: its "hillside countryside town"
  beat "plain background" (first Alex came out on a landscape); the sheet prompt now uses only
  the drawing style and gets a flat cream backdrop.
- **Characters are matched by name in the shot prompt.** `characters/<Name>.png` is attached as
  `<Picture N>` only for names that literally appear in that shot's `prompt`; the script refuses to
  render if any such character has no PNG.
- **Shots run longer than `duration_sec`** when narration needs it (`words/2.5 + 1` s); ep01 is
  35 s, not 30. Rendered with fewer frames than that, the last frame is held and audio padded.
- **Frame-difference "jump" detection was tried and dropped**: it flagged every tracking shot and
  missed a real camera pan and a location jump. Visual review of the grid is the check.
- **H3 audio repeats short lines**: a 6-word line in a 4 s shot was spoken twice. Size the shot to
  the line and use the agent's "say it once" wording.
- **Negations invite the thing**: "no birds" drew birds, "no ghost images" drew ghosts, and
  "on a tripod" drew a tripod. Describe what should be there instead.
- H3 frames must be 17k+5 (handled by `frame_count`) and width/height multiples of 32.

## Troubleshooting

- **`urlopen error [WinError 10061] ... actively refused it`**: ComfyUI backend down (or wrong
  port). `driver.py start`.
- **`missing character references: Alex (create them with --make-character NAME)`**: run
  `--make-character Alex` with that episode's JSON, check the PNG.
- **Camera shakes / houses morph in a shot**: the prompt asked for a crane or pan near buildings;
  use a locked-off camera wording (see the agent's rules) and re-render that shot with `--shots N`.
- **Gibberish words on signs/envelopes**: describe the surface as blank/plain; real text goes in
  `on_screen_text` (drawn afterwards).
- **See-through giant copy of a character (face in the sky, huge legs in front)**: the character
  was drawn small; frame them medium/close, "solid and opaque", "the only N people in the scene".
- **Phone floats or turns its screen to the camera**: a gesture freed her hands; keep the prop in
  her hands all shot, screen facing her.
- **City/outdoors visible through an opening door**: say what the room behind it looks like.
- **Hard cut between shots**: add `"transition_in"` to the later shot (see `join()` docstring).
