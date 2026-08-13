<script setup>
import { computed, onMounted, ref } from 'vue'
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

use([CanvasRenderer, CustomChart, LineChart, PieChart, GeoComponent, GridComponent, LegendComponent, TooltipComponent])
registerMap('china', chinaGeoJson)

const chartTheme = getSavedTheme()
const palette = [chartTheme.primary, chartTheme.secondary, '#64748b', '#d8a23a', chartTheme.pale, '#14b8a6', '#f97316']
const mapPieColors = [chartTheme.primary, chartTheme.secondary, '#d8a23a', '#64748b']

const summary = ref({
  cards: [],
  trend: { days: [], sales: [], orders: [] },
  channels: [],
  map_pies: [],
})

const brandRows = ref([])
const dashboardBrandColumns = [{ key: 'rank', label: '排名', kind: 'integer' }, { key: 'brand', label: '品牌' }, { key: 'orders', label: '订单数', kind: 'integer' }, { key: 'quantity', label: '销售数量', kind: 'integer' }, { key: 'paid_amount', label: '分摊销售额', kind: 'number' }, { key: 'share', label: '占比', kind: 'percent' }]

function formatNumber(value, digits = 0) {
  return Number(value || 0).toLocaleString('zh-CN', {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  })
}

function formatMillion(value, digits = 2) {
  return `${formatNumber(Number(value || 0) / 1000000, digits)}M`
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
  const [dashboardResult, brandResult] = await Promise.all([
    getDashboardSummary(),
    getSalesBrandAnalysis({ range: 'last_30', limit: 30 }),
  ])
  summary.value = dashboardResult.data
  brandRows.value = brandResult.data.rows || []
})

const channelPieData = computed(() => topWithOther(summary.value.channels, 'name', 'value', 6))
const brandPieData = computed(() => topWithOther(brandRows.value, 'brand', 'paid_amount', 7))

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
        const value = item.seriesName === '订单实付金额' ? formatMillion(item.value) : `${formatNumber(item.value)} 单`
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
        formatter: (value) => `${formatNumber(value / 1000000, 0)}M`,
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
      formatter: (params) => `${params.name}<br/>${title}：${formatMillion(params.value)}<br/>占比：${formatNumber(params.percent, 1)}%`,
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
      const lines = data.segments.map((item) => `${item.name}: ${formatMillion(item.value)}`)
      return [`${data.name}<br/>订单实付金额: ${formatMillion(data.total)}`, ...lines].join('<br/>')
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
    <div class="metric-grid dashboard-metrics">
      <MetricCard v-for="card in summary.cards" :key="card.label" v-bind="card" />
    </div>

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
