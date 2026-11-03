<script setup>
import { computed } from 'vue'
import { buildSupplyActions } from '../../utils/monthlyReportActions'
const props = defineProps({ data: Object })
const review = computed(() => buildSupplyActions(props.data))
const number = (value, digits = 0) => value == null || !Number.isFinite(Number(value)) ? '—' : Number(value).toLocaleString('zh-CN', { maximumFractionDigits: digits })
const days = value => Number(value) > 0 && Number(value) < 0.1 ? '<0.1' : number(value, 1)
</script>
<template>
  <div class="supply-actions">
    <div v-if="review.inventory.available" class="check-cards">
      <div><span>供货核查货品</span><strong>{{ number(review.inventory.low_count) }}</strong></div>
      <div><span>库存消化核查货品</span><strong>{{ number(review.inventory.high_count) }}</strong></div>
      <div><span>销售货品未匹配库存</span><strong>{{ number(review.inventory.unmatched_sales_skus) }}</strong></div>
    </div>
    <section v-for="group in [{key:'low',title:'供货核查',action:'核对可用库存、在途及交期'},{key:'high',title:'库存消化',action:'核对效期、预留及采购计划'}]" :key="group.key">
      <header><h3>{{ group.title }}</h3><span>{{ group.action }}</span></header>
      <div class="supply-scroll"><table><thead><tr><th>货品 / 货号</th><th>月末总库存</th><th>本月净销量</th><th>覆盖天数</th></tr></thead>
        <tbody><tr v-for="row in review[group.key]" :key="row.product_code"><td>{{ row.product }}<div class="code">{{ row.product_code }}</div></td><td>{{ number(row.stock) }}</td><td>{{ number(row.quantity) }}</td><td>{{ days(row.days) }}</td></tr>
          <tr v-if="!review[group.key].length"><td colspan="4">暂无可核实货品</td></tr></tbody>
      </table></div>
    </section>
    <p class="basis">{{ review.inventory.snapshot_date || '月末' }} · 总库存 ÷ 本月日均净销量；核查线索，非采购指令</p>
  </div>
</template>
<style scoped>
.check-cards { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:16px; }
.check-cards > div { border-top:3px solid var(--accent-strong); background:var(--surface-soft); padding:16px; }
.check-cards span { display:block; font-size:15px; color:var(--muted); }
.check-cards strong { display:block; margin-top:12px; font-size:26px; }
section { margin: 28px 0; break-inside: avoid; }
header { display:flex; justify-content:space-between; gap:16px; align-items:baseline; margin-bottom:16px; flex-wrap:wrap; }
h3 { margin:0; font-size:18px; } header span,.basis,.code { color:var(--muted); font-size:15px; }
.code { margin-top:5px; } .basis { margin:24px 0; line-height:1.6; }
table { width:100%; border-collapse:collapse; font-size:15px; font-variant-numeric:tabular-nums; }
th,td { text-align:right; padding:12px 8px; border-bottom:1px solid var(--border); vertical-align:top; }
th { color:var(--muted); font-weight:500; } th:first-child,td:first-child { text-align:left; width:44%; overflow-wrap:anywhere; }
td:not(:first-child) { white-space:nowrap; } .supply-scroll { overflow-x:auto; }
.up { color:var(--accent-strong); } .down { color:#b42318; }
@media(max-width:640px) { .supply-scroll table { min-width:570px; } }
:global(.is-exporting) .supply-scroll table { min-width:0; }
</style>
