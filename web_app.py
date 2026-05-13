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
from flask import Flask, Response, jsonify, render_template_string, request, send_from_directory
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


def safe_project_path(relative_path: str) -> Path:
    path = (ROOT / relative_path).resolve()
    if ROOT not in path.parents and path != ROOT:
        raise ValueError("Invalid path.")
    return path


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


HTML = r"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SpriteLift AI Studio</title>
  <style>
    :root {
      color-scheme: light;
      --ink: #172033;
      --muted: #657186;
      --subtle: #8a96a8;
      --line: #d8e0ea;
      --panel: #f7f9fc;
      --accent: #2563eb;
      --accent-strong: #1d4ed8;
      --shadow: 0 12px 32px rgba(20, 31, 48, .08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", "Microsoft YaHei", system-ui, sans-serif;
      color: var(--ink);
      background: #edf2f7;
    }
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 20px;
      padding: 20px 28px 16px;
      border-bottom: 1px solid var(--line);
      background: #fff;
    }
    h1 { margin: 0; font-size: 24px; letter-spacing: 0; }
    h2 { margin: 0 0 12px; font-size: 15px; }
    .sub { margin: 5px 0 0; color: var(--muted); font-size: 13px; }
    .top-status { display: flex; align-items: center; gap: 10px; color: var(--muted); font-size: 13px; white-space: nowrap; }
    .badge { padding: 5px 10px; border-radius: 999px; background: #dbeafe; color: #1e40af; font-weight: 700; }
    main {
      display: grid;
      grid-template-columns: minmax(360px, 430px) minmax(360px, 430px) minmax(460px, 1fr);
      gap: 16px;
      padding: 16px 24px 24px;
    }
    .tool-form { display: contents; }
    section {
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
      box-shadow: var(--shadow);
    }
    label { display: grid; gap: 6px; color: var(--muted); font-size: 13px; }
    input, select {
      width: 100%;
      height: 38px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 0 10px;
      font: inherit;
      color: var(--ink);
      background: #fff;
    }
    input[type="checkbox"] { width: 18px; height: 18px; }
    input[type="file"] { padding-top: 7px; }
    .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
    .wide { grid-column: 1 / -1; }
    .check-grid { display: grid; gap: 8px; margin-top: 10px; }
    .check {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 9px 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--panel);
      color: var(--ink);
      font-size: 13px;
    }
    .metrics { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin: 12px 0 2px; }
    .metric { padding: 10px; border: 1px solid var(--line); border-radius: 6px; background: var(--panel); }
    .metric span { display: block; color: var(--subtle); font-size: 12px; }
    .metric strong { display: block; margin-top: 3px; font-size: 15px; }
    .actions { display: grid; grid-template-columns: 1fr auto; gap: 10px; margin-top: 16px; }
    button {
      height: 42px;
      border: 0;
      border-radius: 6px;
      padding: 0 16px;
      font: inherit;
      font-weight: 700;
      color: #fff;
      background: var(--accent);
      cursor: pointer;
    }
    button:hover { background: var(--accent-strong); }
    button.secondary { color: var(--ink); background: #e2e8f0; }
    button:disabled { opacity: .55; cursor: wait; }
    .hint { margin: 10px 0 0; color: var(--muted); font-size: 12px; line-height: 1.5; }
    .result-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
    .tabs { display: flex; gap: 6px; }
    .tab { height: 32px; padding: 0 11px; color: var(--ink); background: #e8eef6; font-size: 13px; }
    .tab.active { color: #fff; background: var(--accent); }
    .panel { display: none; }
    .panel.active { display: block; }
    pre {
      min-height: 260px;
      max-height: 460px;
      margin: 0;
      overflow: auto;
      padding: 12px;
      border-radius: 6px;
      background: #0f172a;
      color: #e2e8f0;
      font-size: 12px;
      line-height: 1.55;
      white-space: pre-wrap;
    }
    .outputs { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-bottom: 12px; }
    .outputs a {
      display: block;
      padding: 11px 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      color: var(--accent-strong);
      text-align: center;
      text-decoration: none;
      background: var(--panel);
      font-weight: 700;
      overflow-wrap: anywhere;
    }
    .checker {
      background:
        linear-gradient(45deg, #dfe7ef 25%, transparent 25%),
        linear-gradient(-45deg, #dfe7ef 25%, transparent 25%),
        linear-gradient(45deg, transparent 75%, #dfe7ef 75%),
        linear-gradient(-45deg, transparent 75%, #dfe7ef 75%);
      background-size: 18px 18px;
      background-position: 0 0, 0 9px, 9px -9px, -9px 0;
      background-color: #f8fafc;
    }
    .sheet-preview { display: none; width: 100%; max-height: 360px; object-fit: contain; border: 1px solid var(--line); border-radius: 6px; margin-bottom: 12px; }
    .preview-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(92px, 1fr)); gap: 10px; }
    .preview-grid img { width: 100%; aspect-ratio: 1 / 1; object-fit: contain; border: 1px solid var(--line); border-radius: 6px; }
    .empty { padding: 18px; border: 1px dashed var(--line); border-radius: 6px; color: var(--muted); background: var(--panel); text-align: center; font-size: 13px; }
    .command { padding: 12px; border: 1px solid var(--line); border-radius: 6px; background: var(--panel); color: var(--muted); font-size: 12px; line-height: 1.6; overflow-wrap: anywhere; }
    @media (max-width: 1220px) {
      main { grid-template-columns: 1fr 1fr; }
      .results { grid-column: 1 / -1; }
    }
    @media (max-width: 820px) {
      header { align-items: flex-start; flex-direction: column; padding: 18px 14px; }
      main { grid-template-columns: 1fr; padding: 14px; }
      .outputs { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>SpriteLift AI Studio</h1>
      <p class="sub">把视频里的主体提取成透明游戏序列帧、精灵图和 WebP 动画。</p>
    </div>
    <div class="top-status">
      <span id="summary">待机</span>
      <span id="badge" class="badge">Ready</span>
    </div>
  </header>

  <main>
    <form id="jobForm" class="tool-form">
    <section>
      <h2>输入与时间范围</h2>
        <div class="grid">
          <label class="wide">已有视频
            <select name="video" id="videoSelect">
              {% for video in videos %}
              <option value="{{ video }}">{{ video }}</option>
              {% endfor %}
            </select>
          </label>
          <label class="wide">上传新视频
            <input name="upload" id="uploadInput" type="file" accept="video/*">
          </label>
          <label>开始秒数
            <input name="start_sec" type="number" min="0" step="0.1" value="0">
          </label>
          <label>结束秒数
            <input name="end_sec" type="number" min="0" step="0.1" placeholder="留空表示到视频结束">
          </label>
          <label>最大帧数
            <input name="max_frames" type="number" min="1" value="30">
          </label>
          <label>每 N 帧抽取
            <input name="every_n" type="number" min="1" value="3">
          </label>
        </div>
        <div class="metrics" id="videoMeta">
          <div class="metric"><span>时长</span><strong>-</strong></div>
          <div class="metric"><span>FPS</span><strong>-</strong></div>
          <div class="metric"><span>分辨率</span><strong>-</strong></div>
          <div class="metric"><span>预计抽帧</span><strong id="estimate">-</strong></div>
        </div>
        <p class="hint">只处理动作最完整的一小段会更快，也更容易得到干净的 sprite sheet。</p>
    </section>

    <section>
      <h2>AI 与导出设置</h2>
        <div class="grid">
          <label>质量预设
            <select id="preset">
              <option value="balanced">Balanced 512</option>
              <option value="sharp">Sharp 768</option>
              <option value="quick">Quick 256</option>
            </select>
          </label>
          <label>AI 模型
            <select name="model">
              <option value="u2net">u2net</option>
              <option value="isnet-general-use">isnet-general-use</option>
              <option value="u2netp">u2netp</option>
            </select>
          </label>
          <label>画布宽度
            <input name="width" type="number" min="1" value="512">
          </label>
          <label>画布高度
            <input name="height" type="number" min="1" value="512">
          </label>
          <label>Sheet 列数
            <input name="columns" type="number" min="1" value="6">
          </label>
          <label>Sheet 间距
            <input name="spacing" type="number" min="0" value="0">
          </label>
          <label>WebP 帧时长 ms
            <input name="webp_duration" type="number" min="1" value="80">
          </label>
          <label>变化过滤阈值
            <input name="scene_threshold" type="number" min="0" step="0.1" placeholder="留空关闭">
          </label>
          <label>透明阈值
            <input name="alpha_threshold" type="number" min="0" max="255" value="12">
          </label>
          <label>边缘柔化
            <input name="feather" type="number" min="0" step="0.1" value="0.3">
          </label>
          <label>边缘清理
            <input name="morph" type="number" min="0" value="1">
          </label>
          <label>裁剪留白
            <input name="padding" type="number" min="0" value="12">
          </label>
        </div>
        <div class="check-grid">
          <label class="check"><input name="crop" type="checkbox" checked> 自动裁剪主体并居中</label>
          <label class="check"><input name="export_sheet" type="checkbox" checked> 导出透明 Sprite Sheet</label>
          <label class="check"><input name="export_webp" type="checkbox" checked> 导出透明 Animated WebP</label>
          <label class="check"><input name="export_zip" type="checkbox" checked> 打包透明 PNG 序列 ZIP</label>
        </div>
        <div class="actions">
          <button id="startBtn" type="submit">开始处理</button>
          <button class="secondary" type="button" onclick="location.reload()">刷新</button>
        </div>
        <p class="hint">高清素材建议 512 或 768。复杂背景可尝试 isnet-general-use，但速度会慢一些。</p>
    </section>
    </form>

    <section class="results">
      <div class="result-head">
        <h2>结果与日志</h2>
        <div class="tabs">
          <button class="tab active" data-tab="gallery" type="button">预览</button>
          <button class="tab" data-tab="logs" type="button">日志</button>
          <button class="tab" data-tab="command" type="button">命令</button>
        </div>
      </div>
      <div id="galleryPanel" class="panel active">
        <div class="outputs" id="outputs"></div>
        <img id="sheetPreview" class="sheet-preview checker" alt="Sprite sheet preview">
        <div class="preview-grid" id="previews"></div>
        <div class="empty" id="emptyPreview">处理完成后，这里会显示透明帧预览和下载入口。</div>
      </div>
      <div id="logsPanel" class="panel">
        <pre id="logs"></pre>
      </div>
      <div id="commandPanel" class="panel">
        <div class="command" id="commandText">还没有运行命令。</div>
      </div>
    </section>
  </main>

  <script>
    const form = document.getElementById('jobForm');
    const startBtn = document.getElementById('startBtn');
    const logs = document.getElementById('logs');
    const summary = document.getElementById('summary');
    const badge = document.getElementById('badge');
    const outputs = document.getElementById('outputs');
    const previews = document.getElementById('previews');
    const emptyPreview = document.getElementById('emptyPreview');
    const sheetPreview = document.getElementById('sheetPreview');
    const preset = document.getElementById('preset');
    const videoSelect = document.getElementById('videoSelect');
    const uploadInput = document.getElementById('uploadInput');
    const commandText = document.getElementById('commandText');
    let timer = null;
    let currentMeta = null;

    document.querySelectorAll('.tab').forEach((button) => {
      button.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach((item) => item.classList.remove('active'));
        document.querySelectorAll('.panel').forEach((item) => item.classList.remove('active'));
        button.classList.add('active');
        document.getElementById(`${button.dataset.tab}Panel`).classList.add('active');
      });
    });

    preset.addEventListener('change', () => {
      const values = {
        quick: { width: 256, height: 256, feather: 0.2, morph: 0, every_n: 4, max_frames: 20 },
        balanced: { width: 512, height: 512, feather: 0.3, morph: 1, every_n: 3, max_frames: 30 },
        sharp: { width: 768, height: 768, feather: 0.15, morph: 1, every_n: 2, max_frames: 40 },
      }[preset.value];
      for (const [name, value] of Object.entries(values)) {
        const input = form.elements[name];
        if (input) input.value = value;
      }
      updateEstimate();
    });

    ['start_sec', 'end_sec', 'every_n', 'max_frames'].forEach((name) => {
      form.elements[name].addEventListener('input', updateEstimate);
    });
    videoSelect.addEventListener('change', loadSelectedMeta);
    uploadInput.addEventListener('change', () => {
      if (uploadInput.files.length) {
        setMetaText('上传文件会在开始处理后读取');
      } else {
        loadSelectedMeta();
      }
    });

    function setMetaText(message) {
      document.getElementById('videoMeta').innerHTML = `<div class="metric wide"><span>视频信息</span><strong>${message}</strong></div>`;
    }

    function renderMeta(meta) {
      document.getElementById('videoMeta').innerHTML = `
        <div class="metric"><span>时长</span><strong>${meta.duration}s</strong></div>
        <div class="metric"><span>FPS</span><strong>${meta.fps}</strong></div>
        <div class="metric"><span>分辨率</span><strong>${meta.width}x${meta.height}</strong></div>
        <div class="metric"><span>预计抽帧</span><strong id="estimate">-</strong></div>
      `;
      currentMeta = meta;
      updateEstimate();
    }

    function updateEstimate() {
      const target = document.getElementById('estimate');
      if (!target || !currentMeta) return;
      const start = Number(form.elements.start_sec.value || 0);
      const endValue = form.elements.end_sec.value;
      const end = endValue === '' ? currentMeta.duration : Number(endValue);
      const everyN = Math.max(1, Number(form.elements.every_n.value || 1));
      const maxFrames = Math.max(1, Number(form.elements.max_frames.value || 1));
      const fps = Math.max(1, Number(currentMeta.fps || 1));
      const raw = Math.max(1, Math.floor(Math.max(0, end - start) * fps / everyN) + 1);
      target.textContent = `${Math.min(raw, maxFrames)} / ${raw}`;
    }

    async function loadSelectedMeta() {
      if (!videoSelect.value) {
        setMetaText('没有找到视频，请先上传');
        return;
      }
      try {
        const response = await fetch(`/api/video-meta?video=${encodeURIComponent(videoSelect.value)}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || '读取失败');
        renderMeta(data);
      } catch (error) {
        setMetaText(error.message);
      }
    }

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const body = new FormData(form);
      startBtn.disabled = true;
      badge.textContent = 'Starting';
      summary.textContent = '正在提交任务...';
      logs.textContent = 'Submitting...';
      outputs.innerHTML = '';
      previews.innerHTML = '';
      emptyPreview.style.display = 'block';
      sheetPreview.style.display = 'none';
      const response = await fetch('/api/start', { method: 'POST', body });
      const data = await response.json();
      if (!response.ok) {
        logs.textContent = data.error || 'Start failed';
        startBtn.disabled = false;
        return;
      }
      timer = setInterval(poll, 1000);
      poll();
    });

    function makeOutputLinks(data) {
      return (data.output_files || []).map((item) => (
        `<a href="${item.url}" target="_blank">${item.label}</a>`
      )).join('');
    }

    async function poll() {
      let data;
      try {
        const response = await fetch(`/api/status?ts=${Date.now()}`, { cache: 'no-store' });
        data = await response.json();
      } catch (error) {
        logs.textContent = `${logs.textContent}\nStatus refresh failed: ${error.message}`;
        return;
      }
      logs.textContent = (data.logs || []).join('\n');
      logs.scrollTop = logs.scrollHeight;
      commandText.textContent = (data.command || []).join(' ') || '还没有运行命令。';
      badge.textContent = data.running ? 'Running' : (data.returncode === 0 ? 'Done' : 'Ready');
      summary.textContent = data.output_dir ? `输出：${data.output_dir}` : '待机';
      startBtn.disabled = data.running;
      if (!data.running && timer) {
        clearInterval(timer);
        timer = null;
      }
      if (data.output_url && ((data.output_files || []).length || (data.preview_frames || []).length)) {
        outputs.innerHTML = makeOutputLinks(data);
        const sheet = (data.output_files || []).find((item) => item.name === 'sprite_sheet.png');
        if (sheet) {
          sheetPreview.src = `${sheet.url}?t=${Date.now()}`;
          sheetPreview.style.display = 'block';
        }
        previews.innerHTML = (data.preview_frames || []).map((src) => (
          `<a href="${src}" target="_blank"><img class="checker" src="${src}" loading="lazy" alt=""></a>`
        )).join('');
        emptyPreview.style.display = previews.innerHTML || outputs.innerHTML ? 'none' : 'block';
      }
    }

    loadSelectedMeta();
    poll();
  </script>
</body>
</html>
"""


@app.get("/")
def index() -> str:
    ensure_dirs()
    return render_template_string(HTML, videos=list_videos())


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
    output_url_dir = output_dir.replace("\\", "/")
    for name, label in files:
        path = ROOT / output_dir / name
        if path.exists() and path.stat().st_size > 0:
            result.append({"name": name, "label": label, "url": f"/outputs/{output_url_dir}/{name}"})
    return result


@app.get("/api/status")
def status() -> Response:
    with job_lock:
        data = json.loads(json.dumps(job.__dict__))
    output_url_dir = data["output_dir"].replace("\\", "/") if data.get("output_dir") else ""
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
    return send_from_directory(ROOT, filename)


if __name__ == "__main__":
    claim_single_instance()
    import atexit

    atexit.register(cleanup_lock)
    ensure_dirs()
    app.run(host="127.0.0.1", port=7860, debug=False)
