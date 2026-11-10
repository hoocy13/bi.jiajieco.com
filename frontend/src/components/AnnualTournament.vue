<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'

const props = defineProps({ tournament: Object, mode: String, busy: Boolean, screen: Boolean, view: String, revision: Number, runCommand: Function, publicView: Boolean, hideNames: Boolean })
async function renameTeam(team) {
  try {
    const { value } = await ElMessageBox.prompt('填写队伍名称，最多20字', '修改队名', { inputValue: team.name, inputValidator: value => !!value?.trim() && value.trim().length <= 20 || '请填写1至20字队名' })
    await props.runCommand('tournament-rename', { team_id: team.id, name: value.trim() })
  } catch { /* User cancelled. */ }
}
const tournament = computed(() => props.tournament)
const matches = computed(() => tournament.value?.matches || [])
const teamMap = computed(() => Object.fromEntries((tournament.value?.teams || []).map(t => [t.id, t])))
const matchMap = computed(() => Object.fromEntries(matches.value.map(m => [m.id, m])))
const completed = computed(() => matches.value.filter(m => m.winner).length)
const champion = computed(() => teamMap.value[matchMap.value.F1?.winner])
const newFormat = computed(() => tournament.value?.format === '18-9-4-wildcard')
const stages = { opening: '首轮赛', second: '四强争夺赛', qualifier: '四强资格赛', semi: '半决赛', final: '决赛' }
const columns = computed(() => {
  const opening = ids => ids.flatMap(id => (matchMap.value[id]?.sources || []).map(source => source.split(':')[1]))
  return [
    { key: 'left-opening', label: '18进9', bo: 3, ids: opening(['B1', 'B2']), positions: [10, 30, 50, 70] },
    { key: 'left-second', label: '争夺四强', bo: 3, ids: ['B1', 'B2'], positions: [20, 60] },
    { key: 'left-semi', label: '半决赛', bo: 5, ids: ['S1'], positions: [55] },
    { key: 'final', label: '冠军之路', bo: 5, ids: ['F1'], positions: [55] },
    { key: 'right-semi', label: '半决赛', bo: 5, ids: ['S2'], positions: [55] },
    { key: 'right-second', label: '争夺四强', bo: 3, ids: ['B3', 'B4'], positions: [25, 75] },
    { key: 'right-opening', label: '18进9', bo: 3, ids: opening(['B3', 'B4']), positions: [12.5, 37.5, 62.5, 87.5] },
  ]
})
const waitingMatch = computed(() => matchMap.value[matchMap.value.C1?.sources[0]?.split(':')[1]])
const connectors = computed(() => {
  const paths = [
    'M91 51H100V102H109 M91 154H100V102', 'M91 256H100V307H109 M91 358H100V307',
    'M609 64H600V128H591 M609 192H600V128', 'M609 320H600V384H591 M609 448H600V384',
    'M291 282H309', 'M409 282H391',
  ]
  for (const [slot, x, y, bend, end] of [['B1',191,102,200,209],['B2',191,307,200,209],['B3',509,128,500,491],['B4',509,384,500,491]]) {
    paths.push(`M${x} ${y}H${bend}V282H${end}`)
  }
  return paths
})
const challengePaths = computed(() => {
  const waitingPath = 'M91 461H109'
  const slot = tournament.value?.challenge_slot
  if (!slot) return [waitingPath, 'M191 461H200V282H209']
  const paths = [waitingPath, 'M191 461H200V282H209']
  return paths
})
const canDrawChallenge = computed(() => newFormat.value && tournament.value.generated && !tournament.value.challenge_slot && ['B1', 'B2', 'B3', 'B4'].every(id => matchMap.value[id]?.winner))
const waitingTeam = computed(() => resolveSource(matchMap.value.C1?.sources[0] || 'team:pending'))
async function upgrade() {
  try {
    await ElMessageBox.confirm('保留现有队伍，旧赛程归档，按新规则重新抽取签位和记录比分。', '切换新赛制')
    await props.runCommand('tournament-upgrade')
  } catch { /* cancelled */ }
}
const selectedOpponent = ref('')
const challengeCandidates = computed(() => ['B1','B2','B3','B4'].map(id => teamMap.value[matchMap.value[id]?.winner]).filter(Boolean))
async function chooseOpponent() {
  if (!selectedOpponent.value || !canDrawChallenge.value) return
  try {
    await ElMessageBox.confirm('保存后锁定此队作为资格赛对手。', '确认挑战队伍')
    if (await props.runCommand('tournament-challenge', { revision: openedRevision.value, team_id: selectedOpponent.value })) drawer.value = false
  } catch { /* cancelled */ }
}
const selectedId = ref('')
const selectedTeam = ref(null)
const drawer = ref(false)
const scoreA = ref(0)
const scoreB = ref(0)
const banGames = ref([])
const saving = ref(false)
const openedRevision = ref(0)
const selected = computed(() => matchMap.value[selectedId.value])
const sides = computed(() => selected.value ? selected.value.sources.map(resolveSource) : [])
const target = computed(() => (selected.value?.best_of || 3) === 5 ? 3 : 2)
const editable = computed(() => !props.screen && tournament.value?.generated && sides.value.every(t => t.id))
const detailTab = ref('score')

