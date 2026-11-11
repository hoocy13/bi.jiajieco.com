<script setup>
import { computed } from 'vue'
const props=defineProps({tournament:Object,resolve:Function,status:Function,score:Function,screen:Boolean,busy:Boolean})
const emit=defineEmits(['open','bye'])
const stages=[{key:'opening',name:'19进10',bo:3},{key:'playin',name:'晋级资格赛',bo:3},{key:'second',name:'10进5',bo:3},{key:'qualifier',name:'四强资格赛',bo:5},{key:'semi',name:'半决赛',bo:5},{key:'final',name:'决赛',bo:5}]
const nodes=computed(()=>stages.flatMap((stage,column)=>{
 const matches=props.tournament.matches.filter(m=>m.stage===stage.key)
 return matches.map((match,i)=>({match,column,x:(column+.5)*1000/6,y:stage.key==='opening'?45+i*70:stage.key==='second'?100+i*130:stage.key==='semi'?230+i*280:370}))
}))
const paths=computed(()=>{
 const map=Object.fromEntries(nodes.value.map(n=>[n.match.id,n]));const result=[]
 for(const node of nodes.value)for(const source of node.match.sources){
  const [kind,key]=source.split(':');let from
  if(kind==='winner'||kind==='loser')from=map[key]
  if(kind==='team' && key===props.tournament.bye_team_id && node.match.stage==='playin')from={x:1000/12,y:675}
  if(kind==='finalist' && props.tournament.qualification_slots?.length){
   const origins=['C1',...props.tournament.matches.filter(m=>m.stage==='second'&&!props.tournament.qualification_slots.includes(m.id)).map(m=>m.id)]
   from=map[origins[Number(key)]]
  }
  if(from){const bend=(from.x+node.x)/2;result.push(`M${from.x+64} ${from.y}H${bend}V${node.y}H${node.x-64}`)}
 }
 return result
})
const bye=computed(()=>props.tournament.teams.find(t=>t.id===props.tournament.bye_team_id))

</script>
<template><div class="nineteen-board"><div class="flow">19队 → 10队 → 5队 → 正式四强 → 冠军</div><div class="nineteen-scroll"><div class="nineteen-canvas"><div class="nineteen-labels"><div v-for="stage in stages" :key="stage.key"><b>{{stage.name}}</b><small>BO{{stage.bo}}</small></div></div><div class="nineteen-tree"><svg viewBox="0 0 1000 720" preserveAspectRatio="none" aria-hidden="true"><path v-for="(path,i) in paths" :key="i" :d="path" /></svg><button v-for="node in nodes" :key="node.match.id" class="nineteen-match" :style="{left: `${node.column*100/6+1.9}%`,top:`${node.y/720*100}%`}" :aria-label="`${stages[node.column].name} ${node.match.id}`" @click="emit('open',node.match.id)"><header><span>{{stages[node.column].name}}</span><small>{{status(node.match)}}</small></header><div v-for="(source,i) in node.match.sources" :key="i" :class="{winner:node.match.winner&&resolve(source).id===node.match.winner}"><span>{{resolve(source).name}}</span><b>{{score(node.match,i)}}</b></div><span v-if="node.match.stage==='qualifier'&&!tournament.qualification_slots?.length" class="qualify-action">第四、第五名 · 对阵待填写</span><span v-if="node.match.stage==='playin'&&!tournament.playin_opponent" class="qualify-action">轮空队 vs 1:2败队 · 待填写</span></button><div class="nineteen-bye"><small>首轮待赛队伍</small><b>{{bye?.name || '待指定'}}</b><span>先打晋级资格赛</span><button v-if="!screen&&!tournament.bye_team_id" class="bye-choice" @click="emit('bye')">选择队伍</button></div></div></div></div></div></template>
<style scoped>
.nineteen-board{padding:24px;border:1px solid #365571;border-radius:12px;background:linear-gradient(120deg,#10263bf2,#0b1829e8);color:#e8f3fc}.flow{font-size:13px;color:#a1cbe9;padding-bottom:24px;border-bottom:1px solid #ffffff15}.nineteen-canvas{min-width:1100px}.nineteen-scroll{overflow-x:auto}.nineteen-labels{display:grid;grid-template-columns:repeat(6,1fr);padding:28px 0 18px;text-align:center}.nineteen-labels small{margin-left:8px;color:#8bacc5;font-size:10px}.nineteen-tree{position:relative;height:1050px}.nineteen-tree svg{position:absolute;width:100%;height:100%;inset:0;pointer-events:none}.nineteen-tree path{fill:none;stroke:#42617b;stroke-width:1;vector-effect:non-scaling-stroke}.nineteen-match{position:absolute;width:12.83%;padding:11px;border:1px solid #42617b;border-radius:7px;background:#102b43;color:inherit;transform:translateY(-50%);text-align:left;cursor:pointer}.nineteen-match header{display:flex;justify-content:space-between;gap:5px;font-size:10px;color:#92aec4;margin-bottom:9px}.nineteen-match header small{font-size:9px}.nineteen-match>div{display:flex;justify-content:space-between;gap:8px;font-size:13px;line-height:1.8}.nineteen-match>div span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.nineteen-match .winner{color:#cdeebc}.nineteen-match:hover{border-color:#9cd6ff}.nineteen-bye{position:absolute;left:1.9%;top:93.75%;width:12.83%;transform:translateY(-50%);box-sizing:border-box;border:1px solid #9b8757;border-radius:7px;background:#182d3a;padding:12px;display:flex;flex-direction:column;gap:6px}.nineteen-bye small,.nineteen-bye span{font-size:10px;color:#b9cbd8}.qualify-action{display:block;font-size:10px;color:#a5d7fa;margin-top:9px;border-top:1px solid #ffffff18;padding-top:7px}.qualify-action[aria-disabled=true]{color:#71869b}
</style>

<style scoped>.bye-choice{border:1px solid #57778c;background:#20394d;color:#d3e9fb;border-radius:4px;font:inherit;font-size:11px;padding:6px;cursor:pointer}</style>
