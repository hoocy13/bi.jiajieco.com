<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import http from '../../api/http'
import { useAuthStore } from '../../stores/auth'

const frame = ref(null), frameHeight = ref(1500), jobs = ref([]), historyExpanded = ref(false)
const route = useRoute(), router = useRouter()
const auth = useAuthStore()
const modes = { document: '文档解析', kie: '字段提取', vqa: '图像问答' }
const labels = { queued: '等待识别', running: '识别中', succeeded: '已完成', failed: '失败', expired: '已过期' }
const statusType = status => ({ succeeded: 'success', failed: 'danger', running: 'warning' }[status] || 'info')
const raw = { metadata: { rawResponse: true } }
let timer, disposed = false

async function loadHistory() {
  try { const response = await http.get('/tools/ocr/jobs', raw); if (!disposed) jobs.value = response.data.data }
  catch { /* The workbench reports service failures in its original status UI. */ }
}
async function pollHistory() { await loadHistory(); if (!disposed) timer = setTimeout(pollHistory, 10000) }

async function onMessage(event) {
  if (event.origin !== location.origin || event.source !== frame.value?.contentWindow) return
  const message = event.data
  if (message?.channel === 'jjc-ocr-size') {
    if (Number.isFinite(message.height)) frameHeight.value = Math.max(900, Math.min(6000, message.height))
    return
  }
  if (message?.channel !== 'jjc-ocr-request' || typeof message.id !== 'string') return
  const reply = { channel: 'jjc-ocr-reply', id: message.id }
  try {
    const payload = message.payload || {}
    if (message.operation === 'status') {
      reply.data = (await http.get('/tools/ocr/status', raw)).data.data
    } else if (message.operation === 'submit') {
      if (!(payload.source instanceof Blob) || payload.source.size > 20 * 1024 * 1024) throw new Error('文件不能为空或超过 20 MB')
      const form = new FormData()
      form.append('file', payload.source, String(payload.filename || 'document').slice(0, 255))
      for (const key of ['task', 'mode', 'prompt', 'fields', 'question', 'max_tokens']) {
        if (payload[key] !== undefined) form.append(key, payload[key])
      }
      reply.data = (await http.post('/tools/ocr/jobs', form, raw)).data.data
      await router.replace({ query: { ...route.query, job: reply.data.id } })
      await loadHistory()
    } else if (message.operation === 'job') {
      if (!/^[\da-f-]{36}$/i.test(payload.id)) throw new Error('任务编号无效')
      reply.data = (await http.get(`/tools/ocr/jobs/${payload.id}`, raw)).data.data
    } else if (message.operation === 'download') {
      if (typeof payload.content !== 'string' || payload.content.length > 2000000 || !['json','md'].includes(payload.format)) throw new Error('下载内容无效')
      const form = document.createElement('form')
      form.method='POST'; form.action=`${import.meta.env.VITE_API_BASE_URL || '/api/v1'}/tools/ocr/export`; form.hidden=true
      for (const [name,value] of Object.entries({content:payload.content,format:payload.format,token:auth.token})) {
        const field=document.createElement('input'); field.type='hidden'; field.name=name; field.value=value; form.appendChild(field)
      }
      document.body.appendChild(form); form.submit(); form.remove()
      reply.data = {downloaded:true}
    } else throw new Error('不支持的操作')
  } catch (error) {
    reply.error = typeof error.response?.data?.detail === 'string' ? error.response.data.detail : error.message || '识别服务暂不可用'
  }
  if (!disposed) event.source.postMessage(reply, location.origin)
}

async function restore(jobId) {
  if (!/^[\da-f-]{36}$/i.test(jobId)) return
  try {
    const job = (await http.get(`/tools/ocr/jobs/${jobId}`, raw)).data.data
    if (job.status === 'expired') return ElMessage.info('文件与结果已过期')
    const source = (await http.get(`/tools/ocr/jobs/${jobId}/file`, { ...raw, responseType: 'blob' })).data
    frame.value?.contentWindow.postMessage({channel:'jjc-ocr-restore',job,source},location.origin)
  } catch { ElMessage.warning('无法恢复任务，请稍后重试') }
}
async function openJob(job) {
  await router.replace({query:{...route.query,job:job.id}})
  await restore(job.id)
  frame.value?.scrollIntoView({behavior:'smooth',block:'start'})
}
async function removeJob(job) {
  try {
    await http.delete(`/tools/ocr/jobs/${job.id}`, raw)
    if (route.query.job === job.id) { const query={...route.query}; delete query.job; await router.replace({query}) }
    await loadHistory()
  } catch { ElMessage.error('删除失败，请稍后重试') }
}
function frameLoaded() { if (route.query.job) restore(String(route.query.job)) }
onMounted(() => { window.addEventListener('message',onMessage); pollHistory() })
onUnmounted(() => { disposed=true; clearTimeout(timer); window.removeEventListener('message',onMessage) })
</script>

<template>
  <div class="document-recognition page-stack">
    <iframe ref="frame" src="/ocr-workbench/index.html?lang=zh" title="Xiaomi-OCR-0 文档工作台" class="original-workbench" :style="{height:`${frameHeight}px`}" @load="frameLoaded" />
    <section class="panel ocr-history" :class="{'is-expanded':historyExpanded}">
      <header>
        <button class="history-toggle" type="button" :aria-expanded="historyExpanded" aria-controls="ocr-history-content" @click="historyExpanded=!historyExpanded">
          <el-icon><ArrowDown v-if="historyExpanded" /><ArrowRight v-else /></el-icon><span>最近任务</span><span class="ocr-note">{{ jobs.length }}</span>
        </button>
        <span class="ocr-note">{{ historyExpanded ? '仅显示自己的最近 20 条任务 · 文件和结果保留 24 小时' : '点击展开查看' }}</span>
      </header>
      <div v-if="historyExpanded" id="ocr-history-content">
        <el-table :data="jobs" stripe empty-text="暂无识别任务" @row-click="openJob">
          <el-table-column prop="filename" label="文件" min-width="200" show-overflow-tooltip sortable />
          <el-table-column label="功能" width="120"><template #default="{row}">{{ modes[row.task] }}</template></el-table-column>
          <el-table-column label="状态" width="120"><template #default="{row}"><el-tag :type="statusType(row.status)">{{ labels[row.status] }}</el-tag></template></el-table-column>
          <el-table-column label="操作" width="160"><template #default="{row}"><el-button link type="primary" @click.stop="openJob(row)">查看</el-button><el-popconfirm title="删除文件、结果并取消此任务？" @confirm="removeJob(row)"><template #reference><el-button link type="danger" @click.stop>删除</el-button></template></el-popconfirm></template></el-table-column>
        </el-table>
      </div>
    </section>
  </div>
</template>

<style scoped>
.original-workbench { display:block;width:100%;border:0;border-radius:16px;background:#f7f7f5; }
.history-toggle { display:inline-flex;align-items:center;gap:10px;padding:12px 0;border:0;background:transparent;color:var(--el-text-color-primary);font:inherit;font-size:15px;font-weight:600;cursor:pointer; }
.history-toggle:focus-visible { outline:2px solid var(--el-color-primary);outline-offset:4px;border-radius:4px; }
.ocr-note { font-size:13px;color:var(--el-text-color-secondary); }
.ocr-history:not(.is-expanded)>header { border-bottom:0; }
</style>
