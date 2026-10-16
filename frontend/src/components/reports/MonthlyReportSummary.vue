<script setup>
import { computed } from 'vue'
import { salesContributors } from '../../utils/monthlyReportInsights'
import { buildMonthlyComparison, periodMonth } from '../../utils/monthlyReportComparison'
import { summarizeReportChannels } from '../../utils/monthlyReportChannels'

const props = defineProps({ artifact: Object, month: String })
const data = computed(() => props.artifact?.snapshot?.datasets || {})
const comparison = computed(() => buildMonthlyComparison(data.value.periods || [], data.value.channel_structure || [], props.month))
const headline = computed(() => data.value.headline?.[0] || {})
const directions = computed(() => summarizeReportChannels(data.value.channel_sales || [], Number(headline.value.paid_amount || 0)))
const contributors = computed(() => salesContributors(data.value.channel_sales || []))
const metrics = [
  { label: '销售额（万元）', field: 'paid_amount', wan: true },
  { label: '订单数', field: 'orders' }, { label: '销售数量', field: 'quantity' },
  { label: '平均订单金额（元）', field: 'avg_order_amount', money: true },
]
const currentProducts = computed(() => (data.value.product_types || []).filter(row => periodMonth(row.period) === props.month))
const productTotal = computed(() => currentProducts.value.reduce((sum, row) => sum + Number(row.paid_amount), 0))
const customer = computed(() => (data.value.customers || []).find(row => periodMonth(row.period) === props.month) || {})
const arrival = computed(() => (data.value.arrivals || []).find(row => periodMonth(row.period) === props.month) || {})
const inventory = computed(() => (data.value.inventory_snapshots || []).find(row => periodMonth(row.period) === props.month) || {})
function number(value, digits = 0) {
  if (value === undefined || value === null) return '—'
  return Number(value).toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}
function wan(value) { return value == null ? '—' : number(Number(value) / 10000, 2) }
function money(value, divisor = 10000) { return value == null ? '—' : number(Number(value) / divisor, 2) }
function comparisonValue(value) { return String(value).replaceAll('—', '-') }
const salesBars = computed(() => {
  const rows = comparison.value.periods
  const max = Math.max(1, ...rows.map(row => Math.abs(Number(row.paid_amount || 0))))
  return rows.map((row, index) => ({ ...row, x: 70 + index * 110, height: Math.abs(Number(row.paid_amount || 0)) / max * 72 }))
})
function percent(value, signed = false) {
  if (value == null || !Number.isFinite(Number(value))) return '—'
  return `${signed && Number(value) > 0 ? '+' : ''}${number(Number(value) * 100, 1)}%`
}
function tone(value) { return value == null ? '' : Number(value) < 0 ? 'down' : Number(value) > 0 ? 'up' : '' }
</script>

