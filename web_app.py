from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
from flask import Flask, Response, jsonify, render_template, request, send_from_directory
from werkzeug.utils import secure_filename


ROOT = Path(__file__).resolve().parent
INPUTS_DIR = ROOT / "inputs"
OUTPUTS_DIR = ROOT / "web_outputs"
ALLOWED_VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
APP_LOCK = ROOT / ".web_app.lock"

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024


@app.after_request
def add_no_cache_headers(response: Response) -> Response:
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@dataclass
class JobState:
    running: bool = False
    returncode: int | None = None
    command: list[str] = field(default_factory=list)
    output_dir: str = ""
    logs: list[str] = field(default_factory=list)
    started_at: float | None = None
    finished_at: float | None = None
    error: str | None = None


job = JobState()
job_lock = threading.Lock()


def ensure_dirs() -> None:
    INPUTS_DIR.mkdir(exist_ok=True)
    OUTPUTS_DIR.mkdir(exist_ok=True)


def append_log(line: str) -> None:
    with job_lock:
        job.logs.append(line.rstrip())
        job.logs = job.logs[-500:]


def cleanup_lock() -> None:
    try:
        if APP_LOCK.exists() and APP_LOCK.read_text(encoding="utf-8").strip() == str(os.getpid()):
            APP_LOCK.unlink()
    except OSError:
        pass


def claim_single_instance() -> None:
    if APP_LOCK.exists():
        try:
            old_pid = int(APP_LOCK.read_text(encoding="utf-8").strip())
            if old_pid != os.getpid():
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(old_pid), "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                else:
                    os.kill(old_pid, 9)
        except Exception:
            pass
    APP_LOCK.write_text(str(os.getpid()), encoding="utf-8")


def list_videos() -> list[str]:
    paths = []
    for base in (ROOT, INPUTS_DIR):
        if not base.exists():
            continue
        for path in base.iterdir():
            if path.is_file() and path.suffix.lower() in ALLOWED_VIDEO_EXTS:
                paths.append(str(path.relative_to(ROOT)))
    return sorted(set(paths))


def get_lang() -> str:
    lang = request.args.get("lang", "").lower()
    return "en" if lang == "en" else "zh"


def safe_project_path(relative_path: str) -> Path:
    path = (ROOT / relative_path).resolve()
    if ROOT not in path.parents and path != ROOT:
        raise ValueError("Invalid path.")
    return path


def safe_output_path(relative_path: str) -> Path:
    path = (OUTPUTS_DIR / relative_path).resolve()
    if OUTPUTS_DIR not in path.parents and path != OUTPUTS_DIR:
        raise ValueError("Invalid output path.")
    return path


def output_relative_url_dir(output_dir: str) -> str:
    normalized = output_dir.replace("\\", "/")
    prefix = "web_outputs/"
    if normalized == "web_outputs":
        return ""
    if normalized.startswith(prefix):
        return normalized[len(prefix):]
    return normalized


def get_video_meta(path: Path) -> dict[str, Any]:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {path}")

    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        duration = frames / fps if fps > 0 else 0
        return {
            "name": path.name,
            "fps": round(fps, 3),
            "frames": frames,
            "width": width,
            "height": height,
            "duration": round(duration, 3),
        }
    finally:
        cap.release()


def as_int(data: dict[str, Any], key: str, default: int, min_value: int | None = None) -> int:
    value = int(data.get(key) or default)
    if min_value is not None:
        value = max(min_value, value)
    return value


def as_float(data: dict[str, Any], key: str, default: float, min_value: float | None = None) -> float:
    value = float(data.get(key) or default)
    if min_value is not None:
        value = max(min_value, value)
    return value


def build_command(data: dict[str, Any], input_path: Path, output_dir: Path) -> list[str]:
    width = as_int(data, "width", 512, 1)
    height = as_int(data, "height", 512, 1)
    max_frames = as_int(data, "max_frames", 30, 1)
    every_n = as_int(data, "every_n", 3, 1)
    start_sec = as_float(data, "start_sec", 0.0, 0.0)
    end_sec_raw = data.get("end_sec")
    columns = as_int(data, "columns", 6, 1)
    spacing = as_int(data, "spacing", 0, 0)
    padding = as_int(data, "padding", 12, 0)
    alpha_threshold = as_int(data, "alpha_threshold", 12, 0)
    morph = as_int(data, "morph", 1, 0)
    feather = as_float(data, "feather", 0.3, 0.0)
    webp_duration = as_int(data, "webp_duration", 80, 1)
    model = str(data.get("model") or "u2net")

    command = [
        sys.executable,
        "-u",
        str(ROOT / "process_video_sprites.py"),
        str(input_path),
        "-o",
        str(output_dir),
        "--max-frames",
        str(max_frames),
        "--every-n",
        str(every_n),
        "--start-sec",
        str(start_sec),
        "--size",
        f"{width}x{height}",
        "--padding",
        str(padding),
        "--alpha-threshold",
        str(alpha_threshold),
        "--feather",
        str(feather),
        "--morph",
        str(morph),
        "--model",
        model,
    ]

    if end_sec_raw not in (None, ""):
        command.extend(["--end-sec", str(as_float(data, "end_sec", start_sec + 1, 0.0))])
    if data.get("export_sheet", True):
        command.extend(["--sheet", "--columns", str(columns), "--spacing", str(spacing)])
    if data.get("export_webp", True):
        command.extend(["--webp", "--webp-duration", str(webp_duration)])
    if data.get("export_zip", True):
        command.append("--zip")
    if not data.get("crop", True):
        command.append("--no-crop")

    scene_threshold = data.get("scene_threshold")
    if scene_threshold not in (None, ""):
        command.extend(["--scene-threshold", str(float(scene_threshold))])
    return command


