# Handoff: local video generation (MiniMax H3 + Wan 2.2 via ComfyUI)

_Last updated: 2026-11-11_

## Environment

- **ComfyUI Desktop** API at `http://127.0.0.1:8188`, not 8000, which is `generar_h3.py`'s default, so always pass `--server http://127.0.0.1:8188`. The other scripts default to 8188.
  - After opening the Desktop app, the Python backend takes about a minute to start listening.
  - Check that it's up with `curl http://127.0.0.1:8188/system_stats`.
- **Python:** run the scripts with ComfyUI's own Python, which has PyAV and Pillow: `D:\Comfy-Desktop\ComfyUI-Installs\ComfyUI\standalone-env\python.exe`.
- **Paths:**
  - Models live in `D:\Comfy-Desktop\ComfyUI-Shared\models\`.
  - Raw ComfyUI outputs go to `D:\Comfy-Desktop\ComfyUI-Shared\output\video\`.
- **GPU:** RTX 4070 Ti SUPER (16 GB) with 64 GB RAM.
- **Installed video models:**
  - **MiniMax H3**: `ref2va` (reference images) and `fl2va` (first/last frame, also plain text-to-video), plus turbo LoRAs. It generates **video and audio**.
  - **Wan 2.2 14B**, downloaded this session (~70 GB). It is **silent**, with no audio.
    - **T2V:** `wan2.2_t2v_{high,low}_noise_14B_fp8_scaled` with lightx2v 4-step LoRAs v1.1.
    - **I2V:** `wan2.2_i2v_{high,low}_noise_14B_fp8_scaled` with lightx2v 4-step LoRAs v1.
    - **Shared:** `umt5_xxl_fp8_e4m3fn_scaled` text encoder and `wan_2.1_vae`.

## Scripts

### `hhsVbartlett/generar_h3.py` (MiniMax H3)
- **Input:** a prompts JSON with `output`, `style` and `acts[]`, where each act has a `name`, `seconds` and `prompt`.
- **Modes**, chosen by what the JSON contains:
  - `refs` → **Ref2VA**: the images are `<Picture N>` references; turbo runs 4 steps.
  - `first_frame` / `last_frame` → **FL2VA**: the images are pinned as the first and/or last frame, padded with black to the video aspect; turbo runs 6 steps.
  - neither → **plain text-to-video** with FL2VA (official t2v template); turbo runs 6 steps.
- **Flags:** `--acts`, `--seed`, `--no-turbo` (20 steps), `--join-only`, `--width/--height` (multiples of 32).
- **Output:** each act goes to `hhsVbartlett/renders/<output>/`, and the joined video to `hhsVbartlett/<output>.mp4`.
- **Speed:** about 1.5–3 minutes per 10 s at 416×736.

### `hhsVbartlett/generar_wan.py` (Wan 2.2 14B)
- **Input:** the same JSON format, minus `refs`. It accepts an optional `negative`, plus `start_image` / `end_image` for first/last-frame I2V (padded to aspect).
- **Pipeline:** two-expert sampling, where the high-noise model runs the first half of the steps and the low-noise model the second, with shift 8. It runs at 16 fps, so 5 s is 81 frames.
- **Turbo:** the default is 4 steps at cfg 1, and **cfg 1 ignores the negative prompt**. Use `--no-turbo` (20 steps, cfg 3.5) when the negative matters.
- **Speed:**
  - Turbo: about 1.5–3 minutes per 5 s at 480×832.
  - `--no-turbo`: about 19 minutes per 5 s.

### `it_series/generar_episodio.py` ("IT in 30 Seconds" episodes)
- **Input:** an episode JSON from `it_series/ep01…ep10-*.json`. All 10 share the same schema.
- **Pipeline:**
  - Each shot is rendered with H3. The prompt is the shot's prompt plus its narration line and the music cue, so H3 generates the voice and the music.
  - **Shot 1** is text-to-video. A middle frame of it becomes `renders/<ep>/character_ref.png`, which **shots 2–5** use as `<Picture 1>` so the character stays consistent. `--ref img.png` overrides it.
  - Each shot is trimmed to `duration_sec` and padded with silence if it comes out short.
  - `on_screen_text` is drawn afterwards with Pillow as white text on a dark rounded box in the upper third. H3 is told to draw no text.
  - The result is scaled to the episode resolution (1080×1920) and joined into `it_series/<ep>.mp4`.
- **Flags:** `--shots`, `--seed`, `--ref`, `--no-turbo`, `--join-only`, `--width/--height` (default 576×1024 render).
- **Status:** the join, trim, silence padding and text overlay were tested offline with synthetic clips (exactly 30.0 s of video and 30.0 s of audio). **No real render yet**, because ComfyUI was down.

## Work done

### HHS embroidery logo (`stiched/`)
Goal: an embroidery-timelapse animation of the HHS Mustangs horse-head logo (`stiched/hhs_logo/Athletic-3.webp`).

| Version | Output | Notes |
|---|---|---|
| H3 Ref2VA, athletic prompt | `stiched/hhs_althetic/output/HHS_Athletic_Embroidery_H3.mp4` | Good. The text and shield in `hhs_athletic_prompt.md` were dropped because this logo has neither. The face came out lighter than the logo. |
| H3 Ref2VA, `hhs_prompt.md` | (not in output/) | Knit-like fabric, blue tint, golden sparks; worse. |
| Wan T2V, text only (2 tries) | (not in output/) | Without an image Wan drew a generic horse, first as a unicorn with a brown face on an embroidery hoop. A stronger negative fixed the colors and hoop, but the horn remained. |
| Wan FLF, logo as last frame | `stiched/hhs_logo/output/HHS_Logo_Embroidery_Wan_FLF.mp4` | **The user liked it.** First Wan render with the real logo shape; it ends on a flat graphic. |
| Wan FLF2, H3 frames as first and last | `stiched/hhs_logo/output/HHS_Logo_Embroidery_Wan_FLF2.mp4` | The logo appears in under 1 s, then only the lighting changes. |
| **H3 FLF, logo as last frame** | `stiched/hhs_logo/output/HHS_Logo_Embroidery_H3_FLF.mp4` | **Best so far.** Gradual macro satin stitching over ~8 s, with audio. The camera pulls back instead of staying locked, and it ends on a flat-graphic snap. Seed `242031381395302`. |
| **H3 FLF + text** | `stiched/hhs_logo/output/HHS_Logo_Embroidery_H3_FLF_Text.mp4` | Same seed. Adds embroidered "HHS SOCCER" above and "STATE CHAMPIONS" below, spelled correctly once fully stitched. Same flat snap at the end. |

**Supporting files:**
- Prompt JSONs: `stiched/hhs_logo/hhs_logo_*_prompts.json`
- Titled end frame: `stiched/hhs_logo/Athletic-3_soccer_champions.png`, built with PIL using Bahnschrift Bold Condensed in silver `#C4C8D0`
- First/last frames taken from the first H3 video: `stiched/hhs_logo/flf_frames/`