function resolveSource(source) {
  const [kind, id] = source.split(':')
  if (kind === 'team') return teamMap.value[id] || { name: '待抽签' }
  if (kind === 'challenger') {
    const slot = tournament.value?.challenge_slot
    return teamMap.value[matchMap.value[slot]?.winner] || { name: '待选择挑战队伍' }
  }
  if (kind === 'qualified') {
    if (!matchMap.value.C1?.winner) return { name: '1/4待定' }
    return teamMap.value[id === tournament.value.challenge_slot ? matchMap.value.C1.winner : matchMap.value[id]?.winner] || { name: '待晋级' }
  }
  const winner = matchMap.value[id]?.winner
  return teamMap.value[winner] || { name: matchMap.value[id]?.stage === 'semi' ? '1/2待定' : '待定', origin: id }
}
function status(match) {
  if (match.winner) return '已结束'
  if (match.score_a || match.score_b) return '进行中'
  return match.sources.every(s => resolveSource(s).id) && tournament.value?.generated ? '待开赛' : '待晋级'
}
function score(match, side) {
  return tournament.value?.generated && match.sources.every(s => resolveSource(s).id) ? (side === 0 ? match.score_a : match.score_b) : '—'
}
function openMatch(id) {
  const match = matchMap.value[id]
  if (!match) return
  selectedTeam.value = null
  selectedOpponent.value = ''
  selectedId.value = id
  openedRevision.value = props.revision
  scoreA.value = match.score_a
  scoreB.value = match.score_b
  banGames.value = Array.from({ length: match.best_of }, (_, i) => {
    const existing = match.bans?.find(b => b.game === i + 1)
    return { game: i + 1, red: [...(existing?.red || [])], blue: [...(existing?.blue || [])] }
  })
  detailTab.value = 'score'
  drawer.value = true
}
function openTeam(team) {
  selectedId.value = ''
  selectedTeam.value = team
  drawer.value = true
}
async function saveScore() {
  if (!editable.value || saving.value) return
  saving.value = true
  try {
    const ok = await props.runCommand('tournament-score', { revision: openedRevision.value, id: selectedId.value, score_a: scoreA.value, score_b: scoreB.value, bans: selected.value.best_of === 5 ? banGames.value : [] })
    if (ok) drawer.value = false
  } finally { saving.value = false }
}
async function simulate() {
  try {
    await ElMessageBox.confirm('将用模拟比分完成所有尚未结束的比赛，已有结果保留。仅影响演练赛程。', '演示完整晋级')
    await props.runCommand('tournament-demo')
  } catch { /* cancelled */ }
}
watch(() => props.mode, () => { drawer.value = false })
watch(() => props.tournament?.id, () => { drawer.value = false; selectedTeam.value = null })
watch(() => props.hideNames, () => { drawer.value = false; selectedTeam.value = null })
</script>

