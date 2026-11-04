<script setup>
import { computed } from 'vue'
import { reportAmount } from '../../utils/monthlyReportFormat'
const props = defineProps({ rows: Array })
const colors = ['#365f25', '#ff9948', '#50536f', '#8da77b', '#c4c9cf']
const data = computed(() => {
  const rows = props.rows || []
  const valid = rows.length && rows.every(row => Number.isFinite(Number(row.paid_amount)) && Number(row.paid_amount) >= 0)
  const total = rows.reduce((sum, row) => sum + Number(row.paid_amount), 0)
  let angle = -Math.PI / 2
  return valid && total > 0 ? rows.map((row, index) => {
    const share = Number(row.paid_amount) / total
    const end = angle + share * 2 * Math.PI
    const startX = 150 + 112 * Math.cos(angle), startY = 145 + 112 * Math.sin(angle)
    const endX = 150 + 112 * Math.cos(end), endY = 145 + 112 * Math.sin(end)
    const path = `M150,145 L${startX},${startY} A112,112 0 ${share > .5 ? 1 : 0},1 ${endX},${endY} Z`
    angle = end
    return { ...row, share, path, color: colors[index % colors.length] }
  }) : []
})
</script>
<template>
  <figure class="brand-share">
    <div v-if="data.length" class="share-layout">
      <svg viewBox="0 0 300 290" role="img" aria-label="前五品牌销售额构成，比例以这五个品牌合计为分母">
        <template v-for="row in data" :key="row.brand">
          <circle v-if="row.share === 1" cx="150" cy="145" r="112" :fill="row.color" />
          <path v-else :d="row.path" :fill="row.color" stroke="white" stroke-width="2"><title>{{ row.brand }}：{{ (row.share * 100).toFixed(1) }}%</title></path>
        </template>
      </svg>
      <div class="share-legend"><div v-for="row in data" :key="row.brand"><i :style="{background:row.color}" /><strong>{{ row.brand }}</strong><span>{{ reportAmount(row.paid_amount) }} 万元</span><b>{{ (row.share * 100).toFixed(1) }}%</b></div></div>
    </div>
    <p v-else>暂无可展示的品牌销售额构成</p>
    <figcaption>图5-1　前五品牌销售额构成（五品牌内部占比）</figcaption>
  </figure>
</template>
<style scoped>
.brand-share { margin:0; break-inside:avoid; } .share-layout { display:grid; grid-template-columns:minmax(180px,1fr) minmax(210px,1fr); gap:20px; align-items:center; }
svg { width:100%; max-width:330px; margin:auto; display:block; }
.share-legend > div { display:grid; grid-template-columns:12px 1fr auto; align-items:center; gap:8px; padding:10px 0; border-bottom:1px solid var(--border); font-size:15px; }
.share-legend i { width:10px; height:10px; border-radius:2px; } .share-legend span { grid-column:2; color:var(--muted); } .share-legend b { grid-row:1 / span 2; grid-column:3; }
figcaption { text-align:center; font-size:16px; font-weight:600; margin:18px 0 0; }
@media(max-width:600px) { .share-layout { grid-template-columns:1fr; } }
:global(.is-exporting) .share-layout { grid-template-columns:1fr 1fr; }
</style>
