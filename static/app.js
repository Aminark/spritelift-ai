const I18N = {
  zh: {
    subtitle: '把视频里的主体提取成透明游戏序列帧、精灵图和 WebP 动画。',
    idle: '待机',
    inputRange: '输入与时间范围',
    existingVideo: '已有视频',
    uploadVideo: '上传新视频',
    startSecond: '开始秒数',
    endSecond: '结束秒数',
    endPlaceholder: '留空表示到视频结束',
    maxFrames: '最大帧数',
    everyN: '每 N 帧抽取',
    duration: '时长',
    resolution: '分辨率',
    estimatedFrames: '预计抽帧',
    rangeHint: '只处理动作最完整的一小段会更快，也更容易得到干净的 sprite sheet。',
    aiExport: 'AI 与导出设置',
    qualityPreset: '质量预设',
    aiModel: 'AI 模型',
    canvasWidth: '画布宽度',
    canvasHeight: '画布高度',
    sheetColumns: 'Sheet 列数',
    sheetSpacing: 'Sheet 间距',
    webpDuration: 'WebP 帧时长 ms',
    sceneThreshold: '变化过滤阈值',
    disabledPlaceholder: '留空关闭',
    alphaThreshold: '透明阈值',
    feather: '边缘柔化',
    morph: '边缘清理',
    padding: '裁剪留白',
    autoCrop: '自动裁剪主体并居中',
    exportSheet: '导出透明 Sprite Sheet',
    exportWebp: '导出透明 Animated WebP',
    exportZip: '打包透明 PNG 序列 ZIP',
    start: '开始处理',
    refresh: '刷新',
    qualityHint: '高清素材建议 512 或 768。复杂背景可尝试 isnet-general-use，但速度会慢一些。',
    resultsLogs: '结果与日志',
    preview: '预览',
    logs: '日志',
    command: '命令',
    emptyPreview: '处理完成后，这里会显示透明帧预览和下载入口。',
    noCommand: '还没有运行命令。',
    uploadMetaPending: '上传文件会在开始处理后读取',
    videoInfo: '视频信息',
    noVideo: '没有找到视频，请先上传',
    readFailed: '读取失败',
    submitting: '正在提交任务...',
    output: '输出',
    statusRefreshFailed: '状态刷新失败',
    languageToggle: 'English',
  },
  en: {
    subtitle: 'Extract transparent game-ready frame sequences, sprite sheets, and WebP animations from videos.',
    idle: 'Idle',
    inputRange: 'Input & Time Range',
    existingVideo: 'Existing video',
    uploadVideo: 'Upload video',
    startSecond: 'Start second',
    endSecond: 'End second',
    endPlaceholder: 'Leave empty to process until the end',
    maxFrames: 'Max frames',
    everyN: 'Extract every N frames',
    duration: 'Duration',
    resolution: 'Resolution',
    estimatedFrames: 'Estimated frames',
    rangeHint: 'Processing only the useful motion range is faster and usually produces cleaner sprite sheets.',
    aiExport: 'AI & Export Settings',
    qualityPreset: 'Quality preset',
    aiModel: 'AI model',
    canvasWidth: 'Canvas width',
    canvasHeight: 'Canvas height',
    sheetColumns: 'Sheet columns',
    sheetSpacing: 'Sheet spacing',
    webpDuration: 'WebP frame duration ms',
    sceneThreshold: 'Scene threshold',
    disabledPlaceholder: 'Empty means disabled',
    alphaThreshold: 'Alpha threshold',
    feather: 'Edge feather',
    morph: 'Edge cleanup',
    padding: 'Crop padding',
    autoCrop: 'Auto-crop subject and center it',
    exportSheet: 'Export transparent Sprite Sheet',
    exportWebp: 'Export transparent Animated WebP',
    exportZip: 'Bundle transparent PNG frames as ZIP',
    start: 'Start Processing',
    refresh: 'Refresh',
    qualityHint: 'Use 512 or 768 for sharper assets. Try isnet-general-use for complex subjects.',
    resultsLogs: 'Results & Logs',
    preview: 'Preview',
    logs: 'Logs',
    command: 'Command',
    emptyPreview: 'Transparent frame previews and download links will appear here after processing.',
    noCommand: 'No command has been run yet.',
    uploadMetaPending: 'Uploaded files are read after processing starts',
    videoInfo: 'Video info',
    noVideo: 'No video found. Upload one first.',
    readFailed: 'Failed to read',
    submitting: 'Submitting job...',
    output: 'Output',
    statusRefreshFailed: 'Status refresh failed',
    languageToggle: '中文',
  },
};

let lang = localStorage.getItem('spritelift_lang') || window.APP_LANG || 'zh';
if (!I18N[lang]) lang = 'zh';
const t = (key) => I18N[lang][key] || key;

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
const languageToggle = document.getElementById('languageToggle');
let timer = null;
let currentMeta = null;

function applyLanguage() {
  document.documentElement.lang = lang;
  document.querySelectorAll('[data-i18n]').forEach((node) => {
    node.textContent = t(node.dataset.i18n);
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach((node) => {
    node.placeholder = t(node.dataset.i18nPlaceholder);
  });
  languageToggle.textContent = t('languageToggle');
  if (!summary.dataset.hasOutput) summary.textContent = t('idle');
  if (!commandText.dataset.hasCommand) commandText.textContent = t('noCommand');
  if (currentMeta) renderMeta(currentMeta);
}

languageToggle.addEventListener('click', () => {
  lang = lang === 'zh' ? 'en' : 'zh';
  localStorage.setItem('spritelift_lang', lang);
  applyLanguage();
});

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
    setMetaText(t('uploadMetaPending'));
  } else {
    loadSelectedMeta();
  }
});

function setMetaText(message) {
  document.getElementById('videoMeta').innerHTML =
    `<div class="metric wide"><span>${t('videoInfo')}</span><strong>${message}</strong></div>`;
}

function renderMeta(meta) {
  document.getElementById('videoMeta').innerHTML = `
    <div class="metric"><span>${t('duration')}</span><strong>${meta.duration}s</strong></div>
    <div class="metric"><span>FPS</span><strong>${meta.fps}</strong></div>
    <div class="metric"><span>${t('resolution')}</span><strong>${meta.width}x${meta.height}</strong></div>
    <div class="metric"><span>${t('estimatedFrames')}</span><strong id="estimate">-</strong></div>
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
    setMetaText(t('noVideo'));
    return;
  }
  try {
    const response = await fetch(`/api/video-meta?video=${encodeURIComponent(videoSelect.value)}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || t('readFailed'));
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
  summary.textContent = t('submitting');
  summary.dataset.hasOutput = '';
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
    logs.textContent = `${logs.textContent}\n${t('statusRefreshFailed')}: ${error.message}`;
    return;
  }
  logs.textContent = (data.logs || []).join('\n');
  logs.scrollTop = logs.scrollHeight;
  commandText.textContent = (data.command || []).join(' ') || t('noCommand');
  commandText.dataset.hasCommand = data.command && data.command.length ? '1' : '';
  badge.textContent = data.running ? 'Running' : (data.returncode === 0 ? 'Done' : 'Ready');
  if (data.output_dir) {
    summary.textContent = `${t('output')}: ${data.output_dir}`;
    summary.dataset.hasOutput = '1';
  } else {
    summary.textContent = t('idle');
    summary.dataset.hasOutput = '';
  }
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

applyLanguage();
loadSelectedMeta();
poll();
