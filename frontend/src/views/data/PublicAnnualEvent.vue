<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import QRCode from 'qrcode'
import AnnualTournament from '../../components/AnnualTournament.vue'
const route = useRoute()
const drawTotal = computed(() => data.value?.tournament.draw_total || 9)
const teamOnly = computed(() => data.value?.tournament.draw_unit === 'team')
const drawProgress = computed(() => teamOnly.value ? (data.value?.tournament.drawn_teams || 0) : (data.value?.tournament.drawn_matches || 0))
const currentDrawNumber = computed(() => drawReady.value ? drawProgress.value+1 : drawProgress.value || 1)
const nextDrawTeam = computed(() => data.value?.tournament.teams.find(team => !(team.drawn ?? !!team.players.length)))
const displayTeamCode = computed(() => drawReady.value ? nextDrawTeam.value?.id : displayDrawTeams.value[0]?.id)
const byeDraw = computed(() => false)
const hostAllowed = ref(false)
const hostRoleMap = ref({})
const drawing = ref(false)
const revealing = ref(false)
const drawReady = ref(false)
const rollingNames = ref([])
const lockedSlots = ref([])
const nameTicks = ref([])
const nameDurations = ref([])
const drawRoles = ['对抗路', '打野', '中路', '发育路', '游走']
const nameTimers = new Map()
function stopNameTimers() {
  for (const [timer, finish] of nameTimers) { clearTimeout(timer); finish() }
  nameTimers.clear()
}
const displayDrawTeams = computed(() => {
  if (!data.value) return []
  const count = data.value.tournament.drawn_matches || 0
  const t = data.value.tournament
  const pending = drawing.value && drawReady.value
  const ids = teamOnly.value ? (pending ? [nextDrawTeam.value?.id] : t.last_draw_team_ids) : pending ? (count < 9 ? t.matches.filter(m=>m.stage==='opening')[count]?.sources.map(s=>s.split(':')[1]) : [t.bye_team_id]) : t.last_draw_team_ids
  const selection = ids?.length ? ids.map(id=>t.teams.find(team=>team.id===id)).filter(Boolean) : t.teams.slice(Math.max(0,count-1)*2,Math.max(0,count-1)*2+2)
  return selection.map(team => ({ ...team,
    players: drawing.value && !team.players.length && data.value.show_names
      ? drawRoles.map((role, i) => ({ id: String(i), role, name: '待揭晓' })) : team.players,
  }))
})
async function settleNames() {
  if (reducedMotion.matches || !data.value.show_names) return
  const names = displayDrawTeams.value.flatMap(team => team.players.map(player => player.name))
  const selected = new Set(names)
  const knownNames = [...Object.keys(hostRoleMap.value), ...data.value.tournament.teams.flatMap(team=>team.players.map(player=>player.name))]
  const candidateNames = [...new Set(knownNames)].filter(name=>!selected.has(name))
  const pool = candidateNames.length >= 10 ? candidateNames : ['王＊＊','李＊＊','张＊＊','陈＊＊','刘＊＊','赵＊＊','周＊＊','林＊＊','吴＊＊','郑＊＊']
  rollingNames.value = names.map(() => '待揭晓')
  lockedSlots.value = []
  nameTicks.value = names.map(() => 0)
  nameDurations.value = names.map(() => 85 + Math.floor(Math.random() * 70))
  await Promise.all(names.map((name, index) => new Promise(resolve => {
    const started = performance.now()
    const duration = 1900 + Math.random() * 1700
    const tick = () => {
      const elapsed = performance.now() - started
      if (elapsed >= duration) {
        rollingNames.value[index] = name
        lockedSlots.value.push(index)
        resolve()
        return
      }
      const candidates = pool.filter(value => value !== rollingNames.value[index])
      rollingNames.value[index] = candidates[Math.floor(Math.random() * candidates.length)] || name
      nameTicks.value[index]++
      const delay = nameDurations.value[index] * (1 + .45 * elapsed / duration)
      const timer = setTimeout(() => { nameTimers.delete(timer); tick() }, delay)
      nameTimers.set(timer, resolve)
    }
    const timer = setTimeout(() => { nameTimers.delete(timer); tick() }, Math.random() * 180)
    nameTimers.set(timer, resolve)
  })))
}
async function enterDraw() {
  drawReady.value = true
  tab.value = 'draw'
  await nextTick()
  snapScroll(true)
}
let revealTimer
async function checkHost() {
  const token = localStorage.getItem('jjc_token')
  if (!token) return
  try {
    const base = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')
    const response = await fetch(`${base}/auth/me`, { headers: { Authorization: `Bearer ${token}` }, credentials: 'omit' })
    const result = await response.json()
    hostAllowed.value = response.ok && !!result.data?.permissions?.includes('system.users.manage')
    if (hostAllowed.value) {
      const rosterResponse = await fetch(`${base}/annual-match/real`, { headers: { Authorization: `Bearer ${token}` }, credentials: 'omit' })
      if (rosterResponse.ok) {
        const roster = await rosterResponse.json()
        hostRoleMap.value = Object.fromEntries((roster.data?.players || []).map(p=>[p.name,{roles:p.roles,fill:p.fill}]))
      }
    }
  } catch { hostAllowed.value = false }
}
function intentionLabel(player) {
  const preferences = hostRoleMap.value[player.name]
  if (!preferences) return '已就位'
  const rank=preferences.roles.indexOf(player.role)
  return rank>=0 ? `第${rank+1}意向` : !preferences.roles.length ? '随机位置' : preferences.fill ? '同意补位' : '协调补位'
}
async function replayNames() {
  if (drawing.value) return
  drawReady.value=false
  drawing.value=true
  try { await nextTick(); await settleNames() }
  finally { stopNameTimers(); rollingNames.value=[]; drawing.value=false }
}
async function drawTeams() {
  if (drawing.value || !hostAllowed.value || !data.value?.draw_enabled) return
  drawing.value = true
  rollingNames.value = []
  lockedSlots.value = []
  try {
    const base = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')
    const response = await fetch(`${base}/public/annual-events/${encodeURIComponent(route.params.token)}/draw`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem('jjc_token') || ''}` },
      body: JSON.stringify({ revision: data.value.revision }), credentials: 'omit',
    })
    const result = await response.json()
    if (!reducedMotion.matches) await new Promise(resolve => setTimeout(resolve, 1200))
    if (!response.ok) { if ([401,403].includes(response.status)) hostAllowed.value = false; throw new Error(typeof result.detail === 'string' ? result.detail : '抽取失败，请重试') }
    data.value = result.data
    drawReady.value = false
    revealing.value = true
    tab.value = 'draw'
    await nextTick()
    snapScroll(true)
    await settleNames()
    clearTimeout(revealTimer)
    revealTimer = setTimeout(() => { revealing.value = false }, reducedMotion.matches ? 0 : 900)
    ElMessage.success('本次阵容已抽取，结果已自动保存')
  } catch (e) { ElMessage.error(e.message); await load() }
  finally { stopNameTimers(); rollingNames.value = []; drawing.value = false }
}

const data = ref(null)
const error = ref('')
const tab = ref('schedule')
const loading = ref(false)
const rulesVisible = ref(false)
const shareVisible = ref(false)
const shareQr = ref('')
const stage = ref('all')
const matchPanel = ref(null)
const menuItems = [{ id: 'schedule', name: '赛事进程' }, { id: 'matches', name: '比赛列表' }, { id: 'teams', name: '参赛队伍' }]
const filteredMatches = computed(() => (data.value?.tournament.matches || []).filter(m => stage.value === 'all' || m.stage === stage.value))
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)')
let navigationVersion = 0
let snapUntil = 0
let touchStart = null
function panelOffset() {
  const panel = matchPanel.value
  if (!panel) return 0
  const header = document.querySelector('.public-header')?.getBoundingClientRect().height || 64
  return Math.max(0, window.scrollY + panel.getBoundingClientRect().top - header - 16)
}
function snapScroll(down) {
  snapUntil = performance.now() + 950
  window.scrollTo({ top: down ? panelOffset() : 0, behavior: reducedMotion.matches ? 'instant' : 'smooth' })
}
function wheelSnap(event) {
  if (!data.value || rulesVisible.value || shareVisible.value || [...document.querySelectorAll('.el-overlay')].some(el => getComputedStyle(el).display !== 'none') || Math.abs(event.deltaX) > Math.abs(event.deltaY) || event.ctrlKey) return
  const target = event.target
  if (target instanceof Element && target.closest('.el-drawer,.el-dialog,.bracket-scroll')) return
  if (performance.now() < snapUntil) { event.preventDefault(); return }
  const top = panelOffset()
  if (!top || Math.abs(event.deltaY) < 3) return
  if (event.deltaY > 0 && window.scrollY < top - 30) { event.preventDefault(); snapScroll(true) }
  else if (event.deltaY < 0 && window.scrollY <= top + 24 && window.scrollY > 20) { event.preventDefault(); snapScroll(false) }
}
function touchBegin(event) { touchStart = event.touches.length === 1 ? event.touches[0].clientY : null }
function touchFinish(event) {
  if (touchStart === null || !data.value || rulesVisible.value || shareVisible.value) return
  const movement = touchStart - event.changedTouches[0].clientY
  touchStart = null
  if (Math.abs(movement) < 60 || performance.now() < snapUntil) return
  const top = panelOffset()
  if (movement > 0 && window.scrollY < top - 30) snapScroll(true)
  else if (movement < 0 && window.scrollY <= top + 24 && window.scrollY > 20) snapScroll(false)
}
async function selectView(value) {
  const version = ++navigationVersion
  tab.value = value
  await nextTick()
  if (version !== navigationVersion) return
  snapScroll(true)
}
async function share() { shareQr.value = await QRCode.toDataURL(location.href, { width: 240, margin: 2 }); shareVisible.value = true }
async function copyLink() { try { await navigator.clipboard.writeText(location.href); ElMessage.success('观赛链接已复制') } catch { ElMessage.info('请复制地址栏中的观赛链接') } }
async function fullscreen() { try { if (document.fullscreenElement) await document.exitFullscreen(); else await document.documentElement.requestFullscreen() } catch { ElMessage.info('当前浏览器暂不支持全屏') } }
function backToTop() { window.scrollTo({ top: 0, behavior: reducedMotion.matches ? 'instant' : 'smooth' }) }
let timer
let controller
let generation = 0
const teams = computed(() => Object.fromEntries((data.value?.tournament.teams || []).map(t => [t.id, t])))
function sourceName(source) {
  const [kind, id] = source.split(':')
  if (kind === 'team') return teams.value[id]?.drawn === false && data.value.tournament.generated ? '待定' : teams.value[id]?.name || '待定'
  const t = data.value.tournament
  const match = key => t.matches.find(m => m.id === key)
  if (kind === 'challenger') return teams.value[match(t.challenge_slot)?.winner]?.name || '挑战队伍待选择'
  if (kind === 'loser') {
    const origin=match(id)
    if(!origin?.winner) return '1:2败队待填写'
    return teams.value[origin.sources.map(s=>s.split(':')[1]).find(key=>key!==origin.winner)]?.name || '待定'
  }
  if (kind === 'finalist') {
    const origins=['C1',...t.matches.filter(m=>m.stage==='second'&&!t.qualification_slots?.includes(m.id)).map(m=>m.id)]
    return t.qualification_slots?.length ? teams.value[match(origins[Number(id)])?.winner]?.name || '1/4待定' : '1/4待定'
  }
  if (kind === 'qualified') return teams.value[match('C1')?.winner && (id === t.challenge_slot ? match('C1').winner : match(id)?.winner)]?.name || '1/4待定'
  return teams.value[match(id)?.winner]?.name || (match(id)?.stage === 'semi' ? '1/2待定' : '待定')
}
function ready(match) { return match.sources.every(s => !/待定|待选择/.test(sourceName(s))) }
const labels = { playin: '突围挑战赛', opening: '首轮赛', second: '四强争夺赛', qualifier: '四强资格赛', semi: '半决赛', final: '决赛' }
async function load() {
  if (drawing.value) return
  controller?.abort()
  controller = new AbortController()
  const current = ++generation
  if (!data.value) loading.value = true
  try {
    const base = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')
    const response = await fetch(`${base}/public/annual-events/${encodeURIComponent(route.params.token)}`, { signal: controller.signal, cache: 'no-store', credentials: 'omit' })
    if (current !== generation) return
    if (!response.ok) {
      data.value = null
      error.value = response.status === 404 ? '赛事尚未公开或链接已失效' : '暂时无法获取赛事，请稍后重试'
      return
    }
    const result = await response.json()
    if (current !== generation) return
    data.value = result.data
    error.value = ''

  } catch (e) { if (e.name !== 'AbortError') error.value = '网络连接中断，正在自动重试' }
  finally { if (current === generation) loading.value = false }
}
watch(() => route.params.token, () => { data.value = null; load() })
onMounted(() => { checkHost(); load(); timer = setInterval(load, 5000); window.addEventListener('wheel', wheelSnap, { passive: false }); window.addEventListener('touchstart', touchBegin, { passive: true }); window.addEventListener('touchend', touchFinish, { passive: true }) })
onUnmounted(() => { stopNameTimers(); clearTimeout(revealTimer); window.removeEventListener('wheel', wheelSnap); window.removeEventListener('touchstart', touchBegin); window.removeEventListener('touchend', touchFinish); clearInterval(timer); controller?.abort(); generation++ })
</script>
<template>
  <main class="public-event" v-loading="loading">
    <header class="public-header"><a class="event-brand" href="#" @click.prevent="backToTop"><strong>王者荣耀</strong><span>5V5 年会赛事</span></a><nav class="main-nav" aria-label="赛事导航"><button v-for="item in menuItems" :key="item.id" :class="{ active: tab === item.id }" :aria-pressed="tab === item.id" @click="selectView(item.id)">{{ item.name }}</button><button @click="rulesVisible = true">赛事规则</button></nav><button class="header-share" @click="share">分享赛事 ↗</button></header>
    <section class="event-hero"><div class="hero-copy"><span class="hero-kicker">王者荣耀 · 年会挑战赛</span><h1>峡谷集结<br><em>向冠军进发</em></h1><p>{{ data?.tournament.team_count || 18 }}支队伍，同场竞逐。</p><div class="hero-actions"><button class="primary-action" @click="selectView('schedule')">查看全赛程 <span>→</span></button><button class="secondary-action" @click="selectView('teams')">参赛队伍</button></div></div></section>
    <el-alert v-if="error" :title="error" type="info" :closable="false"><el-button size="small" @click="load">重新加载</el-button></el-alert>
    <section v-if="data" ref="matchPanel" class="event-content"><div class="section-heading"><div><span class="heading-mark"></span><h2>{{ tab === 'teams' ? '参赛队伍' : tab === 'matches' ? '比赛列表' : '赛事进程' }}</h2></div><div class="view-switch" aria-label="观赛视图"><button v-for="item in [{id:'schedule',name:'晋级图'},{id:'matches',name:'比赛列表'},{id:'teams',name:'队伍阵容'}]" :key="item.id" :class="{active:tab===item.id}" :aria-pressed="tab===item.id" @click="selectView(item.id)">{{ item.name }}</button></div></div>
      <div v-if="data.draw_enabled" class="public-draw-bar"><div><b>队伍抽签 · {{ drawProgress }} / {{ drawTotal }} 队</b></div><el-button v-if="hostAllowed" type="primary" :loading="drawing" :disabled="drawing || drawProgress >= drawTotal" @click="enterDraw">{{ drawProgress >= drawTotal ? '本轮队伍已抽齐' : `抽取 ${nextDrawTeam?.id || ''} · 5人` }}</el-button><el-button v-if="drawProgress" class="draw-secondary-button" @click="drawReady=false;tab='draw'">查看最近队伍</el-button></div>
      <section v-if="tab === 'draw'" :class="['opening-draw', 'classic-arena', {revealing}]" :aria-busy="drawing">
        <header class="classic-arena-meta"><span>第{{ currentDrawNumber }}轮抽取 · 队伍编号 {{ displayTeamCode || '待定' }}</span><span>{{ drawing ? '正在揭晓' : drawReady ? '等待开始' : '已自动保存' }}</span></header>
        <div class="classic-arena-title"><span>集结队友</span><h2>{{ drawing ? '战队集结 · 阵容揭晓' : drawReady ? '战队集结 · 等待抽取' : '战队集结 · 阵容就位' }}</h2><p>对抗路 / 打野 / 中路 / 发育路 / 游走</p></div>
        <div v-if="drawReady && !drawing" class="draw-waiting"><span class="waiting-team-code">{{ nextDrawTeam?.id || '待定' }}</span><p>第{{ drawProgress+1 }}轮抽取</p><el-button v-if="hostAllowed" type="primary" size="large" @click="drawTeams">开始抽取</el-button></div>
        <div v-else-if="drawing || data.tournament.drawn_matches" class="opening-sides classic-matchup" :class="{single:displayDrawTeams.length===1}">
          <article v-for="(team, index) in displayDrawTeams" :key="team.id" :class="['opening-team', index ? 'blue' : 'red']">
            <h3><span>{{ team.name }} 战队<small>队伍编号 {{ team.id }}</small></span><em>TEAM {{ team.id.replace('T','') }}</em></h3>
            <p v-for="(player, position) in team.players" :key="player.id"><span class="classic-role">{{ player.role }}</span><b :style="{'--name-duration':`${(nameDurations[index * 5 + position] || 200) / 1000}s`}" :class="{ 'name-rolling': drawing && !lockedSlots.includes(index * 5 + position), 'name-locked': drawing && lockedSlots.includes(index * 5 + position) }"><span :key="drawing && !lockedSlots.includes(index * 5 + position) ? nameTicks[index * 5 + position] : player.id">{{ drawing ? (rollingNames[index * 5 + position] || '待揭晓') : player.name }}</span></b><small v-if="hostAllowed" class="classic-intent">{{ drawing && !lockedSlots.includes(index * 5 + position) ? '5V5' : intentionLabel(player) }}</small></p>
            <p v-if="!team.players.length">{{ drawing ? '正在抽取阵容…' : '队员姓名未公开' }}</p>
          </article>

        </div>
        <footer v-if="!drawReady && data.tournament.drawn_matches" class="classic-arena-actions"><el-button v-if="hostAllowed && data.draw_enabled && drawProgress < drawTotal" type="primary" :disabled="drawing" @click="enterDraw">抽取下一支队伍</el-button><el-button v-if="data.show_names" class="draw-secondary-button" :disabled="drawing" @click="replayNames">重播揭晓</el-button></footer>
      </section>
      <Transition name="spectator-view" mode="out-in"><div :key="tab" class="view-content" :class="{ revealing }">
      <div v-if="tab === 'matches'" class="stage-filter" aria-label="比赛阶段"><button v-for="item in [{id:'all',name:'全部比赛'}, ...Object.entries(labels).map(([id,name])=>({id,name}))]" :key="item.id" :class="{active:stage===item.id}" :aria-pressed="stage===item.id" @click="stage=item.id">{{ item.name }}</button></div>
      <AnnualTournament v-if="tab !== 'matches' && tab !== 'draw'" :tournament="data.tournament" :view="tab" :screen="true" public-view :hide-names="!data.show_names" />
      <section v-else-if="tab === 'matches'" class="match-list"><article v-for="m in filteredMatches" :key="m.id"><header><b>{{ labels[m.stage] }}</b><span>BO{{ m.best_of }} · {{ m.winner ? '已结束' : m.score_a || m.score_b ? '进行中' : ready(m) ? '待开赛' : '待晋级' }}</span></header><div><strong>{{ sourceName(m.sources[0]) }}</strong><b>{{ ready(m) ? m.score_a : '—' }} : {{ ready(m) ? m.score_b : '—' }}</b><strong>{{ sourceName(m.sources[1]) }}</strong></div><details v-if="m.bans.some(b=>b.red.length || b.blue.length)"><summary>逐局Ban</summary><p v-for="b in m.bans" :key="b.game">第{{ b.game }}局 · 红方：{{ b.red.join('、') || '无' }} / 蓝方：{{ b.blue.join('、') || '无' }}</p></details></article></section>
      </div></Transition>
    </section>
    <section v-else-if="!loading && !error" class="empty">正在获取赛事…</section>
    <aside class="quick-actions" aria-label="观赛工具"><button aria-label="全屏观赛" @click="fullscreen"><span>⛶</span>全屏</button><button aria-label="分享赛事" @click="share"><span>↗</span>分享</button><button aria-label="返回顶部" @click="backToTop"><span>↑</span>顶部</button></aside>
    <el-dialog v-model="rulesVisible" title="赛事规则" width="min(560px, 94vw)"><div class="rules-copy"><p><b>首轮赛</b>{{ data.tournament.team_count === 19 ? '18队打9场BO3，9支胜队晋级；轮空队与手动选择的1:2败队打BO3，胜者取得第10个名额。' : '18支队伍两两对战，9场BO3决出9支胜队。' }}</p><p><b>四强争夺赛</b>{{ data.tournament.team_count === 19 ? '10队进行5场BO3，决出5支胜队。' : '8支胜队进行4场BO3，另1支胜队进入待定席位。' }}</p><p><b>四强资格赛</b>{{ data.tournament.team_count === 19 ? '2:0胜队直接进四强；积分第四、第五名的两支2:1胜队手动填入BO5资格赛，胜者晋级。出现4支以上2:0胜队时暂停晋级，特殊规则另定。' : '管理员为待定队选择暂晋级对手，BO5胜者晋级，其他3队直接晋级。' }}</p><p><b>半决赛与决赛</b>均为BO5，先赢3局晋级。本阶段及资格赛可记录逐局Ban。</p></div></el-dialog>
    <el-dialog v-model="shareVisible" title="分享赛事" width="min(400px, 94vw)"><div class="share-content"><img :src="shareQr" alt="观赛链接二维码" /><p>扫码查看赛程与比赛结果</p><el-button type="primary" @click="copyLink">复制观赛链接</el-button></div></el-dialog>
  </main>
</template>
<style scoped>
.public-event{position:relative;isolation:isolate;min-height:100dvh;padding:0 3vw 44px;background:#0a1624;color:#edf5fc;--el-bg-color:#15273a;--el-text-color-primary:#edf5fc;--el-text-color-regular:#b3c8dd;--el-border-color-lighter:#344d66}.public-event::before,.public-event::after{content:"";position:fixed;inset:64px 0 0;z-index:-1;pointer-events:none;background-image:url('../../assets/annual-tournament-bg.png');background-repeat:no-repeat}.public-event::before{background-size:cover;background-position:center;filter:blur(28px);opacity:.18;transform:scale(1.04)}.public-event::after{background-size:cover;background-position:left top;opacity:.36}.public-header{position:sticky;top:0;z-index:20;display:flex;align-items:center;justify-content:space-between;gap:24px;min-height:64px;margin:0 -3vw;padding:0 3vw;background:#071421f2;border-bottom:1px solid #6b9bc02b;backdrop-filter:blur(16px)}.event-brand{display:flex;align-items:center;gap:16px;text-decoration:none;color:#eef7ff;white-space:nowrap}.event-brand strong{font-size:23px;letter-spacing:1px}.event-brand>span{font-size:12px;color:#91adc5;padding-left:16px;border-left:1px solid #456078}.main-nav{display:flex;align-self:stretch;gap:30px}.main-nav button{position:relative;background:none;border:0;color:#a9bfd1;font-size:14px;padding:0 4px;cursor:pointer}.main-nav button.active,.main-nav button:hover{color:#c1e6ff}.main-nav button.active::after{content:"";position:absolute;bottom:0;left:0;right:0;height:3px;background:#70bfff;box-shadow:0 0 16px #66b7ff}.header-share,.secondary-action{border:1px solid #547591;background:#142b40aa;color:#d3e9fb;border-radius:3px;padding:10px 18px;cursor:pointer}.event-hero{min-height:clamp(290px,30vw,510px);display:flex;justify-content:flex-end;align-items:center;padding:45px 8% 35px}.hero-copy{max-width:490px;text-shadow:0 2px 24px #07121f}.hero-kicker{font-size:12px;letter-spacing:5px;color:#b0d7f5}.hero-copy h1{font-size:clamp(34px,4vw,72px);line-height:1.18;letter-spacing:4px;margin:22px 0;font-weight:800}.hero-copy h1 em{font-style:normal;color:#b6ddfa}.hero-copy p{font-size:14px;color:#a9c5dc;letter-spacing:2px}.hero-actions{display:flex;gap:14px;margin-top:28px}.primary-action{display:flex;align-items:center;justify-content:space-between;gap:40px;background:#72b7ee;border:1px solid #9ccefa;color:#071d30;font-size:14px;font-weight:650;padding:13px 22px;cursor:pointer;clip-path:polygon(8px 0,100% 0,100% calc(100% - 8px),calc(100% - 8px) 100%,0 100%,0 8px)}.primary-action:hover{background:#a0d5ff}.secondary-action:hover,.header-share:hover{background:#234969}.event-content{scroll-margin-top:85px;padding:26px clamp(14px,2vw,32px);border:1px solid #608bb833;background:#091a2bce;backdrop-filter:blur(5px);border-radius:6px}.section-heading,.section-heading>div{display:flex;align-items:center;justify-content:space-between;gap:14px}.section-heading{margin-bottom:26px}.heading-mark{width:4px;height:25px;background:#84c8fb;transform:skew(-12deg)}h2{margin:0;font-size:24px;letter-spacing:2px;font-weight:600}.view-switch{display:flex;gap:0;border:1px solid #3e5a72;border-radius:3px;overflow:hidden}.view-switch button,.stage-filter button{border:0;background:#12283c;color:#9bb8ce;padding:10px 20px;font-size:12px;cursor:pointer}.view-switch button.active{background:#508bb8;color:#fff}.stage-filter{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:22px}.stage-filter button{border:1px solid #354d64;border-radius:3px}.stage-filter button.active{border-color:#84c8fb;color:#c9eaff;background:#254766}.public-event :deep(.tournament.is-screen){display:block}.public-event :deep(.bracket-board){padding-top:18px!important;border:0;background:transparent;border-radius:0}.public-event :deep(.bracket-board::before){display:none}.public-event :deep(.bracket-tree){height:clamp(470px,60vh,860px);flex:none}.public-event :deep(.tournament-summary b){font-size:12px;font-weight:400;color:#a9c1d5}.public-event :deep(.directory-card){background:#14283bda}.public-event :deep(.directory-title){color:#edf5fc}.public-event :deep(.match-card){background:#10263bea;border-color:#42617b}.public-event :deep(.match-card:hover){border-color:#a1d6ff;box-shadow:0 0 18px #56b9ff20}.public-event :deep(.bracket-lines path){stroke:#4f7391}.public-event :deep(.bracket-intro>span:first-child){color:#a1cbe9}.public-event :deep(.final-column .match-card){border-color:#8cc0e5}.match-list{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}.match-list article{background:#12283ce8;border:1px solid #365571;border-radius:5px;padding:18px}.match-list header{display:flex;justify-content:space-between;font-size:12px;color:#9ab8d0}.match-list article>div{display:flex;justify-content:space-between;align-items:center;gap:12px;margin:24px 0}.match-list article>div>b{color:#a7d9ff;white-space:nowrap}.match-list details{font-size:12px;color:#9ab8d0}.empty{padding:80px 0;text-align:center;color:#91a4b6}.quick-actions{position:fixed;right:10px;bottom:30px;display:flex;flex-direction:column;gap:1px;z-index:22;box-shadow:0 5px 24px #0005}.quick-actions button{display:flex;flex-direction:column;align-items:center;gap:3px;border:1px solid #4d709158;background:#10273beb;color:#b5d3e9;padding:10px 8px;cursor:pointer;font-size:10px}.quick-actions button>span{font-size:21px;line-height:1}.quick-actions button:hover{background:#285271}.rules-copy p{line-height:1.9;margin:0 0 18px}.rules-copy b{display:block;color:var(--el-text-color-primary)}.share-content{display:flex;flex-direction:column;align-items:center;gap:12px}.share-content img{width:220px;height:220px}.share-content p{margin:0 0 8px;font-size:13px}button:focus-visible,a:focus-visible{outline:2px solid #b2e1ff;outline-offset:4px}
@media(max-width:1000px){.main-nav{gap:16px}.event-brand>span{display:none}.header-share{padding:8px 12px}.event-content{padding:20px 12px}.view-switch button{padding:9px 12px}.match-list{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:650px){.public-event{padding:0 12px 28px}.public-header{margin:0 -12px;padding:10px 12px;gap:10px;flex-wrap:wrap;min-height:64px}.event-brand strong{font-size:20px}.header-share{font-size:11px}.main-nav{order:3;width:100%;gap:0;justify-content:space-between;height:36px}.main-nav button{font-size:12px;padding:0 8px}.public-event::before,.public-event::after{inset:98px 0 0}.event-hero{min-height:300px;padding:125px 16px 25px;align-items:flex-end;justify-content:flex-end}.hero-copy{max-width:250px}.hero-kicker{display:none}.hero-copy h1{font-size:30px;margin:0 0 14px;letter-spacing:2px}.hero-copy p{font-size:11px;margin:0}.hero-actions{gap:8px;margin-top:18px}.primary-action{font-size:12px;padding:10px 14px;gap:18px}.secondary-action{font-size:12px;padding:10px 14px}.section-heading{align-items:flex-start;flex-direction:column;gap:18px}.section-heading h2{font-size:20px}.view-switch{width:100%}.view-switch button{flex:1}.event-content{scroll-margin-top:115px}.match-list{grid-template-columns:1fr}.public-event :deep(.team-directory){grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.quick-actions{right:4px;bottom:18px}.quick-actions button{padding:8px 6px}.stage-filter{gap:6px}.stage-filter button{padding:8px 10px;font-size:11px}.public-event::after{opacity:.4}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}
</style>

<style scoped>
/* Keep the illustration visible; use contrast on the cards rather than a page-sized veil. */
.public-event::before{opacity:.1}.public-event::after{opacity:.62}.event-content{background:linear-gradient(180deg,#091a2b38,#091a2b18);backdrop-filter:none;border-color:#91b9db25;min-height:calc(100dvh - 100px)}.section-heading{padding:10px 12px;background:linear-gradient(90deg,#081a2bdd,#081a2b00);border-radius:3px}.public-event :deep(.tournament-toolbar),.public-event :deep(.bracket-intro){text-shadow:0 1px 4px #000,0 0 14px #031425}.public-event :deep(.stage-labels>div){text-shadow:0 1px 4px #000,0 0 10px #031425}.public-event :deep(.match-card){background:#0c2237ed;box-shadow:0 3px 16px #0003}.hero-copy{text-shadow:0 2px 9px #031425,0 0 28px #031425}.main-nav button,.view-switch button,.stage-filter button,.primary-action,.secondary-action,.header-share,.quick-actions button{transition:color .2s ease,background-color .2s ease,border-color .2s ease,box-shadow .2s ease}.main-nav button::after{transition:opacity .2s ease}.primary-action:active,.secondary-action:active{transform:translateY(1px)}.spectator-view-enter-active{transition:opacity .24s ease,transform .24s cubic-bezier(.22,1,.36,1)}.spectator-view-leave-active{transition:opacity .12s ease,transform .12s ease}.spectator-view-enter-from{opacity:0;transform:translateY(10px)}.spectator-view-leave-to{opacity:0;transform:translateY(-4px)}.view-content{min-height:180px}.hero-copy h1{font-size:clamp(32px,3.5vw,64px)}
@media(max-width:650px){.public-event::after{opacity:.58}.event-content{background:#071b2c20;min-height:calc(100dvh - 125px)}.section-heading{background:linear-gradient(90deg,#081a2ba8,transparent);padding:8px}.hero-copy h1{font-size:30px}}
@media(prefers-reduced-motion:reduce){.spectator-view-enter-active,.spectator-view-leave-active,.main-nav button,.view-switch button,.stage-filter button{transition:none}.spectator-view-enter-from,.spectator-view-leave-to{transform:none}}
</style>

<style scoped>
.event-hero{min-height:calc(100svh - 64px);align-items:flex-start;padding-top:clamp(65px,8vh,120px)}.event-content{background:#091a2bf2;border-color:#608bb84d}.section-heading{background:transparent}.public-event :deep(.bracket-lines path){stroke:#63849f}.public-event :deep(.bracket-side.unresolved){color:#a7bfd3}
@media(max-width:650px){.event-hero{min-height:calc(100svh - 98px);padding-top:150px;align-items:flex-start}.event-content{background:#091a2bf2}}
</style>

<style scoped>
.public-draw-bar{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:24px;padding:20px;background:#102b43e8;border:1px solid #4d7a9c;border-radius:6px}.public-draw-bar b{font-size:16px}.public-draw-bar p,.public-draw-bar>span{font-size:12px;color:#a4bed4;line-height:1.8}.revealing :deep(.directory-card){animation:reveal-team .65s cubic-bezier(.22,1,.36,1) both}.revealing :deep(.directory-card:nth-child(3n+2)){animation-delay:.1s}.revealing :deep(.directory-card:nth-child(3n)){animation-delay:.2s}@keyframes reveal-team{from{opacity:0;transform:translateY(18px)}to{opacity:1;transform:none}}@media(max-width:650px){.public-draw-bar{flex-direction:column;align-items:flex-start}}@media(prefers-reduced-motion:reduce){.revealing :deep(.directory-card){animation:none}}
</style>

<style scoped>
.public-draw-bar .el-button--primary{background:#538fbf;border-color:#79b8e8;color:#fff}.public-draw-bar .el-button--primary:hover{background:#69a7d6;border-color:#a5d7fa}
</style>

<style scoped>
.opening-draw{text-align:center;padding:24px 0}.opening-sides{display:grid;grid-template-columns:1fr 1fr;gap:32px;max-width:1000px;margin:28px auto}.opening-team{padding:24px;text-align:left;background:#102b43;border:1px solid #477594;border-radius:10px}.opening-team.red h3{color:#f493a4}.opening-team.blue h3{color:#8ed1ff}.opening-team p{display:grid;grid-template-columns:4em minmax(0,1fr);gap:20px;align-items:center;padding:14px 0;border-top:1px solid #ffffff15;margin:0}.opening-team p span{color:#a9c0d5}.opening-team p b{font-size:22px}@media(max-width:650px){.opening-sides{gap:12px}.opening-team{padding:12px}.opening-team p{gap:10px}.opening-team p b{font-size:17px}}
</style>

<style scoped>
.opening-draw{min-height:440px;display:flex;flex-direction:column;justify-content:center}.opening-sides{width:min(100%,1000px)}.draw-animation{min-height:300px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:24px;color:#a5d7fa}.draw-animation i{height:66px;width:66px;border:2px solid #538fbf44;border-top-color:#a5d7fa;border-radius:50%;animation:draw-spin .7s linear infinite}.draw-animation b{font-size:25px;letter-spacing:8px}.draw-animation span{font-size:14px}.opening-draw.revealing .opening-team{animation:draw-reveal .65s ease-out both}.opening-draw.revealing .opening-team.blue{animation-delay:.12s}@keyframes draw-spin{to{transform:rotate(360deg)}}@keyframes draw-reveal{from{opacity:0;transform:translateY(20px) scale(.98)}to{opacity:1;transform:none}}@media(prefers-reduced-motion:reduce){.draw-animation i,.opening-draw.revealing .opening-team{animation:none}}
</style>

<style scoped>
.draw-waiting{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:20px;min-height:300px}.waiting-vs{font-size:64px;font-weight:800;color:#9cd6ff;letter-spacing:8px;text-shadow:0 0 30px #538fbf77}.draw-waiting p{color:#9cb8ce}.draw-waiting .el-button{min-width:180px;background:#538fbf;border-color:#8fc5ee}
</style>

<style scoped>
.opening-team p b>span{display:inline-block;color:inherit;font-size:inherit;min-width:4em}.name-rolling{color:#b9dcf7}.name-rolling>span{animation:name-jump var(--name-duration,.2s) ease-out}.name-locked{color:#fff;text-shadow:0 0 14px #8bc9ff55}@keyframes name-jump{from{transform:translateY(-6px);opacity:.35;filter:blur(1px)}to{transform:translateY(0);opacity:1;filter:none}}@media(prefers-reduced-motion:reduce){.name-rolling>span{animation:none}}
</style>

<style scoped>
.classic-arena{min-height:560px;padding:26px 30px 24px;border:1px solid #354757;border-radius:14px;background:radial-gradient(ellipse at 20% 100%,#702d491e,transparent 60%),radial-gradient(ellipse at 90% 100%,#2073a42b,transparent 60%),#0e1b28;box-sizing:border-box;justify-content:flex-start}.classic-arena-meta{display:flex;justify-content:space-between;gap:16px;padding-bottom:18px;border-bottom:1px solid #ffffff0c;color:#8da3b8;font-size:11px;letter-spacing:1px}.classic-arena-title{padding:30px 0 26px;text-align:center}.classic-arena-title>span{color:#ceb47b;font-size:11px;letter-spacing:7px}.classic-arena-title h2{font-size:clamp(24px,2.2vw,36px);font-weight:700;letter-spacing:3px;margin:14px 0}.classic-arena-title p{font-size:12px;color:#8ba1b5;margin:0}.classic-matchup{display:grid;grid-template-columns:minmax(0,1fr) 86px minmax(0,1fr);gap:14px;max-width:none;width:100%;margin:12px auto 0;align-items:center}.classic-matchup.single{grid-template-columns:minmax(0,620px);justify-content:center}.classic-matchup .opening-team{padding:23px 22px;border-color:#ffffff18;background:#ffffff03;min-width:0}.classic-matchup .opening-team.red{grid-column:1;grid-row:1;background:linear-gradient(140deg,#b1446210,#ffffff03)}.classic-matchup .opening-team.blue{grid-column:3;grid-row:1;background:linear-gradient(140deg,#318bc210,#ffffff03)}.classic-matchup .opening-team h3{display:flex;align-items:center;justify-content:space-between;gap:14px;margin:0 0 15px;font-size:21px}.classic-matchup .opening-team h3>span{min-width:0;overflow-wrap:anywhere}.classic-matchup .opening-team h3 small{font-size:13px;opacity:.75;margin-left:14px}.classic-matchup .opening-team h3 em{font-size:9px;letter-spacing:2px;font-style:normal;opacity:.75;white-space:nowrap}.classic-matchup .opening-team p{grid-template-columns:4em minmax(0,1fr) auto;gap:16px;min-height:58px;padding:0}.classic-matchup .opening-team .classic-role{font-size:12px;color:#99a9bb}.classic-matchup .opening-team p b{font-size:clamp(21px,1.8vw,29px);letter-spacing:1px}.classic-intent{font-size:11px;color:#ba8b9b;white-space:nowrap}.blue .classic-intent{color:#7faed1}.classic-vs{grid-column:2;grid-row:1;display:flex;flex-direction:column;align-items:center;gap:10px;color:#d0b57d}.classic-vs strong{font-size:36px;font-weight:650}.classic-vs>span{font-size:10px;letter-spacing:3px}.classic-arena-actions{display:flex;justify-content:center;gap:12px;margin-top:26px}.classic-arena-actions .el-button{margin:0}.classic-matchup .opening-team p b>span{min-width:0;max-width:100%;overflow-wrap:anywhere}@media(max-width:700px){.classic-arena{padding:18px 12px}.classic-matchup{grid-template-columns:minmax(0,1fr) 32px minmax(0,1fr);gap:7px}.classic-matchup .opening-team{padding:14px 10px}.classic-matchup .opening-team h3{font-size:16px;flex-wrap:wrap;gap:6px}.classic-matchup .opening-team h3 small{display:block;margin:5px 0 0}.classic-matchup .opening-team h3 em{display:none}.classic-matchup .opening-team p{grid-template-columns:3em minmax(0,1fr);gap:7px;min-height:65px}.classic-matchup .opening-team p b{font-size:18px}.classic-matchup .opening-team .classic-role{font-size:10px}.classic-intent{grid-column:2;font-size:9px;margin-top:-12px}.classic-vs strong{font-size:22px}.classic-vs>span{display:none}.classic-arena-title h2{font-size:23px}.classic-arena-meta{font-size:10px}}
</style>

<style scoped>
.waiting-team-code{font-size:64px;color:#a8d7fa;font-weight:750;letter-spacing:5px}.classic-matchup.single{grid-template-columns:minmax(0,760px)}.classic-matchup.single .opening-team h3>span{display:flex;align-items:baseline;gap:20px}.classic-matchup.single .opening-team h3 small{margin:0;color:#93acc0;font-size:13px}.classic-matchup.single .opening-team.red{background:linear-gradient(135deg,#538fbf12,#ffffff03);border-color:#4a6880}.classic-matchup.single .opening-team.red h3{color:#9ed1f6}.classic-matchup.single .classic-intent{color:#92b8d5}@media(max-width:700px){.classic-matchup.single .opening-team h3>span{flex-wrap:wrap;gap:8px}}
</style>

<style scoped>
.public-event .draw-secondary-button{background:#e8f3fb;border-color:#bad2e5;color:#244b68;font-weight:600}.public-event .draw-secondary-button:hover,.public-event .draw-secondary-button:focus-visible{background:#fff;border-color:#8cb9d9;color:#173c59}.public-event .draw-secondary-button.is-disabled{background:#d9e6f0;border-color:#b7ccd9;color:#718ca0}
</style>
