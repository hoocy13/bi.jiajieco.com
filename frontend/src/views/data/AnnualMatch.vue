<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '../../api/http'
import AnnualPublicSettings from '../../components/AnnualPublicSettings.vue'
import AnnualTournament from '../../components/AnnualTournament.vue'

const route = useRoute()
const router = useRouter()
const roles = ['对抗路', '打野', '中路', '发育路', '游走']
const mode = computed(() => 'real')
const screen = computed(() => route.path.endsWith('/screen'))
const state = ref(null)
const publicDialog = ref(false)
const players = ref([])
const busy = ref(false)
const dirty = ref(false)
const search = ref(String(route.query.q || ''))
const tab = ref(['schedule', 'teams', 'players', 'history'].includes(route.query.tab) ? route.query.tab : 'schedule')
const error = ref('')
const reveal = ref(10)
const countdown = ref(0)
const rollingIndex = ref(0)
let animationTimer
let rollingTimer
let pollTimer
let requestVersion = 0
const reducedMotion = ref(window.matchMedia('(prefers-reduced-motion: reduce)').matches)
const played = computed(() => new Set((state.value?.history || []).filter(m => m.status === 'locked' && m.round === state.value.round).flatMap(m => m.slots.map(p => p.id))))
const pool = computed(() => players.value.filter(p => p.present && !played.value.has(p.id)))
const ready = computed(() => pool.value)
const shownPlayers = computed(() => players.value.filter(p => p.name.includes(search.value.trim())))
const current = computed(() => state.value?.draft || state.value?.batch?.matches[0] || [...(state.value?.history || [])].reverse().find(m => m.status === 'locked' && m.round === state.value.round))
const bulkMatches = computed(() => {
  if (state.value?.draft) return []
  if (state.value?.batch) return state.value.batch.matches
  const batchId = current.value?.batch_id
  return batchId ? state.value.history.filter(m => m.batch_id === batchId && m.status === 'locked') : []
})
const pending = computed(() => !!(state.value?.draft || state.value?.batch))
const configLocked = computed(() => pending.value || state.value?.tournament?.generated)
const waitingPlayers = computed(() => {
  const reserved = new Set((state.value?.batch?.matches || (state.value?.draft ? [state.value.draft] : [])).flatMap(m => m.slots.map(p => p.id)))
  return pool.value.filter(p => !reserved.has(p.id))
})
const lockedMatches = computed(() => (state.value?.history || []).filter(m => m.status === 'locked'))
const slots = computed(() => current.value?.slots || [])
const coverage = role => ready.value.filter(p => !p.roles.length || p.roles.includes(role) || p.fill).length

function apply(data) {
  state.value = data
  players.value = structuredClone(data.players)
  dirty.value = false
}

async function load(quiet = false) {
  if (busy.value || (quiet && dirty.value)) return
  const version = ++requestVersion
  const requestedMode = mode.value
  try {
    const result = await http.get(`/annual-match/${requestedMode}`, { metadata: { rawResponse: true } })
    if (version !== requestVersion || requestedMode !== mode.value) return
    const data = result.data.data
    if (quiet && (busy.value || dirty.value)) return
    if (!state.value || data.revision !== state.value.revision) apply(data)
    error.value = ''
  } catch (e) { error.value = e.response?.data?.detail || '连接失败，请检查本地后端并重试' }
}

async function command(action, extra = {}) {
  if (busy.value || !state.value) return false
  busy.value = true
  requestVersion++
  try {
    const response = await http.post(`/annual-match/${mode.value}/${action}`, { revision: state.value.revision, ...extra }, { metadata: { rawResponse: true } })
    apply(response.data.data)
    error.value = ''
    if (action === 'save') ElMessage.success('人员配置已保存')
    return true
  } catch (e) {
    error.value = e.response?.data?.detail || '操作失败，请刷新后核对结果'
    if (typeof error.value !== 'string') error.value = '配置无效，请检查输入'
    if (action.startsWith('tournament-')) ElMessage.error(error.value)
    return false
  } finally { busy.value = false }
}

function animate() {
  clearInterval(animationTimer)
  clearInterval(rollingTimer)
  if (reducedMotion.value) { countdown.value = 0; reveal.value = 10; return }
  countdown.value = 3
  reveal.value = 0
  rollingTimer = setInterval(() => { rollingIndex.value++ }, 80)
  animationTimer = setInterval(() => {
    if (countdown.value) countdown.value--
    else if (reveal.value < 10) reveal.value += 2
    else { clearInterval(animationTimer); clearInterval(rollingTimer) }
  }, 700)
}

