<script setup>
import { finalistTeamIds } from '../utils/annualFinalists'
import { ref, onUnmounted } from 'vue'
const props=defineProps({kind:String,title:String,tournament:Object,busy:Boolean})
const emit=defineEmits(['start','back'])
const rows=ref([]), names=ref([]), locked=ref([]), complete=ref(false)
const timers=new Map()
const waitingNext=ref(false)
let disposed=false
let advance
function nextGroup(){waitingNext.value=false;advance?.();advance=null}
function teamName(t,id){return t.teams.find(x=>x.id===id)?.name||'待定'}
function sourceTeam(t,source){
 const [kind,id]=source.split(':');const match=key=>t.matches.find(m=>m.id===key)
 if(kind==='team')return id
 if(kind==='winner')return match(id)?.winner
 if(kind==='loser'){const m=match(id);return m?.sources.map(s=>s.split(':')[1]).find(x=>x!==m.winner)}
 if(kind==='finalist')return finalistTeamIds(t)[Number(id)]
}
function resultRows(t){
 const stage={opening:'opening',second:'second',semi:'semi',playin:'playin',qualifier:'qualifier'}[props.kind]
 const result=t.matches.filter(m=>m.stage===stage).map((m,i)=>({id:m.id,label:props.kind==='semi'?`半决赛 ${i+1}`:`第 ${i+1} 组`,names:m.sources.map(s=>teamName(t,sourceTeam(t,s)))}))
 if(props.kind==='opening')result.unshift({id:'bye',label:'轮空队',names:[teamName(t,t.bye_team_id)]})
 return result
}
function poolNames(){
 const t=props.tournament,close=m=>m.winner&&[m.score_a,m.score_b].sort().join(',')==='1,2'
 let ids
 if(props.kind==='playin')ids=t.matches.filter(m=>m.stage==='opening'&&close(m)).map(m=>sourceTeam(t,'loser:'+m.id))
 if(props.kind==='qualifier')ids=t.matches.filter(m=>m.stage==='second'&&close(m)).map(m=>m.winner)
 if(props.kind==='second')ids=t.matches.filter(m=>['opening','playin'].includes(m.stage)).map(m=>m.winner)
 if(props.kind==='semi'){const origins=['C1',...t.matches.filter(m=>m.stage==='second'&&!t.qualification_slots?.includes(m.id)).map(m=>m.id)];ids=origins.map(id=>t.matches.find(m=>m.id===id)?.winner)}
 return t.teams.filter(team=>!ids||ids.includes(team.id)).map(team=>team.name)
}
function stop(){advance?.();advance=null;waitingNext.value=false;for(const [timer,finish] of timers){clearTimeout(timer);finish()}timers.clear()}
async function reveal(t){
 stop();complete.value=false;const allRows=resultRows(t);rows.value=[];locked.value=[]
 const targets=allRows.flatMap(row=>row.names),pool=poolNames()
 names.value=targets.map(()=> '待揭晓')
 const reduced=window.matchMedia('(prefers-reduced-motion: reduce)').matches
 let offset=0
 for(const row of allRows){
 rows.value.push(row)
 await Promise.all(row.names.map((target,localIndex)=>new Promise(resolve=>{
  const index=offset+localIndex
  const fixed=props.kind==='playin'&&index===0
  const duration=reduced||fixed?0:1800+index*125+Math.random()*450
  const start=performance.now(),interval=85+Math.random()*75
  function tick(){
   if(performance.now()-start>=duration){names.value[index]=target;locked.value.push(index);resolve();return}
   const candidates=pool.filter(name=>name!==target)
   names.value[index]=candidates[Math.floor(Math.random()*candidates.length)]||'待揭晓'
   const timer=setTimeout(()=>{timers.delete(timer);tick()},interval*(1+(performance.now()-start)/duration))
   timers.set(timer,resolve)
  }tick()
 })))
 if(disposed)return
 offset+=row.names.length
 if(offset<targets.length){waitingNext.value=true;await new Promise(resolve=>{advance=resolve})}
 if(disposed)return
 }
 complete.value=true
}
function slotIndex(row,index){return rows.value.slice(0,row).reduce((sum,x)=>sum+x.names.length,0)+index}
onUnmounted(()=>{disposed=true;stop()})
defineExpose({reveal})
</script>
<template>
 <section class="pairing-stage" :aria-busy="busy">
  <header><span>主持人抽签</span><span>{{waitingNext?'':busy?'正在揭晓':complete?'已保存':''}}</span></header>
  <div class="pairing-title"><h2>{{kind==='opening'?'首轮抽签':title}}</h2></div>
  <div v-if="!busy&&!complete" class="pairing-wait"><strong>{{kind==='opening'?'19支战队':kind==='second'?'10支战队':kind==='semi'?'四强集结':'突围对决'}}</strong><button class="start-lottery" @click="emit('start')">开始</button></div>
  <div v-else class="pairing-results" :class="{many:kind==='opening',sequential:busy}" aria-live="polite">
   <article v-for="(row,r) in rows" v-show="complete||r===rows.length-1" :key="row.id" :class="{bye:row.id==='bye'}"><small>{{row.label}}</small><div><template v-for="(_,i) in row.names" :key="i"><span v-if="i" class="pairing-vs">VS</span><b :class="{rolling:busy&&!locked.includes(slotIndex(r,i)),locked:locked.includes(slotIndex(r,i))}">{{names[slotIndex(r,i)]||'待揭晓'}}</b></template></div></article>
  </div>
  <footer v-if="waitingNext"><button class="start-lottery" @click="nextGroup">下一组</button></footer>
  <footer v-if="!busy"><button v-if="complete" class="start-lottery" @click="emit('back')">查看晋级图</button><button class="quiet-lottery" @click="emit('back')">{{complete?'返回赛事':'取消'}}</button></footer>
 </section>