**Lessons:**
- **Only image-anchored modes keep the exact logo.** Wan has no reference-image mode; H3 Ref2VA keeps it reasonably and H3 FLF best.
- **A flat logo as last frame leaves a flat ending.** The video snaps to the flat graphic in its last fraction of a second.
- **Name only what you want in a positive prompt.** "without any horn" still produced a horn; keep exclusions in the negative.
- **H3 tends to lighten the horse's dark-gray face.**

## Open items / next steps
1. **Trim the two H3 FLF videos (offered, not done yet).** Cut `HHS_Logo_Embroidery_H3_FLF.mp4` at about 8.5–9 s and `..._Text.mp4` at about 9.5 s, so each ends on the embroidered logo before the flat snap, keeping the audio in sync.
2. **Render IT episode 1** once ComfyUI is up. From `it_series/`:
   ```
   D:\Comfy-Desktop\ComfyUI-Installs\ComfyUI\standalone-env\python.exe generar_episodio.py ep01-ip-address.json
   ```
   Estimated at 12–15 minutes. Things to check:
   - whether the 3 s and 4 s shots and tight narration lines get cut off;
   - whether Bit stays consistent across shots;
   - whether the music jumps between shots.
3. **Render the other 9 IT episodes** with the same script once episode 1 is approved.
4. **Uncommitted:** the latest `generar_h3.py` change (plain text-to-video), the whole `it_series/` folder and this file.
