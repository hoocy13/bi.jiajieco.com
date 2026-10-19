<script setup>
import { computed } from 'vue'
import MonthlyReportFigure from './MonthlyReportFigure.vue'
import MonthlyBrandFlowFigure from './MonthlyBrandFlowFigure.vue'
import { reportAmount } from '../../utils/monthlyReportFormat'
const props = defineProps({ analysis: Object, section: String })
const inventory = computed(() => props.analysis?.inventory || {})
const value = (n, digits = 0) => n == null ? '-' : Number(n).toLocaleString('zh-CN', { maximumFractionDigits: digits, minimumFractionDigits: digits })
const amount = reportAmount
const signed = n => `${n > 0 ? '+' : ''}${amount(n)}`
const percent = n => n == null ? '-' : `${n > 0 ? '+' : ''}${value(n * 100, 1)}%`
const tone = n => n < 0 ? 'down' : 'up'
function bars(rows) {
  const max = Math.max(1, ...rows.map(row => Math.abs(row.change)))
  return rows.map(row => ({ ...row, width: Math.abs(row.change) / max * 100 }))
}
function mix(brand) {
  const positive = brand.channels.filter(row => row.paid_amount > 0)
  const total = positive.reduce((sum, row) => sum + row.paid_amount, 0)
  return positive.slice(0, 3).map(row => ({ ...row, width: row.paid_amount / total * 100 }))
}
</script>
<template>
  <div v-if="analysis" class="operating-analysis">
    <template v-if="section === 'trend'">
      <MonthlyReportFigure v-if="analysis.channel_trends" type="trend" :trend="analysis.channel_trends" caption="图4-1　重点渠道连续三个月净销售额" />
      <div v-if="analysis.channel_trends" class="analysis-table-scroll"><table><caption>表4-1　重点渠道月度销售额（万元）</caption><thead><tr><th>渠道</th><th v-for="month in analysis.channel_trends.months" :key="month">{{ month }}</th></tr></thead><tbody><tr v-for="series in analysis.channel_trends.series" :key="series.name"><td>{{ series.name }}</td><td v-for="(n,i) in series.values" :key="i">{{ amount(n) }}</td></tr></tbody></table></div>
    </template>
    <template v-else-if="section === 'drivers'">
      <figure class="brand-change-figure"><div v-for="channel in analysis.drivers" :key="channel.name" class="driver-block">
        <h4>{{ channel.name }} · {{ signed(channel.change) }}万元</h4>
        <div v-for="row in bars(channel.brands)" :key="row.name" class="change-row"><span>{{ row.name }}</span><div class="track"><i :class="tone(row.change)" :style="{ width: `${row.width / 2}%`, left: row.change >= 0 ? '50%' : 'auto', right: row.change < 0 ? '50%' : 'auto' }" /></div><b :class="tone(row.change)">{{ signed(row.change) }}</b></div>
      </div><figcaption>图5-1　重点渠道品牌销售增减额（万元）</figcaption></figure>
      <table><caption>表5-1　重点渠道商品增减额前三（万元）</caption><thead><tr><th>渠道</th><th>商品</th><th>增减额</th></tr></thead><tbody><template v-for="channel in analysis.drivers" :key="channel.name"><tr v-for="row in channel.products" :key="row.name"><td>{{ channel.name }}</td><td class="product-cell">{{ row.name }}</td><td :class="tone(row.change)">{{ signed(row.change) }}</td></tr></template></tbody></table>
      <p v-if="Math.abs(analysis.headline_gap) > 0.01" class="scope">商品明细与总体金额相差 {{ amount(analysis.headline_gap) }} 万元；本节按商品明细口径。</p>
    </template>
    <template v-else-if="section === 'brands'">
      <h3>品牌 × 渠道（前三渠道 · 万元）</h3>
      <div class="brand-mixes"><div v-for="brand in analysis.brands" :key="brand.name" class="brand-mix"><h4>{{ brand.name }}</h4><div v-for="row in mix(brand)" :key="row.name" class="mix-row"><span>{{ row.name }}</span><div class="track"><i :style="{ width: `${row.width}%` }" /></div><b>{{ amount(row.paid_amount) }}</b></div></div></div>
      <div class="analysis-table-scroll"><table><thead><tr><th>品牌</th><th>销售额（万元）</th><th>环比</th><th>增长最多渠道</th><th>下降最多渠道</th><th>第一渠道占比</th></tr></thead><tbody><tr v-for="brand in analysis.brands" :key="brand.name"><td>{{ brand.name }}</td><td>{{ amount(brand.paid_amount) }}</td><td :class="tone(brand.change)">{{ percent(brand.mom) }}</td><td>{{ brand.growth?.name || '-' }}<small v-if="brand.growth" class="up">{{ signed(brand.growth.change) }}</small></td><td>{{ brand.decline?.name || '-' }}<small v-if="brand.decline" class="down">{{ signed(brand.decline.change) }}</small></td><td>{{ brand.top_channel }}<small>{{ value(brand.top_share * 100, 1) }}%</small></td></tr></tbody></table></div>
    </template>
    <template v-else-if="section === 'inventory'">
      <template v-if="analysis.brand_flows?.brands?.length">
        <div class="scope-tags"><span>{{ analysis.brand_flows.end_date.slice(0,7) }}</span><span>按本月净销售额降序 · 全部仓库</span></div>
        <MonthlyBrandFlowFigure :flows="analysis.brand_flows" />
        <template v-if="analysis.brand_flows.brands.every(flow => flow.segments?.full_size && flow.segments?.sample)">
          <MonthlyBrandFlowFigure :flows="analysis.brand_flows" segment="full_size" figure-number="7-2" />
          <MonthlyBrandFlowFigure :flows="analysis.brand_flows" segment="sample" figure-number="7-3" />
        </template>
      </template>
      <p v-else class="scope">该月报尚无品牌进销存快照。</p>
    </template>
  </div>
