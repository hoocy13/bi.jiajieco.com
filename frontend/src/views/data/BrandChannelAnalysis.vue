<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { getSalesBrandChannelAnalysis } from '../../api/sales'
import ExportExcelButton from '../../components/common/ExportExcelButton.vue'
import { getSavedTheme } from '../../utils/theme'

use([CanvasRenderer, LineChart, GridComponent, LegendComponent, TooltipComponent])

const chartTheme = getSavedTheme()

const route = useRoute()
const router = useRouter()
const brand = computed(() => String(route.params.brand || ''))
const loading = ref(false)
const pageOptions = [
  { label: '月度趋势', value: 'monthly' },
  { label: '渠道效率', value: 'channel' },
  { label: '数据明细', value: 'detail' },
]
const activePage = ref(pageOptions.some((item) => item.value === route.query.view) ? route.query.view : 'monthly')
const supportedRanges = ['last_30', 'this_month', 'this_year']
const initialRange = String(route.query.range || '')
const selectedRange = ref(
  route.query.start_date && route.query.end_date
    ? 'custom'
    : supportedRanges.includes(initialRange) ? initialRange : 'this_year',
)
const dateRange = ref(
  route.query.start_date && route.query.end_date
    ? [String(route.query.start_date), String(route.query.end_date)]
    : [],
)

function queryValues(value) {
  if (Array.isArray(value)) return value.map(String).filter(Boolean)
  return value ? [String(value)] : []
}

const query = reactive({
  channelType: queryValues(route.query.channel_type),
  channelName: queryValues(route.query.channel_name),
  productTypes: queryValues(route.query.product_type).filter((item) => ['正装', '小样'].includes(item)),
})
const productTypeOptions = ['正装', '小样']
const rangeOptions = [
  { label: '近30天', value: 'last_30' },
  { label: '本月', value: 'this_month' },
  { label: '本年', value: 'this_year' },
]
const analysis = ref({
  period: '本年',
  start_date: '',
  end_date: '',
  summary: {
    paid_amount: 0,
    orders: 0,
    quantity: 0,
    avg_order_amount: 0,
    avg_unit_price: 0,
  },
  trend: [],
  channel_types: [],
  platforms: [],
  channels: [],
  products: [],
  salesperson_product_types: [],
  sales_contribution: {
    online: { paid_amount: 0, quantity: 0 },
    offline: { paid_amount: 0, quantity: 0 },
    paid_amount_difference: 0,
    quantity_difference: 0,
  },
  unmatched_channels: [],
  filter_options: {
    channel_types: [],
    channel_names: [],
  },
})
const productExportColumns = [{ key: 'rank', label: '排名', kind: 'integer' }, { key: 'product', label: '商品名称', width: 42 }, { key: 'orders', label: '订单数', kind: 'integer' }, { key: 'quantity', label: '销售数量', kind: 'integer' }, { key: 'paid_amount', label: '分摊销售额', kind: 'number' }, { key: 'share', label: '占比', kind: 'percent' }]

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

function formatPercent(value) {
  return `${formatNumber(value, 1)}%`
}

function progressWidth(value) {
  return `${Math.min(Math.max(Number(value || 0), 0), 100)}%`
}

const dateRangeLabel = computed(() => {
  const start = formatDate(analysis.value.start_date)
  const end = formatDate(analysis.value.end_date)
  return start === '-' || end === '-' ? '-' : `${start} 至 ${end}`
})

const canSearch = computed(() => selectedRange.value !== 'custom' || dateRange.value.length === 2)

const metrics = computed(() => [
  {
    label: '周期明细分摊销售额',
    alias: '',
    value: formatNumber(analysis.value.summary.paid_amount, 2),
    unit: '元',
    note: '含退货 / 冲销',
    accent: true,
  },
  {
    label: '订单数',
    value: formatNumber(analysis.value.summary.orders),
    unit: '单',
    note: '按订单编号去重',
  },
  {
    label: '销售数量',
    value: formatNumber(analysis.value.summary.quantity),
    unit: '件',
    note: analysis.value.period,
  },
  {
    label: '客单价',
    value: formatNumber(analysis.value.summary.avg_order_amount, 2),
    unit: '元',
    note: '明细分摊销售额 / 订单数',
  },
])

const activeChannels = computed(() => analysis.value.channels.filter(
  (item) => Number(item.orders || 0) !== 0 || Number(item.paid_amount || 0) !== 0,
))
function isOnlineChannel(item) {
  if (typeof item.is_online === 'boolean') return item.is_online
  return Boolean(item.platform && item.platform !== '未设置')
}

