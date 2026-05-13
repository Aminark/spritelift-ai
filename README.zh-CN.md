# SpriteLift AI

一个把视频转换成透明游戏序列帧素材的本地 AI 工具。

SpriteLift AI 使用 Python、OpenCV 和 `rembg`：从视频中抽帧，用 AI 移除背景，清理透明边缘，裁剪主体，统一画布尺寸，最后导出透明 PNG 序列、sprite sheet、透明 WebP 和透明帧 ZIP。

> English documentation: [README.md](./README.md)

## 为什么做这个？

- **不要求绿幕**：普通视频也可以用 AI 做主体分割。
- **面向游戏素材**：直接导出透明 PNG、精灵图、WebP 动画和 ZIP。
- **本地 WebUI**：选择视频、设置时间段、调质量、看日志、预览结果都在浏览器里完成。
- **抽帧可控**：支持开始秒数、结束秒数、最大帧数、抽帧间隔和画面变化过滤。
- **边缘可调**：支持透明阈值、柔化、形态学清理、裁剪留白和统一画布。
- **容易二开**：核心是 Python + OpenCV + Pillow + rembg。

## WebUI 功能

- 显示视频时长、FPS、分辨率
- 处理前预估抽帧数量
- 三种质量预设：Quick、Balanced、Sharp
- 导出开关：Sprite Sheet、Animated WebP、Frames ZIP
- 实时日志和实际运行命令
- 透明棋盘背景帧预览
- Sprite sheet 大图预览和下载入口
- 前端已拆分为 HTML/CSS/JS，并支持中文/英文切换

## 快速开始

### Windows 一键启动

双击：

```text
start_web.bat
```

然后打开：

```text
http://127.0.0.1:7860
```

脚本会在需要时自动创建 `.venv` 并安装依赖。

### 手动启动

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe web_app.py
```

第一次运行 `rembg` 可能会下载模型文件，后续会复用本地缓存。

## 命令行示例

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

## 输出内容

- `frames/*.png`：透明 PNG 序列帧
- `sprite_sheet.png`：透明精灵图
- `animation.webp`：透明动态 WebP
- `frames.zip`：透明 PNG 单帧打包
- `manifest.json`：每帧来源、裁剪框、sprite sheet 坐标
- `summary.json`：输出摘要，方便其他工具读取

## 项目结构

```text
process_video_sprites.py   OpenCV/rembg 核心处理流程
web_app.py                 Flask 后端与任务运行器
templates/index.html       WebUI 模板
static/app.css             WebUI 样式
static/app.js              WebUI 交互和中英文切换
start_web.bat              Windows 一键启动脚本
```

## 参数建议

- `--size 512x512`：常规游戏素材推荐
- `--size 768x768`：更清晰，但处理更慢、文件更大
- `--every-n 2`：动画更顺滑
- `--every-n 4`：帧数更少，适合快速测试
- `--start-sec 1.5`：从第 1.5 秒开始
- `--end-sec 4.5`：处理到第 4.5 秒结束
- `--model u2net`：默认均衡模型
- `--model isnet-general-use`：复杂主体可以尝试
- `--model u2netp`：速度更快，质量会低一些

## 适合场景

- 把 AI 生成视频转成游戏角色序列帧
- 把短视频动作转成透明 sprite sheet
- 快速制作 2D 游戏、Web 动画、特效素材
- 给引擎或动画工具准备统一尺寸的透明帧

## 推荐 GitHub Topics

```text
python, opencv, rembg, sprite-sheet, background-removal, game-assets, webp, png-sequence
```

## 开源协议

MIT License。详见 [LICENSE](./LICENSE)。