async function draw() {
  if (await command('draw')) animate()
}
async function drawAll() {
  if (await command('draw-all')) {
    clearInterval(animationTimer)
    clearInterval(rollingTimer)
    countdown.value = 0
    reveal.value = 10
    ElMessage.success(`已生成 ${state.value.batch.matches.length} 场对阵，剩余 ${waitingPlayers.value.length} 人轮候`)
  }
}
async function discard() {
  try {
    const { value } = await ElMessageBox.prompt('请填写作废原因，记录将保留在历史中', '作废本次抽签', { inputPattern: /\S+/, inputErrorMessage: '请填写原因' })
    await command(state.value.batch ? 'discard-all' : 'discard', { id: state.value.batch?.id || state.value.draft.id, reason: value })
  } catch { /* cancelled */ }
}
function handleMore(action) {
  if (action === 'draw-all') drawAll()
  else if (action === 'next-round') nextRound()
  else if (action === 'discard') discard()
  else if (action === 'replay') animate()
  else if (action === 'motion') reducedMotion.value = !reducedMotion.value
}
async function replace(index) {
  try {
    await ElMessageBox.confirm(`将 ${slots.value[index].name} 标记为未到场，并随机抽取同位置替补。其余九人保留。`, '缺席替换')
    await command('replace', { id: state.value.draft.id, slot: index })
  } catch { /* cancelled */ }
}
const historyPreview = ref(null)
async function abandonDraw() {
  try {
    const { value } = await ElMessageBox.prompt('当前队伍、赛程及比分会完整移至抽签记录。填写原因后确认放弃，人员配置保留。', '放弃本次抽选', { inputPattern: /\S+/, inputErrorMessage: '请填写放弃原因', confirmButtonText: '归档并放弃', type: 'warning' })
    if (await command('tournament-abandon', { reason: value })) { tab.value = 'history'; ElMessage.success('本次抽选已归档，可在记录中恢复') }
  } catch { /* cancelled */ }
}
async function restoreDraw(record) {
  try {
    await ElMessageBox.confirm('将恢复这次抽取的队伍和赛程，当前结果仍保留在最近5次记录内。已有比分时不能切换。', '恢复抽签记录')
    await command('tournament-restore', { id: record.id })
  } catch { /* cancelled */ }
}
async function nextRound() {
  try {
    await ElMessageBox.confirm('开启新一轮后，已上场人员可以再次抽中。上一轮轮候人员优先，历史记录保留。', '开启下一轮')
    await command('next-round')
  } catch { /* cancelled */ }
}
async function fullscreen() {
  try {
    if (document.fullscreenElement) await document.exitFullscreen()
    else await document.documentElement.requestFullscreen()
  } catch { ElMessage.warning('请使用浏览器全屏功能') }
}
function csvCell(value) {
  let text = String(value ?? '')
  if (/^[=+@\-\t\r]/.test(text)) text = `'${text}`
  return `"${text.replaceAll('"', '""')}"`
}
function exportResults() {
  const rows = [['模式', '轮次', '场次ID', '状态', '队伍', '位置', '姓名', '说明']]
  for (const m of state.value.history) {
    for (const p of m.slots) rows.push([mode.value === 'demo' ? '模拟演练' : '正式名单', m.round, m.id, m.status === 'locked' ? '已锁定' : '已作废', p.team === 'red' ? '红队' : '蓝队', p.role, p.name, m.reason || ''])
  }
  for (const p of pool.value) rows.push([mode.value, state.value.round, '', '轮候', '', '', p.name, p.present ? '' : '未到场'])
  const url = URL.createObjectURL(new Blob(['\ufeff' + rows.map(r => r.map(csvCell).join(',')).join('\r\n')], { type: 'text/csv;charset=utf-8;' }))
  const a = document.createElement('a'); a.href = url; a.download = `年会5V5-${mode.value}-第${state.value.round}轮.csv`; a.click(); URL.revokeObjectURL(url)
}
function beforeUnload(event) { if (dirty.value) { event.preventDefault(); event.returnValue = '' } }
function slotName(team, i) {
  if (countdown.value || i * 2 + team >= reveal.value) return ready.value[(rollingIndex.value + i * 7 + team * 13) % ready.value.length]?.name || '抽选中…'
  return slots.value[team * 5 + i]?.name || '等待入场'
}
watch(reducedMotion, value => { if (value) { clearInterval(animationTimer); clearInterval(rollingTimer); reveal.value = 10; countdown.value = 0 } })
watch(search, value => router.replace({ query: { ...route.query, q: value || undefined } }))
watch(tab, value => router.replace({ query: { ...route.query, tab: value === 'schedule' ? undefined : value } }))
watch(mode, () => { requestVersion++; state.value = null; players.value = []; dirty.value = false; reveal.value = 10; countdown.value = 0; clearInterval(animationTimer); clearInterval(rollingTimer); load() })
watch(() => state.value?.draft?.id, (id, previous) => { if (screen.value && id && id !== previous) animate() })
onMounted(() => { load(); pollTimer = setInterval(() => load(true), 3000); window.addEventListener('beforeunload', beforeUnload) })
onBeforeRouteLeave(async () => {
  if (!dirty.value) return true
  try { await ElMessageBox.confirm('人员配置尚未保存，确认离开？', '未保存的修改'); return true } catch { return false }
})
onUnmounted(() => { clearInterval(pollTimer); clearInterval(animationTimer); clearInterval(rollingTimer); window.removeEventListener('beforeunload', beforeUnload) })
</script>

