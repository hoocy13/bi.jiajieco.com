<script setup>
import { computed } from 'vue'
import { reportAmount } from '../../utils/monthlyReportFormat'
const props=defineProps({trend:Object,rows:Array,type:String,caption:String,note:String})
const colors=['#00a9e8','#ff8b35','#55597e']
const trendScale=computed(()=>{
 const values=(props.trend?.series||[]).flatMap(s=>s.values.map(v=>v/10000))
 const min=Math.min(0,...values),max=Math.max(1,...values),step=10**Math.floor(Math.log10((max-min)/4))
 const tick=Math.ceil((max-min)/4/step)*step
 const low=Math.floor(min/tick)*tick,high=Math.ceil(max/tick)*tick
 return {min:low,max:high,ticks:Array.from({length:Math.round((high-low)/tick)+1},(_,i)=>low+i*tick)}
})
const y=v=>260-(v-trendScale.value.min)/(trendScale.value.max-trendScale.value.min)*220
const x=i=>100+i*285
const stockMax=computed(()=>Math.max(1,...(props.rows||[]).flatMap(r=>[r.stock,r.quantity])))
const format=n=>Number(n).toLocaleString('zh-CN',{maximumFractionDigits:0})
</script>
<template>
 <figure class="paper-figure">
  <svg v-if="type==='trend' && trend?.series?.length" viewBox="0 0 820 350" role="img" :aria-label="caption">
   <text x="30" y="20">销售额（万元）</text>
   <g v-for="tick in trendScale.ticks" :key="tick"><line x1="100" :y1="y(tick)" x2="670" :y2="y(tick)" class="grid"/><text x="86" :y="y(tick)+5" text-anchor="end">{{ format(tick) }}</text></g>
   <line x1="100" y1="40" x2="100" y2="260" class="axis"/><line x1="100" y1="260" x2="670" y2="260" class="axis"/>
   <text v-for="(month,i) in trend.months" :key="month" :x="x(i)" y="286" text-anchor="middle">{{ month }}</text>
   <g v-for="(series,index) in trend.series" :key="series.name"><polyline :points="series.values.map((v,i)=>`${x(i)},${y(v/10000)}`).join(' ')" fill="none" :stroke="colors[index%3]" stroke-width="2"/>
    <g v-for="(v,i) in series.values" :key="i"><circle :cx="x(i)" :cy="y(v/10000)" r="4" fill="white" :stroke="colors[index%3]" stroke-width="2"/><title>{{ series.name }} · {{ trend.months[i] }}：{{ reportAmount(v) }}万元</title></g>
    <line :x1="60+index*255" y1="326" :x2="85+index*255" y2="326" :stroke="colors[index%3]" stroke-width="3"/><text :x="93+index*255" y="331">{{ series.name }}</text>
   </g>
  </svg>
  <svg v-else-if="type==='stock'" viewBox="0 0 820 350" role="img" :aria-label="caption">
   <text x="150" y="20">数量（件）</text>
   <g v-for="i in [0,1,2,3,4]" :key="i"><line :x1="150+i*145" y1="40" :x2="150+i*145" y2="290" class="grid"/><text :x="150+i*145" y="311" text-anchor="middle">{{ format(stockMax*i/4) }}</text></g>
   <g v-for="(row,i) in rows" :key="row.product_code"><text x="136" :y="65+i*48" text-anchor="end">{{ row.product_code }}</text><rect x="150" :y="48+i*48" :width="row.quantity/stockMax*580" height="12" fill="#244f75"/><rect x="150" :y="63+i*48" :width="row.stock/stockMax*580" height="12" fill="#c3ced7" stroke="#526777" stroke-width=".5"/></g>
   <rect x="245" y="334" width="24" height="10" fill="#244f75"/><text x="277" y="345">本月净销量</text><rect x="450" y="334" width="24" height="10" fill="#c3ced7" stroke="#526777"/><text x="482" y="345">月末总库存</text>
  </svg>
  <figcaption>{{ caption }}</figcaption>
  <p v-if="note" class="figure-note">{{ note }}</p>
 </figure>
</template>
<style scoped>
.paper-figure { margin: 24px 0 28px; padding: 18px 0; border-top: 1px solid var(--border); break-inside: avoid; }
svg { display: block; width: 100%; height: auto; background: #fff; color: #17202a; }
svg text { fill: #17202a; font: 16px system-ui, sans-serif; }
.grid { stroke: #dce1e6; stroke-width: 1; } .axis { stroke: #52606d; stroke-width: 1.2; }
figcaption { text-align: center; font-size: 16px; font-weight: 600; margin-top: 16px; line-height: 1.7; }
.figure-note { font-size: 15px; line-height: 1.7; margin: 10px 0 0; color: var(--muted); }
</style>
