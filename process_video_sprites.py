from __future__ import annotations

import argparse
import json
import math
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np
from PIL import Image
from rembg import new_session, remove


@dataclass
class FrameMeta:
    index: int
    source_frame: int
    time_sec: float
    file: str
    crop_box: tuple[int, int, int, int] | None
    sprite: tuple[int, int, int, int] | None = None


def parse_size(value: str) -> tuple[int, int]:
    try:
        width, height = value.lower().split("x", 1)
        return int(width), int(height)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("size must look like 256x256") from exc


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def extract_frames(
    video_path: Path,
    every_n: int,
    max_frames: int | None,
    scene_threshold: float | None,
    start_sec: float,
    end_sec: float | None,
) -> Iterable[tuple[int, float, np.ndarray]]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    start_frame = max(0, int(round(start_sec * fps)))
    end_frame = None if end_sec is None else max(start_frame, int(round(end_sec * fps)))
    if start_frame > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    previous_gray: np.ndarray | None = None
    emitted = 0
    frame_number = start_frame - 1

    try:
        while True:
            ok, frame_bgr = cap.read()
            if not ok:
                break

            frame_number += 1
            if end_frame is not None and frame_number > end_frame:
                break

            if frame_number % every_n != 0:
                continue

            if scene_threshold is not None:
                gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
                if previous_gray is not None:
                    diff = cv2.absdiff(gray, previous_gray).mean()
                    previous_gray = gray
                    if diff < scene_threshold:
                        continue
                else:
                    previous_gray = gray

            time_sec = frame_number / fps
            yield frame_number, time_sec, frame_bgr
            emitted += 1

            if max_frames is not None and emitted >= max_frames:
                break
    finally:
        cap.release()


def remove_background(frame_bgr: np.ndarray, session: object) -> Image.Image:
    frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    image = Image.fromarray(frame_rgb)
    cutout = remove(image, session=session)
    return cutout.convert("RGBA")


def clean_alpha(image: Image.Image, alpha_threshold: int, feather: float, morph: int) -> Image.Image:
    rgba = np.array(image.convert("RGBA"))
    alpha = rgba[:, :, 3]

    if alpha_threshold > 0:
        alpha = np.where(alpha >= alpha_threshold, alpha, 0).astype(np.uint8)

    if morph > 0:
        kernel_size = morph * 2 + 1
        kernel = np.ones((kernel_size, kernel_size), np.uint8)
        alpha = cv2.morphologyEx(alpha, cv2.MORPH_OPEN, kernel)
        alpha = cv2.morphologyEx(alpha, cv2.MORPH_CLOSE, kernel)

    if feather > 0:
        alpha = cv2.GaussianBlur(alpha, (0, 0), feather)

    rgba[:, :, 3] = alpha
    return Image.fromarray(rgba, "RGBA")


def alpha_bbox(image: Image.Image, threshold: int) -> tuple[int, int, int, int] | None:
    alpha = np.array(image.getchannel("A"))
    points = np.argwhere(alpha > threshold)
    if points.size == 0:
        return None

    y_min, x_min = points.min(axis=0)
    y_max, x_max = points.max(axis=0)
    return int(x_min), int(y_min), int(x_max + 1), int(y_max + 1)


def expand_box(
    box: tuple[int, int, int, int],
    image_size: tuple[int, int],
    padding: int,
) -> tuple[int, int, int, int]:
    left, top, right, bottom = box
    width, height = image_size
    return (
        max(0, left - padding),
        max(0, top - padding),
        min(width, right + padding),
        min(height, bottom + padding),
    )


