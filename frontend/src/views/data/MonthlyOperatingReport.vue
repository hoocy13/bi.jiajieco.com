<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { Download, Printer } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'
import { downloadMonthlyReport, getMonthlyReport, getMonthlyReports } from '../../api/reports'
import { getSavedTheme } from '../../utils/theme'

use([CanvasRenderer, BarChart, LineChart, GridComponent, LegendComponent, TooltipComponent])

const route = useRoute()
const router = useRouter()
const chartTheme = getSavedTheme()
const loading = ref(false)
const downloading = ref(false)
const months = ref([])
const selectedMonth = ref('')
const report = ref(null)

const artifact = computed(() => report.value?.artifact || null)
const manifest = computed(() => artifact.value?.manifest || {})
const datasets = computed(() => artifact.value?.snapshot?.datasets || {})
const cardsById = computed(() => Object.fromEntries((manifest.value.cards || []).map(item => [item.id, item])))
const chartsById = computed(() => Object.fromEntries((manifest.value.charts || []).map(item => [item.id, item])))
const tablesById = computed(() => Object.fromEntries((manifest.value.tables || []).map(item => [item.id, item])))

function formatValue(value, format) {
  if (format === 'percent') return `${(Number(value || 0) * 100).toFixed(1)}%`
  if (format === 'number') return Number(value || 0).toLocaleString('zh-CN', { maximumFractionDigits: 2 })
  return value ?? '-'
}

function signedValue(value, format) {
  const rendered = formatValue(value, format)
  return Number(value) > 0 ? `+${rendered}` : rendered
}

function parseMarkdown(body = '') {
  const result = { heading: '', bullets: [], paragraphs: [] }
  let paragraph = []
  const flush = () => {
    if (paragraph.length) result.paragraphs.push(paragraph.join(' ').replaceAll('**', ''))
    paragraph = []
  }
  body.split('\n').forEach((line) => {
    const text = line.trim()
    if (!text) return flush()
    if (text.startsWith('#')) result.heading = text.replace(/^#+\s*/, '')
    else if (text.startsWith('- ')) result.bullets.push(text.slice(2).replaceAll('**', ''))
    else paragraph.push(text)
  })
  flush()
  return result
}

function metricCards(block) {
  return (block.cardIds || []).map(id => cardsById.value[id]).filter(Boolean)
}

function chartOption(chart) {
  const rows = datasets.value[chart.dataset] || []
  const xField = chart.encodings.x.field
  const yField = chart.encodings.y.field
  const colorField = chart.encodings.color?.field
  const seriesNames = colorField ? [...new Set(rows.map(row => row[colorField]))] : [chart.title]
  const categories = [...new Set(rows.map(row => row[xField]))]
  return {
    color: [chartTheme.primary, chartTheme.secondary, '#64748b', '#d8a23a'],
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#111827',
      borderWidth: 0,
      textStyle: { color: '#fff' },
      valueFormatter: value => Number(value || 0).toLocaleString('zh-CN', { maximumFractionDigits: 2 }),
    },
    legend: colorField ? { bottom: 0, textStyle: { color: '#667085' } } : undefined,
    grid: { top: 28, left: 76, right: 32, bottom: colorField ? 58 : 42 },
    xAxis: {
      type: 'category',
      data: categories.map(value => String(value).replace(/^\d{4}-/, '')),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#cfd6df' } },
      axisLabel: { color: '#667085' },
    },
    yAxis: {
      type: 'value',
      name: chart.yAxisTitle || chart.encodings.y.label,
      splitLine: { lineStyle: { color: '#edf1f6' } },
      axisLabel: { color: '#667085', formatter: value => `${Number(value / 10000).toLocaleString('zh-CN')}万` },
    },
    series: seriesNames.map(name => ({
      name,
      type: chart.type,
      smooth: false,
      symbolSize: 6,
      barMaxWidth: 42,
      lineStyle: { width: 3 },
      areaStyle: chart.type === 'line' ? { opacity: 0.12 } : undefined,
      data: categories.map(category => {
        const row = rows.find(item => item[xField] === category && (!colorField || item[colorField] === name))
        return Number(row?.[yField] || 0)
      }),
    })),
  }
}

async function loadReport(month) {
  if (!month) return
  loading.value = true
  try {
    const result = await getMonthlyReport(month)
    report.value = result.data
    selectedMonth.value = month
    await router.replace({ query: { month } })
  } finally {
    loading.value = false
  }
}

async function downloadReport() {
  downloading.value = true
  try {
    const response = await downloadMonthlyReport(selectedMonth.value)
    const url = URL.createObjectURL(response.data)
    const link = document.createElement('a')
    link.href = url
    link.download = `${selectedMonth.value.replace('-', '年')}月经营月报.pdf`
    link.click()
    URL.revokeObjectURL(url)
  } finally {
    downloading.value = false
  }
}

async function printReport() {
  await nextTick()
  window.print()
}

onMounted(async () => {
  const result = await getMonthlyReports()
  months.value = result.data || []
  const requested = String(route.query.month || '')
  const initial = months.value.some(item => item.month === requested) ? requested : months.value[0]?.month
  if (initial) await loadReport(initial)
})
</script>

