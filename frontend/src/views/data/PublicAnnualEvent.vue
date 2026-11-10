<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import QRCode from 'qrcode'
import AnnualTournament from '../../components/AnnualTournament.vue'
const route = useRoute()
const hostAllowed = ref(false)
const drawing = ref(false)
const revealing = ref(false)
const drawReady = ref(false)
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
  } catch { hostAllowed.value = false }
}
async function drawTeams() {
  if (drawing.value || !hostAllowed.value || !data.value?.draw_enabled) return
  drawing.value = true
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
    clearTimeout(revealTimer)
    revealTimer = setTimeout(() => { revealing.value = false }, reducedMotion.matches ? 0 : 900)
    ElMessage.success('本场10人已抽取，结果已自动保存')
  } catch (e) { ElMessage.error(e.message); await load() }
  finally { drawing.value = false }
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
  if (kind === 'team') return teams.value[id]?.name || '待定'
  const t = data.value.tournament
  const match = key => t.matches.find(m => m.id === key)
  if (kind === 'challenger') return teams.value[match(t.challenge_slot)?.winner]?.name || '挑战队伍待选择'
  if (kind === 'qualified') return teams.value[match('C1')?.winner && (id === t.challenge_slot ? match('C1').winner : match(id)?.winner)]?.name || '1/4待定'
  return teams.value[match(id)?.winner]?.name || (match(id)?.stage === 'semi' ? '1/2待定' : '待定')
}
function ready(match) { return match.sources.every(s => !/待定|待选择/.test(sourceName(s))) }
const labels = { opening: '首轮赛', second: '四强争夺赛', qualifier: '四强资格赛', semi: '半决赛', final: '决赛' }
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
onUnmounted(() => { clearTimeout(revealTimer); window.removeEventListener('wheel', wheelSnap); window.removeEventListener('touchstart', touchBegin); window.removeEventListener('touchend', touchFinish); clearInterval(timer); controller?.abort(); generation++ })
</script>
<template>
  <main class="public-event" v-loading="loading">
    <header class="public-header"><a class="event-brand" href="#" @click.prevent="backToTop"><strong>王者荣耀</strong><span>5V5 年会赛事</span></a><nav class="main-nav" aria-label="赛事导航"><button v-for="item in menuItems" :key="item.id" :class="{ active: tab === item.id }" :aria-pressed="tab === item.id" @click="selectView(item.id)">{{ item.name }}</button><button @click="rulesVisible = true">赛事规则</button></nav><button class="header-share" @click="share">分享赛事 ↗</button></header>
    <section class="event-hero"><div class="hero-copy"><span class="hero-kicker">王者荣耀 · 年会挑战赛</span><h1>峡谷集结<br><em>向冠军进发</em></h1><p>18支队伍，同场竞逐。</p><div class="hero-actions"><button class="primary-action" @click="selectView('schedule')">查看全赛程 <span>→</span></button><button class="secondary-action" @click="selectView('teams')">参赛队伍</button></div></div></section>
    <el-alert v-if="error" :title="error" type="info" :closable="false"><el-button size="small" @click="load">重新加载</el-button></el-alert>
    <section v-if="data" ref="matchPanel" class="event-content"><div class="section-heading"><div><span class="heading-mark"></span><h2>{{ tab === 'teams' ? '参赛队伍' : tab === 'matches' ? '比赛列表' : '赛事进程' }}</h2></div><div class="view-switch" aria-label="观赛视图"><button v-for="item in [{id:'schedule',name:'晋级图'},{id:'matches',name:'比赛列表'},{id:'teams',name:'队伍阵容'}]" :key="item.id" :class="{active:tab===item.id}" :aria-pressed="tab===item.id" @click="selectView(item.id)">{{ item.name }}</button></div></div>
      <div v-if="data.draw_enabled" class="public-draw-bar"><div><b>首战对局抽签 · {{ data.tournament.drawn_matches || 0 }} / 9 场</b><p>每场抽取10人，按位置组成两队；本轮人员不重复。</p></div><el-button v-if="hostAllowed" type="primary" :loading="drawing" :disabled="drawing || data.tournament.drawn_matches >= 9" @click="enterDraw">{{ data.tournament.drawn_matches >= 9 ? '首战抽签已完成' : `抽取第${(data.tournament.drawn_matches || 0) + 1}场 · 10人` }}</el-button><el-button v-if="data.tournament.drawn_matches" @click="drawReady=false;tab='draw'">查看最近对局</el-button></div>
      <section v-if="tab === 'draw'" :class="['opening-draw', {revealing}]" :aria-busy="drawing"><h2>{{ drawing ? '正在抽取首战阵容…' : drawReady ? `第 ${(data.tournament.drawn_matches || 0) + 1} 场 · 待抽取` : data.tournament.drawn_matches ? `第 ${data.tournament.drawn_matches} 场首战对局` : '首战对局抽签' }}</h2><div v-if="drawReady && !drawing" class="draw-waiting"><span class="waiting-vs">VS</span><p>红蓝双方各5人，阵容即将揭晓</p><el-button v-if="hostAllowed" type="primary" size="large" @click="drawTeams">开始抽取</el-button></div><div v-else-if="drawing" class="draw-animation" role="status"><i></i><b>集结队友</b><span>对抗路 · 打野 · 中路 · 发育路 · 游走</span></div><div v-else-if="data.tournament.drawn_matches" class="opening-sides"><article v-for="(team, index) in data.tournament.teams.slice((data.tournament.drawn_matches - 1) * 2, data.tournament.drawn_matches * 2)" :key="team.id" :class="['opening-team', index ? 'blue' : 'red']"><h3>{{ team.name }} 队 · {{ index ? '蓝方' : '红方' }}</h3><p v-for="player in team.players" :key="player.id"><span>{{ player.role }}</span><b>{{ player.name }}</b></p><p v-if="!team.players.length">队员姓名未公开</p></article></div></section>
      <Transition name="spectator-view" mode="out-in"><div :key="tab" class="view-content" :class="{ revealing }">
      <div v-if="tab === 'matches'" class="stage-filter" aria-label="比赛阶段"><button v-for="item in [{id:'all',name:'全部比赛'}, ...Object.entries(labels).map(([id,name])=>({id,name}))]" :key="item.id" :class="{active:stage===item.id}" :aria-pressed="stage===item.id" @click="stage=item.id">{{ item.name }}</button></div>
      <AnnualTournament v-if="tab !== 'matches' && tab !== 'draw'" :tournament="data.tournament" :view="tab" :screen="true" public-view :hide-names="!data.show_names" />
      <section v-else-if="tab === 'matches'" class="match-list"><article v-for="m in filteredMatches" :key="m.id"><header><b>{{ labels[m.stage] }}</b><span>BO{{ m.best_of }} · {{ m.winner ? '已结束' : m.score_a || m.score_b ? '进行中' : ready(m) ? '待开赛' : '待晋级' }}</span></header><div><strong>{{ sourceName(m.sources[0]) }}</strong><b>{{ ready(m) ? m.score_a : '—' }} : {{ ready(m) ? m.score_b : '—' }}</b><strong>{{ sourceName(m.sources[1]) }}</strong></div><details v-if="m.bans.some(b=>b.red.length || b.blue.length)"><summary>逐局Ban</summary><p v-for="b in m.bans" :key="b.game">第{{ b.game }}局 · 红方：{{ b.red.join('、') || '无' }} / 蓝方：{{ b.blue.join('、') || '无' }}</p></details></article></section>
      </div></Transition>
    </section>
    <section v-else-if="!loading && !error" class="empty">正在获取赛事…</section>
    <aside class="quick-actions" aria-label="观赛工具"><button aria-label="全屏观赛" @click="fullscreen"><span>⛶</span>全屏</button><button aria-label="分享赛事" @click="share"><span>↗</span>分享</button><button aria-label="返回顶部" @click="backToTop"><span>↑</span>顶部</button></aside>
    <el-dialog v-model="rulesVisible" title="赛事规则" width="min(560px, 94vw)"><div class="rules-copy"><p><b>首轮赛</b>18支队伍两两对战，9场BO3决出9支胜队。</p><p><b>四强争夺赛</b>8支胜队进行4场BO3，另1支胜队进入待定席位。</p><p><b>四强资格赛</b>由管理员为待定队选择1支暂晋级队作为对手，进行BO5。胜者接替对应四强席位，败者淘汰，其他3队直接晋级。</p><p><b>半决赛与决赛</b>均为BO5，先赢3局晋级。本阶段及资格赛可记录逐局Ban。</p></div></el-dialog>
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