def fit_to_canvas(image: Image.Image, canvas_size: tuple[int, int]) -> Image.Image:
    canvas_w, canvas_h = canvas_size
    scale = min(canvas_w / image.width, canvas_h / image.height)
    new_size = (
        max(1, int(round(image.width * scale))),
        max(1, int(round(image.height * scale))),
    )
    resized = image.resize(new_size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    x = (canvas_w - new_size[0]) // 2
    y = (canvas_h - new_size[1]) // 2
    canvas.alpha_composite(resized, (x, y))
    return canvas


def process_frame(
    frame_bgr: np.ndarray,
    session: object,
    canvas_size: tuple[int, int],
    crop: bool,
    padding: int,
    alpha_threshold: int,
    feather: float,
    morph: int,
) -> tuple[Image.Image, tuple[int, int, int, int] | None]:
    image = remove_background(frame_bgr, session)
    image = clean_alpha(image, alpha_threshold, feather, morph)

    bbox = alpha_bbox(image, alpha_threshold)
    if crop and bbox is not None:
        padded = expand_box(bbox, image.size, padding)
        image = image.crop(padded)
        bbox = padded

    return fit_to_canvas(image, canvas_size), bbox


def build_sprite_sheet(
    frames: list[Image.Image],
    columns: int | None,
    spacing: int,
    background: tuple[int, int, int, int],
) -> tuple[Image.Image, list[tuple[int, int, int, int]]]:
    if not frames:
        raise RuntimeError("No frames to write to sprite sheet.")

    tile_w, tile_h = frames[0].size
    if columns is None:
        columns = math.ceil(math.sqrt(len(frames)))
    rows = math.ceil(len(frames) / columns)

    sheet_w = columns * tile_w + max(0, columns - 1) * spacing
    sheet_h = rows * tile_h + max(0, rows - 1) * spacing
    sheet = Image.new("RGBA", (sheet_w, sheet_h), background)
    rects: list[tuple[int, int, int, int]] = []

    for index, frame in enumerate(frames):
        row, col = divmod(index, columns)
        x = col * (tile_w + spacing)
        y = row * (tile_h + spacing)
        sheet.alpha_composite(frame, (x, y))
        rects.append((x, y, tile_w, tile_h))

    return sheet, rects


def save_animated_webp(frames: list[Image.Image], output_path: Path, duration_ms: int) -> None:
    if not frames:
        raise RuntimeError("No frames to write to WebP.")
    first, *rest = frames
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    if temp_path.exists():
        temp_path.unlink()
    first.save(
        temp_path,
        format="WEBP",
        save_all=True,
        append_images=rest,
        duration=duration_ms,
        loop=0,
        lossless=True,
        quality=100,
        method=6,
    )
    if temp_path.stat().st_size <= 0:
        raise RuntimeError(f"WebP export failed: {temp_path} is empty.")
    temp_path.replace(output_path)


def save_frames_zip(frames_dir: Path, output_path: Path) -> None:
    frame_paths = sorted(frames_dir.glob("*.png"))
    if not frame_paths:
        raise RuntimeError("No PNG frames to write to ZIP.")

    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    if temp_path.exists():
        temp_path.unlink()
    with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in frame_paths:
            archive.write(path, arcname=f"frames/{path.name}")
    if temp_path.stat().st_size <= 0:
        raise RuntimeError(f"ZIP export failed: {temp_path} is empty.")
    temp_path.replace(output_path)


def run(args: argparse.Namespace) -> None:
    input_path = args.input.resolve()
    output_dir = args.output.resolve()
    frames_dir = output_dir / "frames"
    ensure_dir(frames_dir)

    session = new_session(args.model)
    frames: list[Image.Image] = []
    meta: list[FrameMeta] = []

    for out_index, (source_frame, time_sec, frame_bgr) in enumerate(
        extract_frames(
            input_path,
            args.every_n,
            args.max_frames,
            args.scene_threshold,
            args.start_sec,
            args.end_sec,
        )
    ):
        processed, bbox = process_frame(
            frame_bgr,
            session,
            args.size,
            args.crop,
            args.padding,
            args.alpha_threshold,
            args.feather,
            args.morph,
        )
        frame_name = f"frame_{out_index:04d}.png"
        processed.save(frames_dir / frame_name)
        frames.append(processed)
        meta.append(
            FrameMeta(
                index=out_index,
                source_frame=source_frame,
                time_sec=round(time_sec, 4),
                file=str(Path("frames") / frame_name),
                crop_box=bbox,
            )
        )
        print(f"processed {frame_name} from source frame {source_frame}")

    if not frames:
        raise RuntimeError("No frames were extracted. Try lowering --every-n or --scene-threshold.")

    if args.sheet:
        sheet, rects = build_sprite_sheet(frames, args.columns, args.spacing, (0, 0, 0, 0))
        sheet_path = output_dir / args.sheet_name
        temp_sheet_path = sheet_path.with_suffix(sheet_path.suffix + ".tmp")
        if temp_sheet_path.exists():
            temp_sheet_path.unlink()
        sheet.save(temp_sheet_path, format="PNG")
        if temp_sheet_path.stat().st_size <= 0:
            raise RuntimeError(f"Sprite sheet export failed: {temp_sheet_path} is empty.")
        temp_sheet_path.replace(sheet_path)
        for item, rect in zip(meta, rects):
            item.sprite = rect

    if args.webp:
        save_animated_webp(frames, output_dir / args.webp_name, args.webp_duration)

    if args.zip:
        save_frames_zip(frames_dir, output_dir / args.zip_name)

    meta_path = output_dir / "manifest.json"
    with meta_path.open("w", encoding="utf-8") as file:
        json.dump([asdict(item) for item in meta], file, ensure_ascii=False, indent=2)

    summary = {
        "input": str(input_path),
        "output": str(output_dir),
        "frame_count": len(frames),
        "frame_size": {"width": frames[0].width, "height": frames[0].height},
        "sprite_sheet": args.sheet_name if args.sheet else None,
        "animated_webp": args.webp_name if args.webp else None,
        "frames_zip": args.zip_name if args.zip else None,
    }
    with (output_dir / "summary.json").open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)

    print(f"done: {len(frames)} frames written to {output_dir}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Remove video backgrounds with rembg and export PNG frames, sprite sheets, or animated WebP."
    )
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        default=Path("Generate_a_spinning_202604271541.mp4"),
        help="Input video path.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("out_sprites"),
        help="Output directory.",
    )
    parser.add_argument(
        "--size",
        type=parse_size,
        default=(256, 256),
        help="Final frame canvas size, for example 256x256.",
    )
    parser.add_argument(
        "--every-n",
        type=int,
        default=3,
        help="Extract every Nth frame before background removal.",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=None,
        help="Stop after this many exported frames.",
    )
    parser.add_argument(
        "--start-sec",
        type=float,
        default=0.0,
        help="Start extracting frames from this timestamp in seconds.",
    )
    parser.add_argument(
        "--end-sec",
        type=float,
        default=None,
        help="Stop extracting frames at this timestamp in seconds.",
    )
    parser.add_argument(
        "--scene-threshold",
        type=float,
        default=None,
        help="Optional frame-difference threshold. Higher values keep fewer frames.",
    )
    parser.add_argument(
        "--model",
        default="u2net",
        help="rembg model name, for example u2net, isnet-general-use, u2netp.",
    )
    parser.add_argument(
        "--no-crop",
        dest="crop",
        action="store_false",
        help="Keep the original full frame before fitting to the canvas.",
    )
    parser.set_defaults(crop=True)
    parser.add_argument(
        "--padding",
        type=int,
        default=12,
        help="Transparent padding around the detected alpha bounding box before resizing.",
    )
    parser.add_argument(
        "--alpha-threshold",
        type=int,
        default=12,
        help="Alpha value below this threshold becomes transparent.",
    )
    parser.add_argument(
        "--feather",
        type=float,
        default=0.6,
        help="Gaussian blur radius for softening alpha edges. Use 0 to disable.",
    )
    parser.add_argument(
        "--morph",
        type=int,
        default=1,
        help="Morphology cleanup radius for alpha edges. Use 0 to disable.",
    )
    parser.add_argument(
        "--sheet",
        action="store_true",
        help="Also export a transparent PNG sprite sheet.",
    )
    parser.add_argument(
        "--sheet-name",
        default="sprite_sheet.png",
        help="Sprite sheet file name inside output directory.",
    )
    parser.add_argument(
        "--columns",
        type=int,
        default=None,
        help="Sprite sheet column count. Defaults to a near-square layout.",
    )
    parser.add_argument(
        "--spacing",
        type=int,
        default=0,
        help="Transparent spacing between sprite sheet tiles.",
    )
    parser.add_argument(
        "--webp",
        action="store_true",
        help="Also export a lossless animated transparent WebP.",
    )
    parser.add_argument(
        "--webp-name",
        default="animation.webp",
        help="Animated WebP file name inside output directory.",
    )
    parser.add_argument(
        "--webp-duration",
        type=int,
        default=80,
        help="Frame duration for animated WebP in milliseconds.",
    )
    parser.add_argument(
        "--zip",
        action="store_true",
        help="Also export transparent PNG frames as a ZIP bundle.",
    )
    parser.add_argument(
        "--zip-name",
        default="frames.zip",
        help="ZIP file name inside output directory.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.every_n < 1:
        parser.error("--every-n must be >= 1")
    if args.max_frames is not None and args.max_frames < 1:
        parser.error("--max-frames must be >= 1")
    if args.start_sec < 0:
        parser.error("--start-sec must be >= 0")
    if args.end_sec is not None and args.end_sec <= args.start_sec:
        parser.error("--end-sec must be greater than --start-sec")
    if args.columns is not None and args.columns < 1:
        parser.error("--columns must be >= 1")
    if not args.input.exists():
        parser.error(f"input video does not exist: {args.input}")
    run(args)


if __name__ == "__main__":
    main()