<template>
  <section v-if="tournament" class="tournament" :class="{ 'is-screen': screen }">
    <div class="tournament-toolbar">
      <div class="tournament-summary"><b>18队淘汰赛</b><span>{{ tournament.generated ? `已完成 ${completed} / 17 场` : '90人上场 · 18支队伍' }}</span><el-tag v-if="tournament.simulated_results" type="warning" size="small">模拟比分</el-tag></div>
      <div v-if="!screen" class="tournament-actions">
        <el-button v-if="!newFormat" :disabled="busy" @click="upgrade">切换新赛制</el-button>

        <el-button v-if="newFormat && mode === 'demo' && tournament.generated && completed < 17" :disabled="busy" @click="simulate">演示完整晋级</el-button>
      </div>
    </div>
    <template v-if="view !== 'teams'">
      <div v-if="newFormat" class="bracket-board">
        <div class="bracket-intro"><span>18队 → 9队 → 4队暂晋级＋1队待定 → 正式四强 → 冠军</span></div>
        <div class="bracket-scroll">
          <div class="bracket-canvas">
            <div class="stage-labels"><div v-for="column in columns" :key="column.key" :class="{ 'final-label': column.key === 'final' }"><b>{{ column.label }}</b><span v-if="column.key !== 'final'">BO{{ column.bo }}</span></div></div>
            <div class="bracket-tree">
              <svg class="bracket-lines" viewBox="0 0 700 512" preserveAspectRatio="none" aria-hidden="true"><path v-for="(path, i) in connectors" :key="i" :d="path" /><path v-for="(path, i) in challengePaths" :key="`challenge-${i}`" :d="path" class="challenge-line" /></svg>
              <div v-for="column in columns" :key="column.key" class="bracket-column" :class="{ 'final-column': column.key === 'final' }">
                <button v-for="(id, index) in column.ids" :key="id" class="match-card" :class="{ finished: matchMap[id]?.winner, live: status(matchMap[id]) === '进行中' }" :style="{ top: `${column.positions[index]}%` }" :aria-label="`${stages[matchMap[id].stage]} ${id}`" @click="openMatch(id)">
                  <div class="match-meta"><span>{{ stages[matchMap[id].stage] }}</span><span>{{ status(matchMap[id]) }}</span></div>
                  <div v-for="(source, side) in matchMap[id].sources" :key="side" class="bracket-side" :class="{ winner: matchMap[id].winner && resolveSource(source).id === matchMap[id].winner, unresolved: !resolveSource(source).id }"><span>{{ resolveSource(source).name }}</span><b>{{ score(matchMap[id], side) }}</b></div>
                </button>
                  <button v-if="column.key === 'left-opening' && waitingMatch" class="match-card waiting-tree-card" aria-label="待定队首轮比赛" @click="openMatch(waitingMatch.id)"><div class="match-meta"><span>首轮赛 · 18进9</span><span>BO3</span></div><div v-for="(source, side) in waitingMatch.sources" :key="side" class="bracket-side" :class="{ winner: waitingMatch.winner && resolveSource(source).id === waitingMatch.winner }"><span>{{ resolveSource(source).name }}</span><b>{{ score(waitingMatch, side) }}</b></div><small>胜者挑战指定暂晋级队</small></button>
                  <button v-if="column.key === 'left-second'" class="match-card qualifier-tree-card" aria-label="四强资格赛 C1" @click="openMatch('C1')"><div class="match-meta"><span>四强资格赛</span><span>BO5</span></div><div v-for="(source, side) in matchMap.C1.sources" :key="side" class="bracket-side" :class="{ winner: matchMap.C1.winner && resolveSource(source).id === matchMap.C1.winner, unresolved: !resolveSource(source).id }"><span>{{ resolveSource(source).name }}</span><b>{{ score(matchMap.C1, side) }}</b></div><small>{{ tournament.challenge_slot ? `挑战 ${resolveSource('challenger:pending').name} 队 · 胜者进四强` : '点击选择挑战队伍' }}</small></button>

                <template v-if="column.key === 'final'">


                </template>
                <div v-if="column.key === 'final'" class="champion-display" :class="{ crowned: champion }"><svg viewBox="0 0 48 48" aria-hidden="true"><path d="M14 7h20v10c0 9-4 15-10 15s-10-6-10-15V7Z M14 11H7v7c0 6 4 9 10 9 M34 11h7v7c0 6-4 9-10 9 M24 32v8 M16 42h16" /></svg><span>{{ champion ? '冠军' : '冠军席位' }}</span><strong>{{ champion?.name || '虚位以待' }}</strong></div>
              </div>
            </div>
          </div>
        </div>
        
      </div>
      <el-alert v-else title="当前保存的是旧赛制。切换新赛制后保留队员，旧赛程归档保存。" type="info" :closable="false" />
      <p v-if="!tournament.generated" class="tournament-hint">当前展示赛程结构，参赛队伍确定后显示对阵。</p>
    </template>
    <div v-else class="team-directory"><article v-for="team in tournament.teams" :key="team.id" class="directory-card"><button class="directory-title" @click="openTeam(team)"><b>{{ team.name }}</b><span>{{ team.id }}</span></button><el-button v-if="!screen && tournament.generated" text size="small" :disabled="busy" @click="renameTeam(team)" :aria-label="`修改${team.name}队名`">改名</el-button><template v-if="team.players.length"><div v-for="p in team.players" :key="p.id" class="directory-player"><span>{{ p.role }}</span><strong>{{ p.name }}</strong></div></template><p v-else class="empty-team">{{ hideNames ? '队员姓名未公开' : '等待抽取队员' }}</p></article></div>


    <el-drawer v-model="drawer" append-to-body size="min(560px, 100vw)" :title="selectedTeam ? `${selectedTeam.name} · 队员名单` : selected ? `${stages[selected.stage]} · BO${selected.best_of}` : '比赛详情'" class="tournament-drawer">
      <template v-if="selectedTeam"><p v-if="!selectedTeam.players.length">{{ hideNames ? '队员姓名未公开' : '队伍尚未生成' }}</p><div v-for="p in selectedTeam.players" :key="p.id" class="roster-line"><span>{{ p.role }}</span><b>{{ p.name }}</b></div></template>
      <template v-else-if="selected">
        <section v-if="selected.stage === 'qualifier' && !screen && !tournament.challenge_slot" class="opponent-choice"><h3>选择资格赛对手</h3><p class="score-hint">第二轮结束后，从4支暂晋级队伍中手动选择一队。保存后锁定。</p><el-select v-model="selectedOpponent" :disabled="!canDrawChallenge || busy" placeholder="选择挑战队伍" aria-label="资格赛挑战队伍"><el-option v-for="team in challengeCandidates" :key="team.id" :label="`${team.name} 队`" :value="team.id" /></el-select><el-button type="primary" :disabled="!canDrawChallenge || !selectedOpponent || busy" @click="chooseOpponent">确认对手</el-button></section>
        <el-tabs v-model="detailTab"><el-tab-pane label="比分与阵容" name="score" /><el-tab-pane v-if="selected.best_of === 5" label="逐局 Ban" name="ban" /></el-tabs>
        <template v-if="detailTab === 'score'">
          <div class="score-editor"><div><b>{{ sides[0]?.name }}</b><el-input-number v-model="scoreA" :min="0" :max="target" :disabled="!editable || busy" aria-label="红方胜局" /></div><span>:</span><div><b>{{ sides[1]?.name }}</b><el-input-number v-model="scoreB" :min="0" :max="target" :disabled="!editable || busy" aria-label="蓝方胜局" /></div></div>
          <p class="score-hint">{{ target }}局获胜即晋级{{ selected.best_of === 5 ? '，本阶段可记录逐局禁用英雄' : '，本阶段全英雄、不设赛事 Ban' }}。</p>
          <el-alert v-if="!sides.every(t => t.id)" title="上游比赛结束后自动填入晋级队伍" type="info" :closable="false" />
          <div class="detail-rosters"><section v-for="(team, side) in sides" :key="side"><h3>{{ team.name }}</h3><div v-for="p in team.players || []" :key="p.id" class="roster-line"><span>{{ p.role }}</span><b>{{ p.name }}</b></div><p v-if="!team.players?.length" class="score-hint">{{ hideNames ? '队员姓名未公开' : '等待队伍就位' }}</p></section></div>
        </template>
        <template v-else><p class="score-hint">按现场规则填写每局禁用英雄，输入名字后回车确认。两队同一局不能重复禁用同一英雄。</p><section v-for="game in banGames" :key="game.game" class="ban-game"><h3>第 {{ game.game }} 局</h3><label>红方禁用</label><el-select v-model="game.red" multiple filterable allow-create default-first-option :disabled="!editable || busy" placeholder="输入英雄名称后回车" /><label>蓝方禁用</label><el-select v-model="game.blue" multiple filterable allow-create default-first-option :disabled="!editable || busy" placeholder="输入英雄名称后回车" /></section></template>
      </template>
      <template #footer><el-button @click="drawer = false">关闭</el-button><el-button v-if="selected && !screen" type="primary" :disabled="!editable || busy" :loading="saving" @click="saveScore">保存比分与 Ban</el-button></template>
    </el-drawer>
  </section>