<template>
  <article class="report-paper monthly-summary">
    <header class="summary-cover"><h1>{{ artifact?.manifest?.title }}</h1></header>
    <section class="report-intro"><h2>一、销售总体情况</h2>
    <section class="summary-metrics">
      <article v-for="metric in metrics" :key="metric.field" class="summary-metric">
        <span>{{ metric.label }}</span>
        <strong>{{ metric.wan ? money(headline[metric.field]) : metric.money ? money(headline[metric.field], 1) : number(headline[metric.field]) }}</strong>
        <div>环比 <b :class="tone(comparison.current?.[`${metric.field}_mom`])">{{ percent(comparison.current?.[`${metric.field}_mom`], true) }}</b></div>
        <small>同比 {{ percent(headline[`${metric.field}_yoy`], true) }}</small>
      </article>
    </section>
    </section>
    <section class="summary-panel month-comparison">
      <h2>二、月度销售对比</h2>
      <div class="month-table-scroll"><table><thead><tr><th>月份</th><th>销售额（万元）</th><th>环比</th><th>订单数</th><th>环比</th><th>销售数量</th><th>环比</th></tr></thead><tbody>
        <tr v-for="row in comparison.periods" :key="row.period"><td>{{ periodMonth(row.period) }}</td><td>{{ comparisonValue(money(row.paid_amount)) }}</td><td :class="tone(row.paid_amount_mom)">{{ comparisonValue(percent(row.paid_amount_mom, true)) }}</td><td>{{ comparisonValue(number(row.orders)) }}</td><td :class="tone(row.orders_mom)">{{ comparisonValue(percent(row.orders_mom, true)) }}</td><td>{{ comparisonValue(number(row.quantity)) }}</td><td :class="tone(row.quantity_mom)">{{ comparisonValue(percent(row.quantity_mom, true)) }}</td></tr>
      </tbody></table></div>
      <svg class="monthly-sales-bars" viewBox="0 0 360 136" role="img" aria-label="月度销售额柱状对比，单位万元">
        <line x1="22" y1="106" x2="338" y2="106" class="chart-baseline" />
        <g v-for="row in salesBars" :key="row.period">
          <title>{{ periodMonth(row.period) }}：{{ money(row.paid_amount) }} 万元</title>
          <rect :x="row.x - 32" :y="106 - row.height" width="64" :height="row.height" rx="3" class="sales-bar" :class="{ 'is-current': periodMonth(row.period) === month }" />
          <text :x="row.x" :y="98 - row.height" text-anchor="middle" class="bar-value">{{ money(row.paid_amount) }}</text>
          <text :x="row.x" y="129" text-anchor="middle" class="bar-month">{{ periodMonth(row.period) }}</text>
        </g>
      </svg>
    </section>
    <section class="summary-panel channel-overview">
      <h2>三、渠道经营</h2>
      <table><thead><tr><th>分类</th><th>销售额</th><th>占比</th><th>环比</th></tr></thead><tbody>
        <tr v-for="group in directions" :key="group.name"><td>{{ group.name }}</td><td>{{ group.available ? money(group.paid_amount) : '—' }}</td><td>{{ group.available ? percent(group.share) : '—' }}</td><td :class="tone(group.mom)">{{ group.available ? percent(group.mom, true) : '—' }}</td></tr>
      </tbody></table>
      <div class="channel-columns">
        <section v-for="group in directions" :key="group.name" class="channel-group">
          <h3>{{ group.name }}</h3>
          <table><thead><tr><th>{{ group.name === '线上平台' ? '平台' : '渠道' }}</th><th>万元</th><th>环比</th></tr></thead><tbody>
            <tr v-for="row in group.rows" :key="row.name"><td>{{ row.name }}</td><td>{{ money(row.paid_amount) }}</td><td :class="tone(row.mom)">{{ percent(row.mom, true) }}</td></tr>
            <tr v-if="!group.available"><td colspan="3">暂无渠道明细</td></tr>
          </tbody></table>
        </section>
      </div>
    </section>
    <section class="summary-panel contribution-panel">
      <h2>四、销售变化贡献</h2>
      <div class="contribution-columns">
        <section v-for="(rows, key) in contributors" :key="key">
          <h3>{{ key === 'growth' ? '月增长前三' : '月下降前三' }}</h3>
          <table><thead><tr><th>渠道</th><th>变化（万元）</th><th>贡献</th></tr></thead><tbody>
            <tr v-for="row in rows" :key="row.channel"><td>{{ row.channel }}</td><td :class="tone(row.paid_amount_change)">{{ row.paid_amount_change > 0 ? '+' : '' }}{{ money(row.paid_amount_change) }}</td><td>{{ percent(row.contribution, true) }}</td></tr>
            <tr v-if="!rows.length"><td colspan="3">暂无</td></tr>
          </tbody></table>
        </section>
      </div>
    </section>
    <section class="summary-panel">
      <h2>五、品牌与商品结构</h2>
      <div class="report-columns">
        <div><h3>品牌销售前五</h3><table><thead><tr><th>品牌</th><th>销售额（万元）</th></tr></thead><tbody><tr v-for="row in data.brands || []" :key="row.brand"><td>{{ row.brand }}</td><td>{{ money(row.paid_amount) }}</td></tr></tbody></table></div>
        <div><h3>正装／小样</h3><table><thead><tr><th>分类</th><th>销售额（万元）</th><th>两类占比</th></tr></thead><tbody><tr v-for="row in currentProducts" :key="row.product_type"><td>{{ row.product_type }}</td><td>{{ money(row.paid_amount) }}</td><td>{{ percent(productTotal ? row.paid_amount / productTotal : null) }}</td></tr></tbody></table></div>
      </div>
    </section>
    <section class="summary-panel">
      <h2>六、客户情况</h2>
      <div class="mini-metrics"><div><span>可识别客户</span><b>{{ number(customer.customers) }}</b></div><div><span>月内复购客户</span><b>{{ number(customer.repeat_customers) }}</b></div><div><span>月内复购率</span><b>{{ percent(customer.repeat_rate) }}</b></div></div>
    </section>
    <section class="summary-panel">
      <h2>七、采购到货与月末库存</h2>
      <div class="report-columns"><div><h3>采购到货</h3><div class="mini-metrics"><div><span>净到货（万件）</span><b>{{ wan(arrival.net_quantity) }}</b></div><div><span>入库单</span><b>{{ number(arrival.document_count) }}</b></div></div></div><div><h3>月末库存</h3><div class="mini-metrics"><div><span>库存量（万件）</span><b>{{ wan(inventory.stock_quantity) }}</b></div><div><span>快照明细</span><b>{{ number(inventory.detail_rows) }}</b></div></div></div></div>
    </section>
  </article>