<template>
  <main class="annual-match" :class="{ 'screen-mode': screen }" v-loading="busy">
    <AnnualPublicSettings v-if="state && mode === 'real'" v-model="publicDialog" :settings="state.public_view" :busy="busy" :run-command="command" />
    <header class="event-toolbar">
      <div class="event-heading"><h1>王者荣耀 <span>5V5 年会赛事</span></h1><span v-if="state && !screen && tab === 'draw'" class="event-summary">第 {{ state.round }} 轮 · 待分配 {{ waitingPlayers.length }} 人 · 已上场 {{ played.size }} 人</span></div>
      <div class="toolbar-actions">
        <el-tag :type="mode === 'demo' ? 'warning' : 'success'">{{ mode === 'demo' ? '模拟位置' : '正式名单' }}</el-tag>
        <el-button v-if="state?.tournament?.generated" :disabled="busy" @click="abandonDraw">放弃本次抽选</el-button><el-button @click="publicDialog = true">公开展示</el-button>
        
      </div>
    </header>
    <el-alert v-if="error" class="event-alert" type="error" :closable="false" :title="error" show-icon><el-button size="small" @click="load()">重新加载</el-button></el-alert>
    <template v-if="state">
      <el-tabs v-if="!screen" v-model="tab">
        <el-tab-pane label="全赛程" name="schedule" /><el-tab-pane label="18支队伍" name="teams" /><el-tab-pane label="人员与位置" name="players" /><el-tab-pane :label="`抽签记录（${(state.team_draw_history || []).length}）`" name="history" />
      </el-tabs>
      <AnnualTournament v-if="screen || tab === 'schedule' || tab === 'teams'" :tournament="state.tournament" :revision="state.revision" :mode="mode" :screen="screen" :busy="busy || dirty" :view="screen ? 'schedule' : tab" :run-command="command" />
      <template v-if="!screen && tab === 'draw'">
        <section class="arena" :class="{ 'no-motion': reducedMotion }">
          <div class="arena-heading"><span>第 {{ state.round }} 轮{{ bulkMatches.length ? ` · ${bulkMatches.length} 场对阵` : '' }}</span><span>{{ current ? (pending ? '待确认' : '已锁定') : '等待抽选' }}</span></div>
          <div v-if="!bulkMatches.length" class="arena-title"><h2>{{ countdown ? `即将揭晓 ${countdown}` : current ? '红蓝对决' : '等待选手入场' }}</h2></div>
          <div v-if="!bulkMatches.length" class="matchup">
            <article v-for="(team, t) in ['red', 'blue']" :key="team" class="team" :class="team">
              <div class="team-heading"><span>{{ team === 'red' ? '红队' : '蓝队' }}</span></div>
              <div v-for="(role, i) in roles" :key="role" class="player-slot"><span class="slot-role">{{ role }}</span><strong>{{ slotName(t, i) }}</strong><span class="slot-note">{{ !countdown && i * 2 + t < reveal && slots[t * 5 + i] ? (slots[t * 5 + i].rank === 11 ? '随机位置' : slots[t * 5 + i].rank === 10 ? '已同意补位' : `第${slots[t * 5 + i].rank + 1}意向`) : '5V5' }}</span><el-button v-if="!screen && state.draft && !countdown && reveal === 10" link size="small" :disabled="busy" @click="replace(t * 5 + i)">替换</el-button></div>
            </article>
            <div class="versus">VS</div>
          </div>
          <div v-else class="batch-grid">
            <article v-for="(m, index) in bulkMatches" :key="m.id" class="batch-card">
              <div class="batch-card-heading"><b>第 {{ index + 1 }} 场</b><span class="red-label">红队</span><span class="blue-label">蓝队</span></div>
              <div v-for="(role, r) in roles" :key="role" class="batch-row"><span>{{ role }}</span><strong>{{ m.slots[r].name }}</strong><strong>{{ m.slots[r + 5].name }}</strong></div>
            </article>
          </div>
        </section>
        <div class="draw-actions" v-if="!screen">
          <el-button v-if="!pending" class="draw-button draw-next-button" size="large" :disabled="busy || dirty || ready.length < 10" @click="draw">抽取下一场</el-button>
          <el-button v-else class="draw-button" size="large" :disabled="busy || countdown > 0 || reveal < 10" @click="command(state.batch ? 'lock-all' : 'lock', { id: state.batch?.id || state.draft.id })">{{ state.batch ? '确认全部对阵' : '确认并锁定本场' }}</el-button>
          <el-dropdown trigger="click" :disabled="busy || dirty || countdown > 0 || reveal < 10" @command="handleMore">
            <el-button text>更多操作</el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item v-if="!state.batch" command="draw-all" :disabled="ready.length < 10">一键抽完本轮</el-dropdown-item>
                <el-dropdown-item v-if="pending" command="discard">{{ state.batch ? '作废全部待确认对阵' : '作废重抽' }}</el-dropdown-item>
                <el-dropdown-item v-if="state.draft" command="replay">重播揭晓</el-dropdown-item>
                <el-dropdown-item v-if="!pending" command="next-round">开启下一轮</el-dropdown-item>
                <el-dropdown-item command="motion">{{ reducedMotion ? '开启揭晓动画' : '关闭揭晓动画' }}</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <span v-if="dirty" class="muted">请先保存人员配置</span><span v-else-if="!pending && ready.length < 10" class="muted">到场人员不足 10 人</span>
        </div>
        <details v-if="!screen" class="waiting"><summary>轮候名单 · {{ waitingPlayers.length }} 人</summary><p>{{ waitingPlayers.map(p => p.name).join('、') || '暂无轮候人员' }}</p></details>
      </template>
      <section v-if="!screen && tab === 'players'" class="config-panel">
        <div class="coverage"><span>共 {{ players.length }} 人 · {{ players.filter(p => p.roles.length).length }} 人填写位置 · 未填写则随机分配</span><el-tag v-for="r in roles" :key="r" :type="coverage(r) < 2 ? 'danger' : 'info'">{{ r }} {{ coverage(r) }} 人</el-tag></div>
        <el-alert title="位置按第一至第五意向依次填写；全部留空则随机分配位置；已填写的优先按意向匹配，不根据英雄推断。" type="info" :closable="false" show-icon />
        <div class="config-actions"><el-input v-model="search" placeholder="搜索姓名" clearable style="width: 220px" /><span>共 {{ shownPlayers.length }} 人</span><el-button type="primary" :disabled="!dirty || busy || configLocked" @click="command('save', { players })">保存配置</el-button><el-button :disabled="!dirty || busy" @click="dirty = false; state = null; load()">撤销修改</el-button><span v-if="configLocked" class="muted">队伍已固定或有待确认抽签，暂不可修改配置</span></div>
        <el-table :data="shownPlayers" row-key="id" height="540" stripe>
          <el-table-column prop="name" label="姓名" width="120" sortable><template #default="{ row }"><el-input v-model="row.name" :disabled="configLocked" maxlength="30" @input="dirty = true" /></template></el-table-column>
          <el-table-column label="到场" width="85"><template #default="{ row }"><el-switch v-model="row.present" :disabled="configLocked" @change="dirty = true" /></template></el-table-column>
          <el-table-column v-for="i in 5" :key="i" :label="`第${i}意向`" min-width="125"><template #default="{ row }"><el-select :model-value="row.roles[i - 1] || ''" :disabled="configLocked || i > row.roles.length + 1" :placeholder="i === 1 ? '不填则随机' : '选填'" clearable @change="value => { const next = [...row.roles]; if (value) next[i - 1] = value; else next.splice(i - 1, 1); row.roles = next; dirty = true }"><el-option v-for="r in roles" :key="r" :label="r" :value="r" :disabled="row.roles.includes(r) && row.roles[i - 1] !== r" /></el-select></template></el-table-column>
          <el-table-column label="接受补位" width="100"><template #default="{ row }"><el-switch v-model="row.fill" :disabled="configLocked" @change="dirty = true" /></template></el-table-column>
          <el-table-column label="本轮状态" width="100"><template #default="{ row }"><el-tag :type="played.has(row.id) ? 'success' : row.roles.length ? 'info' : 'warning'">{{ played.has(row.id) ? '已上场' : row.roles.length ? '待抽选' : '随机抽选' }}</el-tag></template></el-table-column>
        </el-table>
      </section>
      <section v-if="!screen && tab === 'history'" class="history-panel">
        <p class="muted">自动保留最近5次完整抽队快照，包含队伍、替补、签位和已保存比分。超过5次后自动淘汰最早记录。</p>
        <el-empty v-if="!state.team_draw_history?.length" description="尚无抽队记录" />
        <el-collapse><el-collapse-item v-for="(record, index) in [...(state.team_draw_history || [])].reverse()" :key="record.id" :name="record.id" :title="`${new Date(record.created_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })} · 18队 · ${record.id === state.tournament.id ? '当前使用' : record.status === 'abandoned' ? '已放弃' : '历史快照'}`"><p v-if="record.status === 'abandoned'">放弃原因：{{ record.reason }}</p><div class="config-actions"><el-button @click="historyPreview = record.tournament">查看完整队伍</el-button><el-button v-if="record.id !== state.tournament.id" :disabled="busy || state.tournament.matches.some(m=>m.score_a || m.score_b)" @click="restoreDraw(record)">恢复这次结果</el-button><span>替补：{{ record.tournament.reserves.map(p=>p.name).join('、') || '无' }}</span></div></el-collapse-item></el-collapse>
        <el-dialog :model-value="!!historyPreview" title="抽队记录 · 完整阵容" width="min(1100px, 95vw)" @update:model-value="value => { if (!value) historyPreview = null }"><AnnualTournament v-if="historyPreview" :tournament="historyPreview" screen view="teams" /></el-dialog>
      </section>
    </template>
  </main>