def run_job(command: list[str], output_dir: Path) -> None:
    append_log("Starting job...")
    append_log(" ".join(command))
    try:
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            append_log(line)
        returncode = process.wait()
        with job_lock:
            job.returncode = returncode
            job.running = False
            job.finished_at = time.time()
            if returncode != 0:
                job.error = f"Process exited with code {returncode}"
        append_log("Done." if returncode == 0 else f"Failed with code {returncode}.")
    except Exception as exc:
        with job_lock:
            job.returncode = -1
            job.running = False
            job.finished_at = time.time()
            job.error = str(exc)
        append_log(f"ERROR: {exc}")


@app.get("/")
def index() -> str:
    ensure_dirs()
    return render_template("index.html", videos=list_videos(), lang=get_lang())


@app.get("/api/video-meta")
def video_meta() -> Response:
    ensure_dirs()
    selected = request.args.get("video") or ""
    try:
        path = safe_project_path(selected)
        if not path.exists():
            return jsonify({"error": "Video file does not exist."}), 404
        return jsonify(get_video_meta(path))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/start")
def start() -> Response:
    ensure_dirs()
    with job_lock:
        if job.running:
            return jsonify({"error": "A job is already running."}), 409

    upload = request.files.get("upload")
    if upload and upload.filename:
        safe_name = secure_filename(upload.filename)
        if Path(safe_name).suffix.lower() not in ALLOWED_VIDEO_EXTS:
            return jsonify({"error": "Unsupported video file type."}), 400
        input_path = INPUTS_DIR / safe_name
        upload.save(input_path)
    else:
        selected = request.form.get("video") or ""
        try:
            input_path = safe_project_path(selected)
        except ValueError:
            return jsonify({"error": "Invalid input path."}), 400
        if not input_path.exists():
            return jsonify({"error": "Video file does not exist."}), 400

    stamp = time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}"
    output_dir = OUTPUTS_DIR / f"{input_path.stem}_{stamp}"
    form_data = request.form.to_dict()
    for key in ("crop", "export_sheet", "export_webp", "export_zip"):
        form_data[key] = key in request.form
    command = build_command(form_data, input_path, output_dir)

    with job_lock:
        job.running = True
        job.returncode = None
        job.command = command
        job.output_dir = str(output_dir.relative_to(ROOT))
        job.logs = []
        job.started_at = time.time()
        job.finished_at = None
        job.error = None

    thread = threading.Thread(target=run_job, args=(command, output_dir), daemon=True)
    thread.start()
    return jsonify({"ok": True, "output_dir": job.output_dir})


def output_files_for(output_dir: str) -> list[dict[str, str]]:
    files = [
        ("sprite_sheet.png", "Sprite Sheet"),
        ("animation.webp", "Animated WebP"),
        ("frames.zip", "Frames ZIP"),
        ("manifest.json", "Manifest"),
        ("summary.json", "Summary"),
    ]
    result = []
    output_url_dir = output_relative_url_dir(output_dir)
    for name, label in files:
        path = ROOT / output_dir / name
        if path.exists() and path.stat().st_size > 0:
            result.append({"name": name, "label": label, "url": f"/outputs/{output_url_dir}/{name}"})
    return result


@app.get("/api/status")
def status() -> Response:
    with job_lock:
        data = json.loads(json.dumps(job.__dict__))
    output_url_dir = output_relative_url_dir(data["output_dir"]) if data.get("output_dir") else ""
    data["output_url"] = f"/outputs/{output_url_dir}" if output_url_dir else ""
    data["output_files"] = output_files_for(data["output_dir"]) if data.get("output_dir") else []
    data["preview_frames"] = []
    if data.get("output_dir"):
        frames_dir = ROOT / data["output_dir"] / "frames"
        if frames_dir.exists():
            data["preview_frames"] = [
                f"/outputs/{output_url_dir}/frames/{path.name}"
                for path in sorted(frames_dir.glob("*.png"))[:24]
            ]
    return jsonify(data)


@app.get("/outputs/<path:filename>")
def outputs(filename: str) -> Response:
    try:
        path = safe_output_path(filename)
    except ValueError:
        return jsonify({"error": "Invalid output path."}), 400
    if not path.exists() or not path.is_file():
        return jsonify({"error": "Output file does not exist."}), 404
    return send_from_directory(OUTPUTS_DIR, filename)


if __name__ == "__main__":
    claim_single_instance()
    import atexit

    atexit.register(cleanup_lock)
    ensure_dirs()
    app.run(host="127.0.0.1", port=7860, debug=False)
