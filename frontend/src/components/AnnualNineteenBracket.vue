<script setup>
import { computed } from 'vue'
import { hasSemifinalDraw } from '../utils/annualFinalists'
const props=defineProps({tournament:Object,resolve:Function,status:Function,score:Function,screen:Boolean,busy:Boolean})
const emit=defineEmits(['open','bye'])
const stages=[{key:'opening',name:'19进10',bo:3},{key:'second',name:'10进5',bo:3},{key:'semi',name:'半决赛',bo:5},{key:'final',name:'决赛',bo:5}]
const nodes=computed(()=>stages.flatMap((stage,column)=>{
 const matches=props.tournament.matches.filter(m=>m.stage===stage.key||(stage.key==='opening'&&m.stage==='playin'))
 return matches.map((match,i)=>({match,column,x:(column+.5)*880/4,y:match.stage==='playin'?675:stage.key==='opening'?45+i*70:stage.key==='second'?100+i*130:stage.key==='semi'?230+i*280:370}))
}))
const paths=computed(()=>{
 const map=Object.fromEntries(nodes.value.map(n=>[n.match.id,n]));const result=[]
 for(const node of nodes.value)for(const source of node.match.sources){
  const [kind,key]=source.split(':');let from
  if(kind==='winner'||kind==='loser')from=map[key]
  if(node.match.stage==='playin')continue
  if(kind==='finalist')continue
  if(from){const bend=(from.x+node.x)/2;result.push(`M${from.x+85} ${from.y}H${bend}V${node.y}H${node.x-85}`)}
 }
 if(hasSemifinalDraw(props.tournament)){
  const inputs=nodes.value.filter(n=>n.match.stage==='second')
  const outputs=nodes.value.filter(n=>n.match.stage==='semi')
  const ys=[...inputs,...outputs].map(n=>n.y)
  if(ys.length){
   const trunk=440
   result.push(`M${trunk} ${Math.min(...ys)}V${Math.max(...ys)}`)
   for(const n of inputs)result.push(`M${n.x+85} ${n.y}H${trunk}`)
   for(const n of outputs)result.push(`M${trunk} ${n.y}H${n.x-85}`)
  }
 }
 return [...new Set(result)]
})
const extraMatches=computed(()=>props.tournament.matches.filter(m=>m.stage==='qualifier'))
const extraName=m=>m.stage==='playin'?'突围挑战赛':props.tournament.qualification_mode==='four-paired'?`四强突围赛 · 第${m.number}组`:'四强突围赛'
const fourPending=computed(()=>props.tournament.qualification_mode==='four-paired'&&props.tournament.matches.filter(m=>m.stage==='qualifier').every(m=>m.winner))
const champion=computed(()=>props.tournament.teams.find(t=>t.id===props.tournament.matches.find(m=>m.stage==='final')?.winner))
const nodeName=node=>node.match.stage==='playin'?'突围挑战赛':stages[node.column].name

