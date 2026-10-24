# Orb — OpenCV product demo

96 seconds · 120 BPM · 30 fps · 48 bars. Separate 1920×1080 and 1080×1920 compositions.

## What is real

- Product wording, colors, Segoe UI font stack, ringed sphere and control order come from `web/index.html`, `web/styles.css`, and `web/app.js`.
- The original example image was created with the built-in image generation tool. No reference-video footage or soundtrack is reused.
- One authorized judge-mode image Decode was executed on the existing AWS Lambda. `public/live-result.json` contains the sanitized result. `live_hud.jpg` and `live_clahe.jpg` are the actual AWS/S3 artifacts.
- The sample reports OpenCV **5.0.0**, compute **AWS S3 · ARM64 NEON**, **1,578.769 ms** OpenCV processing, and **46.67 s** for upload/result/artifact retrieval. Interaction and processing timings in the film are recreated/edited, not real-time screen capture.
- Video optical-flow data comes from the repository's actual `analyze_video_cv()` on an original generated pan sequence. It is a separate local example, not falsely attributed to the image Decode.
- Analysis and prompt text come from the live result. No real wallet/account or user media is shown. Auth tokens, wallet identifiers and pre-signed URLs are removed from exported data.
- The AI synthesis stage and exported provider label are presented as **Orb AI** throughout the film and public source assets.

## Source discrepancies resolved

The requested 42.8 ms / 23.3 FPS, 86.5 ms / 11.5 FPS, +142–184% edge gain and CLAHE clipLimit 2.8 do **not** match the supplied repository at production time.

The film uses the checked implementation (`clipLimit=2.5`, 8×8 grid) and measured `BENCHMARKS.md` figures:

| Measurement | Repository figure | Provenance |
|---|---:|---|
| 1080p Standard Scene | 260.9 ms / 3.83 FPS | Local x86_64 AVX2, OpenCV 5.0.0 |
| 30-frame 720p video | 1,429.36 ms / 21.92 FPS | Same benchmark machine |
| Laplacian focus sharpness recovery | +42.6% | Underexposed synthetic fixture |
| Mean luminance recovery | +22.4% | Same fixture |

These are not represented as Graviton benchmark measurements. The video does not claim guaranteed elimination of hallucinations or literal zero cold-start/processing latency.

The actual UI labels are **Original Reference**, **OpenCV Vision HUD**, **CLAHE Shadow Recovery**, and **OpenCV 5.0 Agentic Telemetry**. The current application also retains the judge query on the explicit judge link, unlike the older submission guide.

## Original sound

`score.py` synthesizes every pad, bass note, bell, drum and interface effect mathematically. No samples or stock tracks are used. `timeline.json` is the single source for scene boundaries, visual interactions and sound-effect timestamps. Every section starts on a musical bar.

The revised exports add English female synthetic narration using the installed **Microsoft Zira Desktop** voice (Windows System.Speech, offline). `narration.json` contains the 14 timed cues and readable script. `synthesize_voiceover.ps1` generates the individual cues; `mix_voiceover.py` fits them to the existing shots and smoothly ducks the music during speech. The 96-second edit and scene timing are preserved. This is synthesized narration, not a human voice recording.

`public/orb-voiceover.wav` is the isolated 48 kHz voiceover; `public/orb-narrated-mix.wav` combines it with the original score and interface sounds. Both MP4s use the narrated mix. `public/narration-report.json` records the voice, actual cue timings and mix headroom; `Voiceover-Script.txt` is included alongside the exports.

## Reproduce with the existing runtime

No packages or browsers were installed for this work. The renderer reuses the already-installed Remotion 4.0.530 / React 19.2.3 / Chromium / FFmpeg runtime in the sibling `orb-demo-video/node_modules` directory, without changing that project.

```powershell
# Optional when the existing runtime is elsewhere:
$env:REMOTION_DEPS_DIR = 'C:/path/to/existing/node_modules'
pwsh -NoProfile -File video/orb-opencv-demo/synthesize_voiceover.ps1
.venv/Scripts/python.exe video/orb-opencv-demo/mix_voiceover.py
node video/orb-opencv-demo/render.mjs review
node video/orb-opencv-demo/render.mjs landscape
node video/orb-opencv-demo/render.mjs portrait
```

The renderer refuses to download a missing browser. Segoe UI is used from the Windows installation; font files are not redistributed. Narration regeneration uses the installed Windows voice and full system FFmpeg; rendering can reuse the included WAV assets without regenerating narration.

For this revision, full simultaneous renders exceeded the local timeout. The delivered MP4s reuse the approved footage, replace the architecture shot at exactly 66–72 seconds with newly rendered frames, and use the new narrated mix throughout. `render.mjs patch-landscape --reuse` and `patch-portrait --reuse` render those 180-frame shots from the verified bundle; `revise_exports.py` assembles them at frame-exact boundaries using the existing FFmpeg installation, encoding H.264 CRF 16. The approved originals are preserved under the local `output/orb-product-demo/work/` directory.

`prepare_assets.py` regenerates the local CV examples and invokes `score.py`. `build_data.py` assembles the sanitized live data for the composition. The live-capture script is separate and intentionally refuses an automatic second media submission.

Exports and scene review PNGs are written to `output/orb-product-demo/`. Application/backend behavior is unchanged. No commit, push or deployment is performed for video authoring.

## Example-scene generation prompt

Built-in image generation, photorealistic-natural: an original, empty industrial maintenance corridor at night; steel beams, pipes, conduits, machinery and damp floor; low-key exposure with blue and amber practical light; genuine shadow texture recoverable by LAB CLAHE. Cinematic photographic realism, wide 16:9 composition, no people, text, logos, HUD or watermark.

## Visual review and export quality

Every chapter was rendered and visually reviewed in both layouts (19 review frames per orientation). Corrections made during review include UTF-8 caption punctuation, keeping all three preview tabs visible with the complete HUD image, scrolling telemetry to expose the numerical measurements, and scrolling the portrait result far enough to show the complete prompt and Copy control. First-frame covers are supplied separately.

The final exports use H.264 CRF 16, 30 fps, 4:2:0 color and AAC stereo at 320 kbps. The original 48 kHz stereo soundtrack, isolated narration and narrated mix are included in the source assets. `validate.py` checks duration, dimensions, codecs, narration timing, exported audio against the narrated mix, Orb AI branding and sanitized public data offline. Reuse of a reviewed bundle is guarded by a SHA-256 source/asset fingerprint.

Revised export validation: both files contain 2,880 frames and run exactly 96.000 seconds. All 14 narration cues fit their shot windows; decoded AAC audio correlates above 0.9999 with the narrated source mix. Revised architecture frames were checked in both orientations. `Orb-Voiceover.wav` supplies the isolated narration alongside the exports.

The repository and cloud product are not edited or deployed by this project. Only one new original-media judge Decode was used to obtain the real output; no wallet payment was made. All interactions and waits in the film are deliberately paced motion-design recreations. The example filename, credits shown and original scene are demonstration data, not real user information.

## Shot timing

| Time | Feature |
|---|---|
| 00:00–00:04 | Finished logo/tagline cover |
| 00:04–00:16 | Judge entry, Decode, media drop, readability check, dispatch |
| 00:16–00:34 | Perception → Decision → Action explainer |
| 00:34–00:54 | Original / HUD / CLAHE preview interaction |
| 00:54–01:12 | AWS telemetry, verified local benchmarks, cloud architecture |
| 01:12–01:28 | Authentic scene analysis, prompt and Copy |
| 01:28–01:36 | Logo, three-word promise, live URLs |
