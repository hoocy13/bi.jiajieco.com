/* Original Xiaomi-OCR-0 UI, served inside BI. No credentials enter the iframe. */
window.biOcr = (() => {
  const pending = new Map();
  window.addEventListener('message', event => {
    if (event.origin !== location.origin || event.source !== parent || event.data?.channel !== 'jjc-ocr-reply') return;
    const entry = pending.get(event.data.id);
    if (!entry) return;
    pending.delete(event.data.id); clearTimeout(entry.timer);
    event.data.error ? entry.reject(new Error(event.data.error)) : entry.resolve(event.data.data);
  });
  function call(operation, payload = {}) {
    if (parent === window) return Promise.reject(new Error('请从 BI 网站的文档识别页面使用此工具'));
    return new Promise((resolve, reject) => {
      const id = crypto.randomUUID();
      const timer = setTimeout(() => { pending.delete(id); reject(new Error('连接 BI 超时，请刷新页面重试')); }, 45000);
      pending.set(id, { resolve, reject, timer });
      parent.postMessage({channel:'jjc-ocr-request',id,operation,payload},location.origin);
    });
  }
  async function run(source, options) {
    const blob = typeof source === 'string' ? await (await fetch(source)).blob() : source;
    if (blob.size > 20 * 1024 * 1024) throw new Error('文件不能超过 20 MB，PDF 最多支持 20 页');
    const started = performance.now();
    const job = await call('submit', { source:blob, filename:source.name || 'image.png', ...options });
    return wait(job.id, started);
  }
  async function wait(jobId, started = performance.now()) {
    const progress = document.getElementById('taskProgress');
    progress.hidden = false;
    try {
      while (true) {
        const current = await call('job', {id:jobId});
        const total = current.pages_total || 0;
        const done = current.pages_done || 0;
        document.getElementById('taskProgressFill').style.width = (total ? Math.round(done / total * 100) : 0) + '%';
        const message = current.status === 'queued' ? '等待识别节点领取任务' : current.mode === 'region'
          ? `正在识别 ${done}/${total || '…'} 页 · 区域 ${current.regions_done}/${current.regions_total || '…'}`
          : `正在识别 ${done}/${total || '…'} 页`;
        uiText('sideHint', () => message);
        if (current.status === 'succeeded') return {
          content:current.result, pages:total, latency_ms:Math.round(performance.now()-started), usage:{}, model:'longwayxu/xiaomi-ocr-0:bf16',
          region_count:current.regions_total, regions_done:current.regions_done,
        };
        if (['failed','expired'].includes(current.status)) throw new Error(current.error || '任务未完成');
        await new Promise(resolve => setTimeout(resolve, 2000));
      }
    } finally { progress.hidden = true; }
  }
  window.addEventListener('message', async event => {
    if (event.origin !== location.origin || event.source !== parent || event.data?.channel !== 'jjc-ocr-restore') return;
    if (state.busy) { showError('当前任务正在识别，请完成后再查看历史任务'); return; }
    const {job,source} = event.data;
    if (!job || !(source instanceof Blob)) return;
    setBusy(true);
    try {
      if (state.pdfUrl) URL.revokeObjectURL(state.pdfUrl);
      state.activeId = 'custom'; state.task = job.task; state.mode = job.mode || 'page';
      $('docPrompt').value = job.prompt || '';
      $('kieFields').value = job.fields || '';
      $('vqaQuestion').value = job.question || '';
      const isPdf = source.type === 'application/pdf';
      const file = new File([source], job.filename, {type:source.type});
      if (isPdf) {
        state.pdfUrl = URL.createObjectURL(file);
        state.custom = {name:job.filename,file,isPdf:true,size:file.size};
        $('stagePdf').src = state.pdfUrl;
      } else {
        const dataUrl = await blobToDataUrl(file);
        state.custom = {name:job.filename,dataUrl,isPdf:false,size:file.size};
        $('stageImg').src = dataUrl; $('stageImg').alt = job.filename;
      }
      $('stagePdf').hidden = !isPdf; $('stageImg').hidden = isPdf;
      uiText('stageTitle', () => job.filename); uiText('badgeLeft', () => isPdf ? 'PDF' : 'IMAGE');
      document.querySelectorAll('#taskSeg button').forEach(b => {b.classList.toggle('active',b.dataset.task===job.task);b.setAttribute('aria-pressed',String(b.dataset.task===job.task));});
      document.querySelectorAll('#modeSeg button').forEach(b => {b.classList.toggle('active',b.dataset.mode===state.mode);b.setAttribute('aria-pressed',String(b.dataset.mode===state.mode));});
      document.querySelectorAll('.film').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.film-upload').forEach(b => b.classList.add('active'));
      updateTaskInputs(); resetResult(); clearError();
      if (job.status === 'failed') { showError(job.error || '识别失败，请重新提交'); return; }
      const result = job.status === 'succeeded' ? {content:job.result,model:'longwayxu/xiaomi-ocr-0:bf16'} : await wait(job.id);
      recordResult(result.content,result);
      $('resEmpty').style.display = 'none'; $('resText').style.display = 'block';
      paintResult(); uiText('badgeRight', () => t('已完成')); setLed('on');
      uiText('pillModeText', () => t('已完成'));
      uiText('stageHint', () => (isPdf ? 'PDF' : job.task.toUpperCase()) + ' · DONE');
      uiText('sideHint', () => t('点击画面可重新解析'));
    } catch (error) { showError(error.message || '恢复任务失败'); }
    finally { setBusy(false); }
  });
  const resize = () => parent.postMessage({channel:'jjc-ocr-size',height:Math.ceil(document.querySelector('.shell')?.getBoundingClientRect().height || document.body.scrollHeight)},location.origin);
  window.addEventListener('DOMContentLoaded', () => { new ResizeObserver(resize).observe(document.querySelector('.shell') || document.body); resize(); });
  return {call,run};
})();
