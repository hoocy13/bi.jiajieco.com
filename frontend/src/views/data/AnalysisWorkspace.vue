<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart, BarChart } from 'echarts/charts'
import { CanvasRenderer } from 'echarts/renderers'
import { GridComponent, TooltipComponent, MarkPointComponent } from 'echarts/components'
import MetricCard from '../../components/dashboard/MetricCard.vue'
import { getAnalysisWorkspace } from '../../api/ai'
import { getSavedTheme } from '../../utils/theme'

use([CanvasRenderer, LineChart, BarChart, GridComponent, TooltipComponent, MarkPointComponent])
const router = useRouter()
const chartTheme = getSavedTheme()
const loading = ref(false)
const result = ref({ start_date: '', end_date: '', as_of: '', summary: {}, trend: [], brands: [], anomalies: [] })
const money = (value, digits = 2) => Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
const percent = (value) => value === null || value === undefined ? '暂无可比数据' : `${value >= 0 ? '+' : ''}${money(value, 1)}%`
const dateText = (value) => value ? String(value).slice(0, 10) : '-'
const metrics = computed(() => [
  { label: '近90天销售额', value: money(result.value.summary.paid_amount), unit: '元', trend: `${dateText(result.value.start_date)} 至 ${dateText(result.value.end_date)}` },
  { label: '较上一周期', value: percent(result.value.summary.change_rate), unit: '', trend: `上一周期 ${money(result.value.summary.previous_paid_amount)} 元` },
  { label: '日均销售额', value: money(result.value.summary.daily_average), unit: '元', trend: '按自然日计算' },
  { label: '异常波动', value: Number(result.value.summary.anomaly_count || 0), unit: '天', trend: '偏离均值至少 2 个标准差' },
])
const trendOption = computed(() => ({
  color: [chartTheme.primary],
  tooltip: { trigger: 'axis', backgroundColor: '#111827', borderWidth: 0, textStyle: { color: '#fff' }, formatter: ([item]) => `${item.axisValue}<br/>销售额：${money(item.value)} 元` },
  grid: { top: 28, left: 70, right: 22, bottom: 42 },
  xAxis: { type: 'category', data: result.value.trend.map(item => dateText(item.date).slice(5)), axisTick: { show: false }, axisLabel: { color: '#667085' } },
  yAxis: { type: 'value', splitLine: { lineStyle: { color: '#edf1f6' } }, axisLabel: { color: '#667085', formatter: value => `${money(value / 10000, 0)}万` } },
  series: [{ type: 'line', smooth: true, symbol: 'none', lineStyle: { width: 3 }, areaStyle: { opacity: 0.12 }, data: result.value.trend.map(item => item.paid_amount), markPoint: { symbolSize: 48, data: result.value.anomalies.map(item => ({ coord: [dateText(item.date).slice(5), item.paid_amount], itemStyle: { color: item.direction === 'up' ? '#e61d4f' : '#16a36a' } })) } }],
}))
const brandOption = computed(() => ({
  color: [chartTheme.primary],
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, backgroundColor: '#111827', borderWidth: 0, textStyle: { color: '#fff' }, formatter: ([item]) => { const row = result.value.brands[item.dataIndex]; return `${row.brand}<br/>销售额：${money(row.paid_amount)} 元<br/>贡献：${money(row.share, 1)}%` } },
  grid: { top: 12, left: 100, right: 54, bottom: 24 },
  xAxis: { type: 'value', axisLabel: { color: '#98a2b3', formatter: value => `${money(value / 10000, 0)}万` }, splitLine: { lineStyle: { color: '#edf1f6' } } },
  yAxis: { type: 'category', inverse: true, data: result.value.brands.map(item => item.brand), axisTick: { show: false }, axisLine: { show: false }, axisLabel: { color: '#475467', width: 82, overflow: 'truncate' } },
  series: [{ type: 'bar', barWidth: 12, data: result.value.brands.map(item => item.paid_amount), itemStyle: { borderRadius: [0, 7, 7, 0] }, label: { show: true, position: 'right', color: '#667085', formatter: ({ dataIndex }) => `${money(result.value.brands[dataIndex]?.share, 1)}%` } }],
}))
async function fetchAnalysis() { loading.value = true; try { const response = await getAnalysisWorkspace(); result.value = response.data } finally { loading.value = false } }
function openBrand(brand) { router.push({ path: `/sales/brand-analysis/${encodeURIComponent(brand)}`, query: { range: 'custom', start_date: result.value.start_date, end_date: result.value.end_date } }) }
function handleBrandClick(event) { const brand = result.value.brands[event.dataIndex]?.brand; if (brand) openBrand(brand) }
onMounted(fetchAnalysis)
</script>