</template>
<style scoped>
.operating-analysis { margin-top: 28px; min-width: 0; }
h3 { font-size: 18px; margin: 0 0 12px; } h4 { font-size: 16px; margin: 0 0 12px; } h4 b { margin-left: 12px; } h4 small { color: var(--muted); font-weight: 400; font-size: 13px; } h5 { font-size: 14px; margin: 0 0 12px; }
.scope { color: var(--muted); font-size: 13px; line-height: 1.7; margin: 10px 0 16px; }
.analysis-columns { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; } .analysis-columns > section { min-width: 0; }
.driver-block { padding: 18px 0; border-top: 1px solid var(--border); break-inside: avoid; }
.change-row, .mix-row { display: grid; grid-template-columns: 6em minmax(0, 1fr) auto; gap: 8px; align-items: center; font-size: 13px; margin: 12px 0; }
.change-row > span, .mix-row > span { overflow-wrap: anywhere; }
.track { height: 12px; background: var(--surface-soft); border-radius: 3px; overflow: hidden; } .track i { display: block; height: 100%; background: var(--accent-strong); } .track i.down { background: #b42318; }
.up { color: var(--accent-strong); } .down { color: #b42318; }
table { width: 100%; border-collapse: collapse; font-size: 13px; } th, td { padding: 8px 4px; text-align: right; border-bottom: 1px solid var(--border); vertical-align: top; font-variant-numeric: tabular-nums; } th { color: var(--muted); font-weight: 600; } th:first-child, td:first-child { text-align: left; } td:first-child { overflow-wrap: anywhere; } td:not(:first-child) { white-space: nowrap; } td small { display: block; font-size: 12px; margin-top: 4px; } .analysis-table-scroll { overflow-x: auto; }
.brand-mixes { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin: 20px 0; }.brand-mix { min-width: 0; }
.stock-columns { grid-template-columns: 1fr; gap: 24px; } .stock-columns td:first-child { width: 58%; }
@media (max-width:640px) { .analysis-columns, .brand-mixes { grid-template-columns: 1fr; } .analysis-table-scroll > table { min-width: 700px; } }
:global(.is-exporting) .analysis-columns { grid-template-columns: 1fr 1fr; } :global(.is-exporting) .stock-columns { grid-template-columns: 1fr; } :global(.is-exporting) .brand-mixes { grid-template-columns: 1fr 1fr; } :global(.is-exporting) .analysis-table-scroll > table { min-width: 0; font-size: 12px; }

.scope-tags { display: flex; flex-wrap: wrap; gap: 10px 18px; margin: 16px 0 24px; font-size: 15px; color: var(--muted); }
.scope { font-size: 15px; }
h4 small, td small { font-size: inherit; }
.change-row, .mix-row, table { font-size: 15px; }
h5 { font-size: 15px; }
.operating-analysis { margin-top: 36px; }
:global(.is-exporting) .analysis-table-scroll > table { font-size: 14px; }

caption { caption-side: bottom; text-align: center; font-size: 16px; font-weight: 600; padding-top: 16px; padding-bottom: 12px; }
.brand-change-figure { margin: 28px 0; break-inside: avoid; }
.brand-change-figure figcaption { text-align: center; font-size: 16px; font-weight: 600; margin-top: 16px; }
.brand-change-figure { display: grid; grid-template-columns: 1fr; }
.driver-block { padding: 18px 0; }
.product-cell { white-space: normal !important; }
.stock-columns > section { break-inside: avoid; }

.brand-change-figure .track { position: relative; }
.brand-change-figure .track::after { content: ''; position: absolute; left: 50%; top: 0; bottom: 0; width: 1px; background: #52606d; }
.brand-change-figure .track i { position: absolute; }
</style>
