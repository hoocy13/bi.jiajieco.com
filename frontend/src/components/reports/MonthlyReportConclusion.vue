<script setup>
import { computed } from 'vue'
import { buildMonthlyComparison } from '../../utils/monthlyReportComparison'
import { salesContributors } from '../../utils/monthlyReportInsights'
const props = defineProps({ artifact: Object, month: String })
const data = computed(() => props.artifact?.snapshot?.datasets || {})
const current = computed(() => buildMonthlyComparison(data.value.periods || [], [], props.month).current)
const drivers = computed(() => salesContributors(data.value.channel_sales || []))
const assessment = computed(() => {
  if (current.value?.paid_amount_mom == null) return '本月销售规模已呈现，但缺少可比较的上月基期，暂不判断增长趋势。'
  const direction = current.value.paid_amount_mom > 0 ? '回升' : current.value.paid_amount_mom < 0 ? '回落' : '持平'
  return `本月销售较上月${direction}。${current.value.orders_mom > 0 && current.value.avg_order_amount_mom < 0 ? '订单增长与平均订单金额下降并存，下一步应关注增长质量。' : '渠道之间的表现存在差异，下一步应分别跟进主要增长和下降渠道。'}`
})
</script>
<template>
  <article class="report-paper report-conclusion">
    <h2>九、总结</h2>
    <p>{{ assessment }}</p>
    <h3>主管推测与建议（供讨论）</h3>
    <p>从现有数据推测，渠道和订单结构变化可能影响本月经营表现，尚需结合活动、退货及同款商品成交价核实。建议优先复盘{{ drivers.growth[0]?.channel ? ` ${drivers.growth[0].channel} 等增长渠道` : '主要销售渠道' }}的增长能否持续，并向{{ drivers.decline[0]?.channel ? ` ${drivers.decline[0].channel} 等下降渠道` : '销售下降渠道' }}确认订单变化原因。先区分一次性大单、促销和持续需求，再决定下月资源投入；同步补齐核心成本，核准毛利后再调整采购与备货。</p>
    <p v-for="note in data.report_quality_notes || []" :key="note.scope" class="quality-note">{{ note.text }}</p>
  </article>
</template>
<style scoped>
.report-conclusion { box-sizing: border-box; width: min(960px, 100%); margin: auto; padding: 36px; background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 10px; }
h2 { font-size: 22px; margin: 0 0 20px; } h3 { font-size: 18px; margin: 28px 0 12px; }
p { font-size: 16px; line-height: 1.85; margin: 0; max-width: 76ch; }
.quality-note { margin-top: 20px; color: var(--muted); font-size: 14px; }
.is-exporting { width: 794px; min-width: 794px; max-width: none; padding: 28px; border: 0; background: #fff; color: #17202a; }
.is-exporting p { font-size: 15px; }
@media (max-width: 640px) { .report-conclusion { padding: 20px; } }
@media print { .report-conclusion { break-before: page; border: 0; width: 100%; padding: 0; } }
</style>
