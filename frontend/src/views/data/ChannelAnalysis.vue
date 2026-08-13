<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { getSalesChannelAnalysis, getSalesChannelCustomerAnalysis } from '../../api/sales'
import ExportExcelButton from '../../components/common/ExportExcelButton.vue'
import { getSavedTheme } from '../../utils/theme'

use([CanvasRenderer, LineChart, GridComponent, LegendComponent, TooltipComponent])

const chartTheme = getSavedTheme()

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const pageOptions = [
  { label: '月度渠道信息', value: 'monthly' },
  { label: '渠道表现', value: 'channel' },
  { label: '数据明细', value: 'detail' },
]
const supportedViews = pageOptions.map((item) => item.value)
const supportedRanges = ['last_30', 'this_month', 'this_year']
const activePage = ref(supportedViews.includes(String(route.query.view)) ? String(route.query.view) : 'monthly')
const selectedRange = ref(
  route.query.start_date && route.query.end_date
    ? 'custom'
    : supportedRanges.includes(String(route.query.range)) ? String(route.query.range) : 'this_year',
)
const dateRange = ref(
  route.query.start_date && route.query.end_date
    ? [String(route.query.start_date), String(route.query.end_date)]
    : [],
)
const rangeOptions = [
  { label: '近30天', value: 'last_30' },
  { label: '本月', value: 'this_month' },
  { label: '本年', value: 'this_year' },
]
const query = reactive({
  keyword: String(route.query.keyword || ''),
  channelType: String(route.query.channel_type || ''),
  platform: String(route.query.platform || ''),
  authorized: String(route.query.authorized || ''),
})
const analysis = ref({
  period: '本年',
  start_date: '',
  end_date: '',
  summary: { paid_amount: 0, orders: 0, quantity: 0 },
  channel_summary: {
    total_channels: 0,
    active_channels: 0,
    authorized_channels: 0,
    unmatched_sales_channels: 0,
  },
  trend: [],
  type_summary: [],
  platform_summary: [],
  rows: [],
  unmatched_channels: [],
  filter_options: { channel_types: [], platforms: [] },
})
const channelExportColumns = [{ key: 'channel_code', label: '编号' }, { key: 'channel_name', label: '渠道名称' }, { key: 'category', label: '渠道分类' }, { key: 'platform', label: '平台归属' }, { key: 'owner', label: '负责人' }, { key: 'orders', label: '订单数', kind: 'integer' }, { key: 'quantity', label: '销售数量', kind: 'integer' }, { key: 'paid_amount', label: '分摊销售额', kind: 'number' }, { key: 'share', label: '销售占比', kind: 'percent' }]
const customerDrawerVisible = ref(false)
const customerLoading = ref(false)
const selectedOfflineChannel = ref(null)
const customerKeyword = ref('')
const customerPage = ref(1)
const customerPageSize = ref(20)
const customerAnalysis = ref({
  channel_name: '',
  owner: '-',
  start_date: '',
  end_date: '',
  summary: { customers: 0, orders: 0, quantity: 0, paid_amount: 0 },
  pagination: { page: 1, page_size: 20, total: 0 },
  rows: [],
})

function formatNumber(value, digits = 0) {
  return Number(value || 0).toLocaleString('zh-CN', {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  })
}

function formatDate(value) {
  return value ? String(value).slice(0, 10) : '-'
}

function formatPercent(value) {
  return `${formatNumber(value, 1)}%`
}

function progressWidth(value) {
  return `${Math.min(Math.max(Number(value || 0), 0), 100)}%`
}

function isOnlineChannel(item) {
  if (typeof item.is_online === 'boolean') return item.is_online
  return Boolean(item.platform && item.platform !== '未设置')
}

function displayPlatform(platform) {
  const value = String(platform || '')
  const platformNames = [
    ['天猫', '天猫'], ['淘宝', '淘宝'], ['拼多多', '拼多多'], ['得物', '得物'],
    ['京东', '京东'], ['快手', '快手'], ['抖店', '抖音'], ['抖音', '抖音'],
    ['美团', '美团'], ['微信', '微信'], ['SHEIN', 'SHEIN'], ['95分', '95分'],
    ['度小店', '百度'], ['基木鱼', '百度'],
  ]
  return platformNames.find(([keyword]) => value.includes(keyword))?.[1] || value
}