<template>
  <div class="analysis-workspace page-stack" v-loading="loading">
    <section class="analysis-intro">
      <div><h2>销售趋势与品牌贡献</h2><p>自动比较连续两个 90 天周期，并识别明显偏离日常水平的销售日期。</p></div>
      <div class="freshness"><span>数据截至</span><strong>{{ dateText(result.as_of) }}</strong></div>
    </section>
    <section class="toolbar-panel analysis-scope">
      <el-select model-value="paid_amount" disabled><el-option label="销售额" value="paid_amount" /></el-select>
      <el-select model-value="trend" disabled><el-option label="趋势与环比" value="trend" /></el-select>
      <el-select model-value="brand" disabled><el-option label="品牌" value="brand" /></el-select>
      <el-select model-value="last_90" disabled><el-option label="近90天" value="last_90" /></el-select>
      <el-button type="primary" @click="fetchAnalysis">重新分析</el-button><span class="mvp-note">首期已开放此分析组合</span>
    </section>
    <div class="metric-grid"><MetricCard v-for="item in metrics" :key="item.label" v-bind="item" /></div>
    <section class="panel"><header><h2>每日销售趋势</h2><span class="panel-source">异常点已标记</span></header><v-chart class="chart" :option="trendOption" autoresize /></section>
    <div class="analysis-grid">
      <section class="panel"><header><h2>品牌贡献 Top 10</h2><span class="panel-source">点击品牌下钻</span></header><v-chart class="brand-chart" :option="brandOption" autoresize @click="handleBrandClick" /></section>
      <section class="panel anomaly-panel"><header><h2>异常波动日期</h2><span class="panel-source">相对日均销售额</span></header>
        <el-empty v-if="!result.anomalies.length" description="本周期未发现明显异常" />
        <div v-for="item in result.anomalies" :key="item.date" class="anomaly-row"><span><strong>{{ dateText(item.date) }}</strong><small>{{ item.direction === 'up' ? '显著高于日常' : '显著低于日常' }}</small></span><span :class="item.direction">{{ percent(item.deviation_rate) }}</span><b>{{ money(item.paid_amount) }} 元</b></div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.analysis-intro{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:20px;color:var(--text);background:var(--surface);border:1px solid var(--border);border-radius:9px}.analysis-intro h2{margin:0;font-size:20px}.analysis-intro p{margin:7px 0 0;color:var(--text-soft);font-size:13px}.freshness{display:grid;gap:3px;text-align:right}.freshness span,.mvp-note{color:var(--text-soft);font-size:12px}.analysis-scope{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.analysis-scope .el-select{width:150px}.mvp-note{margin-left:auto}.chart{height:330px}.analysis-grid{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(320px,.8fr);gap:16px}.brand-chart{height:390px;cursor:pointer}.anomaly-panel{min-width:0}.anomaly-row{display:grid;grid-template-columns:1fr auto;gap:3px 12px;margin:0 16px;padding:13px 4px;color:var(--text);border-bottom:1px solid var(--border)}.anomaly-row span:first-child{display:grid;gap:3px}.anomaly-row small{color:var(--text-soft)}.anomaly-row span.up{color:#e61d4f;font-weight:700}.anomaly-row span.down{color:#16865c;font-weight:700}.anomaly-row b{color:var(--text-soft);font-size:12px;font-weight:500}@media(max-width:1050px){.analysis-grid{grid-template-columns:1fr}}@media(max-width:700px){.analysis-intro{align-items:flex-start;flex-direction:column}.freshness{text-align:left}.analysis-scope .el-select{width:calc(50% - 5px)}.mvp-note{width:100%;margin:0}}
</style>
