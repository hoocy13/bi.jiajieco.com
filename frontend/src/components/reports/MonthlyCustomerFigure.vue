<script setup>
import { computed } from 'vue'
const props = defineProps({ customer: Object })
const valid = n => n != null && Number.isFinite(Number(n))
const charts = computed(() => [
  { title: '客户识别销售额覆盖率', rate: props.customer?.identified_amount_rate, detail: '分母：本月销售额', label: '已识别销售额' },
  { title: '月内复购率', showCount: true, rate: props.customer?.repeat_rate, detail: `复购 ${count(props.customer?.repeat_customers)} / 可识别客户 ${count(props.customer?.customers)}`, label: '月内复购客户' },
])
function count(n) { return valid(n) ? Number(n).toLocaleString('zh-CN', { maximumFractionDigits: 0 }) : '—' }
const percent = n => valid(n) && n >= 0 && n <= 1 ? `${(n * 100).toFixed(1)}%` : '—'
const length = n => valid(n) && n >= 0 && n <= 1 ? n * 100 : 0
</script>
<template>
  <figure class="customer-figure">
    <div class="customer-charts">
      <div v-for="chart in charts" :key="chart.title" class="customer-chart">
        <h3>{{ chart.title }}</h3>
        <svg viewBox="0 0 300 190" role="img" :aria-label="`${chart.title} ${percent(chart.rate)}；${chart.detail}`">
          <circle cx="150" cy="105" r="72" class="ring-track" />
          <circle cx="150" cy="105" r="72" class="ring-value" pathLength="100" :stroke-dasharray="`${length(chart.rate)} 100`" transform="rotate(-90 150 105)" />
          <text x="150" y="115" text-anchor="middle" class="rate">{{ percent(chart.rate) }}</text>
        </svg>
        <p v-if="chart.showCount" class="customer-count">复购 {{ count(customer?.repeat_customers) }} 人 / 可识别客户 {{ count(customer?.customers) }} 人</p>
      </div>
    </div>
    <figcaption>图6-1　客户识别覆盖与月内复购</figcaption>
  </figure>
</template>
<style scoped>
.customer-figure { margin:28px 0 0; break-inside:avoid; }
.customer-charts { display:grid; grid-template-columns:1fr 1fr; gap:24px; }
h3 { text-align:center; font-size:17px; margin:0 0 12px; }
svg { display:block; width:100%; max-width:360px; margin:auto; }
circle { fill:none; stroke-width:17px; }
.ring-track { stroke:#e8ece5; } .ring-value { stroke:var(--accent-strong,#365f25); }
text { fill:var(--text,#28323c); font-family:system-ui,sans-serif; }
.rate { font-size:30px; font-weight:700; } .ring-label { font-size:15px; } .detail { font-size:15px; }
.customer-count { text-align:center; font-size:15px; margin:8px 0 0; color:var(--text,#28323c); }
figcaption { text-align:center; font-size:16px; font-weight:600; margin-top:20px; }
@media(max-width:560px) { .customer-charts { grid-template-columns:1fr; } }
:global(.is-exporting) .customer-charts { grid-template-columns:1fr 1fr; }
</style>