function displayPlatform(platform) {
  const value = String(platform || '')
  const platformNames = [
    ['天猫', '天猫'],
    ['淘宝', '淘宝'],
    ['拼多多', '拼多多'],
    ['得物', '得物'],
    ['京东', '京东'],
    ['快手', '快手'],
    ['抖店', '抖音'],
    ['抖音', '抖音'],
    ['美团', '美团'],
    ['微信', '微信'],
    ['SHEIN', 'SHEIN'],
    ['95分', '95分'],
    ['度小店', '百度'],
    ['基木鱼', '百度'],
  ]
  return platformNames.find(([keyword]) => value.includes(keyword))?.[1] || value
}

const onlineChannels = computed(() => activeChannels.value
  .filter(isOnlineChannel)
  .sort((a, b) => Number(b.paid_amount || 0) - Number(a.paid_amount || 0))
  .slice(0, 5))
const offlineChannels = computed(() => activeChannels.value
  .filter((item) => !isOnlineChannel(item))
  .sort((a, b) => Number(b.paid_amount || 0) - Number(a.paid_amount || 0))
  .slice(0, 6))
const onlineShare = computed(() => onlineChannels.value.reduce((sum, item) => sum + Number(item.share || 0), 0))
const offlineShare = computed(() => offlineChannels.value.reduce((sum, item) => sum + Number(item.share || 0), 0))

const salesContribution = computed(() => {
  const channels = activeChannels.value.filter((item) => Number(item.paid_amount || 0) !== 0)
  const contribution = analysis.value.sales_contribution
  const summarize = (field, label, unit, digits) => {
    const hasBackendContribution = contribution?.online && contribution?.offline
    const online = hasBackendContribution
      ? Number(contribution.online[field] || 0)
      : channels.filter(isOnlineChannel).reduce((sum, item) => sum + Number(item[field] || 0), 0)
    const offline = hasBackendContribution
      ? Number(contribution.offline[field] || 0)
      : channels.filter((item) => !isOnlineChannel(item)).reduce((sum, item) => sum + Number(item[field] || 0), 0)
    const comparableTotal = Math.max(online, 0) + Math.max(offline, 0)
    return {
      field,
      label,
      unit,
      digits,
      online,
      offline,
      onlinePercent: comparableTotal ? Math.max(online, 0) / comparableTotal * 100 : 0,
      offlinePercent: comparableTotal ? Math.max(offline, 0) / comparableTotal * 100 : 0,
    }
  }
  const amount = summarize('paid_amount', '分摊销售额贡献', '元', 2)
  return {
    hasData: channels.length > 0 && (amount.online !== 0 || amount.offline !== 0),
    metrics: [
      summarize('quantity', '销售数量贡献', '件', 0),
      amount,
    ],
  }
})

const monthlyTrend = computed(() => {
  const buckets = new Map()
  analysis.value.trend.forEach((item) => {
    const month = String(item.date || '').slice(0, 7)
    if (!month) return
    const current = buckets.get(month) || { month, paid_amount: 0, orders: 0 }
    current.paid_amount += Number(item.paid_amount || 0)
    current.orders += Number(item.orders || 0)
    buckets.set(month, current)
  })
  return Array.from(buckets.values())
    .map((item) => ({
      ...item,
      paid_amount: Math.round(item.paid_amount * 100) / 100,
      orders: Math.round(item.orders),
    }))
    .sort((a, b) => a.month.localeCompare(b.month))
})

const trendOption = computed(() => ({
  color: [chartTheme.primary, chartTheme.secondary],
  tooltip: {
    trigger: 'axis',
    backgroundColor: '#172033',
    borderWidth: 0,
    padding: [10, 12],
    textStyle: { color: '#ffffff' },
    formatter: (params) => {
      const items = Array.isArray(params) ? params : [params]
      const title = items[0]?.axisValueLabel || ''
      const rows = items.map((item) => {
        const digits = item.seriesName === '订单数' ? 0 : 2
        return `<div style="display:flex;align-items:center;gap:8px;min-width:180px;margin-top:6px;">${item.marker}<span>${item.seriesName}</span><strong style="margin-left:auto;">${formatNumber(item.value, digits)}</strong></div>`
      })
      return `<strong>${title}</strong>${rows.join('')}`
    },
  },
  legend: {
    top: 0,
    right: 4,
    icon: 'roundRect',
    itemWidth: 10,
    itemHeight: 10,
    textStyle: { color: '#64748b' },
  },
  grid: { top: 42, left: 66, right: 62, bottom: 36 },
  xAxis: {
    type: 'category',
    boundaryGap: false,
    data: monthlyTrend.value.map((item) => `${Number(item.month.slice(5))}月`),
    axisTick: { show: false },
    axisLine: { lineStyle: { color: '#dce2ea' } },
    axisLabel: { color: '#64748b', hideOverlap: true },
  },
  yAxis: [
    {
      type: 'value',
      splitNumber: 4,
      splitLine: { lineStyle: { color: '#edf0f4', type: 'dashed' } },
      axisLabel: { color: '#94a3b8' },
    },
    {
      type: 'value',
      splitNumber: 4,
      splitLine: { show: false },
      axisLabel: { color: '#94a3b8' },
    },
  ],
  series: [
    {
      name: '明细分摊销售额',
      type: 'line',
      smooth: false,
      symbol: 'circle',
      symbolSize: 5,
      showSymbol: monthlyTrend.value.length <= 2,
      lineStyle: { width: 3 },
      areaStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(230, 29, 79, 0.18)' },
            { offset: 1, color: 'rgba(230, 29, 79, 0)' },
          ],
        },
      },
      data: monthlyTrend.value.map((item) => item.paid_amount),
    },
    {
      name: '订单数',
      type: 'line',
      yAxisIndex: 1,
      smooth: false,
      showSymbol: monthlyTrend.value.length <= 2,
      lineStyle: { width: 2 },
      data: monthlyTrend.value.map((item) => item.orders),
    },
  ],
}))