const dateRangeLabel = computed(() => {
  const start = formatDate(analysis.value.start_date)
  const end = formatDate(analysis.value.end_date)
  return start === '-' || end === '-' ? '-' : `${start} 至 ${end}`
})
const canSearch = computed(() => selectedRange.value !== 'custom' || dateRange.value.length === 2)
const salesChannelCounts = computed(() => analysis.value.rows.reduce((result, item) => {
  if (Number(item.orders || 0) === 0 && Number(item.paid_amount || 0) === 0) return result
  const key = isOnlineChannel(item) ? 'online' : 'offline'
  result[key] += 1
  result[`${key}Amount`] += Number(item.paid_amount || 0)
  return result
}, { online: 0, offline: 0, onlineAmount: 0, offlineAmount: 0 }))
const metrics = computed(() => [
  {
    label: '周期明细分摊销售额', alias: '', value: formatNumber(analysis.value.summary.paid_amount, 2),
    unit: '元', note: analysis.value.period, accent: true,
  },
  {
    label: '订单数', value: formatNumber(analysis.value.summary.orders), unit: '单', note: '按订单编号去重',
  },
  {
    label: '销售数量', value: formatNumber(analysis.value.summary.quantity), unit: '件', note: analysis.value.period,
  },
  {
    label: '线上销售渠道', value: formatNumber(salesChannelCounts.value.online), unit: '个',
    note: `销售额占比 ${formatPercent(analysis.value.summary.paid_amount ? salesChannelCounts.value.onlineAmount / analysis.value.summary.paid_amount * 100 : 0)}`,
  },
  {
    label: '线下销售渠道', value: formatNumber(salesChannelCounts.value.offline), unit: '个',
    note: `销售额占比 ${formatPercent(analysis.value.summary.paid_amount ? salesChannelCounts.value.offlineAmount / analysis.value.summary.paid_amount * 100 : 0)}`,
  },
])

const activeChannels = computed(() => analysis.value.rows.filter(
  (item) => Number(item.orders || 0) !== 0 || Number(item.paid_amount || 0) !== 0,
))
const allOnlineChannels = computed(() => activeChannels.value
  .filter(isOnlineChannel)
  .sort((a, b) => Number(b.paid_amount || 0) - Number(a.paid_amount || 0)))
const allOfflineChannels = computed(() => activeChannels.value
  .filter((item) => !isOnlineChannel(item))
  .sort((a, b) => Number(b.paid_amount || 0) - Number(a.paid_amount || 0)))
const onlineChannels = computed(() => allOnlineChannels.value.slice(0, 5))
const offlineChannels = computed(() => allOfflineChannels.value.slice(0, 6))
const onlineShare = computed(() => allOnlineChannels.value.reduce((sum, item) => sum + Number(item.share || 0), 0))
const offlineShare = computed(() => allOfflineChannels.value.reduce((sum, item) => sum + Number(item.share || 0), 0))
const onlinePlatforms = computed(() => analysis.value.platform_summary.filter((item) => item.platform !== '未设置'))
const channelDirectionSummary = computed(() => [
  { label: '线上渠道', rows: allOnlineChannels.value },
  { label: '线下渠道', rows: allOfflineChannels.value },
].map((group) => ({
  channel_kind: group.label,
  channels: group.rows.length,
  orders: group.rows.reduce((sum, item) => sum + Number(item.orders || 0), 0),
  paid_amount: group.rows.reduce((sum, item) => sum + Number(item.paid_amount || 0), 0),
  share: group.rows.reduce((sum, item) => sum + Number(item.share || 0), 0),
})))

const salesContribution = computed(() => {
  const channels = activeChannels.value.filter((item) => Number(item.paid_amount || 0) !== 0)
  const summarize = (field, label, unit, digits) => {
    const online = channels.filter(isOnlineChannel).reduce((sum, item) => sum + Number(item[field] || 0), 0)
    const offline = channels.filter((item) => !isOnlineChannel(item)).reduce((sum, item) => sum + Number(item[field] || 0), 0)
    const total = Math.max(online, 0) + Math.max(offline, 0)
    return {
      field, label, unit, digits, online, offline,
      onlinePercent: total ? Math.max(online, 0) / total * 100 : 0,
      offlinePercent: total ? Math.max(offline, 0) / total * 100 : 0,
    }
  }
  const amount = summarize('paid_amount', '分摊销售额贡献', '元', 2)
  return {
    hasData: channels.length > 0 && (amount.online !== 0 || amount.offline !== 0),
    metrics: [summarize('quantity', '销售数量贡献', '件', 0), amount],
  }
})

const trendOption = computed(() => ({
  color: [chartTheme.primary, chartTheme.secondary],
  tooltip: {
    trigger: 'axis',
    backgroundColor: '#172033', borderWidth: 0, padding: [10, 12],
    textStyle: { color: '#ffffff' },
    formatter: (params) => {
      const items = Array.isArray(params) ? params : [params]
      const rows = items.map((item) => {
        const digits = item.seriesName === '订单数' ? 0 : 2
        return `<div style="display:flex;align-items:center;gap:8px;min-width:180px;margin-top:6px;">${item.marker}<span>${item.seriesName}</span><strong style="margin-left:auto;">${formatNumber(item.value, digits)}</strong></div>`
      })
      return `<strong>${items[0]?.axisValueLabel || ''}</strong>${rows.join('')}`
    },
  },
  legend: {
    top: 0, right: 4, icon: 'roundRect', itemWidth: 10, itemHeight: 10,
    textStyle: { color: '#64748b' },
  },
  grid: { top: 42, left: 68, right: 62, bottom: 36 },
  xAxis: {
    type: 'category', boundaryGap: false,
    data: analysis.value.trend.map((item) => `${Number(String(item.month).slice(5, 7))}月`),
    axisTick: { show: false }, axisLine: { lineStyle: { color: '#dce2ea' } },
    axisLabel: { color: '#64748b', hideOverlap: true },
  },
  yAxis: [
    {
      type: 'value', splitNumber: 4,
      splitLine: { lineStyle: { color: '#edf0f4', type: 'dashed' } },
      axisLabel: { color: '#94a3b8' },
    },
    { type: 'value', splitNumber: 4, splitLine: { show: false }, axisLabel: { color: '#94a3b8' } },
  ],
  series: [
    {
      name: '明细分摊销售额', type: 'line', smooth: false, symbol: 'circle', symbolSize: 5,
      showSymbol: analysis.value.trend.length <= 2, lineStyle: { width: 3 },
      areaStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(79, 127, 45, 0.20)' },
            { offset: 1, color: 'rgba(79, 127, 45, 0)' },
          ],
        },
      },
      data: analysis.value.trend.map((item) => item.paid_amount),
    },
    {
      name: '订单数', type: 'line', yAxisIndex: 1, smooth: false,
      showSymbol: analysis.value.trend.length <= 2, lineStyle: { width: 2 },
      data: analysis.value.trend.map((item) => item.orders),
    },
  ],
}))

