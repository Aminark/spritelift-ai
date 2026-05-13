# SpriteLift AI

AI-powered local studio for turning videos into transparent game sprite assets.

SpriteLift AI extracts frames from a video, removes the background with `rembg`, cleans alpha edges, crops the subject, normalizes every frame to a consistent canvas, and exports game-ready PNG sequences, sprite sheets, animated WebP, and ZIP bundles.

> Chinese documentation: [README.zh-CN.md](./README.zh-CN.md)

## Why SpriteLift AI?

- **AI background removal**: works with normal videos, not only green-screen footage.
- **Game asset workflow**: exports transparent PNG frames, sprite sheets, WebP animation, and frame ZIPs.
- **Local WebUI**: upload/select videos, set time ranges, tune quality, preview results, and inspect logs.
- **Precise extraction**: start/end timestamps, max frame count, frame interval, and scene-difference filtering.
- **Clean alpha controls**: alpha threshold, feathering, morphology cleanup, crop padding, and canvas normalization.
- **Open tooling**: Python + OpenCV + Pillow + rembg, easy to modify and integrate.

## WebUI Features

- Video metadata: duration, FPS, resolution
- Estimated extraction count before processing
- Quality presets: Quick, Balanced, Sharp
- Export toggles: Sprite Sheet, Animated WebP, Frames ZIP
- Live logs and generated command view
- Transparent checkerboard preview for frames
- Sprite sheet preview and direct download links
- Extracted HTML/CSS/JS frontend with Chinese/English switching

## Quick Start

### Windows one-click start

Double-click:

```text
start_web.bat
```

Then open:

```text
http://127.0.0.1:7860
```

The batch file creates `.venv` and installs dependencies when needed.

### Manual start

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe web_app.py
```

The first `rembg` run may download a model file. Later runs reuse the cached model.

## Command Line Example

```powershell
.\.venv\Scripts\python.exe process_video_sprites.py input.mp4 `
  --start-sec 1.5 `
  --end-sec 4.5 `
  --max-frames 30 `
  --every-n 2 `
  --size 512x512 `
  --sheet `
  --webp `
  --zip `
  --columns 6 `
  -o output_sprites
```

## Outputs

- `frames/*.png`: transparent PNG frame sequence
- `sprite_sheet.png`: transparent sprite sheet
- `animation.webp`: animated transparent WebP
- `frames.zip`: ZIP bundle of transparent PNG frames
- `manifest.json`: frame source info, crop boxes, and sprite sheet rectangles
- `summary.json`: compact output summary for tools

## Project Layout

```text
process_video_sprites.py   Core OpenCV/rembg processing pipeline
web_app.py                 Flask backend and job runner
templates/index.html       WebUI template
static/app.css             WebUI styles
static/app.js              WebUI behavior and i18n
start_web.bat              Windows one-click launcher
```

## Tips

- Use `u2net` for balanced quality.
- Try `isnet-general-use` for harder subjects.
- Use `u2netp` for faster low-resource tests.
- Increase canvas size to `768x768` or `1024x1024` for sharper assets.
- Lower `--every-n` for smoother animation.
- Use `--start-sec` and `--end-sec` to process only the useful motion range.

## Recommended GitHub Topics

```text
python, opencv, rembg, sprite-sheet, background-removal, game-assets, webp, png-sequence
```

## License

MIT License. See [LICENSE](./LICENSE).