</template>

<style scoped>
.monthly-summary { box-sizing: border-box; width: min(1000px, 100%); min-width: 0; max-width: 100%; margin: auto; padding: 24px; color: var(--text); background: var(--surface); border: 1px solid var(--border); border-radius: 10px; font-variant-numeric: tabular-nums; }
.summary-cover { border-bottom: 2px solid var(--text); padding-bottom: 12px; margin-bottom: 16px; }
h1 { margin: 0; font-size: 28px; } h2 { font-size: 19px; margin: 0 0 8px; } h3 { font-size: 16px; margin: 12px 0 6px; }
h2 small { font-size: 12px; font-weight: 400; color: var(--muted); margin-left: 8px; }
.summary-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 14px; }
.summary-metric { padding: 12px; background: var(--surface-soft); border: 1px solid var(--border); border-radius: 6px; }
.summary-metric > span { font-size: 14px; color: var(--muted); } .summary-metric > strong { display: block; font-size: 26px; margin: 6px 0; }
.summary-metric div { font-size: 14px; } .summary-metric div b { font-size: 22px; } .summary-metric small { display: block; margin-top: 4px; font-size: 13px; color: var(--muted); }
.up { color: var(--accent-strong); font-weight: 700; } .down { color: #b42318; font-weight: 700; }
.summary-panel { border: 1px solid var(--border); border-radius: 6px; padding: 12px; min-width: 0; margin-bottom: 12px; }
table { border-collapse: collapse; width: 100%; font-size: 14px; } th, td { padding: 6px 4px; text-align: right; border-bottom: 1px solid var(--border); white-space: nowrap; } th { color: var(--muted); font-weight: 600; font-size: 13px; } th:first-child, td:first-child { text-align: left; } tr:last-child td { border-bottom: 0; }
.channel-columns { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; } .channel-group td:first-child { white-space: normal; overflow-wrap: anywhere; } .channel-group table { font-size: 13px; } .channel-group td { padding: 5px 3px; }
.summary-bottom { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; } .summary-bottom .summary-panel { margin: 0; }
.mini-metrics { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 10px; } .mini-metrics span { display: block; color: var(--muted); font-size: 13px; } .mini-metrics b { display: block; font-size: 22px; margin-top: 6px; }
.monthly-sales-bars { display: block; width: 100%; height: 148px; margin-top: 8px; }
.month-table-scroll { overflow-x: auto; }
.chart-baseline { stroke: var(--border); stroke-width: 1; }
.sales-bar { fill: var(--accent-strong); opacity: .55; } .sales-bar.is-current { opacity: 1; }
.bar-value { fill: var(--text); font-size: 17px; font-weight: 700; } .bar-month, .chart-unit { fill: var(--muted); font-size: 15px; }
@media (max-width: 640px) {
 .monthly-summary { padding: 16px; } h1 { font-size: 24px; } .summary-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); } .summary-metric { padding: 10px; } .summary-metric > strong { font-size: 24px; }
 .channel-columns, .summary-bottom { grid-template-columns: 1fr; } .channel-group table, table { font-size: 16px; } .month-comparison table { min-width: 660px; }
 .channel-group td { padding: 8px 4px; } .mini-metrics b { font-size: 24px; }
 .channel-overview > table { font-size: 14px; }
 .channel-overview > table td, .channel-overview > table th { padding-left: 2px; padding-right: 2px; }
 .channel-overview > table td:first-child { white-space: normal; }
}
@media (max-width: 380px) { .summary-metrics { grid-template-columns: 1fr; } }
.monthly-summary.is-exporting { width: 794px; min-width: 794px; max-width: none; padding: 20px; border: 0; background: #fff; color: #17202a; }
.is-exporting .summary-metrics { grid-template-columns: repeat(4, minmax(0, 1fr)); } .is-exporting .channel-columns { grid-template-columns: repeat(3, minmax(0, 1fr)); } .is-exporting .summary-bottom { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.is-exporting table { font-size: 13px; } .is-exporting .channel-group table { font-size: 12px; } .is-exporting .channel-group td { padding: 5px 3px; } .is-exporting .month-comparison table { min-width: 0; } .is-exporting h1 { font-size: 28px; } .is-exporting .summary-metric > strong { font-size: 25px; }
.monthly-summary.is-exporting { line-height: 1.3; }
.is-exporting th, .is-exporting td { padding: 4px; line-height: 1.3; }
.is-exporting .channel-group td { padding: 4px 3px; }
.is-exporting .summary-panel { padding: 10px; margin-bottom: 10px; }
.is-exporting .summary-bottom .summary-panel { margin: 0; }
.is-exporting .summary-cover { padding-bottom: 10px; margin-bottom: 12px; }
.is-exporting h2 { font-size: 18px; margin-bottom: 6px; }
.is-exporting h3 { font-size: 15px; margin: 10px 0 4px; }
.is-exporting .monthly-sales-bars { height: 118px; margin-top: 4px; }
@media print { .monthly-summary { border: 0; padding: 0; width: 100%; } .summary-panel { break-inside: avoid; } }
 .contribution-columns { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.contribution-note { margin: 0; font-size: 13px; color: var(--muted); }
.contribution-panel td:first-child { white-space: normal; overflow-wrap: anywhere; }
@media (max-width: 640px) { .contribution-columns { grid-template-columns: 1fr; } }
.is-exporting .contribution-columns { grid-template-columns: 1fr 1fr; }
table { font-size: 15px; } th { font-size: 14px; }
.channel-group table { font-size: 14px; }
.summary-metric > strong { font-size: 28px; }
.is-exporting table { font-size: 15px; }
.is-exporting .channel-group table { font-size: 14px; }
.is-exporting th { font-size: 14px; }
.is-exporting .summary-metric > strong { font-size: 27px; }
.is-exporting .summary-panel { padding: 12px; }
/* 正文采用报告式纵向章节，标题与段落留出阅读间距。 */
.monthly-summary { width: min(960px, 100%); padding: 36px; }
.summary-panel, .report-intro { border: 0; border-top: 1px solid var(--border); border-radius: 0; padding: 28px 0; margin: 0; }
.report-intro { border-top: 0; }
h2 { font-size: 22px; margin-bottom: 16px; }
.report-prose { max-width: 76ch; font-size: 16px; line-height: 1.85; margin: 0 0 20px; }
.report-columns { display: grid; grid-template-columns: 1fr 1fr; gap: 32px; }
.channel-columns { gap: 24px; margin-top: 20px; }
.is-exporting .summary-panel, .is-exporting .report-intro { padding: 22px 0; margin: 0; }
.is-exporting h2 { font-size: 21px; margin-bottom: 14px; }
.is-exporting .report-prose { font-size: 15px; line-height: 1.75; margin-bottom: 16px; }
@media (max-width: 640px) { .monthly-summary { padding: 20px; } .report-columns { grid-template-columns: 1fr; } }
.is-exporting .report-columns { grid-template-columns: 1fr 1fr; }
</style>