</template>

<style scoped>
.bracket-board{position:relative;isolation:isolate}.bracket-board::before{content:"";position:absolute;inset:0;z-index:-1;border-radius:inherit;background:url('../assets/annual-tournament-bg.png') left top / contain no-repeat;opacity:.22;pointer-events:none}
.tournament-toolbar,.tournament-summary,.tournament-actions{display:flex;align-items:center;gap:14px;flex-wrap:wrap}.tournament-toolbar{justify-content:space-between;margin-bottom:16px}.tournament-summary b{font-size:16px}.tournament-summary>span,.tournament-hint,.tournament-reserves{font-size:12px;color:#7c8792}.tournament-actions .el-button+.el-button{margin-left:0}.generate-button{background:#315e1b;color:white;border-color:#315e1b}.bracket-board{background:radial-gradient(ellipse at 50% 40%,#1f303c66,transparent 60%),#101923;color:#edf2f7;border:1px solid #283845;border-radius:14px;padding:20px 22px}.bracket-intro{display:flex;justify-content:space-between;gap:12px;font-size:12px;color:#a5b4c1;padding-bottom:18px;border-bottom:1px solid #ffffff12}.bracket-intro>span:first-child{color:#e2c58c;letter-spacing:2px}.bracket-scroll{overflow-x:auto;padding-top:20px;padding-bottom:8px}.bracket-canvas{min-width:900px}.stage-labels{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));text-align:center;gap:0}.stage-labels>div{display:flex;justify-content:center;align-items:center;gap:8px}.stage-labels b{font-size:14px;font-weight:500}.stage-labels span{font-size:10px;color:#8495a3}.stage-labels .final-label b{color:#e2c58c;font-size:17px}.bracket-tree{height:clamp(360px,calc(100dvh - 390px),850px);position:relative;display:grid;grid-template-columns:repeat(7,minmax(0,1fr))}.bracket-lines{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}.bracket-lines path{fill:none;stroke:#3b4c5d;stroke-width:1;vector-effect:non-scaling-stroke}.bracket-column{position:relative;min-width:0}.match-card{position:absolute;left:9%;width:82%;transform:translateY(-50%);background:#18232f;border:1px solid #354351;border-radius:8px;padding:9px 10px;color:#e5edf4;text-align:left;cursor:pointer;font-family:inherit;transition:border-color .15s}.match-card:hover,.match-card:focus-visible{border-color:#8aa4b9;outline:0;background:#1c2b39}.match-card.finished{border-color:#4c6654}.match-card.live{border-color:#bd9557}.match-meta{display:flex;justify-content:space-between;font-size:9px;color:#8395a5;margin-bottom:7px}.bracket-side{display:flex;justify-content:space-between;gap:6px;font-size:12px;align-items:center;min-height:25px}.bracket-side>span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.bracket-side b{font-size:14px;min-width:13px;text-align:right;color:#93a6b6}.bracket-side.winner{color:#d6e8b8;font-weight:650}.bracket-side.winner b{color:#d6e8b8}.bracket-side.unresolved{color:#7d91a2;font-size:11px}.final-column .match-card{border-color:#a98e5b;background:#242a2e}.champion-display{position:absolute;top:68%;left:0;width:100%;display:flex;align-items:center;flex-direction:column;gap:7px;color:#a58d61;text-align:center}.champion-display svg{width:48px;height:48px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}.champion-display>span{font-size:10px;letter-spacing:3px}.champion-display strong{font-size:17px;font-weight:550}.champion-display.crowned{color:#f0cf82}.playin-section{display:flex;align-items:center;gap:24px;border-top:1px solid #ffffff12;padding-top:18px;flex-wrap:wrap}.playin-label{display:flex;flex-direction:column;gap:6px}.playin-label b{font-size:13px;font-weight:500}.playin-label span{font-size:10px;color:#8294a4}.playin-matches{display:flex;gap:12px;flex:1;flex-wrap:wrap}.playin-card{display:flex;align-items:center;justify-content:space-between;gap:12px;min-width:310px;flex:1;border:1px solid #344452;background:#17232f;color:#e5edf4;border-radius:8px;padding:12px 14px;cursor:pointer;font:inherit;font-size:12px}.playin-card:hover{border-color:#8aa4b9}.playin-card .playin-id,.playin-card small{font-size:10px;color:#8b9eaf}.playin-name{min-width:36px}.playin-card b{color:#d7bd87;white-space:nowrap}.tournament-reserves{margin:14px 0}.tournament-reserves summary{cursor:pointer;width:fit-content}.team-directory{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:14px}.directory-card{background:var(--el-bg-color);border:1px solid var(--el-border-color-lighter);border-radius:10px;padding:15px}.directory-title{display:flex;justify-content:space-between;align-items:center;width:100%;border:0;background:none;color:var(--el-text-color-primary);padding:0 0 12px;cursor:pointer}.directory-title b{font-size:16px}.directory-title span{color:#91a08a;font-size:11px}.directory-player{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:10px 0;border-top:1px solid var(--el-border-color-lighter);font-size:13px}.directory-player>span{font-size:11px;color:#84917e}.directory-player strong{font-weight:500}.empty-team{font-size:12px;color:#9aa1a8;padding:25px 0}.score-editor{display:flex;justify-content:center;align-items:center;gap:18px;margin:20px 0}.score-editor>div{display:flex;flex-direction:column;align-items:center;gap:18px}.score-editor>span{font-size:30px;color:#89939d}.score-hint{font-size:12px;color:var(--el-text-color-secondary);line-height:1.8}.detail-rosters{display:grid;grid-template-columns:1fr 1fr;gap:22px;margin-top:24px}.detail-rosters h3,.ban-game h3{font-size:14px;font-weight:600}.roster-line{display:flex;align-items:center;justify-content:space-between;gap:10px;border-bottom:1px solid var(--el-border-color-lighter);padding:12px 0;font-size:13px}.roster-line span{font-size:11px;color:var(--el-text-color-secondary)}.ban-game{border:1px solid var(--el-border-color-lighter);border-radius:8px;padding:14px;margin-bottom:12px}.ban-game h3{margin-top:0}.ban-game label{display:block;font-size:12px;color:var(--el-text-color-secondary);margin:12px 0 7px}.ban-game .el-select{width:100%}
@media(min-width:1700px){.bracket-side{font-size:14px;min-height:28px}.match-card{padding:11px 12px}.match-meta{font-size:10px}}
@media(min-width:651px) and (max-height:850px){.tournament.is-screen .bracket-board{padding:14px 18px}.tournament.is-screen .bracket-intro{padding-bottom:12px}.tournament.is-screen .bracket-scroll{padding-top:12px}.tournament.is-screen .playin-section{padding-top:12px}.tournament.is-screen .match-card{padding:7px 9px}.tournament.is-screen .bracket-side{min-height:23px;font-size:12px}.tournament.is-screen .match-meta{font-size:9px;margin-bottom:5px}.tournament.is-screen .champion-display svg{width:34px;height:34px}}
@media(max-width:1250px){.team-directory{grid-template-columns:repeat(3,minmax(0,1fr))}.bracket-board{padding:16px}.playin-label{width:100%}}
@media(max-width:650px){.team-directory{grid-template-columns:repeat(2,minmax(0,1fr))}.bracket-intro{flex-direction:column;font-size:10px}.playin-card{min-width:260px;padding:10px;gap:7px}.bracket-board{padding:12px}.score-editor{gap:10px}.score-editor .el-input-number{width:125px}}
.tournament.is-screen{flex:1;min-height:0;display:flex;flex-direction:column}.is-screen .tournament-toolbar{flex-shrink:0}.is-screen .bracket-board{flex:1;min-height:0;display:flex;flex-direction:column}.is-screen .bracket-intro,.is-screen .playin-section{flex-shrink:0}.is-screen .bracket-scroll{flex:1;min-height:390px;display:flex;flex-direction:column}.is-screen .bracket-canvas{flex:1;min-height:0;display:flex;flex-direction:column}.is-screen .stage-labels{flex-shrink:0}.is-screen .bracket-tree{height:auto;flex:1;min-height:360px}.is-screen .bracket-side{font-size:clamp(11px,.9vw,17px)}.is-screen .playin-name{font-size:clamp(12px,1vw,17px)}
.bracket-board,.tournament.is-screen .bracket-board{padding-top:clamp(88px,8.2vw,164px)}
</style>


<style scoped>
.bracket-canvas{min-width:1100px}.bracket-tree{height:clamp(360px,calc(100dvh - 430px),800px)}.match-card{background:#16232fe8;box-shadow:0 4px 18px #00000014}.bracket-side.unresolved{font-size:10px}.wildcard-strip{display:flex;align-items:center;gap:16px;border-top:1px solid #ffffff12;padding-top:15px;margin-top:8px;flex-shrink:0}.wildcard-heading{display:flex;flex-direction:column;gap:6px;min-width:130px}.wildcard-heading b{font-size:13px;color:#dfc28a;font-weight:500}.wildcard-heading span,.wildcard-result{font-size:10px;color:#91a3b3;line-height:1.7}.wildcard-match{border:1px solid #3a4d5d;background:#14232dcc;border-radius:8px;padding:9px 14px;color:#e5edf4;cursor:pointer;text-align:left;flex:1;max-width:380px;min-width:230px;font:inherit}.wildcard-match:hover{border-color:#b9a172}.wildcard-match>div{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:6px 0;font-size:13px}.wildcard-match b{color:#dfc28a;white-space:nowrap}.wildcard-match small{color:#94a7b6;font-size:10px}.qualifier-match{border-color:#776648}.wildcard-arrow{color:#bca372}.wildcard-result{margin-left:auto;white-space:nowrap}.schedule-rule{font-size:10px;color:#8193a2;margin-top:12px;flex-shrink:0}.is-screen .bracket-scroll{min-height:350px}.is-screen .bracket-tree{min-height:320px}.is-screen .bracket-side{font-size:clamp(11px,.85vw,16px)}
@media(max-width:1000px){.wildcard-strip{flex-wrap:wrap}.wildcard-heading{width:100%}.wildcard-result{display:none}.wildcard-match{max-width:none}.wildcard-arrow{display:none}}
@media(max-height:850px) and (min-width:1001px){.wildcard-strip{gap:12px;padding-top:10px}.wildcard-match{padding:6px 10px}.wildcard-match>div{padding:4px 0}.wildcard-heading{min-width:110px}.is-screen .match-card{padding:6px 8px}.is-screen .bracket-side{min-height:21px}.is-screen .champion-display{top:72%;gap:4px}}
</style>

<style scoped>
.final-column .waiting-tree-card{top:8%;border-color:#4a6174;background:#142332f2}.final-column .qualifier-tree-card{top:27%;border-color:#aa8b54;background:#222a30f2}.waiting-tree-card small,.qualifier-tree-card small{display:block;font-size:9px;color:#a6b5c1;margin-top:5px;line-height:1.4}.bracket-lines .challenge-line{stroke:#c6a56c;stroke-dasharray:5 4}.champion-display,.tournament.is-screen .champion-display{top:77%}.tree-draw-button{position:absolute;top:40%;left:50%;transform:translateX(-50%);font-size:10px}.bracket-tree{height:clamp(470px,calc(100dvh - 340px),900px)}.is-screen .bracket-tree{min-height:470px}.bracket-canvas{padding-top:30px}.is-screen .bracket-scroll{min-height:530px}.final-column .qualifier-tree-card{width:90%;left:5%}
@media(max-height:850px){.is-screen .match-card{padding:5px 8px}.is-screen .bracket-side{min-height:19px}.is-screen .match-meta{margin-bottom:3px}.waiting-tree-card small,.qualifier-tree-card small{font-size:8px;margin-top:3px}.is-screen .bracket-tree{min-height:420px}.is-screen .bracket-scroll{min-height:470px}.bracket-canvas{padding-top:24px}}
</style>

<style scoped>
.bracket-column .waiting-tree-card{top:90%;border-color:#aa8b54;background:#182630f2}.waiting-tree-card small{color:#cfb77e}.qualifier-tree-card small{color:#cfb77e}
</style>

<style scoped>
.bracket-column .qualifier-tree-card{top:87%;left:9%;width:82%;border-color:#aa8b54;background:#222a30f2}.tree-draw-button{top:98%;left:50%}.final-column .match-card{border-color:#a98e5b}
</style>

<style scoped>
.bracket-column .qualifier-tree-card{top:90%}.bracket-column .waiting-tree-card,.bracket-column .qualifier-tree-card{min-height:100px}.tree-draw-button{top:99%}.bracket-lines .challenge-line{stroke-width:1.25;stroke:#d3b16e}
@media(max-height:850px){.bracket-column .waiting-tree-card,.bracket-column .qualifier-tree-card{min-height:76px}}
</style>

<style scoped>
.bracket-lines .challenge-line{stroke:#3b4c5d;stroke-width:1;stroke-dasharray:none}
</style>

<style scoped>
.tournament:not(.is-screen) .bracket-scroll{overflow:visible;height:auto;max-height:none}.tournament:not(.is-screen) .bracket-canvas{min-width:0;padding-bottom:30px}.tournament:not(.is-screen) .bracket-tree{height:clamp(620px,70vh,960px);min-height:620px}.tournament:not(.is-screen) .match-card{padding:7px 8px}.tournament:not(.is-screen) .bracket-side{min-height:24px}.tournament:not(.is-screen) .stage-labels b{font-size:12px}
@media(max-width:900px){.tournament:not(.is-screen) .bracket-canvas{min-width:900px}}
</style>

<style scoped>
@media(max-width:900px){.tournament:not(.is-screen) .bracket-scroll{overflow-x:auto;overflow-y:hidden}}
</style>

<style scoped>
.opponent-choice{padding:16px;border:1px solid var(--el-border-color-lighter);border-radius:8px;margin-bottom:20px}.opponent-choice h3{font-size:14px;margin-top:0}.opponent-choice .el-select{width:100%;margin-bottom:12px}
</style>
