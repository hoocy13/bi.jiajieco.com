<script setup>
import { computed, onMounted, ref } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import MetricCard from '../../components/dashboard/MetricCard.vue'
import { getSalesOverview } from '../../api/sales'

use([CanvasRenderer, BarChart, LineChart, GridComponent, LegendComponent, TooltipComponent])

const loading = ref(false)
const selectedRange = ref('last_30')
const dateRange = ref([])
const rangeOptions = [
  { label: '近30天', value: 'last_30' },
  { label: '本月', value: 'this_month' },
]
const overview = ref({
  as_of: '',
  period: '近30天',
  range: 'last_30',
  start_date: '',
  end_date: '',
  metrics: {
    paid_amount: 0,
    orders: 0,
    quantity: 0,
    avg_order_amount: 0,
  },
  trend: [],
  channels: [],
})

function formatNumber(value, digits = 0) {
  return Number(value || 0).toLocaleString('zh-CN', {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  })
}

function formatDate(value) {
  if (!value) return '-'
  return value.slice(0, 10)
}

const dateRangeLabel = computed(() => {
  const start = formatDate(overview.value.start_date)
  const end = formatDate(overview.value.end_date)
  return start === '-' || end === '-' ? '-' : `${start} 至 ${end}`
})

const canSearch = computed(() => selectedRange.value !== 'custom' || dateRange.value.length === 2)

const metrics = computed(() => [
  { label: '销售额', value: formatNumber(overview.value.metrics.paid_amount), unit: '元', trend: overview.value.period },
  { label: '订单数', value: formatNumber(overview.value.metrics.orders), unit: '单', trend: '正向订单去重' },
  { label: '销售数量', value: formatNumber(overview.value.metrics.quantity), unit: '件', trend: '货品数量合计' },
  { label: '客单价', value: formatNumber(overview.value.metrics.avg_order_amount, 2), unit: '元', trend: `截至 ${formatDate(overview.value.as_of)}` },
])

const trendOption = computed(() => ({
  color: ['#2563eb', '#139966'],
  tooltip: {
    trigger: 'axis',
    backgroundColor: '#111827',
    borderWidth: 0,
    textStyle: { color: '#ffffff' },
  },
  legend: {
    bottom: 2,
    icon: 'roundRect',
    textStyle: { color: '#667085' },
  },
  grid: { top: 28, left: 56, right: 24, bottom: 54 },
  xAxis: {
    type: 'category',
    data: overview.value.trend.map((item) => item.date.slice(5)),
    axisTick: { show: false },
    axisLine: { lineStyle: { color: '#c9d4e2' } },
    axisLabel: { color: '#667085' },
  },
  yAxis: {
    type: 'value',
    splitLine: { lineStyle: { color: '#edf1f6' } },
    axisLabel: { color: '#667085' },
  },
  series: [
    {
      name: '销售额',
      type: 'line',
      smooth: false,
      symbolSize: 6,
      lineStyle: { width: 3 },
      areaStyle: {
        opacity: 0.16,
      },
      data: overview.value.trend.map((item) => item.paid_amount),
    },
    {
      name: '订单数',
      type: 'line',
      smooth: false,
      symbolSize: 6,
      lineStyle: { width: 3 },
      areaStyle: {
        opacity: 0.12,
      },
      data: overview.value.trend.map((item) => item.orders),
    },
  ],
}))