function handleRangeChange() {
  dateRange.value = []
}

function handleDateRangeChange(value) {
  if (value?.length === 2) selectedRange.value = 'custom'
}

async function fetchAnalysis() {
  if (!canSearch.value || !brand.value) return
  loading.value = true
  try {
    const params = selectedRange.value === 'custom'
      ? { brand: brand.value, start_date: dateRange.value[0], end_date: dateRange.value[1] }
      : { brand: brand.value, range: selectedRange.value }
    if (query.channelType.length) params.channel_type = query.channelType
    if (query.channelName.length) params.channel_name = query.channelName
    if (query.productTypes.length) params.product_type = query.productTypes
    const result = await getSalesBrandChannelAnalysis(params)
    analysis.value = result.data
    dateRange.value = [analysis.value.start_date, analysis.value.end_date]
  } finally {
    loading.value = false
  }
}

onMounted(fetchAnalysis)

function returnToBrands() {
  const routeQuery = selectedRange.value === 'custom'
    ? { start_date: analysis.value.start_date, end_date: analysis.value.end_date }
    : { range: selectedRange.value }
  if (query.productTypes.length) routeQuery.product_type = query.productTypes
  router.push({ path: '/sales/brand-analysis', query: routeQuery })
}
</script>

<template>
  <div class="page-stack brand-dashboard-shell" v-loading="loading">
    <section class="toolbar-panel sales-filter brand-detail-filter">
      <div class="filter-controls">
        <el-button :icon="'ArrowLeft'" circle title="返回品牌销售分析" @click="returnToBrands" />
        <strong class="brand-detail-name">{{ brand }}</strong>
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
        <el-select
          v-model="query.productTypes"
          class="filter-select multi-filter-select"
          clearable multiple collapse-tags collapse-tags-tooltip
          :max-collapse-tags="1"
          placeholder="正装 / 小样"
        >
          <el-option v-for="item in productTypeOptions" :key="item" :label="item" :value="item">
            <span class="filter-option-content">
              <el-checkbox :model-value="query.productTypes.includes(item)" tabindex="-1" />
              <span>{{ item }}</span>
            </span>
          </el-option>
        </el-select>
        <el-select
          v-model="query.channelType"
          class="filter-select multi-filter-select"
          clearable multiple collapse-tags collapse-tags-tooltip
          :max-collapse-tags="1"
          placeholder="渠道分类"
        >
          <el-option v-for="item in analysis.filter_options.channel_types" :key="item" :label="item" :value="item">
            <span class="filter-option-content">
              <el-checkbox :model-value="query.channelType.includes(item)" tabindex="-1" />
              <span>{{ item }}</span>
            </span>
          </el-option>
        </el-select>
        <el-select
          v-model="query.channelName"
          class="filter-select channel-name-filter"
          clearable filterable multiple collapse-tags collapse-tags-tooltip
          :max-collapse-tags="1"
          placeholder="渠道名称"
        >
          <el-option v-for="item in analysis.filter_options.channel_names" :key="item" :label="item" :value="item">
            <span class="filter-option-content">
              <el-checkbox :model-value="query.channelName.includes(item)" tabindex="-1" />
              <span>{{ item }}</span>
            </span>
          </el-option>
        </el-select>
        <el-button type="primary" :disabled="!canSearch" @click="fetchAnalysis">查询</el-button>
      </div>
    </section>

    <section class="brand-overview-hero" data-testid="brand-hero">
      <div class="hero-title-group">
        <span class="hero-mark" aria-hidden="true"></span>
        <div>
          <p class="hero-eyebrow">SALES PERFORMANCE</p>
          <h1>{{ brand }} 品牌经营看板</h1>
          <p>销售趋势、渠道贡献与商品表现一屏掌握</p>
        </div>
      </div>
      <div class="hero-actions">
        <nav class="hero-pages" aria-label="品牌经营看板分页">
          <button
            v-for="item in pageOptions"
            :key="item.value"
            type="button"
            :class="{ 'is-active': activePage === item.value }"
            :aria-pressed="activePage === item.value"
            @click="activePage = item.value"
          >
            {{ item.label }}
          </button>
        </nav>
        <div class="hero-period">
          <span>{{ analysis.period }}</span>
          <strong>{{ dateRangeLabel }}</strong>
        </div>
      </div>
    </section>

    <section class="brand-kpi-grid" data-testid="brand-kpis">
      <article v-for="item in metrics" :key="item.label" class="brand-kpi-card" :class="{ 'is-accent': item.accent }">
        <span class="kpi-label">
          {{ item.label }}
          <small v-if="item.alias" class="kpi-alias">{{ item.alias }}</small>
        </span>
        <div class="kpi-value"><strong>{{ item.value }}</strong><em>{{ item.unit }}</em></div>
        <span class="kpi-note">{{ item.note }}</span>
      </article>
    </section>

    <section
      v-if="activePage === 'monthly'"
      class="brand-insight-grid"
      :class="{ 'is-trend-only': !salesContribution.hasData }"
      data-testid="trend-panel"
    >
      <article class="panel brand-trend-panel">
        <header>
          <div>
            <p class="section-kicker">经营走势</p>
            <h2>月度明细分摊销售额趋势</h2>
          </div>
          <el-button :icon="'Refresh'" circle title="刷新数据" @click="fetchAnalysis" />
        </header>
        <v-chart class="brand-trend-chart" :option="trendOption" autoresize />
      </article>

      <article v-if="salesContribution.hasData" class="panel contribution-panel" data-testid="sales-contribution">
        <header>
          <div>
            <p class="section-kicker">结构洞察</p>
            <h2>销售贡献度分析</h2>
          </div>
          <div class="contribution-legend" aria-label="渠道维度图例">
            <span><i class="is-online"></i>线上</span>
            <span><i class="is-offline"></i>线下</span>
          </div>
        </header>
        <div class="comparison-list">
          <div v-for="item in salesContribution.metrics" :key="item.field" class="comparison-item">
            <div class="comparison-title">
              <strong>{{ item.label }}</strong>
              <div class="comparison-percentages">
                <span class="is-online">线上 <strong>{{ formatPercent(item.onlinePercent) }}</strong></span>
                <span class="is-offline">线下 <strong>{{ formatPercent(item.offlinePercent) }}</strong></span>
              </div>
            </div>
            <div class="comparison-bar" :aria-label="`${item.label}线上线下占比`">
              <i class="is-online" :style="{ width: progressWidth(item.onlinePercent) }"></i>
              <i class="is-offline" :style="{ width: progressWidth(item.offlinePercent) }"></i>
            </div>
            <div class="comparison-values">
              <span>
                <i class="is-online"></i>
                <em>线上</em>
                <span class="metric-value">{{ formatNumber(item.online, item.digits) }} {{ item.unit }}</span>
              </span>
              <span>
                <i class="is-offline"></i>
                <em>线下</em>
                <span class="metric-value">{{ formatNumber(item.offline, item.digits) }} {{ item.unit }}</span>
              </span>
            </div>
          </div>
        </div>
      </article>
    </section>

    <section v-else-if="activePage === 'channel'" class="channel-efficiency-section" data-testid="channel-efficiency">
      <div class="section-heading">
        <div>
          <p class="section-kicker">渠道效率</p>
          <h2>线上与线下渠道表现</h2>
        </div>
        <span>按明细分摊销售额排序</span>
      </div>
      <div class="channel-efficiency-grid">
        <article class="panel efficiency-card">
          <header>
            <div>
              <h2>线上 TOP 渠道</h2>
              <p>已配置线上平台的有效销售渠道</p>
            </div>
            <strong class="share-total">{{ formatPercent(onlineShare) }}</strong>
          </header>
          <div v-if="onlineChannels.length" class="ranked-channel-list">
            <div v-for="(item, index) in onlineChannels" :key="item.channel_name" class="ranked-channel-item">
              <span class="channel-rank">{{ index + 1 }}</span>
              <div class="channel-main">
                <strong>{{ displayPlatform(item.platform) }}</strong>
                <span>{{ item.channel_name }}</span>
              </div>
              <div class="channel-result">
                <strong>{{ formatPercent(item.share) }}</strong>
                <span>¥ {{ formatNumber(item.paid_amount, 2) }}</span>
              </div>
            </div>
          </div>
          <el-empty v-else description="暂无线上渠道数据" :image-size="76" />
        </article>

        <article class="panel efficiency-card">
          <header>
            <div>
              <h2>线下核心渠道</h2>
            </div>
            <strong class="share-total">{{ formatPercent(offlineShare) }}</strong>
          </header>
          <div v-if="offlineChannels.length" class="offline-channel-list">
            <div v-for="item in offlineChannels" :key="item.channel_name" class="offline-channel-item">
              <div class="contribution-meta">
                <strong>{{ item.channel_name }}</strong>
                <span>{{ formatPercent(item.share) }}</span>
              </div>
              <div class="progress-track"><i :style="{ width: progressWidth(item.share) }"></i></div>
              <div class="contribution-detail">
                <span>{{ item.channel_type || '未设置' }}</span>
                <span>¥ {{ formatNumber(item.paid_amount, 2) }}</span>
              </div>
            </div>
          </div>
          <el-empty v-else description="暂无线下渠道数据" :image-size="76" />
        </article>
      </div>
    </section>

    <template v-else>
      <div class="section-heading detail-heading">
        <div>
          <p class="section-kicker">数据明细</p>
          <h2>多维销售明细</h2>
        </div>
        <span>点击列头可升降序排序</span>
      </div>

      <div class="content-grid detail-summary-grid">
      <section class="panel">
        <header><h2>渠道分类表现<span class="panel-source">（渠道列表 + 销售单明细账）</span></h2></header>
        <el-table :data="analysis.channel_types" height="300">
          <el-table-column prop="channel_type" label="渠道分类" min-width="150" sortable />
          <el-table-column prop="active_channels" label="有销售渠道" width="132" sortable />
          <el-table-column prop="orders" label="订单数" width="110" sortable><template #default="{ row }">{{ formatNumber(row.orders) }}</template></el-table-column>
          <el-table-column prop="paid_amount" label="分摊销售额" width="150" sortable><template #default="{ row }">{{ formatNumber(row.paid_amount, 2) }}</template></el-table-column>
          <el-table-column prop="share" label="占比" width="90" sortable><template #default="{ row }">{{ formatPercent(row.share) }}</template></el-table-column>
        </el-table>
      </section>

      <section class="panel">
        <header><h2>线上平台表现<span class="panel-source">（渠道列表 + 销售单明细账）</span></h2></header>
        <el-table :data="analysis.platforms" height="300">
          <el-table-column prop="platform" label="线上平台" min-width="150" sortable />
          <el-table-column prop="active_channels" label="有销售渠道" width="132" sortable />
          <el-table-column prop="orders" label="订单数" width="110" sortable><template #default="{ row }">{{ formatNumber(row.orders) }}</template></el-table-column>
          <el-table-column prop="paid_amount" label="分摊销售额" width="150" sortable><template #default="{ row }">{{ formatNumber(row.paid_amount, 2) }}</template></el-table-column>
          <el-table-column prop="share" label="占比" width="90" sortable><template #default="{ row }">{{ formatPercent(row.share) }}</template></el-table-column>
        </el-table>
      </section>
      </div>

      <section class="panel">
      <header><h2>渠道名称表现<span class="panel-source">（渠道列表 + 销售单明细账）</span></h2></header>
      <el-table :data="analysis.channels" height="520">
        <el-table-column prop="channel_name" label="渠道名称" min-width="220" show-overflow-tooltip sortable>
          <template #default="{ row }"><div class="channel-cell"><strong>{{ row.channel_name }}</strong><span><i :style="{ width: progressWidth(row.share) }"></i></span></div></template>
        </el-table-column>
        <el-table-column prop="channel_type" label="渠道分类" width="150" sortable />
        <el-table-column prop="platform" label="线上平台" width="140" sortable />
        <el-table-column prop="owner" label="负责人" width="110" sortable />
        <el-table-column prop="detail_rows" label="明细行数" width="110" sortable><template #default="{ row }">{{ formatNumber(row.detail_rows) }}</template></el-table-column>
        <el-table-column prop="orders" label="订单数" width="110" sortable><template #default="{ row }">{{ formatNumber(row.orders) }}</template></el-table-column>
        <el-table-column prop="quantity" label="销售数量" width="120" sortable><template #default="{ row }">{{ formatNumber(row.quantity) }}</template></el-table-column>
        <el-table-column prop="paid_amount" label="分摊销售额" width="160" sortable><template #default="{ row }">{{ formatNumber(row.paid_amount, 2) }}</template></el-table-column>
        <el-table-column prop="share" label="占比" width="100" sortable><template #default="{ row }">{{ formatPercent(row.share) }}</template></el-table-column>
        <el-table-column prop="avg_order_amount" label="客单价" width="130" sortable><template #default="{ row }">{{ formatNumber(row.avg_order_amount, 2) }}</template></el-table-column>
      </el-table>
      </section>

      <section class="panel">
      <header><h2>销售人员正装与小样销售情况<span class="panel-source">（销售单明细账 + 渠道负责人）</span></h2></header>
      <el-table :data="analysis.salesperson_product_types" height="420">
        <el-table-column prop="salesperson" label="销售人员" min-width="140" sortable />
        <el-table-column prop="regular_quantity" label="正装数量" width="125" sortable><template #default="{ row }">{{ formatNumber(row.regular_quantity) }}</template></el-table-column>
        <el-table-column prop="regular_paid_amount" label="正装分摊金额" width="160" sortable><template #default="{ row }">{{ formatNumber(row.regular_paid_amount, 2) }}</template></el-table-column>
        <el-table-column prop="sample_quantity" label="小样数量" width="125" sortable><template #default="{ row }">{{ formatNumber(row.sample_quantity) }}</template></el-table-column>
        <el-table-column prop="sample_paid_amount" label="小样分摊金额" width="160" sortable><template #default="{ row }">{{ formatNumber(row.sample_paid_amount, 2) }}</template></el-table-column>
        <el-table-column prop="total_quantity" label="合计数量" width="130" sortable><template #default="{ row }">{{ formatNumber(row.total_quantity) }}</template></el-table-column>
        <el-table-column prop="total_paid_amount" label="分摊金额合计" width="170" sortable><template #default="{ row }">{{ formatNumber(row.total_paid_amount, 2) }}</template></el-table-column>
      </el-table>
      </section>

      <section class="panel">
      <header><h2>{{ brand }} 商品排行<span class="panel-source">（销售单明细账）</span></h2><ExportExcelButton title="品牌商品排行" :rows="analysis.products" :columns="productExportColumns" :total="analysis.products.length" :filters="{ 品牌: brand, 开始日期: analysis.start_date, 结束日期: analysis.end_date }" /></header>
      <el-table :data="analysis.products" height="460">
        <el-table-column prop="rank" label="排名" width="74" align="center"><template #default="{ row }"><span class="rank-badge">{{ row.rank }}</span></template></el-table-column>
        <el-table-column prop="product" label="商品名称" min-width="300" show-overflow-tooltip sortable />
        <el-table-column prop="orders" label="订单数" width="120" sortable><template #default="{ row }">{{ formatNumber(row.orders) }}</template></el-table-column>
        <el-table-column prop="quantity" label="销售数量" width="130" sortable><template #default="{ row }">{{ formatNumber(row.quantity) }}</template></el-table-column>
        <el-table-column prop="paid_amount" label="分摊销售额" width="160" sortable><template #default="{ row }">{{ formatNumber(row.paid_amount, 2) }}</template></el-table-column>
        <el-table-column prop="share" label="占比" width="110" sortable><template #default="{ row }">{{ formatPercent(row.share) }}</template></el-table-column>
      </el-table>
      </section>
    </template>
  </div>