function handleRangeChange() {
  dateRange.value = []
}

function handleDateRangeChange(value) {
  if (value?.length === 2) selectedRange.value = 'custom'
}

function switchPage(value) {
  activePage.value = value
  router.replace({ query: { ...route.query, view: value } })
}

function buildParams() {
  const params = selectedRange.value === 'custom'
    ? { start_date: dateRange.value[0], end_date: dateRange.value[1] }
    : { range: selectedRange.value }
  if (query.keyword.trim()) params.keyword = query.keyword.trim()
  if (query.channelType) params.channel_type = query.channelType
  if (query.platform) params.platform = query.platform
  if (query.authorized !== '') params.authorized = query.authorized
  return params
}

async function fetchAnalysis() {
  if (!canSearch.value) return
  loading.value = true
  try {
    const params = buildParams()
    const result = await getSalesChannelAnalysis(params)
    analysis.value = result.data
    dateRange.value = [analysis.value.start_date, analysis.value.end_date]
    const nextQuery = { view: activePage.value, ...params }
    router.replace({ query: nextQuery })
  } finally {
    loading.value = false
  }
}

async function fetchCustomerAnalysis() {
  if (!selectedOfflineChannel.value) return
  customerLoading.value = true
  try {
    const result = await getSalesChannelCustomerAnalysis({
      channel_name: selectedOfflineChannel.value.channel_name,
      start_date: analysis.value.start_date,
      end_date: analysis.value.end_date,
      keyword: customerKeyword.value.trim() || undefined,
      page: customerPage.value,
      page_size: customerPageSize.value,
    })
    customerAnalysis.value = result.data
  } finally {
    customerLoading.value = false
  }
}

function openCustomerDrilldown(row) {
  selectedOfflineChannel.value = row
  customerKeyword.value = ''
  customerPage.value = 1
  customerPageSize.value = 20
  customerDrawerVisible.value = true
  fetchCustomerAnalysis()
}

function searchCustomers() {
  customerPage.value = 1
  fetchCustomerAnalysis()
}

function changeCustomerPage(page) {
  customerPage.value = page
  fetchCustomerAnalysis()
}

function changeCustomerPageSize(size) {
  customerPageSize.value = size
  customerPage.value = 1
  fetchCustomerAnalysis()
}

onMounted(fetchAnalysis)
</script>