const channelBarOption = computed(() => ({
  color: ['#2563eb'],
  tooltip: {
    trigger: 'axis',
    axisPointer: { type: 'shadow' },
    backgroundColor: '#111827',
    borderWidth: 0,
    textStyle: { color: '#ffffff' },
    formatter: (params) => {
      const item = params[0]
      const row = overview.value.channels[item.dataIndex]
      return [
        `${row.channel}`,
        `销售额：${formatNumber(row.paid_amount, 2)} 元`,
        `销售占比：${formatPercent(row.share)}`,
        `订单数：${formatNumber(row.orders)} 单`,
      ].join('<br/>')
    },
  },
  grid: { top: 14, left: 112, right: 30, bottom: 20 },
  xAxis: {
    type: 'value',
    splitLine: { lineStyle: { color: '#edf1f6' } },
    axisLabel: { color: '#98a2b3' },
  },
  yAxis: {
    type: 'category',
    inverse: true,
    data: overview.value.channels.slice(0, 8).map((item) => item.channel),
    axisTick: { show: false },
    axisLine: { show: false },
    axisLabel: {
      color: '#475467',
      width: 96,
      overflow: 'truncate',
    },
  },
  series: [
    {
      name: '销售额',
      type: 'bar',
      barWidth: 12,
      itemStyle: {
        borderRadius: [0, 8, 8, 0],
        color: {
          type: 'linear',
          x: 0,
          y: 0,
          x2: 1,
          y2: 0,
          colorStops: [
            { offset: 0, color: '#2563eb' },
            { offset: 1, color: '#139966' },
          ],
        },
      },
      label: {
        show: true,
        position: 'right',
        color: '#667085',
        fontSize: 11,
        formatter: (params) => formatNumber(params.value),
      },
      data: overview.value.channels.slice(0, 8).map((item) => item.paid_amount),
    },
  ],
}))

function formatPercent(value) {
  return `${formatNumber(value, 1)}%`
}

function handleRangeChange() {
  dateRange.value = []
}

function handleDateRangeChange(value) {
  if (value?.length === 2) {
    selectedRange.value = 'custom'
  }
}

async function fetchOverview() {
  if (!canSearch.value) return
  loading.value = true
  try {
    const params = selectedRange.value === 'custom'
      ? { start_date: dateRange.value[0], end_date: dateRange.value[1] }
      : { range: selectedRange.value }
    const result = await getSalesOverview(params)
    overview.value = result.data
    dateRange.value = [overview.value.start_date, overview.value.end_date]
  } finally {
    loading.value = false
  }
}

onMounted(fetchOverview)
</script>

<template>
  <div class="page-stack" v-loading="loading">
    <section class="toolbar-panel sales-filter">
      <div class="filter-controls">
        <el-segmented v-model="selectedRange" :options="rangeOptions" @change="handleRangeChange" />
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          value-format="YYYY-MM-DD"
          :unlink-panels="true"
          @change="handleDateRangeChange"
        />
        <el-button type="primary" :disabled="!canSearch" @click="fetchOverview">查询</el-button>
      </div>
      <div class="range-summary">
        <strong>{{ overview.period }}</strong>
        <span>{{ dateRangeLabel }}</span>
      </div>
    </section>

    <div class="metric-grid">
      <MetricCard v-for="item in metrics" :key="item.label" v-bind="item" />
    </div>

    <section class="panel">
      <header>
        <h2>{{ overview.period }}销售趋势<span class="panel-source">（销售单查询）</span></h2>
        <el-button :icon="'Refresh'" circle @click="fetchOverview" />
      </header>
      <v-chart class="chart" :option="trendOption" autoresize />
    </section>

    <section class="panel">
      <header>
        <h2>{{ overview.period }}渠道排行<span class="panel-source">（销售单查询）</span></h2>
      </header>
      <v-chart class="chart chart-compact" :option="channelBarOption" autoresize />
      <el-table :data="overview.channels" height="360">
        <el-table-column label="排名" width="74" align="center">
          <template #default="{ $index }">
            <span class="rank-badge">{{ $index + 1 }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="channel" label="销售渠道" min-width="220">
          <template #default="{ row }">
            <div class="channel-cell">
              <strong>{{ row.channel }}</strong>
              <span>
                <i :style="{ width: `${Math.min(row.share || 0, 100)}%` }"></i>
              </span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="share" label="销售占比" width="120">
          <template #default="{ row }">{{ formatPercent(row.share) }}</template>
        </el-table-column>
        <el-table-column prop="orders" label="订单数" width="130">
          <template #default="{ row }">{{ formatNumber(row.orders) }}</template>
        </el-table-column>
        <el-table-column prop="quantity" label="销售数量" width="130">
          <template #default="{ row }">{{ formatNumber(row.quantity) }}</template>
        </el-table-column>
        <el-table-column prop="paid_amount" label="销售额" width="180">
          <template #default="{ row }">{{ formatNumber(row.paid_amount, 2) }}</template>
        </el-table-column>
        <el-table-column prop="avg_order_amount" label="客单价" width="150">
          <template #default="{ row }">{{ formatNumber(row.avg_order_amount, 2) }}</template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>