<template>
  <div class="monthly-report-page" v-loading="loading">
    <section class="report-toolbar no-print">
      <div>
        <span>报告月份</span>
        <el-select v-model="selectedMonth" placeholder="选择月份" @change="loadReport">
          <el-option v-for="item in months" :key="item.month" :label="item.month" :value="item.month" />
        </el-select>
      </div>
      <div class="toolbar-actions">
        <el-button :icon="Download" :loading="downloading" @click="downloadReport">下载报告</el-button>
        <el-button type="primary" :icon="Printer" @click="printReport">打印 / 保存PDF</el-button>
      </div>
    </section>

    <el-empty v-if="!loading && !artifact" description="暂无已发布经营月报" />

    <article v-else-if="artifact" class="report-paper">
      <header class="report-cover">
        <h1>{{ manifest.title }}</h1>
      </header>

      <template v-for="block in manifest.blocks" :key="block.id">
        <section v-if="block.type === 'markdown' && block.id !== 'title'" class="report-section narrative-block">
          <h2>{{ parseMarkdown(block.body).heading }}</h2>
          <ul v-if="parseMarkdown(block.body).bullets.length">
            <li v-for="item in parseMarkdown(block.body).bullets" :key="item">{{ item }}</li>
          </ul>
          <p v-for="item in parseMarkdown(block.body).paragraphs" :key="item">{{ item }}</p>
        </section>

        <section v-else-if="block.type === 'metric-strip'" class="metric-grid report-section">
          <article v-for="card in metricCards(block)" :key="card.id" class="metric-card">
            <span>{{ card.metrics[0].label }}</span>
            <strong>{{ formatValue(datasets[card.dataset]?.[0]?.[card.metrics[0].field], card.metrics[0].format) }}</strong>
            <div>
              <em v-for="metric in card.metrics.slice(1)" :key="metric.field">
                {{ metric.label }} {{ metric.signed ? signedValue(datasets[card.dataset]?.[0]?.[metric.field], metric.format) : formatValue(datasets[card.dataset]?.[0]?.[metric.field], metric.format) }}
              </em>
            </div>
          </article>
        </section>

        <section v-else-if="block.type === 'chart'" class="report-panel report-section">
          <header><h3>{{ chartsById[block.chartId]?.title }}</h3><span>{{ chartsById[block.chartId]?.subtitle }}</span></header>
          <VChart class="report-chart" :option="chartOption(chartsById[block.chartId])" autoresize />
        </section>

        <section v-else-if="block.type === 'table'" class="report-panel report-section">
          <header><h3>{{ tablesById[block.tableId]?.title }}</h3><span>{{ tablesById[block.tableId]?.subtitle }}</span></header>
          <el-table :data="datasets[tablesById[block.tableId]?.dataset] || []" stripe>
            <el-table-column
              v-for="column in tablesById[block.tableId]?.columns || []"
              :key="column.field"
              :prop="column.field"
              :label="column.label"
              min-width="130"
              sortable
            >
              <template #default="scope">{{ formatValue(scope.row[column.field], column.format) }}</template>
            </el-table-column>
          </el-table>
        </section>
      </template>
    </article>
  </div>
</template>

<style scoped>
.monthly-report-page { display: grid; gap: 16px; }
.report-toolbar { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); }
.report-toolbar > div { display: flex; align-items: center; gap: 10px; }.report-toolbar span { color: var(--muted); font-size: 13px; font-weight: 700; }.report-toolbar .el-select { width: 150px; }
.toolbar-actions { display: flex; gap: 8px; }
.report-paper { width: min(1060px, 100%); margin: 0 auto; padding: 42px 54px 64px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); box-shadow: var(--shadow); }
.report-cover { padding-bottom: 26px; border-bottom: 2px solid var(--text); }.report-cover h1 { margin: 0; font-size: 30px; }
.report-section { margin-top: 30px; break-inside: avoid; }.narrative-block h2 { margin: 0 0 14px; font-size: 21px; }.narrative-block p, .narrative-block li { color: var(--text-soft); font-size: 14px; line-height: 1.85; }.narrative-block p { margin: 8px 0; }.narrative-block ul { display: grid; gap: 8px; margin: 0; padding-left: 22px; }
.metric-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }.metric-card { padding: 18px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface-soft); }.metric-card > span { color: var(--muted); font-size: 12px; font-weight: 700; }.metric-card strong { display: block; margin: 10px 0; font-size: 23px; }.metric-card div { display: flex; flex-wrap: wrap; gap: 6px; }.metric-card em { padding: 4px 7px; border-radius: 5px; background: var(--accent-soft); color: var(--accent-strong); font-size: 11px; font-style: normal; font-weight: 700; }
.report-panel { overflow: hidden; border: 1px solid var(--border); border-radius: 8px; }.report-panel > header { padding: 14px 16px; border-bottom: 1px solid var(--border); }.report-panel h3 { margin: 0; font-size: 16px; }.report-panel header span { display: block; margin-top: 5px; color: var(--muted); font-size: 11px; }.report-chart { height: 360px; }
@media (max-width: 900px) { .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }.report-paper { padding: 28px 24px 44px; } }
@media (max-width: 640px) { .report-toolbar { align-items: stretch; flex-direction: column; gap: 12px; }.toolbar-actions { justify-content: flex-end; }.metric-grid { grid-template-columns: 1fr; } }
@media print {
  :global(.sidebar), :global(.topbar), .no-print { display: none !important; }
  :global(.main-content) { padding: 0 !important; }
  :global(body), :global(#app), :global(.app-shell) { background: #fff !important; }
  .monthly-report-page { display: block; }.report-paper { width: 100%; padding: 0; border: 0; box-shadow: none; color: #111; }.report-panel, .metric-card { border-color: #bbb; }.report-section { break-inside: avoid; }
  @page { size: A4 portrait; margin: 14mm; }
}
</style>
