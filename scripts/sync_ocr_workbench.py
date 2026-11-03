"""Vendor the complete upstream demo; replace transport only. Pass upstream repo path."""
import json
import hashlib
from pathlib import Path
import re
import shutil
import sys

root = Path(__file__).resolve().parents[1]
upstream = Path(sys.argv[1])
destination = root / 'frontend/public/ocr-workbench'
shutil.copytree(upstream / 'demo/static', destination, dirs_exist_ok=True)
for name in ('LICENSE', 'THIRD_PARTY_NOTICES.md'):
    shutil.copy2(upstream / name, destination / name)
(destination / 'example_pics').mkdir(exist_ok=True)
showcase = json.loads((destination / 'showcase.json').read_text(encoding='utf-8'))
for item in showcase['items']:
    shutil.copy2(upstream / 'example_pics' / item['file'], destination / 'example_pics' / item['file'])
    item['image'] = '/ocr-workbench/example_pics/' + item['file']
(destination / 'showcase.json').write_text(json.dumps(showcase, ensure_ascii=False, indent=2), encoding='utf-8')
html = (destination / 'index.html').read_text(encoding='utf-8')
html = re.sub(r'(src|href)="/(?!/)', r'\1="/ocr-workbench/', html)
html = html.replace('<script src="/ocr-workbench/app.js', '<script src="/ocr-workbench/bi-adapter.js"></script>\n<script src="/ocr-workbench/app.js')
(destination / 'index.html').write_text(html, encoding='utf-8')
app = (destination / 'app.js').read_text(encoding='utf-8')

def replace_between(start, end, replacement):
    global app
    left, right = app.index(start), app.index(end, app.index(start))
    app = app[:left] + replacement + '\n\n' + app[right:]

replace_between('async function streamLiveOcr(', '/** Parse all regions', '''async function streamLiveOcr(dataUrl, onDelta, prompt, task) {
  const result = await biOcr.run(dataUrl, {
    task: task || "document", prompt: prompt || LIVE_PROMPT,
    fields: $("kieFields").value || "", question: $("vqaQuestion").value || "",
    max_tokens: task === "vqa" ? 1024 : cfg().max_tokens || 4096,
    filename: state.custom?.name || itemById(state.activeId)?.file || "image.png",
  });
  if (onDelta) onDelta(result.content, result.content);
  return result;
}''')
replace_between('async function runRegionOcr(', '/** Resolve a data URL', '''async function runRegionOcr(dataUrl) {
  const health = await biOcr.call("status");
  if (!health.region_ready) throw new Error("版面检测模型尚未就绪，请稍后重试，或使用整页模式。");
  return biOcr.run(dataUrl, {task:"document", mode:"region", max_tokens:cfg().max_tokens || 4096,
    filename:state.custom?.name || itemById(state.activeId)?.file || "image.png"});
}''')
replace_between('async function runPdfParse(', 'function formatKieResult(', '''async function runPdfParse(file) {
  return biOcr.run(file, { task: "document", mode:state.mode, prompt: $("docPrompt").value || LIVE_PROMPT, max_tokens: cfg().max_tokens || 4096 });
}''')
replace_between('$("btnDownload").onclick = () => {', 'document.addEventListener("keydown"', '''$("btnDownload").onclick = () => {
  if (!state.lastText) return;
  biOcr.call("download", {content:state.lastText, format:state.lastTask === "kie" ? "json" : "md"}).catch(error => showError(error.message));
};''')
replace_between('async function checkHealth()', '// Refresh sample labels', '''async function checkHealth() {
  try {
    const health = await biOcr.call("status");
    updateRegionDependencyStatus({available: !!health.region_ready, missing: health.region_ready ? [] : ["PP-DocLayoutV3 尚未就绪"]});
    $("connDot").classList.toggle("off", !health.online);
    uiText("statusText", () => t(health.online ? "模型已连接" : "模型未连接"));
    $("statusText").title = health.online ? "Xiaomi-OCR-0 · BI 任务节点" : "识别节点离线，任务将等待服务恢复";
  } catch (_) {
    $("connDot").classList.add("off"); uiText("statusText", () => t("服务未连接"));
  }
}''')
app = app.replace('fetch("/showcase.json")', 'fetch("/ocr-workbench/showcase.json")')
app = app.replace('"流式输出中"', '"等待识别结果"').replace('"STREAMING…"', '"QUEUED…"')
app = app.replace('layout + parallel', 'CPU layout').replace('layout + 并发 region OCR', 'CPU 版面检测与区域识别')
app = app.replace('const count = regions.length;', 'const count = data.region_count ?? regions.length;')
app = app.replace('const okN = regions.filter(region => region.ok).length;', 'const okN = data.regions_done ?? regions.filter(region => region.ok).length;')
app = app.replace('uiText("sideHint", () => t("版面检测 {ms}ms · 并发 {count}", {ms: data.layout_ms || 0, count: data.concurrency || 16}));', 'uiText("sideHint", () => "区域识别完成 · " + count + " 个区域");')
app = app.replace('55 * 1024 * 1024', '20 * 1024 * 1024').replace('55 MiB', '20 MB')
(destination / 'app.js').write_text(app, encoding='utf-8')
app_version = hashlib.sha256(app.encode()).hexdigest()[:12]
adapter_version = hashlib.sha256((destination / 'bi-adapter.js').read_bytes()).hexdigest()[:12]
html = html.replace('app.js?v=50', 'app.js?v=bi-' + app_version).replace('bi-adapter.js"', 'bi-adapter.js?v=' + adapter_version + '"')
(destination / 'index.html').write_text(html, encoding='utf-8')
print('Complete upstream UI copied; BI transport adapter applied.')