</template>
<style scoped>
.pairing-stage{border:1px solid #36546c;border-radius:12px;padding:24px 28px;background:radial-gradient(ellipse at 80% 100%,#17354a66,transparent 65%),#0c1b29;color:#e1eff9;min-height:480px}.pairing-stage>header{display:flex;justify-content:space-between;padding-bottom:16px;border-bottom:1px solid #ffffff0c;color:#87a3b9;font-size:11px}.pairing-title{text-align:center;padding:28px 0 24px}.pairing-title small{letter-spacing:6px;color:#c6af7c;font-size:10px}.pairing-title h2{margin:15px 0 10px;font-size:28px;letter-spacing:2px}.pairing-title p{color:#8da9be;font-size:12px}.pairing-wait{display:flex;flex-direction:column;align-items:center;gap:30px;padding:30px 0 50px}.pairing-wait strong{font-size:38px;color:#a4d7f6;letter-spacing:5px}.start-lottery,.quiet-lottery{border-radius:5px;padding:11px 26px;font:inherit;font-size:13px;cursor:pointer}.start-lottery{background:#508bb8;border:1px solid #80b8dc;color:white}.quiet-lottery{background:#142c40;border:1px solid #35566f;color:#a7c3d8}.pairing-results{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;max-width:760px;margin:0 auto 24px}.pairing-results:not(.many)>article:only-child{grid-column:1/-1;max-width:480px;width:100%;justify-self:center;box-sizing:border-box}.pairing-results article{border:1px solid #3c5d77;border-radius:7px;padding:13px 18px;background:#122b40}.pairing-results article>small{display:block;font-size:11px;color:#8aaac2;margin-bottom:12px}.pairing-results article>div{display:flex;align-items:center;justify-content:space-between;gap:12px;min-height:34px}.pairing-results b{font-size:22px;min-width:0;overflow-wrap:anywhere;line-height:1.4}.pairing-vs{font-size:11px;letter-spacing:2px;color:#8babc3}.pairing-results .bye>div{justify-content:center}.rolling{color:#90b9d6;filter:blur(.35px)}.locked{color:#d7edfc}.pairing-stage footer{display:flex;justify-content:center;gap:12px;padding-top:12px}@media(max-width:650px){.pairing-stage{padding:18px 14px}.pairing-title h2{font-size:23px}.pairing-results{grid-template-columns:1fr}.pairing-results.many{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.pairing-results article{padding:11px}.pairing-results b{font-size:17px}.pairing-vs{font-size:9px}.pairing-title p{line-height:1.7}}
</style>

<style scoped>
.pairing-results:not(:has(article:nth-child(1):last-child)){max-width:900px}.pairing-results article{min-height:150px;padding:30px;box-sizing:border-box}.pairing-results article>div{min-height:85px;justify-content:center;gap:50px}.pairing-results b{font-size:46px}.pairing-results article>small{text-align:center;font-size:16px}.pairing-results.many:has(.rolling),.pairing-results.many:has(~footer .start-lottery){display:block}.pairing-vs{font-size:24px}.pairing-results.sequential{display:block;max-width:900px}.pairing-results.sequential>article:only-child{max-width:none}@media(max-width:650px){.pairing-results b{font-size:30px}.pairing-results article>div{gap:22px}.pairing-results article{padding:24px 14px}}
</style>
