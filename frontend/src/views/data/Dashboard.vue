<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth'
import VChart from 'vue-echarts'
import { registerMap, use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { CustomChart, LineChart, PieChart } from 'echarts/charts'
import { GeoComponent, GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import MetricCard from '../../components/dashboard/MetricCard.vue'
import ExportExcelButton from '../../components/common/ExportExcelButton.vue'
import chinaGeoJson from '../../assets/china.json'
import { getDashboardSummary } from '../../api/dashboard'
import { getSalesBrandAnalysis } from '../../api/sales'
import { getSavedTheme } from '../../utils/theme'
import { getActiveAnnouncements } from '../../api/announcements'

use([CanvasRenderer, CustomChart, LineChart, PieChart, GeoComponent, GridComponent, LegendComponent, TooltipComponent])
registerMap('china', chinaGeoJson)

const chartTheme = getSavedTheme()
const router = useRouter()
const auth = useAuthStore()
const palette = [chartTheme.primary, chartTheme.secondary, '#64748b', '#d8a23a', chartTheme.pale, '#14b8a6', '#f97316']
const mapPieColors = [chartTheme.primary, chartTheme.secondary, '#d8a23a', '#64748b']

const summary = ref({
  cards: [],
  trend: { days: [], sales: [], orders: [] },
  channels: [],
  map_pies: [],
})

const brandRows = ref([])
const announcements = ref([])
const dashboardBrandColumns = [{ key: 'rank', label: '排名', kind: 'integer' }, { key: 'brand', label: '品牌' }, { key: 'orders', label: '订单数', kind: 'integer' }, { key: 'quantity', label: '销售数量', kind: 'integer' }, { key: 'paid_amount', label: '分摊销售额', kind: 'number' }, { key: 'share', label: '占比', kind: 'percent' }]

function formatNumber(value, digits = 0) {
  return Number(value || 0).toLocaleString('zh-CN', {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  })
}

function formatWan(value, digits = 2) {
  return `${formatNumber(Number(value || 0) / 10000, digits)}万`
}

function topWithOther(rows, nameKey = 'name', valueKey = 'value', limit = 7) {
  const positiveRows = rows
    .map((item) => ({
      name: item[nameKey] || '未归类',
      value: Number(item[valueKey] || 0),
    }))
    .filter((item) => item.value > 0)

  const topRows = positiveRows.slice(0, limit)
  const other = positiveRows.slice(limit).reduce((sum, item) => sum + item.value, 0)
  return other > 0 ? [...topRows, { name: '其他', value: other }] : topRows
}

onMounted(async () => {
  const [dashboardResult, brandResult, announcementResult] = await Promise.all([
    getDashboardSummary(),
    getSalesBrandAnalysis({ range: 'last_30', limit: 30 }),
    getActiveAnnouncements(),
  ])
  summary.value = dashboardResult.data
  brandRows.value = brandResult.data.rows || []
  announcements.value = announcementResult.data || []
})

const channelPieData = computed(() => topWithOther(summary.value.channels, 'name', 'value', 6))
const brandPieData = computed(() => topWithOther(brandRows.value, 'brand', 'paid_amount', 7))

const recentTrend = computed(() => {
  const sales = summary.value.trend.sales.map(Number).filter(Number.isFinite)
  if (sales.length < 6) return { change: null, current: 0, previous: 0, sufficient: false }
  const previousRows = sales.slice(-6, -3)
  const currentRows = sales.slice(-3)
  const previous = previousRows.reduce((sum, value) => sum + value, 0) / previousRows.length
  const current = currentRows.reduce((sum, value) => sum + value, 0) / currentRows.length
  return {
    previous,
    current,
    change: previous ? ((current - previous) / previous) * 100 : null,
    sufficient: previous > 0,
  }
})

const operatingSummary = computed(() => {
  const direction = Number(recentTrend.value.change) >= 0 ? '增长' : '下降'
  const topChannel = summary.value.channels[0]
  const topBrand = brandRows.value[0]
  return [
    recentTrend.value.sufficient
      ? `最近3日平均销售额较此前3日${direction}${formatNumber(Math.abs(recentTrend.value.change), 1)}%`
      : '近期趋势数据不足，暂不生成环比结论',
    topChannel ? `${topChannel.name}是当前销售额最高的渠道，贡献${formatWan(topChannel.value)}` : '渠道数据正在准备中',
    topBrand ? `${topBrand.brand || '未归类品牌'}位列近30天品牌销售首位，占比${formatNumber(Number(topBrand.share || 0) * (Number(topBrand.share || 0) <= 1 ? 100 : 1), 1)}%` : '品牌数据正在准备中',
  ]
})

const anomalyItems = computed(() => {
  const days = summary.value.trend.days || []
  const sales = summary.value.trend.sales.map(Number)
  return sales.slice(1).map((value, index) => {
    const previous = sales[index]
    const change = previous >= 10000 ? ((value - previous) / previous) * 100 : null
    return {
      date: days[index + 1],
      change,
      text: `销售额较前一日${change >= 0 ? '上升' : '下降'}${formatNumber(Math.abs(change), 1)}%`,
    }
  }).filter(item => item.change !== null && Math.abs(item.change) >= 20)
    .sort((a, b) => Math.abs(b.change) - Math.abs(a.change))
    .slice(0, 3)
})

const contributionItems = computed(() => {
  const rows = summary.value.channels || []
  const total = rows.reduce((sum, item) => sum + Number(item.value || 0), 0)
  return rows.slice(0, 4).map(item => ({
    name: item.name || '未归类',
    value: Number(item.value || 0),
    share: total ? (Number(item.value || 0) / total) * 100 : 0,
  }))
})

const riskItems = computed(() => {
  const items = []
  if (recentTrend.value.sufficient && recentTrend.value.change <= -10) items.push({ label: '近期销售走弱', value: `${formatNumber(Math.abs(recentTrend.value.change), 1)}%` })
  if (anomalyItems.value.length) items.push({ label: '销售波动日期', value: `${anomalyItems.value.length}天` })
  const firstShare = contributionItems.value[0]?.share || 0
  if (firstShare >= 50) items.push({ label: '渠道集中度较高', value: `${formatNumber(firstShare, 1)}%` })
  return items.length ? items.slice(0, 3) : [{ label: '当前未发现高风险规则', value: '正常' }]
})

const opportunityItems = computed(() => {
  const items = []
  if (recentTrend.value.sufficient && recentTrend.value.change >= 10) items.push({ label: '近期销售增长', value: `${formatNumber(recentTrend.value.change, 1)}%` })
  return items.slice(0, 3)
})

function openInsight(path = '/ai/decisions') {
  router.push(path)
}

const trendOption = computed(() => ({
  color: [chartTheme.primary, chartTheme.secondary],
  tooltip: {
    trigger: 'axis',
    backgroundColor: '#111217',
    borderWidth: 0,
    textStyle: { color: '#ffffff' },
    formatter: (params) => [
      params[0]?.axisValue,
      ...params.map((item) => {
        const value = item.seriesName === '订单实付金额' ? formatWan(item.value) : `${formatNumber(item.value)} 单`
        return `${item.marker}${item.seriesName}：${value}`
      }),
    ].join('<br/>'),
  },
  legend: {
    bottom: 2,
    icon: 'roundRect',
    textStyle: { color: '#6f7480' },
  },
  grid: { top: 30, left: 56, right: 56, bottom: 54 },
  xAxis: {
    type: 'category',
    data: summary.value.trend.days,
    axisTick: { show: false },
    axisLine: { lineStyle: { color: '#d7d9e0' } },
    axisLabel: { color: '#6f7480' },
  },
  yAxis: [
    {
      type: 'value',
      name: '订单实付金额',
      splitLine: { lineStyle: { color: '#eceef3' } },
      axisLabel: {
        color: '#6f7480',
        formatter: (value) => `${formatNumber(value / 10000, 0)}万`,
      },
    },
    {
      type: 'value',
      name: '订单数',
      splitLine: { show: false },
      axisLabel: {
        color: '#6f7480',
        formatter: (value) => formatNumber(value),
      },
    },
  ],
  series: [
    {
      name: '订单实付金额',
      type: 'line',
      smooth: false,
      symbolSize: 7,
      lineStyle: { width: 3 },
      areaStyle: { opacity: 0.14 },
      data: summary.value.trend.sales,
    },
    {
      name: '订单数',
      type: 'line',
      yAxisIndex: 1,
      smooth: false,
      symbolSize: 6,
      lineStyle: { width: 2 },
      data: summary.value.trend.orders,
    },
  ],
}))

function pieOption(title, data) {
  return {
    color: palette,
    tooltip: {
      trigger: 'item',
      backgroundColor: '#111217',
      borderWidth: 0,
      textStyle: { color: '#ffffff' },
      formatter: (params) => `${params.name}<br/>${title}：${formatWan(params.value)}<br/>占比：${formatNumber(params.percent, 1)}%`,
    },
    legend: {
      bottom: 2,
      type: 'scroll',
      icon: 'circle',
      itemWidth: 8,
      itemHeight: 8,
      textStyle: { color: '#6f7480', fontSize: 11 },
    },
    series: [
      {
        name: title,
        type: 'pie',
        radius: ['52%', '72%'],
        center: ['50%', '42%'],
        avoidLabelOverlap: true,
        label: { show: false },
        labelLine: { show: false },
        data,
      },
    ],
  }
}

const channelOption = computed(() => pieOption('订单实付金额', channelPieData.value))
const brandOption = computed(() => pieOption('明细分摊销售额', brandPieData.value))

const geoPieOption = computed(() => ({
  color: mapPieColors,
  tooltip: {
    trigger: 'item',
    show: true,
    backgroundColor: '#111217',
    borderWidth: 0,
    textStyle: { color: '#ffffff' },
    formatter: (params) => {
      if (params.seriesName !== '城市渠道构成') return ''
      const data = params.data
      if (!data?.segments) return ''
      const lines = data.segments.map((item) => `${item.name}: ${formatWan(item.value)}`)
      return [`${data.name}<br/>订单实付金额: ${formatWan(data.total)}`, ...lines].join('<br/>')
    },
  },
  geo: {
    map: 'china',
    roam: true,
    silent: true,
    layoutCenter: ['50%', '54%'],
    layoutSize: '108%',
    itemStyle: {
      areaColor: '#f2f3f5',
      borderColor: '#d7d9e0',
      borderWidth: 1,
    },
    emphasis: {
      disabled: true,
    },
    label: {
      show: false,
    },
  },
  series: [
    {
      name: '城市渠道构成',
      type: 'custom',
      coordinateSystem: 'geo',
      silent: false,
      data: summary.value.map_pies.map((item) => ({
        ...item,
        value: [item.coord[0], item.coord[1], item.total],
      })),
      renderItem: (params, api) => {
        const data = summary.value.map_pies[params.dataIndex]
        if (!data) return null
        const point = api.coord([api.value(0), api.value(1)])
        const radius = Math.max(10, Math.min(24, Math.sqrt(Number(api.value(2)) || 0) / 290))
        const total = data.segments.reduce((sum, item) => sum + Number(item.value || 0), 0)
        let startAngle = -Math.PI / 2
        const children = data.segments.map((item, index) => {
          const angle = total ? (Number(item.value || 0) / total) * Math.PI * 2 : 0
          const sector = {
            type: 'sector',
            shape: {
              cx: point[0],
              cy: point[1],
              r: radius,
              r0: radius * 0.42,
              startAngle,
              endAngle: startAngle + angle,
              clockwise: true,
            },
            style: {
              fill: mapPieColors[index % mapPieColors.length],
              stroke: '#ffffff',
              lineWidth: 1,
            },
          }
          startAngle += angle
          return sector
        })
        children.push({
          type: 'text',
          style: {
            x: point[0],
            y: point[1] + radius + 12,
            text: data.name.replace('市', ''),
            fill: '#6f7480',
            fontSize: 10,
            align: 'center',
          },
        })
        return { type: 'group', children }
      },
    },
  ],
}))
</script>

<template>
  <div class="page-stack">
    <section v-if="announcements.length" class="dashboard-announcements" aria-label="系统公告">
      <article v-for="item in announcements" :key="item.id" class="dashboard-announcement">
        <el-icon><Bell /></el-icon>
        <div><strong>{{ item.title }}</strong><p>{{ item.content }}</p></div>
      </article>
    </section>
    <div class="metric-grid dashboard-metrics">
      <MetricCard v-for="card in summary.cards" :key="card.label" v-bind="card" />
    </div>

    <section class="insight-grid" aria-label="经营智能分析">
      <article class="insight-panel insight-summary">
        <header><div><h2>经营摘要</h2><span>基于当前经营数据自动整理</span></div><el-button v-if="auth.hasPermission('ai.decision.view')" link @click="openInsight()">查看全部</el-button></header>
        <ol><li v-for="item in operatingSummary" :key="item">{{ item }}</li></ol>
      </article>

      <article class="insight-panel insight-anomaly">
        <header><div><h2>异常监测</h2><span>前一日销售额不少于1万且波动超过20%</span></div><el-button v-if="auth.hasPermission('ai.decision.view')" link @click="openInsight()">智能洞察</el-button></header>
        <div v-if="anomalyItems.length" class="insight-list">
          <button v-for="item in anomalyItems" :key="item.date" type="button" @click="openInsight('/sales/overview')"><span>{{ item.text }}</span><small>{{ item.date }}</small></button>
        </div>
        <div v-else class="insight-empty">近7日未发现超过规则阈值的销售波动</div>
      </article>

      <article class="insight-panel insight-contribution">
        <header><div><h2>近期变化与渠道结构</h2><span>趋势对比和本期渠道占比，不代表因果归因</span></div><el-button v-if="auth.hasPermission('sales.view')" link @click="openInsight('/sales/channel-analysis')">渠道明细</el-button></header>
        <div class="trend-callout"><strong v-if="recentTrend.sufficient" :class="{ 'is-down': recentTrend.change < 0 }">{{ recentTrend.change >= 0 ? '+' : '' }}{{ formatNumber(recentTrend.change, 1) }}%</strong><strong v-else>数据不足</strong><span>最近3日平均销售额对比此前3日</span></div>
        <div class="contribution-list"><div v-for="item in contributionItems" :key="item.name"><span>{{ item.name }}</span><strong>{{ formatNumber(item.share, 1) }}%</strong></div></div>
      </article>

      <article class="insight-panel insight-risks">
        <header><div><h2>风险与机会</h2><span>下降或增长≥10%，波动≥20%，渠道占比≥50%</span></div><el-button v-if="auth.hasPermission('ai.decision.view')" link @click="openInsight('/ai/analysis')">分析工作台</el-button></header>
        <div class="risk-columns">
          <div><h3>需要关注</h3><p v-for="item in riskItems" :key="item.label"><span>{{ item.label }}</span><strong>{{ item.value }}</strong></p></div>
          <div><h3>当前机会</h3><p v-for="item in opportunityItems" :key="item.label"><span>{{ item.label }}</span><strong>{{ item.value }}</strong></p><p v-if="!opportunityItems.length"><span>暂未命中增长规则</span><strong>无</strong></p></div>
        </div>
      </article>
    </section>

    <div class="content-grid">
      <section class="panel wide">
        <header><h2>近七日订单实付趋势<span class="panel-source">（订单头实付金额口径）</span></h2></header>
        <v-chart class="chart" :option="trendOption" autoresize />
      </section>
      <section class="panel">
        <header><h2>渠道订单实付占比<span class="panel-source">（订单头实付金额口径）</span></h2></header>
        <v-chart class="chart" :option="channelOption" autoresize />
      </section>
    </div>

    <div class="content-grid">
      <section class="panel">
        <header><h2>城市渠道构成<span class="panel-source">（订单头实付金额口径）</span></h2></header>
        <v-chart class="map-chart map-chart-compact" :option="geoPieOption" autoresize />
      </section>
      <section class="panel">
        <header><h2>品牌占比<span class="panel-source">（商品明细分摊金额口径）</span></h2><ExportExcelButton title="经营总览_品牌排行" :rows="brandRows" :columns="dashboardBrandColumns" :total="brandRows.length" :filters="{ 统计区间: '近30天' }" /></header>
        <v-chart class="chart" :option="brandOption" autoresize />
      </section>
    </div>
  </div>
</template>

<style scoped>
.dashboard-announcements { display: grid; gap: 8px; }
.dashboard-announcement { display: grid; grid-template-columns: 24px 1fr; gap: 10px; align-items: start; padding: 12px 16px; border: 1px solid var(--border); border-radius: 9px; background: var(--surface); }
.dashboard-announcement .el-icon { margin-top: 2px; color: var(--accent-strong); }
.dashboard-announcement strong { font-size: 14px; }
.dashboard-announcement p { margin: 4px 0 0; color: var(--text-soft); font-size: 13px; line-height: 1.6; white-space: pre-wrap; }
.insight-grid { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(0, .85fr); gap: 12px; }
.insight-panel { min-width: 0; padding: 0 16px 15px; background: var(--surface); border: 1px solid var(--border); border-radius: 9px; }
.insight-panel > header { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 62px; border-bottom: 1px solid var(--border); }
.insight-panel h2 { margin: 0; font-size: 15px; }
.insight-panel header span { display: block; margin-top: 4px; color: var(--text-soft); font-size: 11px; }
.insight-summary ol { display: grid; gap: 10px; margin: 14px 0 0; padding-left: 22px; }
.insight-summary li { padding-left: 4px; color: var(--text); font-size: 13px; line-height: 1.55; }
.insight-summary li::marker { color: var(--text-soft); font-variant-numeric: tabular-nums; }
.insight-list { display: grid; margin-top: 5px; }
.insight-list button { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 40px; padding: 0; color: var(--text); background: transparent; border: 0; border-bottom: 1px solid var(--border); font: inherit; font-size: 12px; text-align: left; cursor: pointer; }
.insight-list button:last-child { border-bottom: 0; }
.insight-list button:hover span { color: var(--accent-strong); }
.insight-list small { flex: 0 0 auto; color: var(--text-soft); }
.insight-empty { display: grid; min-height: 116px; place-items: center; color: var(--text-soft); font-size: 12px; text-align: center; }
.trend-callout { display: flex; align-items: baseline; gap: 10px; padding: 14px 0 12px; }
.trend-callout strong { color: var(--accent-strong); font-size: 24px; font-variant-numeric: tabular-nums; }
.trend-callout strong.is-down { color: #b45353; }
.trend-callout span { color: var(--text-soft); font-size: 11px; }
.contribution-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px 18px; }
.contribution-list div { display: flex; justify-content: space-between; gap: 10px; padding-top: 7px; border-top: 1px solid var(--border); font-size: 12px; }
.contribution-list span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.contribution-list strong { font-variant-numeric: tabular-nums; }
.risk-columns { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; padding-top: 12px; }
.risk-columns > div + div { padding-left: 18px; border-left: 1px solid var(--border); }
.risk-columns h3 { margin: 0 0 5px; color: var(--text-soft); font-size: 11px; font-weight: 600; }
.risk-columns p { display: flex; justify-content: space-between; gap: 10px; margin: 0; padding: 7px 0; font-size: 12px; }
.risk-columns p + p { border-top: 1px solid var(--border); }
.risk-columns p span { color: var(--text-soft); }
.risk-columns p strong { max-width: 110px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
@media (max-width: 980px) { .insight-grid { grid-template-columns: 1fr; } }
@media (max-width: 600px) { .contribution-list, .risk-columns { grid-template-columns: 1fr; } .risk-columns > div + div { padding: 10px 0 0; border-top: 1px solid var(--border); border-left: 0; } }
</style>