</template>

<style scoped>
.brand-dashboard-shell {
  --brand-primary: var(--theme-primary);
  --brand-primary-dark: var(--theme-strong);
  --brand-secondary: var(--theme-secondary);
  --brand-soft: var(--theme-soft);
  --ink: #172033;
  --muted: #64748b;
  --line: #e7ebf0;
  --el-color-primary: var(--theme-primary);
  --el-color-primary-light-3: color-mix(in srgb, var(--theme-primary) 70%, white);
  --el-color-primary-light-5: color-mix(in srgb, var(--theme-primary) 50%, white);
  --el-color-primary-light-7: color-mix(in srgb, var(--theme-primary) 30%, white);
  --el-color-primary-light-9: var(--theme-soft);
  --el-color-primary-dark-2: var(--theme-strong);
}

.brand-overview-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  min-height: 132px;
  padding: 24px 28px;
  background: linear-gradient(110deg, #ffffff 0%, #ffffff 64%, var(--theme-soft) 100%);
  border: 1px solid var(--line);
  border-top: 4px solid var(--brand-primary);
  border-radius: 8px;
  box-shadow: 0 4px 16px rgba(23, 32, 51, 0.04);
}

.hero-title-group { display: flex; align-items: center; gap: 18px; }
.hero-mark { width: 6px; height: 62px; flex: 0 0 auto; background: var(--brand-primary); }
.hero-eyebrow, .section-kicker { margin: 0 0 6px; color: var(--brand-primary); font-size: 11px; font-weight: 750; letter-spacing: .12em; }
.hero-title-group h1 { margin: 0; color: #111827; font-size: clamp(24px, 2vw, 34px); line-height: 1.2; letter-spacing: -.03em; }
.hero-title-group p:last-child { margin: 8px 0 0; color: var(--muted); font-size: 14px; }
.hero-actions { display: flex; min-width: min(100%, 460px); align-items: flex-end; flex-direction: column; gap: 14px; }
.hero-pages { display: inline-flex; padding: 4px; background: #f1f4f8; border-radius: 8px; }
.hero-pages button { min-height: 36px; padding: 0 18px; color: #64748b; background: transparent; border: 0; border-radius: 6px; font: inherit; font-size: 13px; font-weight: 700; white-space: nowrap; cursor: pointer; transition: color .16s ease, background-color .16s ease, box-shadow .16s ease; }
.hero-pages button:hover { color: var(--ink); }
.hero-pages button:active { transform: translateY(1px); }
.hero-pages button:focus-visible { outline: 2px solid var(--brand-primary); outline-offset: 2px; }
.hero-pages button.is-active { color: var(--brand-primary); background: #fff; box-shadow: 0 1px 4px rgba(23, 32, 51, .1); }
.hero-period { min-width: 240px; padding: 0 2px; text-align: right; }
.hero-period span { display: block; color: var(--brand-primary); font-size: 13px; font-weight: 700; }
.hero-period strong { display: block; margin-top: 7px; color: var(--ink); font-size: 14px; }

.brand-kpi-grid { display: grid; grid-template-columns: 1.28fr repeat(3, 1fr); gap: 12px; }
.brand-kpi-card { min-width: 0; padding: 20px; background: #fff; border: 1px solid var(--line); border-radius: 8px; box-shadow: 0 3px 12px rgba(23, 32, 51, .035); }
.kpi-label { display: block; color: var(--muted); font-size: 13px; font-weight: 650; }
.kpi-alias { margin-left: 4px; color: #94a3b8; font-size: 11px; font-weight: 500; }
.kpi-value { display: flex; align-items: baseline; gap: 6px; min-width: 0; margin: 12px 0 8px; color: var(--ink); }
.kpi-value strong { overflow: hidden; font-size: clamp(22px, 1.7vw, 30px); line-height: 1; letter-spacing: -.03em; text-overflow: ellipsis; white-space: nowrap; }
.kpi-value em { flex: 0 0 auto; color: var(--muted); font-size: 12px; font-style: normal; }
.kpi-note { color: #94a3b8; font-size: 12px; }
.brand-kpi-card.is-accent { background: linear-gradient(135deg, var(--brand-primary), var(--brand-primary-dark)); border-color: transparent; }
.brand-kpi-card.is-accent :is(.kpi-label, .kpi-value, .kpi-value em, .kpi-note) { color: #fff; }
.brand-kpi-card.is-accent .kpi-alias { color: rgba(255, 255, 255, .66); }
.brand-kpi-card.is-accent .kpi-note { opacity: .72; }

.brand-insight-grid { display: grid; grid-template-columns: minmax(0, 1.7fr) minmax(320px, .72fr); gap: 14px; }
.brand-insight-grid.is-trend-only { grid-template-columns: 1fr; }
.brand-insight-grid .panel, .efficiency-card { overflow: hidden; }
.brand-insight-grid .panel > header, .efficiency-card > header { min-height: 72px; padding: 16px 20px; }
.brand-insight-grid h2, .section-heading h2, .efficiency-card h2 { margin: 0; color: var(--ink); font-size: 17px; }
.brand-trend-chart { width: 100%; height: 360px; }

.contribution-panel > header { align-items: center; }
.contribution-legend { display: flex; align-items: center; gap: 12px; color: #64748b; font-size: 11px; }
.contribution-legend span, .comparison-values span { display: flex; align-items: center; gap: 6px; }
.contribution-legend i, .comparison-values i { width: 8px; height: 8px; flex: 0 0 auto; border-radius: 2px; }
.contribution-legend i.is-online, .comparison-values i.is-online, .comparison-bar i.is-online { background: var(--brand-primary); }
.contribution-legend i.is-offline, .comparison-values i.is-offline, .comparison-bar i.is-offline { background: var(--brand-secondary); }
.comparison-list { display: grid; gap: 34px; padding: 30px 24px 28px; }
.comparison-item { min-width: 0; }
.comparison-title { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.comparison-title strong { color: var(--ink); font-size: 13px; }
.comparison-percentages { display: flex; align-items: baseline; gap: 10px; white-space: nowrap; }
.comparison-percentages span { color: #475569; font-size: 11px; }
.comparison-percentages strong { margin-left: 2px; font-size: 14px; font-weight: 800; }
.comparison-percentages .is-online strong { color: var(--brand-primary); }
.comparison-percentages .is-offline strong { color: var(--theme-secondary); }
.comparison-bar { display: flex; width: 100%; height: 10px; margin: 13px 0 12px; overflow: hidden; background: #eef1f5; border-radius: 3px; }
.comparison-bar i { display: block; height: 100%; }
.comparison-values { display: grid; grid-template-columns: 1fr; gap: 6px; }
.comparison-values span { min-width: 0; }
.comparison-values em { color: #475569; font-size: 11px; font-style: normal; white-space: nowrap; }
.comparison-values .metric-value { margin-left: auto; color: #475569; font-size: 11px; font-weight: 500; white-space: nowrap; }
.offline-channel-item { min-width: 0; }
.contribution-meta, .contribution-detail { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.contribution-meta strong { overflow: hidden; color: var(--ink); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.contribution-meta span { color: var(--brand-primary); font-size: 13px; font-weight: 750; }
.progress-track { height: 6px; margin: 9px 0 7px; overflow: hidden; background: #eef1f5; border-radius: 2px; }
.progress-track i { display: block; height: 100%; background: linear-gradient(90deg, var(--brand-primary), var(--brand-secondary)); border-radius: inherit; }
.contribution-detail { color: #94a3b8; font-size: 11px; }

.channel-efficiency-section { padding: 4px 0 0; }
.section-heading { display: flex; align-items: end; justify-content: space-between; gap: 18px; margin-bottom: 14px; padding: 0 4px; }
.section-heading > span { color: #94a3b8; font-size: 12px; }
.channel-efficiency-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.efficiency-card > header { display: flex; justify-content: space-between; align-items: center; }
.efficiency-card header p { margin: 6px 0 0; color: #94a3b8; font-size: 12px; }
.share-total { color: var(--brand-primary); font-size: 20px; }
.ranked-channel-list { padding: 4px 20px 18px; }
.ranked-channel-item { display: grid; grid-template-columns: 32px minmax(0, 1fr) auto; align-items: center; gap: 12px; padding: 14px 0; border-bottom: 1px solid #eef1f4; }
.ranked-channel-item:last-child { border-bottom: 0; }
.channel-rank { display: grid; width: 30px; height: 30px; place-items: center; color: var(--brand-primary); background: var(--brand-soft); border-radius: 50%; font-size: 12px; font-weight: 800; }
.ranked-channel-item:nth-child(n+4) .channel-rank { color: #64748b; background: #f1f4f8; }
.channel-main, .channel-result { min-width: 0; }
.channel-main strong, .channel-main span, .channel-result strong, .channel-result span { display: block; }
.channel-main strong { overflow: hidden; color: var(--ink); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.channel-main span, .channel-result span { margin-top: 5px; color: #94a3b8; font-size: 11px; }
.channel-result { text-align: right; }
.channel-result strong { color: var(--ink); font-size: 14px; }
.offline-channel-list { display: grid; gap: 18px; padding: 14px 20px 23px; }
.detail-heading { margin-top: 8px; }
.brand-dashboard-shell :deep(.channel-cell i) { background: var(--brand-primary); }
.brand-dashboard-shell :deep(.rank-badge) { color: var(--brand-primary-dark); background: var(--brand-soft); }

@media (max-width: 1280px) {
  .brand-kpi-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
}

@media (max-width: 1100px) {
  .brand-insight-grid { grid-template-columns: 1fr; }
}

@media (max-width: 900px) {
  .brand-overview-hero { align-items: flex-start; flex-direction: column; }
  .hero-actions { width: 100%; min-width: 0; align-items: stretch; }
  .hero-pages { align-self: flex-start; }
  .hero-period { width: 100%; min-width: 0; padding: 12px 0 0; border-top: 1px solid #f5ccd6; text-align: left; }
  .brand-kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .channel-efficiency-grid { grid-template-columns: 1fr; }
}

@media (max-width: 640px) {
  .brand-overview-hero { padding: 20px; }
  .hero-mark { height: 52px; }
  .hero-pages { display: grid; width: 100%; grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .hero-pages button { padding: 0 8px; }
  .brand-kpi-grid { grid-template-columns: 1fr; }
  .section-heading { align-items: flex-start; flex-direction: column; }
}
</style>