</script>
<template><div class="nineteen-board"><div class="flow">19队 → 10队 → 5队 → 正式四强 → 冠军</div><div class="nineteen-scroll"><div class="nineteen-canvas"><div class="nineteen-labels"><div v-for="stage in stages" :key="stage.key"><b>{{stage.name}}</b><small>BO{{stage.bo}}</small></div></div><div class="nineteen-tree"><svg viewBox="0 0 1000 720" preserveAspectRatio="none" aria-hidden="true"><path v-for="(path,i) in paths" :key="i" :d="path" /></svg><button v-for="node in nodes" :key="node.match.id" class="nineteen-match" :style="{left: `${node.column*88/4+2.5}%`,top:`${node.y/720*100}%`}" :aria-label="`${nodeName(node)} ${node.match.id}`" @click="emit('open',node.match.id)"><header><span>{{nodeName(node)}}</span><small>{{status(node.match)}}</small></header><div v-for="(source,i) in node.match.sources" :key="i" :class="{winner:node.match.winner&&resolve(source).id===node.match.winner,loser:node.match.winner&&resolve(source).id!==node.match.winner}"><span>{{resolve(source).name}}</span><b>{{score(node.match,i)}}</b></div><span v-if="node.match.stage==='qualifier'&&!tournament.qualification_slots?.length" class="qualify-action">第四、第五名 · 对阵待填写</span><span v-if="node.match.stage==='playin'&&node.match.sources[1]==='loser:pending'" class="qualify-action">轮空队 vs 1:2败队 · 待填写</span></button><div class="nineteen-champion"><svg viewBox="0 0 48 48" aria-hidden="true"><path d="M14 7h20v10c0 9-4 15-10 15s-10-6-10-15V7Z M14 11H7v7c0 6 4 9 10 9 M34 11h7v7c0 6-4 9-10 9 M24 32v8 M16 42h16" /></svg><small>冠军</small><strong>{{champion?.name || '待定'}}</strong></div></div></div></div><button v-if="!screen&&!tournament.bye_team_id" class="bye-choice" @click="emit('bye')">选择轮空队</button><div class="extra-matches"><button v-for="match in extraMatches" :key="match.id" class="extra-match" :aria-label="`${extraName(match)} ${match.id}`" @click="emit('open',match.id)"><header><b>{{extraName(match)}}</b><small>BO{{match.best_of}} · {{status(match)}}</small></header><div v-for="(source,side) in match.sources" :key="side" class="extra-side" :class="{winner:match.winner&&resolve(source).id===match.winner,loser:match.winner&&resolve(source).id!==match.winner}"><span :title="resolve(source).name">{{resolve(source).name}}</span><b>{{score(match,side)}}</b></div></button></div><div v-if="tournament.qualification_mode==='four-paired'" class="final-seat-pending">{{fourPending?'最后席位待确认':'四队两组 · BO3'}}</div></div></template>
<style scoped>
.nineteen-board{padding:24px;border:1px solid #365571;border-radius:12px;background:linear-gradient(120deg,#10263bf2,#0b1829e8);color:#e8f3fc}.flow{font-size:13px;color:#a1cbe9;padding-bottom:24px;border-bottom:1px solid #ffffff15}.nineteen-canvas{min-width:800px}.nineteen-scroll{overflow-x:auto}.nineteen-labels{display:grid;grid-template-columns:repeat(4,1fr);width:88%;padding:28px 0 18px;text-align:center}.nineteen-labels>div{position:relative}.nineteen-labels>div:not(:last-child)::after{content:"→";position:absolute;right:-8px;color:#7695ad}.extra-matches{display:grid;grid-template-columns:repeat(2,minmax(0,320px));justify-content:center;gap:14px;padding-top:18px;margin-top:12px;border-top:1px solid #ffffff12}.extra-match{min-width:0;padding:11px 15px;border:1px solid #36526a;border-radius:6px;background:#10263b80;color:inherit;text-align:left;cursor:pointer;transition:background .2s,border-color .2s}.extra-match header{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:9px}.extra-match header b{font-size:12px;font-weight:600}.extra-match header small{color:#8ba7bc;font-size:10px;white-space:nowrap}.extra-scoreline{display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);gap:12px;align-items:center;font-size:13px;line-height:1.6}.extra-scoreline span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.extra-scoreline span:last-child{text-align:right}.extra-scoreline b{font-size:14px;color:#c9e4f7;font-variant-numeric:tabular-nums}.extra-scoreline em{font-style:normal;color:#7595ae;margin:0 5px}.extra-match:hover{border-color:#6c9fbe;background:#16314a}.extra-match:focus-visible{outline:2px solid #8dc9ef;outline-offset:3px}@media(max-width:600px){.extra-matches{grid-template-columns:minmax(0,360px);gap:10px}}
.nineteen-labels small{margin-left:8px;color:#8bacc5;font-size:10px}.nineteen-tree{position:relative;height:1050px}.nineteen-tree>svg{position:absolute;width:100%;height:100%;inset:0;pointer-events:none}.nineteen-champion{position:absolute;left:89%;width:11%;top:51.39%;transform:translateY(-50%);display:flex;align-items:center;flex-direction:column;gap:9px;text-align:center;color:#e4bd70}.nineteen-champion svg{width:48px;height:48px;fill:none;stroke:currentColor;stroke-width:1.5}.nineteen-champion small{font-size:11px}.nineteen-champion strong{font-size:15px;overflow-wrap:anywhere}.nineteen-tree>svg path{fill:none;stroke:#42617b;stroke-width:1;vector-effect:non-scaling-stroke}.nineteen-match{position:absolute;width:17%;padding:11px;border:1px solid #42617b;border-radius:7px;background:#102b43;color:inherit;transform:translateY(-50%);text-align:left;cursor:pointer}.nineteen-match header{display:flex;justify-content:space-between;gap:5px;font-size:10px;color:#92aec4;margin-bottom:9px}.nineteen-match header small{font-size:9px}.nineteen-match>div{display:flex;justify-content:space-between;gap:8px;font-size:13px;line-height:1.8}.nineteen-match>div span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.nineteen-match .winner{color:#cdeebc}.nineteen-match:hover{border-color:#9cd6ff}.nineteen-bye{position:absolute;left:2.5%;top:93.75%;width:17%;transform:translateY(-50%);box-sizing:border-box;border:1px solid #42617b;border-radius:7px;background:#102b43;padding:12px;display:flex;flex-direction:column;gap:6px}.nineteen-bye small,.nineteen-bye span{font-size:10px;color:#b9cbd8}.qualify-action{display:block;font-size:10px;color:#a5d7fa;margin-top:9px;border-top:1px solid #ffffff18;padding-top:7px}.qualify-action[aria-disabled=true]{color:#71869b}
</style>

<style scoped>.bye-choice{border:1px solid #57778c;background:#20394d;color:#d3e9fb;border-radius:4px;font:inherit;font-size:11px;padding:6px;cursor:pointer}</style>

<style scoped>.final-seat-pending{text-align:center;color:#9db6ca;font-size:13px;padding:18px 0 4px}</style>

<style scoped>.nineteen-match .loser>span,.extra-scoreline>span.loser{color:#7890a4;font-weight:400}.nineteen-match .loser>b{color:#7890a4}</style>

<style scoped>
.extra-match{padding:11px;border-color:#42617b;border-radius:7px;background:#102b43}
.extra-match header{gap:5px;align-items:baseline;color:#92aec4}
.extra-match header b{font-size:10px;font-weight:400}
.extra-match header small{font-size:9px;color:inherit}
.extra-side{display:flex;justify-content:space-between;gap:8px;font-size:13px;line-height:1.8}
.extra-side>span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.extra-side>b{font-size:13px;font-variant-numeric:tabular-nums}
.extra-side.winner{color:#cdeebc}
.extra-side.loser{color:#7890a4}
</style>
