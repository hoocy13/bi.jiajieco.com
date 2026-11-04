<script setup>
import { computed } from 'vue'
import { buildMonthlyComparison, periodMonth, previousMonth, monthOverMonth } from '../../utils/monthlyReportComparison'
const props = defineProps({ data: Object, month: String })
const valid = value => value != null && value !== '' && Number.isFinite(Number(value))
const number = (value, digits = 0) => valid(value) ? Number(value).toLocaleString('zh-CN', { maximumFractionDigits: digits }) : '—'
const wan = value => valid(value) ? number(Number(value) / 10000) : '—'
const change = value => !valid(value) ? '暂无可比数据' : Number(value) === 0 ? '持平' : `${Number(value) > 0 ? '增长' : '下降'} ${number(Math.abs(Number(value)) * 100, 1)}%`
const sections = computed(() => {
  const d = props.data || {}
  const h = d.headline?.[0] || {}
  const comparison = buildMonthlyComparison(d.periods || [], [], props.month)
  const current = comparison.current || h
  const prev = previousMonth(props.month)
  const types = (d.product_types || []).filter(r => periodMonth(r.period) === props.month)
  const typeText = types.map(r => {
    const old = (d.product_types || []).find(p => periodMonth(p.period) === prev && p.product_type === r.product_type)
    const delta = valid(old?.paid_amount) && valid(r.paid_amount) ? Number(r.paid_amount) - Number(old.paid_amount) : null
    return `${r.product_type}销售额 ${wan(r.paid_amount)} 万元${delta == null ? '' : `，较上月${delta >= 0 ? '增加' : '减少'} ${wan(Math.abs(delta))} 万元`}`
  }).join('；')
  const channels = (d.channel_sales || []).filter(r => valid(r.paid_amount_change))
  const up = channels.filter(r => Number(r.paid_amount_change) > 0).sort((a,b) => b.paid_amount_change-a.paid_amount_change).slice(0,2)
  const down = channels.filter(r => Number(r.paid_amount_change) < 0).sort((a,b) => a.paid_amount_change-b.paid_amount_change).slice(0,2)
  const channelText = [...up,...down].map(r => `${r.channel}${r.paid_amount_change >= 0 ? '增加' : '减少'} ${wan(Math.abs(r.paid_amount_change))} 万元`).join('，')
  const brand = [...(d.brands || [])].filter(r => valid(r.paid_amount)).sort((a,b) => b.paid_amount-a.paid_amount)[0]
  const brandText = brand && Number(h.paid_amount) > 0 ? `${brand.brand}销售额 ${wan(brand.paid_amount)} 万元，占整体销售额 ${number(brand.paid_amount / h.paid_amount * 100, 1)}%。应持续关注主要品牌的渠道订单和供货稳定性。` : ''
  const stock = (d.inventory_snapshots || []).find(r => periodMonth(r.period) === props.month)
  const oldStock = (d.inventory_snapshots || []).find(r => periodMonth(r.period) === prev)
  const stockDelta = valid(stock?.stock_quantity) && valid(oldStock?.stock_quantity) ? stock.stock_quantity-oldStock.stock_quantity : null
  return [
    { title: '经营结果', text: `本月销售额 ${wan(h.paid_amount)} 万元，环比${change(current.paid_amount_mom)}，同比${change(h.paid_amount_yoy)}。盈利是否同步改善，仍需结合成本覆盖完整的毛利数据判断。` },
    { title: '增长来源', text: `${typeText || '暂无分类销售数据。'}${typeText ? '。' : ''}${channelText ? `渠道方面，${channelText}。` : ''}` },
    { title: '增长质量', text: `销售数量环比${change(current.quantity_mom)}，订单数环比${change(current.orders_mom)}，平均订单金额 ${number(h.avg_order_amount)} 元，环比${change(current.avg_order_amount_mom)}。${brandText}` },
    { title: '库存与供货', text: `${valid(stock?.stock_quantity) ? `月末总库存 ${wan(stock.stock_quantity)} 万件${stockDelta == null ? '' : `，较上月${stockDelta >= 0 ? '增加' : '减少'} ${wan(Math.abs(stockDelta))} 万件，环比${change(monthOverMonth(stock.stock_quantity, oldStock.stock_quantity))}`}。` : '暂无月末库存快照。'}总量不能代表单品供货情况，应结合第九节明细，核对可用库存、在途和效期，分别安排补货与库存消化。` },
    { title: '下月重点', actions: [up.length ? `跟进${up.map(r=>r.channel).join('、')}的后续订单与供货安排，确认本月增量能否延续。` : '跟进主要渠道的后续订单与供货安排。', down.length ? `核查${down.map(r=>r.channel).join('、')}的销售回落，区分订单节奏、供货和需求变化，再决定销售动作。` : '跟踪渠道及货品的销售变化，再决定销售动作。', '优先核对畅销低库存货品的补货需求；对高库存、低销量货品，先核查效期和预留，再安排促销、调拨或采购调整。'] },
  ]
})
</script>
<template>
  <section class="operating-conclusion">
    <h2>十、经营总结</h2>
    <section v-for="(section,index) in sections" :key="section.title" class="conclusion-dimension">
      <h3>{{ index + 1 }}. {{ section.title }}</h3>
      <p v-if="section.text">{{ section.text }}</p>
      <ul v-else><li v-for="action in section.actions" :key="action">{{ action }}</li></ul>
    </section>
  </section>
</template>
<style scoped>
.operating-conclusion { margin-top:48px; padding-top:32px; border-top:1px solid var(--border); }
h2 { margin:0 0 28px; font-size:22px; color:var(--text); }
.conclusion-dimension { margin:0 0 24px; break-inside:avoid; }
h3 { margin:0 0 10px; font-size:17px; color:var(--text); font-weight:700; }
p,ul { margin:0; color:#6b7280; font-size:15px; line-height:1.9; }
ul { padding-left:20px; } li + li { margin-top:8px; }
</style>