<template>
  <div class="page-stack channel-dashboard-shell" v-loading="loading">
    <section class="toolbar-panel sales-filter channel-filter-bar">
      <div class="filter-controls">
        <el-segmented v-model="selectedRange" :options="rangeOptions" @change="handleRangeChange" />
        <div class="channel-date-filter-wrap">
          <el-date-picker
            v-model="dateRange"
            class="channel-date-filter"
            type="daterange"
            range-separator="至"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            value-format="YYYY-MM-DD"
            :unlink-panels="true"
            @change="handleDateRangeChange"
          />
        </div>
        <el-input v-model="query.keyword" class="filter-input" clearable placeholder="渠道 / 负责人" />
        <el-select v-model="query.channelType" class="filter-select" clearable placeholder="渠道类型">
          <el-option v-for="item in analysis.filter_options.channel_types" :key="item" :label="item" :value="item" />
        </el-select>
        <el-select v-model="query.platform" class="filter-select" clearable placeholder="线上平台">
          <el-option v-for="item in analysis.filter_options.platforms" :key="item" :label="item" :value="item" />
        </el-select>
        <el-select v-model="query.authorized" class="filter-select" clearable placeholder="授权状态">
          <el-option label="已授权" value="1" />
          <el-option label="未授权" value="0" />
        </el-select>
        <el-button type="primary" :disabled="!canSearch" @click="fetchAnalysis">查询</el-button>
      </div>
    </section>

    <section class="channel-overview-hero" data-testid="channel-hero">
      <div class="hero-title-group">
        <span class="hero-mark" aria-hidden="true"></span>
        <div>
          <p class="hero-eyebrow">CHANNEL PERFORMANCE</p>
          <h1>渠道经营看板</h1>
          <p>月度走势、线上线下贡献与渠道明细集中查看</p>
        </div>
      </div>
      <div class="hero-actions">
        <nav class="hero-pages" aria-label="渠道经营看板分页">
          <button
            v-for="item in pageOptions"
            :key="item.value"
            type="button"
            :class="{ 'is-active': activePage === item.value }"
            :aria-pressed="activePage === item.value"
            @click="switchPage(item.value)"
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

    <section class="channel-kpi-grid" data-testid="channel-kpis">
      <article v-for="item in metrics" :key="item.label" class="channel-kpi-card" :class="{ 'is-accent': item.accent }">
        <span class="kpi-label">{{ item.label }} <small v-if="item.alias" class="kpi-alias">{{ item.alias }}</small></span>
        <div class="kpi-value"><strong>{{ item.value }}</strong><em>{{ item.unit }}</em></div>
        <span class="kpi-note">{{ item.note }}</span>
      </article>
    </section>

    <section
      v-if="activePage === 'monthly'"
      class="channel-insight-grid"
      :class="{ 'is-trend-only': !salesContribution.hasData }"
      data-testid="channel-monthly"
    >
      <article class="panel channel-trend-panel">
        <header>
          <div><p class="section-kicker">月度渠道信息</p><h2>月度明细分摊销售额与订单趋势</h2></div>
          <el-button :icon="'Refresh'" circle title="刷新数据" @click="fetchAnalysis" />
        </header>
        <v-chart v-if="analysis.trend.length" class="channel-trend-chart" :option="trendOption" autoresize />
        <el-empty v-else description="当前筛选暂无月度趋势" :image-size="88" />
      </article>

      <article v-if="salesContribution.hasData" class="panel contribution-panel">
        <header>
          <div><p class="section-kicker">结构洞察</p><h2>线上与线下贡献</h2></div>
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
              <span><i class="is-online"></i><em>线上</em><b>{{ formatNumber(item.online, item.digits) }} {{ item.unit }}</b></span>
              <span><i class="is-offline"></i><em>线下</em><b>{{ formatNumber(item.offline, item.digits) }} {{ item.unit }}</b></span>
            </div>
          </div>
        </div>
      </article>
    </section>

    <section v-else-if="activePage === 'channel'" class="channel-efficiency-section" data-testid="channel-efficiency">
      <div class="section-heading">
        <div><p class="section-kicker">渠道表现</p><h2>线上与线下渠道表现</h2></div>
        <span>按明细分摊销售额排序</span>
      </div>
      <div class="channel-efficiency-grid">
        <article class="panel efficiency-card">
          <header>
            <div><h2>线上 TOP 渠道</h2><p>按业务渠道分类口径统计</p></div>
            <strong class="share-total">{{ formatPercent(onlineShare) }}</strong>
          </header>
          <div v-if="onlineChannels.length" class="ranked-channel-list">
            <div v-for="(item, index) in onlineChannels" :key="item.channel_name" class="ranked-channel-item">
              <span class="channel-rank">{{ index + 1 }}</span>
              <div class="channel-main"><strong>{{ displayPlatform(item.platform === '未设置' ? '线上渠道' : item.platform) }}</strong><span>{{ item.channel_name }}</span></div>
              <div class="channel-result"><strong>{{ formatPercent(item.share) }}</strong><span>¥ {{ formatNumber(item.paid_amount, 2) }}</span></div>
            </div>
          </div>
          <el-empty v-else description="暂无线上渠道数据" :image-size="76" />
        </article>

        <article class="panel efficiency-card">
          <header>
            <div><h2>线下核心渠道</h2><p>按业务渠道分类口径统计</p></div>
            <strong class="share-total">{{ formatPercent(offlineShare) }}</strong>
          </header>
          <div v-if="offlineChannels.length" class="offline-channel-list">
            <div v-for="item in offlineChannels" :key="item.channel_name" class="offline-channel-item">
              <div class="contribution-meta"><strong>{{ item.channel_name }}</strong><span>{{ formatPercent(item.share) }}</span></div>
              <div class="progress-track"><i :style="{ width: progressWidth(item.share) }"></i></div>
              <div class="contribution-detail"><span>{{ item.category || '未分类' }}</span><span>¥ {{ formatNumber(item.paid_amount, 2) }}</span></div>
            </div>
          </div>
          <el-empty v-else description="暂无线下渠道数据" :image-size="76" />
        </article>
      </div>
    </section>

    <template v-else>
      <div class="section-heading detail-heading">
        <div><p class="section-kicker">数据明细</p><h2>渠道多维明细</h2></div>
        <span>点击列头可升降序排序</span>
      </div>

      <div class="content-grid detail-summary-grid">
        <section class="panel">
          <header><h2>线上与线下渠道表现<span class="panel-source">（渠道列表 + 销售单明细账）</span></h2></header>
          <el-table :data="channelDirectionSummary" height="300">
            <el-table-column prop="channel_kind" label="渠道归属" min-width="150" sortable />
            <el-table-column prop="channels" label="渠道数" width="120" sortable />
            <el-table-column prop="orders" label="订单数" width="110" sortable><template #default="{ row }">{{ formatNumber(row.orders) }}</template></el-table-column>
            <el-table-column prop="paid_amount" label="分摊销售额" width="150" sortable><template #default="{ row }">{{ formatNumber(row.paid_amount, 2) }}</template></el-table-column>
            <el-table-column prop="share" label="占比" width="90" sortable><template #default="{ row }">{{ formatPercent(row.share) }}</template></el-table-column>
          </el-table>
        </section>

        <section class="panel">
          <header><h2>线上平台表现<span class="panel-source">（不含线下渠道）</span></h2></header>
          <el-table :data="onlinePlatforms" height="300">
            <el-table-column prop="platform" label="线上平台" min-width="150" sortable />
            <el-table-column prop="channels" label="渠道数" width="120" sortable />
            <el-table-column prop="orders" label="订单数" width="110" sortable><template #default="{ row }">{{ formatNumber(row.orders) }}</template></el-table-column>
            <el-table-column prop="paid_amount" label="分摊销售额" width="150" sortable><template #default="{ row }">{{ formatNumber(row.paid_amount, 2) }}</template></el-table-column>
            <el-table-column prop="share" label="占比" width="90" sortable><template #default="{ row }">{{ formatPercent(row.share) }}</template></el-table-column>
          </el-table>
        </section>
      </div>

      <section class="panel">
        <header><h2>渠道清单<span class="panel-source">（销售单明细账 + 渠道列表）</span></h2><div class="header-actions"><ExportExcelButton title="渠道分析" :rows="analysis.rows" :columns="channelExportColumns" :total="analysis.rows.length" /><el-button :icon="'Refresh'" circle @click="fetchAnalysis" /></div></header>
        <el-table :data="analysis.rows" height="520">
          <el-table-column prop="channel_code" label="编号" width="90" sortable />
          <el-table-column prop="channel_name" label="渠道名称" min-width="220" show-overflow-tooltip sortable>
            <template #default="{ row }"><div class="channel-cell"><strong>{{ row.channel_name }}</strong><span><i :style="{ width: progressWidth(row.share) }"></i></span></div></template>
          </el-table-column>
          <el-table-column prop="category" label="渠道分类" width="150" sortable />
          <el-table-column prop="platform" label="平台归属" width="140" sortable>
            <template #default="{ row }">{{ isOnlineChannel(row) ? (row.platform === '未设置' ? '线上' : row.platform) : '线下' }}</template>
          </el-table-column>
          <el-table-column prop="owner" label="负责人" width="110" sortable />
          <el-table-column prop="authorized" label="授权" width="90" sortable>
            <template #default="{ row }"><el-tag :type="row.authorized ? 'success' : 'info'" effect="plain">{{ row.authorized ? '已授权' : '未授权' }}</el-tag></template>
          </el-table-column>
          <el-table-column prop="orders" label="订单数" width="110" sortable><template #default="{ row }">{{ formatNumber(row.orders) }}</template></el-table-column>
          <el-table-column prop="quantity" label="销售数量" width="120" sortable><template #default="{ row }">{{ formatNumber(row.quantity) }}</template></el-table-column>
          <el-table-column prop="paid_amount" label="分摊销售额" width="150" sortable><template #default="{ row }">{{ formatNumber(row.paid_amount, 2) }}</template></el-table-column>
          <el-table-column prop="share" label="销售占比" width="110" sortable><template #default="{ row }">{{ formatPercent(row.share) }}</template></el-table-column>
          <el-table-column prop="avg_order_amount" label="客单价" width="130" sortable><template #default="{ row }">{{ formatNumber(row.avg_order_amount, 2) }}</template></el-table-column>
        </el-table>
      </section>

      <section class="panel">
        <header><h2>线下渠道表现<span class="panel-source">（销售单明细账 + 渠道列表，可下钻客户）</span></h2></header>
        <el-table :data="allOfflineChannels" height="360" @row-dblclick="openCustomerDrilldown">
          <el-table-column prop="channel_name" label="线下渠道" min-width="240" show-overflow-tooltip sortable />
          <el-table-column prop="category" label="渠道分类" width="150" sortable />
          <el-table-column prop="orders" label="订单数" width="130" sortable><template #default="{ row }">{{ formatNumber(row.orders) }}</template></el-table-column>
          <el-table-column prop="quantity" label="销售数量" width="130" sortable><template #default="{ row }">{{ formatNumber(row.quantity) }}</template></el-table-column>
          <el-table-column prop="paid_amount" label="分摊销售额" width="160" sortable><template #default="{ row }">{{ formatNumber(row.paid_amount, 2) }}</template></el-table-column>
          <el-table-column prop="share" label="销售占比" width="120" sortable><template #default="{ row }">{{ formatPercent(row.share) }}</template></el-table-column>
          <el-table-column label="客户下钻" width="110" fixed="right" align="center">
            <template #default="{ row }"><el-button link type="primary" @click.stop="openCustomerDrilldown(row)">查看客户</el-button></template>
          </el-table-column>
        </el-table>
      </section>
    </template>

    <el-drawer v-model="customerDrawerVisible" size="78%" class="customer-sales-drawer" destroy-on-close>
      <template #header>
        <div class="customer-drawer-title">
          <div>
            <p class="section-kicker">线下渠道 · 客户销售下钻</p>
            <h2>{{ customerAnalysis.channel_name || selectedOfflineChannel?.channel_name }}</h2>
          </div>
          <span>销售人员：<strong>{{ customerAnalysis.owner || selectedOfflineChannel?.owner || '-' }}</strong></span>
        </div>
      </template>

      <div class="customer-drawer-body" v-loading="customerLoading">
        <div class="customer-drill-meta">
          <span>统计期间：{{ formatDate(customerAnalysis.start_date) }} 至 {{ formatDate(customerAnalysis.end_date) }}</span>
          <div class="customer-search">
            <el-input v-model="customerKeyword" clearable placeholder="客户编号 / 客户名称" @keyup.enter="searchCustomers" />
            <el-button type="primary" @click="searchCustomers">查询</el-button>
          </div>
        </div>

        <div class="customer-summary-grid">
          <article><span>客户数</span><strong>{{ formatNumber(customerAnalysis.summary.customers) }} <small>个</small></strong></article>
          <article><span>订单数</span><strong>{{ formatNumber(customerAnalysis.summary.orders) }} <small>单</small></strong></article>
          <article><span>销售数量</span><strong>{{ formatNumber(customerAnalysis.summary.quantity) }} <small>件</small></strong></article>
          <article class="is-accent"><span>明细分摊销售额</span><strong>¥ {{ formatNumber(customerAnalysis.summary.paid_amount, 2) }}</strong></article>
        </div>

        <section class="panel customer-sales-table">
          <header><h2>客户销售情况<span class="panel-source">（金额/数量：销售单明细账；客户名称：销售单查询）</span></h2></header>
          <el-table :data="customerAnalysis.rows" height="500">
            <el-table-column prop="customer_code" label="客户编号" min-width="150" show-overflow-tooltip sortable />
            <el-table-column prop="customer_name" label="客户名称" min-width="220" show-overflow-tooltip sortable />
            <el-table-column prop="orders" label="订单数" width="110" sortable><template #default="{ row }">{{ formatNumber(row.orders) }}</template></el-table-column>
            <el-table-column prop="quantity" label="销售数量" width="120" sortable><template #default="{ row }">{{ formatNumber(row.quantity) }}</template></el-table-column>
            <el-table-column prop="paid_amount" label="分摊销售额" width="160" sortable><template #default="{ row }">{{ formatNumber(row.paid_amount, 2) }}</template></el-table-column>
            <el-table-column prop="share" label="销售占比" width="110" sortable><template #default="{ row }">{{ formatPercent(row.share) }}</template></el-table-column>
            <el-table-column prop="avg_order_amount" label="客单价" width="130" sortable><template #default="{ row }">{{ formatNumber(row.avg_order_amount, 2) }}</template></el-table-column>
          </el-table>
          <div class="customer-table-footer">
            <el-pagination
              background layout="total, sizes, prev, pager, next"
              :total="customerAnalysis.pagination.total"
              :current-page="customerPage"
              :page-size="customerPageSize"
              :page-sizes="[20, 50, 100]"
              @current-change="changeCustomerPage"
              @size-change="changeCustomerPageSize"
            />
          </div>
        </section>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.channel-dashboard-shell {
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
  width: 100%;
  min-width: 0;
  grid-template-columns: minmax(0, 1fr);
}

