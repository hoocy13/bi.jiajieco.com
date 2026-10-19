<script setup>
import { computed } from 'vue'
import { reportAmount } from '../../utils/monthlyReportFormat'
const props=defineProps({ flows:Object, segment: { type:String, default:'combined' }, figureNumber: { type:String, default:'7-1' } })
const segmentLabel=computed(()=>({combined:'正装＋小样',full_size:'正装',sample:'小样'}[props.segment]))
const rows=computed(()=>(props.flows?.brands||[]).map(flow=>({brand:flow.brand,...(props.segment==='combined'?flow.months:flow.segments?.[props.segment]?.months)?.at(-1)})))
const scale=computed(()=>{
 const comparable=(props.flows?.brands||[]).flatMap(flow=>[flow.months.at(-1),flow.segments?.full_size?.months?.at(-1),flow.segments?.sample?.months?.at(-1)]).filter(Boolean)
 const values=comparable.flatMap(r=>[r.inbound_quantity/10000,r.ending_quantity/10000,-r.sales_quantity/10000])
 const min=Math.min(0,...values),max=Math.max(.01,...values),base=10**Math.floor(Math.log10((max-min)/6))
 const step=Math.ceil((max-min)/6/base)*base,low=Math.floor(min/step)*step,high=Math.ceil(max/step)*step
 return {low,high,ticks:Array.from({length:Math.round((high-low)/step)+1},(_,i)=>low+i*step)}
})
const x=n=>150+(n/10000-scale.value.low)/(scale.value.high-scale.value.low)*500
const number=n=>Number(n).toLocaleString('zh-CN',{maximumFractionDigits:2})
const series=[{field:'inbound_quantity',label:'净采购入库',color:'#506fe0',direction:1,offset:0},{field:'sales_quantity',label:'净销售（左向）',color:'#555779',direction:-1,offset:23},{field:'ending_quantity',label:'月末总库存',color:'#b0d72b',direction:1,offset:23}]
const directed=(row,s)=>row[s.field]*s.direction
</script>
<template>
 <figure class="brand-flow-figure">
  <svg viewBox="0 0 820 500" role="img" :aria-label="`${segmentLabel}进销存对比；销售左向，采购与库存右向，共用数量刻度`">
   <text x="150" y="25">数量（万件）</text>
   <g v-for="tick in scale.ticks" :key="tick"><line :x1="x(tick*10000)" y1="45" :x2="x(tick*10000)" y2="415" class="grid"/><text :x="x(tick*10000)" y="442" text-anchor="middle">{{ number(Math.abs(tick)) }}</text></g>
   <line :x1="x(0)" y1="45" :x2="x(0)" y2="415" class="axis"/>
   <g v-for="(row,i) in rows" :key="row.brand">
    <text x="125" :y="83+i*70" text-anchor="end" class="brand-label">{{ row.brand }}</text>
    <g v-for="(s,j) in series" :key="s.field">
     <rect :x="Math.min(x(directed(row,s)),x(0))" :y="60+i*70+s.offset" :width="Math.abs(x(directed(row,s))-x(0))" height="16" :fill="s.color"/>
     <text :x="directed(row,s)<0 ? x(directed(row,s))-8 : x(directed(row,s))+8" :y="73+i*70+s.offset" :text-anchor="directed(row,s)<0?'end':'start'" class="bar-value">{{ reportAmount(row[s.field]) }}</text>
     <title>{{ row.brand }} · {{ s.label }}：{{ number(row[s.field]) }}件</title>
    </g>
   </g>
   <g v-for="(s,j) in series" :key="s.field"><rect :x="75+j*255" y="472" width="22" height="14" :fill="s.color"/><text :x="107+j*255" y="485">{{ s.label }}</text></g>
  </svg>
  <figcaption>图{{ figureNumber }}　{{ flows.end_date.slice(0,7) }}前五品牌进销存（{{ segmentLabel }}）</figcaption>
 </figure>
</template>
<style scoped>
.brand-flow-figure { margin: 20px 0 32px; break-inside: avoid; }
svg { display: block; width: 100%; height: auto; background: white; }
svg text { font: 17px system-ui, sans-serif; fill: #28323c; }
.brand-label, .bar-value { font-weight: 600; }
.grid { stroke: #dce1e6; stroke-width: 1; } .axis { stroke: #68747e; stroke-width: 1; }
figcaption { text-align: center; font-size: 16px; font-weight: 600; line-height: 1.7; margin-top: 16px; }
</style>