</template>

<style scoped>
.annual-match{--event-muted:#77828f;max-width:none;width:100%;min-width:0;margin:0;padding:4px 0 20px}
.event-toolbar,.toolbar-actions,.config-actions,.coverage,.draw-actions,.event-heading{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.event-toolbar{justify-content:space-between;margin-bottom:18px}.event-heading{gap:20px}h1{font-size:23px;margin:0}h1 span{font-size:15px;font-weight:400;color:var(--event-muted);margin-left:8px}.event-summary,.muted{font-size:12px;color:var(--event-muted)}.event-alert{margin-bottom:16px}.toolbar-actions{gap:8px}.toolbar-actions .el-button+.el-button{margin-left:0}
.coverage{margin:0 0 18px;font-size:13px}
.arena{color:#f0f3f9;background:radial-gradient(ellipse at 4% 80%,#49233166,transparent 55%),radial-gradient(ellipse at 96% 80%,#1b416666,transparent 55%),#101923;border:1px solid #293748;border-radius:14px;padding:20px 26px;overflow:hidden}
.arena-heading{display:flex;justify-content:space-between;gap:12px;color:#9aaabb;font-size:12px;padding-bottom:16px;border-bottom:1px solid #ffffff14}.arena-title{text-align:center;padding:20px 0}.arena-title h2{font-size:26px;letter-spacing:2px;margin:0}
.matchup{display:grid;grid-template-columns:minmax(0,1fr) 70px minmax(0,1fr);align-items:center;gap:16px}.team{border:1px solid #ffffff18;border-radius:10px;padding:18px;background:#ffffff03}.team.red{grid-column:1;grid-row:1;--team-color:#f18f9b}.team.blue{grid-column:3;grid-row:1;--team-color:#82bdf5}.team-heading{color:var(--team-color);font-size:18px;font-weight:650;padding-bottom:14px}.player-slot{display:flex;align-items:center;gap:12px;min-height:58px;border-top:1px solid #ffffff0c}.slot-role{font-size:12px;color:#a2afbd;width:44px;flex-shrink:0}.player-slot strong{font-size:22px;letter-spacing:1px;flex:1;overflow-wrap:anywhere}.slot-note{font-size:11px;color:var(--team-color)}.player-slot .el-button{color:#a9b6c5}.versus{grid-column:2;grid-row:1;text-align:center;font-style:italic;font-size:30px;font-weight:750;color:#d3ba83}
.draw-actions{justify-content:center;padding:20px 0;gap:10px}.draw-actions .el-button+.el-button{margin-left:0}.draw-button.el-button{background:#fff!important;color:#26313d!important;border:1px solid #d9dee5!important;box-shadow:0 1px 2px #00000006;font-weight:600;min-width:140px}.draw-button.el-button:hover:not(:disabled){background:#f5f7fa!important;border-color:#aeb8c5!important}.draw-button.el-button:disabled{opacity:.45}.draw-button.el-button:focus-visible{outline:2px solid #7d8da3;outline-offset:3px}
.draw-next-button.el-button{background:#315e1b!important;color:#fff!important;border-color:#315e1b!important}.draw-next-button.el-button:hover:not(:disabled){background:#244813!important;border-color:#244813!important}.draw-next-button.el-button:focus-visible{outline-color:#315e1b}
.waiting{font-size:12px;color:var(--event-muted);padding:6px 0}.waiting summary{cursor:pointer;width:fit-content}.waiting p{line-height:2;margin:10px 0 0}
.config-panel,.history-panel{background:var(--el-bg-color);padding:18px;border-radius:12px;border:1px solid var(--el-border-color-lighter)}.config-actions{margin:18px 0}.history-teams{display:grid;grid-template-columns:1fr 1fr;gap:24px}
.batch-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;padding-top:20px}.batch-card{background:#ffffff03;border:1px solid #ffffff16;border-radius:10px;padding:14px 16px}.batch-card-heading,.batch-row{display:grid;grid-template-columns:46px minmax(0,1fr) minmax(0,1fr);align-items:center;gap:12px}.batch-card-heading{padding-bottom:12px;border-bottom:1px solid #ffffff12;font-size:13px}.batch-card-heading b{font-weight:400;color:#9aaabb;font-size:11px}.red-label{color:#f18f9b}.blue-label{color:#82bdf5}.batch-row{min-height:39px}.batch-row>span{font-size:11px;color:#9aaabb}.batch-row strong{font-size:17px;font-weight:600;overflow-wrap:anywhere}
.screen-mode{max-width:none;min-height:100vh;background:#0c121b;color:#f0f3f9;padding:24px 5vw;box-sizing:border-box}.screen-mode .arena{margin-top:22px}.screen-mode .arena-title{padding:30px 0}.screen-mode .player-slot{min-height:75px}.screen-mode .player-slot strong{font-size:30px}
@media(min-width:1500px){.screen-mode .arena{max-width:1600px;margin:22px auto}.screen-mode .player-slot{min-height:90px}.screen-mode .arena-title h2{font-size:36px}}
@media(min-width:651px) and (max-height:850px){.screen-mode{padding:16px 4vw}.screen-mode .event-toolbar{margin-bottom:12px}.screen-mode .arena{margin-top:10px;padding:16px 24px}.screen-mode .arena-title{padding:16px 0}.screen-mode .arena-title h2{font-size:28px}.screen-mode .player-slot{min-height:clamp(42px,6.5vh,62px)}.screen-mode .player-slot strong{font-size:26px}}
@media(max-width:1200px){.batch-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:1050px){.team{padding:14px}.player-slot{gap:8px}.player-slot strong{font-size:18px}.slot-note{display:none}.arena{padding:18px}.matchup{grid-template-columns:minmax(0,1fr) 42px minmax(0,1fr);gap:10px}.versus{font-size:24px}}
@media(max-width:650px){.event-heading{gap:8px;align-items:baseline}.event-summary{width:100%}.toolbar-actions{gap:6px}.arena-title h2{font-size:22px}.matchup{grid-template-columns:1fr}.team.red{grid-column:1;grid-row:1}.team.blue{grid-column:1;grid-row:3}.versus{grid-column:1;grid-row:2;padding:10px}.screen-mode{padding:16px}.screen-mode .player-slot{min-height:55px}.screen-mode .player-slot strong{font-size:22px}.batch-grid{grid-template-columns:1fr}.draw-button.el-button{min-width:120px}}
.screen-mode{height:100dvh;min-height:600px;display:flex;flex-direction:column;padding:clamp(12px,2vh,24px) clamp(16px,3vw,56px)}.screen-mode>.event-toolbar,.screen-mode>.event-alert{flex-shrink:0}
</style>