.channel-dashboard-shell > *,
.channel-filter-bar,
.channel-filter-bar .filter-controls,
.channel-overview-hero,
.channel-kpi-grid,
.channel-insight-grid,
.channel-efficiency-section,
.channel-efficiency-grid,
.detail-summary-grid {
  min-width: 0;
  max-width: 100%;
  box-sizing: border-box;
}
.channel-filter-bar .filter-controls { flex: 1 1 760px; flex-wrap: wrap; }
.channel-date-filter-wrap {
  width: 300px;
  min-width: 300px;
  flex: 0 0 300px;
}
.channel-date-filter-wrap :deep(.channel-date-filter) {
  width: 100%;
}
.channel-overview-hero {
  display: flex; align-items: center; justify-content: space-between; gap: 24px;
  min-height: 132px; padding: 24px 28px;
  background: linear-gradient(110deg, #ffffff 0%, #ffffff 64%, var(--theme-soft) 100%);
  border: 1px solid var(--line); border-top: 4px solid var(--brand-primary); border-radius: 8px;
  box-shadow: 0 4px 16px rgba(23, 32, 51, .04);
}
.hero-title-group { display: flex; align-items: center; gap: 18px; }
.hero-mark { width: 6px; height: 62px; flex: 0 0 auto; background: var(--brand-primary); }
.hero-eyebrow, .section-kicker { margin: 0 0 6px; color: var(--brand-primary); font-size: 11px; font-weight: 750; letter-spacing: .12em; }
.hero-title-group h1 { margin: 0; color: #111827; font-size: clamp(24px, 2vw, 34px); line-height: 1.2; letter-spacing: -.03em; }
.hero-title-group p:last-child { margin: 8px 0 0; color: var(--muted); font-size: 14px; }
.hero-actions { display: flex; min-width: min(100%, 470px); align-items: flex-end; flex-direction: column; gap: 14px; }
.hero-pages { display: inline-flex; padding: 4px; background: #f1f4f8; border-radius: 8px; }
.hero-pages button { min-height: 36px; padding: 0 18px; color: #64748b; background: transparent; border: 0; border-radius: 6px; font: inherit; font-size: 13px; font-weight: 700; white-space: nowrap; cursor: pointer; transition: color .16s ease, background-color .16s ease, box-shadow .16s ease; }
.hero-pages button:hover { color: var(--ink); }
.hero-pages button:active { transform: translateY(1px); }
.hero-pages button:focus-visible { outline: 2px solid var(--brand-primary); outline-offset: 2px; }
.hero-pages button.is-active { color: var(--brand-primary); background: #fff; box-shadow: 0 1px 4px rgba(23, 32, 51, .1); }
.hero-period { min-width: 240px; text-align: right; }
.hero-period span { display: block; color: var(--brand-primary); font-size: 13px; font-weight: 700; }
.hero-period strong { display: block; margin-top: 7px; color: var(--ink); font-size: 14px; }

.channel-kpi-grid { display: grid; grid-template-columns: 1.28fr repeat(4, 1fr); gap: 12px; }
.channel-kpi-card { min-width: 0; padding: 20px; background: #fff; border: 1px solid var(--line); border-radius: 8px; box-shadow: 0 3px 12px rgba(23, 32, 51, .035); }
.kpi-label { display: block; color: var(--muted); font-size: 13px; font-weight: 650; }
.kpi-alias { margin-left: 4px; color: #94a3b8; font-size: 11px; font-weight: 500; }
.kpi-value { display: flex; align-items: baseline; gap: 6px; min-width: 0; margin: 12px 0 8px; color: var(--ink); }
.kpi-value strong { overflow: hidden; font-size: clamp(22px, 1.7vw, 30px); line-height: 1; letter-spacing: -.03em; text-overflow: ellipsis; white-space: nowrap; }
.kpi-value em { color: var(--muted); font-size: 12px; font-style: normal; }
.kpi-note { color: #94a3b8; font-size: 12px; }
.channel-kpi-card.is-accent { background: linear-gradient(135deg, var(--brand-primary), var(--brand-primary-dark)); border-color: transparent; }
.channel-kpi-card.is-accent :is(.kpi-label, .kpi-value, .kpi-value em, .kpi-note) { color: #fff; }
.channel-kpi-card.is-accent .kpi-alias { color: rgba(255, 255, 255, .66); }
.channel-kpi-card.is-accent .kpi-note { opacity: .72; }

.channel-insight-grid { display: grid; grid-template-columns: minmax(0, 1.7fr) minmax(320px, .72fr); gap: 14px; }
.channel-insight-grid.is-trend-only { grid-template-columns: 1fr; }
.channel-insight-grid .panel, .efficiency-card { overflow: hidden; }
.channel-insight-grid .panel > header, .efficiency-card > header { min-height: 72px; padding: 16px 20px; }
.channel-insight-grid h2, .section-heading h2, .efficiency-card h2 { margin: 0; color: var(--ink); font-size: 17px; }
.channel-trend-chart { width: 100%; height: 360px; }
.contribution-panel > header { align-items: center; }
.contribution-legend { display: flex; align-items: center; gap: 12px; color: #64748b; font-size: 11px; }
.contribution-legend span, .comparison-values span { display: flex; align-items: center; gap: 6px; }
.contribution-legend i, .comparison-values i { width: 8px; height: 8px; flex: 0 0 auto; border-radius: 2px; }
.is-online { background: var(--brand-primary); }
.is-offline { background: var(--brand-secondary); }
.comparison-list { display: grid; gap: 34px; padding: 30px 24px 28px; }
.comparison-title { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.comparison-title > strong { color: var(--ink); font-size: 13px; }
.comparison-percentages { display: flex; align-items: baseline; gap: 10px; white-space: nowrap; }
.comparison-percentages span { color: #475569; font-size: 11px; }
.comparison-percentages strong { margin-left: 2px; font-size: 14px; font-weight: 800; }
.comparison-percentages .is-online, .comparison-percentages .is-offline { background: transparent; }
.comparison-percentages .is-online strong { color: var(--brand-primary); }
.comparison-percentages .is-offline strong { color: var(--theme-secondary); }
.comparison-bar { display: flex; width: 100%; height: 10px; margin: 13px 0 12px; overflow: hidden; background: #eef1f5; border-radius: 3px; }
.comparison-bar i { display: block; height: 100%; }
.comparison-values { display: grid; gap: 6px; }
.comparison-values span { min-width: 0; }
.comparison-values em { color: #475569; font-size: 11px; font-style: normal; }
.comparison-values b { margin-left: auto; color: #475569; font-size: 11px; font-weight: 500; white-space: nowrap; }

.channel-efficiency-section { padding-top: 4px; }
.section-heading { display: flex; align-items: end; justify-content: space-between; gap: 18px; margin-bottom: 14px; padding: 0 4px; }
.section-heading > span { color: #94a3b8; font-size: 12px; }
.channel-efficiency-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.efficiency-card > header { display: flex; justify-content: space-between; align-items: center; }
.efficiency-card header p { margin: 6px 0 0; color: #94a3b8; font-size: 12px; }
.share-total { color: var(--brand-primary); font-size: 20px; }
.ranked-channel-list, .offline-channel-list { display: grid; gap: 0; padding: 4px 20px 18px; }
.ranked-channel-item { display: grid; grid-template-columns: 34px minmax(0, 1fr) auto; align-items: center; gap: 12px; min-height: 68px; border-bottom: 1px solid #edf0f4; }
.ranked-channel-item:last-child { border-bottom: 0; }
.channel-rank { display: grid; width: 30px; height: 30px; place-items: center; color: var(--brand-primary); background: var(--brand-soft); border-radius: 50%; font-size: 12px; font-weight: 800; }
.channel-main, .channel-result { display: grid; gap: 5px; min-width: 0; }
.channel-main strong, .channel-main span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.channel-main strong { color: var(--ink); font-size: 14px; }
.channel-main span, .channel-result span { color: #94a3b8; font-size: 11px; }
.channel-result { text-align: right; }
.channel-result strong { color: var(--brand-primary); font-size: 14px; }
.offline-channel-item { padding: 14px 0; border-bottom: 1px solid #edf0f4; }
.offline-channel-item:last-child { border-bottom: 0; }
.contribution-meta, .contribution-detail { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.contribution-meta strong { overflow: hidden; color: var(--ink); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.contribution-meta span { color: var(--brand-primary); font-size: 13px; font-weight: 750; }
.progress-track { height: 6px; margin: 9px 0 7px; overflow: hidden; background: #eef1f5; border-radius: 2px; }
.progress-track i { display: block; height: 100%; background: linear-gradient(90deg, var(--brand-primary), var(--brand-secondary)); border-radius: inherit; }
.contribution-detail { color: #94a3b8; font-size: 11px; }
.detail-summary-grid { margin-bottom: 0; }
.channel-dashboard-shell :deep(.channel-cell i) { background: var(--brand-primary); }
.customer-drawer-title { display: flex; width: 100%; align-items: center; justify-content: space-between; gap: 20px; padding-right: 12px; }
.customer-drawer-title h2 { margin: 2px 0 0; color: var(--ink); font-size: 22px; }
.customer-drawer-title > span { color: var(--muted); font-size: 13px; }
.customer-drawer-title > span strong { color: var(--ink); }
.customer-drawer-body { display: grid; gap: 14px; min-height: 300px; }
.customer-drill-meta { display: flex; align-items: center; justify-content: space-between; gap: 16px; color: var(--muted); font-size: 12px; }
.customer-search { display: flex; width: min(380px, 100%); gap: 8px; }
.customer-summary-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.customer-summary-grid article { display: grid; gap: 10px; min-height: 88px; align-content: center; padding: 16px 18px; background: #fff; border: 1px solid var(--line); border-radius: 8px; }
.customer-summary-grid article > span { color: var(--muted); font-size: 12px; }
.customer-summary-grid article > strong { color: var(--ink); font-size: 22px; }
.customer-summary-grid article small { color: var(--muted); font-size: 11px; }
.customer-summary-grid article.is-accent { background: linear-gradient(135deg, var(--brand-primary), var(--brand-primary-dark)); border-color: transparent; }
.customer-summary-grid article.is-accent :is(span, strong) { color: #fff; }
.customer-sales-table { overflow: hidden; }
.customer-table-footer { display: flex; justify-content: flex-end; padding: 14px 16px; border-top: 1px solid var(--line); }
:deep(.customer-sales-drawer .el-drawer__header) { margin-bottom: 0; padding-bottom: 18px; border-bottom: 1px solid var(--line); }
:deep(.customer-sales-drawer .el-drawer__body) { background: #f6f7f9; }

@media (max-width: 1180px) {
  .channel-filter-bar .filter-controls { flex-wrap: wrap; }
  .channel-kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .channel-insight-grid { grid-template-columns: 1fr; }
}
@media (max-width: 900px) {
  .channel-overview-hero { align-items: flex-start; flex-direction: column; }
  .hero-actions { width: 100%; align-items: flex-start; }
  .hero-period { text-align: left; }
  .channel-efficiency-grid { grid-template-columns: 1fr; }
  .customer-summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 640px) {
  .channel-date-filter-wrap { width: 100%; min-width: 0; flex-basis: 100%; }
  .channel-overview-hero { padding: 20px; }
  .hero-title-group { align-items: flex-start; }
  .hero-pages { width: 100%; overflow-x: auto; }
  .hero-pages button { flex: 1 0 auto; padding: 0 12px; }
  .channel-kpi-grid { grid-template-columns: 1fr; }
  .section-heading { align-items: flex-start; flex-direction: column; }
  .comparison-title { align-items: flex-start; flex-direction: column; }
  .customer-drawer-title, .customer-drill-meta { align-items: flex-start; flex-direction: column; }
  .customer-search { width: 100%; }
  .customer-summary-grid { grid-template-columns: 1fr; }
}
</style>
