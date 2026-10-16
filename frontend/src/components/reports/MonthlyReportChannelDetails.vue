<script setup>
import { computed } from 'vue'
import { channelWarning } from '../../utils/monthlyReportInsights'
import { isOnlineChannel, isWuyanChannel } from '../../utils/salesChannelClassification'

const props = defineProps({ artifact: Object, month: String })
const data = computed(() => props.artifact?.snapshot?.datasets || {})
const groups = computed(() => ['线上渠道', '线下渠道', '梧颜'].map((name, index) => ({
  name,
  rows: (data.value.channel_sales || []).filter(row => (isWuyanChannel(row) ? 2 : isOnlineChannel(row) ? 0 : 1) === index)
    .slice().sort((a, b) => Number(b.paid_amount) - Number(a.paid_amount) || a.channel.localeCompare(b.channel, 'zh-CN')),
})))
const total = computed(() => (data.value.channel_sales || []).reduce((sum, row) => sum + Number(row.paid_amount || 0), 0))
function number(value) { return value == null ? '-' : Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 0 }) }
function money(value) {
  if (value == null) return '-'
  return (Number(value) / 10000).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
function percent(value, signed = false) {
  if (value == null) return '-'
  return `${signed && value > 0 ? '+' : ''}${(Number(value) * 100).toFixed(1)}%`
}
function tone(value) { return value < 0 ? 'down' : value > 0 ? 'up' : '' }
</script>

<template>
  <article class="report-paper channel-details">
    <header><h1>八、全渠道经营明细</h1><span>{{ month }} · 金额：万元</span></header>
    <div class="detail-scroll">
      <table class="channel-detail-table">
        <colgroup><col class="name-column" /><col class="platform-column" /><col /><col /><col /><col /><col /></colgroup>
        <thead><tr><th>渠道名称</th><th>平台</th><th>销售额</th><th>占比</th><th>环比</th><th>订单数</th><th>销售数量</th></tr></thead>
        <tbody>
          <template v-for="group in groups" :key="group.name">
            <tr class="group-row"><th colspan="7">{{ group.name }} <small>{{ group.rows.length }} 个</small></th></tr>
            <tr v-for="row in group.rows" :key="row.channel" class="detail-row">
              <td>{{ row.channel }}</td><td>{{ row.platform && row.platform !== '未设置' ? row.platform : '-' }}</td>
              <td :class="{ down: row.paid_amount < 0 }">{{ money(row.paid_amount) }}</td><td>{{ percent(row.share) }}</td>
              <td :class="tone(row.paid_amount_mom)">{{ ['缺少基期', '上月负净额', '上月为零', '两月无销售'].includes(channelWarning(row)) ? '-' : percent(row.paid_amount_mom, true) }}<small v-if="channelWarning(row)" class="warning">{{ channelWarning(row) }}</small></td><td>{{ number(row.orders) }}</td><td>{{ number(row.quantity) }}</td>
            </tr>
          </template>
          <tr v-if="data.channel_sales?.length" class="total-row"><th colspan="2">合计</th><td>{{ money(total) }}</td><td>{{ percent(data.headline?.[0]?.paid_amount ? total / data.headline[0].paid_amount : null) }}</td><td>-</td><td>{{ number(data.channel_sales.reduce((sum, row) => sum + Number(row.orders || 0), 0)) }}</td><td>{{ number(data.channel_sales.reduce((sum, row) => sum + Number(row.quantity || 0), 0)) }}</td></tr>
          <tr v-else><td colspan="7">暂无渠道明细</td></tr>
        </tbody>
      </table>
    </div>
  </article>
</template>

<style scoped>
.channel-details { box-sizing: border-box; width: min(960px, 100%); min-width: 0; max-width: 100%; margin: auto; padding: 36px; color: var(--text); background: var(--surface); border: 1px solid var(--border); border-radius: 10px; font-variant-numeric: tabular-nums; }
header { display: flex; align-items: baseline; justify-content: space-between; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; } h1 { margin: 0; font-size: 24px; } header span { font-size: 14px; color: var(--muted); }
.detail-scroll { overflow-x: auto; } table { width: 100%; border-collapse: collapse; font-size: 14px; } th, td { border-bottom: 1px solid var(--border); padding: 6px 4px; text-align: right; white-space: nowrap; } th:first-child, td:first-child { text-align: left; white-space: normal; overflow-wrap: anywhere; } td:nth-child(2), th:nth-child(2) { text-align: left; white-space: normal; }
.name-column { width: 34%; } .platform-column { width: 15%; } thead th { color: var(--muted); }
.group-row th { background: var(--surface-soft); color: var(--accent-strong); padding: 6px 4px; } small { font-weight: 400; color: var(--muted); margin-left: 8px; }
.total-row { font-weight: 700; } .up { color: var(--accent-strong); } .down { color: #b42318; }
@media (max-width: 640px) { .channel-details { padding: 20px; } h1 { font-size: 22px; } table { min-width: 760px; font-size: 16px; } }
.channel-details.is-exporting { width: 794px; min-width: 794px; max-width: none; padding: 16px 20px; background: #fff; color: #17202a; border: 0; }
.is-exporting table { min-width: 0; table-layout: fixed; font-size: 12px; line-height: 1.15; } .is-exporting td, .is-exporting th { padding: 1px 3px; } .is-exporting .group-row th { padding: 3px; } .is-exporting h1 { font-size: 22px; } .is-exporting header span { font-size: 12px; }
@media print { .channel-details { break-before: page; width: 100%; border: 0; padding: 0; } thead { display: table-header-group; } tr { break-inside: avoid; } }
.warning { display: block; margin: 0; color: #9a6700; font-size: 12px; white-space: normal; }
.is-exporting .warning { font-size: 10px; }
table { font-size: 15px; }
.is-exporting table { font-size: 14px; line-height: 1.25; }
.is-exporting td, .is-exporting th { padding: 3px; }
.is-exporting .warning { font-size: 11px; }
</style>
