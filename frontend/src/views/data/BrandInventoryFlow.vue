<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { getBrandInventoryFlow, getBrandInventoryTurnoverAnalysis, getInventoryWarehouses } from '../../api/inventory'
import { getSavedTheme } from '../../utils/theme'

use([CanvasRenderer, BarChart, LineChart, GridComponent, LegendComponent, TooltipComponent])

const chartTheme = getSavedTheme()

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const turnoverLoading = ref(false)
const brandOptions = ref([])
const selectedBrand = ref(String(route.query.brand || '资生堂'))
const activePage = ref(['overview', 'turnover', 'detail'].includes(String(route.query.view)) ? String(route.query.view) : 'overview')

async function loadBrandOptions() {
  try {
    const res = await getInventoryWarehouses()
    brandOptions.value = res.data?.brands || []
  } catch { /* silent */ }
}

const defaultYear = new Date().getFullYear()
const defaultStartDate = `${defaultYear}-01-01`
const defaultEndDate = `${defaultYear}-12-31`
const monthRange = ref([
  String(route.query.start_date || defaultStartDate).slice(0, 7),
  String(route.query.end_date || defaultEndDate).slice(0, 7),
])
const selectedWarehouses = ref(
  Array.isArray(route.query.warehouse)
    ? route.query.warehouse.map(String)
    : route.query.warehouse ? [String(route.query.warehouse)] : [],
)
const selectedProductTypes = ref(
  Array.isArray(route.query.product_type)
    ? route.query.product_type.map(String).filter((item) => ['正装', '小样'].includes(item))
    : ['正装', '小样'].includes(String(route.query.product_type)) ? [String(route.query.product_type)] : ['正装', '小样'],
)
const analysis = ref({
  brand: selectedBrand.value,
  start_date: defaultStartDate,
  end_date: defaultEndDate,
  opening_snapshot_date: `${defaultYear - 1}-12-31`,
  ending_snapshot_date: defaultEndDate,
  period: `${defaultYear}年01月—${defaultYear}年12月`,
  summary: {
    opening_quantity: 0,
    inbound_quantity: 0,
    sales_quantity: 0,
    ending_quantity: 0,
    sell_through_rate: 0,
    inbound_cost: 0,
    sales_amount: 0,
    ending_stock_amount: 0,
  },
  months: [],
  segments: [],
  filter_options: { warehouses: [] },
  freshness: {},
  metric_notes: {},
})
const turnoverAnalysis = ref({
  brand: selectedBrand.value, start_date: defaultStartDate, end_date: defaultEndDate, period: `${defaultYear}年01月—${defaultYear}年12月`, period_days: 365,
  summary: { sales_quantity: 0, sales_amount: 0, average_inventory: 0, ending_inventory: 0, ending_inventory_amount: 0, turnover_rate: null, turnover_days: null },
  category_summary: [], waterline: [], channel_mix: [], slow_products: [], hot_products: [], details: [],
  channel_turnover: { available: false, reason: '' },
  freshness: { snapshot_count: 0, snapshot_expected: 0, snapshot_complete: false, source_updated_at: '' },
  metric_notes: {},
})
const detailType = ref(['all', '正装', '小样'].includes(String(route.query.detail_type)) ? String(route.query.detail_type) : 'all')
const detailKeyword = ref(String(route.query.keyword || ''))
const detailPage = ref(Number(route.query.page || 1))
const detailPageSize = ref(20)

function formatNumber(value, digits = 0) {
  return Number(value || 0).toLocaleString('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

function formatCompact(value) {
  const amount = Number(value || 0)
  if (Math.abs(amount) >= 100000000) return formatNumber(amount / 100000000, 2) + '亿'
  if (Math.abs(amount) >= 10000) return formatNumber(amount / 10000, 1) + '万'
  return formatNumber(amount)
}

function formatDateTime(value) {
  return value ? String(value).replace('T', ' ').slice(0, 16) : '-'
}

function monthLastDay(month) {
  const [year, monthNumber] = month.split('-').map(Number)
  return month + '-' + String(new Date(year, monthNumber, 0).getDate()).padStart(2, '0')
}

const canSearch = computed(() => (
  selectedBrand.value && monthRange.value?.length === 2 && monthRange.value[0] <= monthRange.value[1]
))


// 入销比：采购入库 / 销售
const inboundSalesRatio = computed(() => {
  const inbound = analysis.value.summary.inbound_quantity || 0
  const sales = analysis.value.summary.sales_quantity || 0
  if (sales <= 0) return null
  return (inbound / sales).toFixed(2)
})

const metricCards = computed(() => [
  {
    label: '期初库存',
    value: analysis.value.summary.opening_quantity,
    unit: '件',
    note: analysis.value.opening_snapshot_date + ' 月末快照',
  },
  {
    label: '净采购入库',
    value: analysis.value.summary.inbound_quantity,
    unit: '件',
    note: '成本 ' + formatCompact(analysis.value.summary.inbound_cost) + ' 元',
    accent: true,
  },
  {
    label: '净销售',
    value: analysis.value.summary.sales_quantity,
    unit: '件',
    note: '明细分摊销售额 ' + formatCompact(analysis.value.summary.sales_amount) + ' 元',
  },
  {
    label: '期末库存',
    value: analysis.value.summary.ending_quantity,
    unit: '件',
    note: '库存金额 ' + formatCompact(analysis.value.summary.ending_stock_amount) + ' 元',
  },

  {
    label: '入销比',
    value: inboundSalesRatio.value || '-',
    unit: '倍',
    note: inboundSalesRatio.value
      ? '入库' + analysis.value.summary.inbound_quantity + '件 / 销售' + analysis.value.summary.sales_quantity + '件'
      : '暂无销售数据',
  },
])

function turnoverRateText(value) {
  return value === null || value === undefined ? '暂不可算' : formatNumber(value, 2)
}

function turnoverDaysText(value) {
  return value === null || value === undefined ? '暂不可算' : formatNumber(value, 1)
}

const categoryTurnover = computed(() => Object.fromEntries(
  turnoverAnalysis.value.category_summary.map((item) => [item.product_type, item]),
))

const effectiveProductTypes = computed(() => selectedProductTypes.value.length ? selectedProductTypes.value : ['正装', '小样'])
const productTypeLabel = computed(() => effectiveProductTypes.value.length === 2 ? '正装 + 小样' : effectiveProductTypes.value[0])
const periodYearLabel = computed(() => {
  const startYear = monthRange.value?.[0]?.slice(0, 4)
  const endYear = monthRange.value?.[1]?.slice(0, 4)
  return startYear && startYear === endYear ? startYear : '所选期间'
})
const turnoverMetrics = computed(() => [
  { label: '库存周转次数', value: turnoverRateText(turnoverAnalysis.value.summary.turnover_rate), unit: '次', note: '净销售数量 ÷ 月末平均库存', accent: true },
  { label: '库存周转天数', value: turnoverDaysText(turnoverAnalysis.value.summary.turnover_days), unit: '天', note: `${turnoverAnalysis.value.period_days}天 ÷ 周转次数` },
  ...effectiveProductTypes.value.map((productType) => ({
    label: `${productType}周转次数`, value: turnoverRateText(categoryTurnover.value[productType]?.turnover_rate), unit: '次',
    note: `月末平均库存 ${formatNumber(categoryTurnover.value[productType]?.average_inventory)} 件`,
  })),
  { label: `${periodYearLabel.value}净销售`, value: formatNumber(turnoverAnalysis.value.summary.sales_quantity), unit: '件', note: `明细分摊销售额 ${formatCompact(turnoverAnalysis.value.summary.sales_amount)} 元` },
  { label: `${periodYearLabel.value}期末库存`, value: formatNumber(turnoverAnalysis.value.summary.ending_inventory), unit: '件', note: `库存金额 ${formatCompact(turnoverAnalysis.value.summary.ending_inventory_amount)} 元` },
])

const waterlineChartOption = computed(() => ({
  color: [chartTheme.primary, chartTheme.secondary, '#334155', chartTheme.pale],
  tooltip: {
    trigger: 'axis', backgroundColor: '#172033', borderWidth: 0, textStyle: { color: '#fff' },
    formatter: (params) => {
      const title = params[0]?.axisValueLabel || ''
      return `<strong>${title}</strong>${params.map((item) => `<div style="display:flex;gap:16px;margin-top:6px;min-width:210px">${item.marker}<span>${item.seriesName}</span><strong style="margin-left:auto">${formatNumber(item.value)} 件</strong></div>`).join('')}`
    },
  },
  legend: { top: 4, right: 24, orient: 'horizontal', icon: 'roundRect', itemWidth: 10, itemHeight: 10, itemGap: 16, textStyle: { color: '#64748b', fontSize: 12 } },
  grid: { top: 48, left: 76, right: 78, bottom: 42 },
  xAxis: { type: 'category', data: turnoverAnalysis.value.waterline.map((item) => item.month.slice(5) + '月'), axisTick: { show: false }, axisLine: { lineStyle: { color: '#dce3e9' } } },
  yAxis: [
    { type: 'value', name: '库存', axisLabel: { color: '#94a3b8', formatter: formatCompact }, splitLine: { lineStyle: { color: '#edf1f4', type: 'dashed' } } },
    { type: 'value', axisLabel: { color: '#94a3b8', formatter: formatCompact }, splitLine: { show: false } },
  ],
  series: [
    ...(effectiveProductTypes.value.length === 2 ? [{ name: '总库存', type: 'line', smooth: false, symbol: 'circle', symbolSize: 6, lineStyle: { width: 3, color: chartTheme.primary }, itemStyle: { color: chartTheme.primary }, data: turnoverAnalysis.value.waterline.map((item) => item.total_inventory) }] : []),
    ...(effectiveProductTypes.value.includes('正装') ? [{ name: '正装库存', type: 'line', smooth: false, symbol: 'circle', symbolSize: 5, lineStyle: { width: 2.5, color: chartTheme.secondary }, itemStyle: { color: chartTheme.secondary }, data: turnoverAnalysis.value.waterline.map((item) => item.full_size_inventory) }] : []),
    ...(effectiveProductTypes.value.includes('小样') ? [{ name: '小样库存', type: 'line', smooth: false, symbol: 'circle', symbolSize: 5, lineStyle: { width: 2.5, color: '#334155' }, itemStyle: { color: '#334155' }, data: turnoverAnalysis.value.waterline.map((item) => item.sample_inventory) }] : []),
    { name: '月度净销售', type: 'bar', yAxisIndex: 1, barMaxWidth: 18, itemStyle: { color: chartTheme.pale, opacity: .45, borderRadius: [4, 4, 0, 0] }, data: turnoverAnalysis.value.waterline.map((item) => item.sales_quantity) },
  ],
}))

const detailRows = computed(() => turnoverAnalysis.value.details.filter((row) => {
  if (detailType.value !== 'all' && row.product_type !== detailType.value) return false
  const keyword = detailKeyword.value.trim().toLowerCase()
  return !keyword || `${row.product_code} ${row.product_name}`.toLowerCase().includes(keyword)
}))
const pagedDetailRows = computed(() => {
  const start = (detailPage.value - 1) * detailPageSize.value
  return detailRows.value.slice(start, start + detailPageSize.value)
})

const quantityChartOption = computed(() => ({
  color: [chartTheme.primary, '#334155', chartTheme.secondary],
  tooltip: {
    trigger: 'axis',
    backgroundColor: '#172033',
    borderWidth: 0,
    textStyle: { color: '#fff' },
    formatter: function(params) {
      var html = '<strong>' + (params[0]?.axisValue || '') + '</strong>'
      params.forEach(function(item) {
        html += '<div style="display:flex;gap:18px;margin-top:7px;min-width:220px">' + item.marker + '<span>' + item.seriesName + '</span><strong style="margin-left:auto">' + formatNumber(item.value) + ' 件</strong></div>'
      })
      return html
    },
  },
  legend: { top: 4, right: 8, icon: 'roundRect', itemWidth: 10, itemHeight: 10 },
  grid: { top: 48, left: 76, right: 36, bottom: 44 },
  xAxis: {
    type: 'category',
    data: analysis.value.months.map(function(item) { return item.month.slice(2).replace('-', '年') + '月' }),
    axisTick: { show: false },
    axisLine: { lineStyle: { color: '#dce3e9' } },
    axisLabel: { color: '#64748b', hideOverlap: true },
  },
  yAxis: {
    type: 'value',
    axisLabel: { color: '#94a3b8', formatter: formatCompact },
    splitLine: { lineStyle: { color: '#edf1f4', type: 'dashed' } },
  },
  series: [
    {
      name: '采购入库',
      type: 'bar',
      barMaxWidth: 18,
      itemStyle: { borderRadius: [4, 4, 0, 0] },
      data: analysis.value.months.map(function(item) { return item.inbound_quantity }),
    },
    {
      name: '销售',
      type: 'bar',
      barMaxWidth: 18,
      itemStyle: { borderRadius: [4, 4, 0, 0] },
      data: analysis.value.months.map(function(item) { return item.sales_quantity }),
    },
    {
      name: '月末库存',
      type: 'line',
      symbol: 'circle',
      symbolSize: 6,
      lineStyle: { width: 2.5 },
      data: analysis.value.months.map(function(item) { return item.ending_quantity }),
    },
  ],
}))

function segmentChartOption(segment) {
  return {
    color: [chartTheme.primary, '#344054', chartTheme.secondary],
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#172033',
      borderWidth: 0,
      textStyle: { color: '#fff' },
      formatter: function(params) {
        var html = '<strong>' + (params[0]?.axisValue || '') + '</strong>'
        params.forEach(function(item) {
          html += '<div style="display:flex;gap:12px;margin-top:5px;min-width:170px">' + item.marker + '<span>' + item.seriesName + '</span><strong style="margin-left:auto">' + formatNumber(item.value) + '</strong></div>'
        })
        return html
      },
    },
    grid: { top: 16, left: 56, right: 18, bottom: 32 },
    xAxis: {
      type: 'category',
      data: segment.months.map(function(item) { return item.month.slice(5) + '月' }),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#dce3e9' } },
      axisLabel: { color: '#8a96a5', fontSize: 10, hideOverlap: true },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#9aa5b3', fontSize: 10, formatter: formatCompact },
      splitLine: { lineStyle: { color: '#edf1f4', type: 'dashed' } },
    },
    series: [
      { name: '入库', type: 'bar', barMaxWidth: 10, data: segment.months.map(function(item) { return item.inbound_quantity }) },
      { name: '销售', type: 'bar', barMaxWidth: 10, data: segment.months.map(function(item) { return item.sales_quantity }) },
      { name: '库存', type: 'line', symbol: 'none', lineStyle: { width: 2 }, data: segment.months.map(function(item) { return item.ending_quantity }) },
    ],
  }
}

async function fetchData() {
  if (!canSearch.value) return
  const startDate = monthRange.value[0] + '-01'
  const endDate = monthLastDay(monthRange.value[1])
  loading.value = true
  try {
    const tasks = [getBrandInventoryFlow({
      brand: selectedBrand.value, start_date: startDate, end_date: endDate,
      warehouse: selectedWarehouses.value, product_type: effectiveProductTypes.value,
    })]
    if (activePage.value !== 'overview') {
      turnoverLoading.value = true
      tasks.push(getBrandInventoryTurnoverAnalysis({
        brand: selectedBrand.value, start_date: startDate, end_date: endDate,
        warehouse: selectedWarehouses.value, product_type: effectiveProductTypes.value, ranking_limit: 10,
      }))
    }
    const [flowResponse, turnoverResponse] = await Promise.all(tasks)
    analysis.value = flowResponse.data
    if (turnoverResponse) turnoverAnalysis.value = turnoverResponse.data
    router.replace({
      query: {
        view: activePage.value,
        brand: selectedBrand.value,
        start_date: startDate,
        end_date: endDate,
        ...(selectedWarehouses.value.length ? { warehouse: selectedWarehouses.value } : {}),
        ...(effectiveProductTypes.value.length < 2 ? { product_type: effectiveProductTypes.value } : {}),
        ...(activePage.value === 'detail' && detailType.value !== 'all' ? { detail_type: detailType.value } : {}),
        ...(activePage.value === 'detail' && detailKeyword.value ? { keyword: detailKeyword.value } : {}),
      },
    })
  } finally {
    loading.value = false
    turnoverLoading.value = false
  }
}

async function fetchTurnoverData() {
  if (!canSearch.value) return
  const startDate = monthRange.value[0] + '-01'
  const endDate = monthLastDay(monthRange.value[1])
  turnoverLoading.value = true
  try {
    const response = await getBrandInventoryTurnoverAnalysis({
      brand: selectedBrand.value, start_date: startDate, end_date: endDate,
      warehouse: selectedWarehouses.value, product_type: effectiveProductTypes.value, ranking_limit: 10,
    })
    turnoverAnalysis.value = response.data
  } finally {
    turnoverLoading.value = false
  }
}

async function switchPage(value) {
  activePage.value = value
  detailPage.value = 1
  router.replace({ query: { ...route.query, view: value, page: undefined } })
  if (value !== 'overview') await fetchTurnoverData()
}

function openProductDetail(row) {
  activePage.value = 'detail'
  detailType.value = row.product_type
  detailKeyword.value = row.product_code || row.product_name
  detailPage.value = 1
  router.replace({ query: { ...route.query, view: 'detail', detail_type: detailType.value, keyword: detailKeyword.value, page: undefined } })
}

function changeDetailType(value) {
  detailType.value = value
  detailPage.value = 1
  syncDetailQuery()
}

function changeDetailKeyword() {
  detailPage.value = 1
  syncDetailQuery()
}

function changeDetailPageSize(value) {
  detailPageSize.value = value
  detailPage.value = 1
  syncDetailQuery()
}

function changeDetailPage(value) {
  detailPage.value = value
  syncDetailQuery()
}

function syncDetailQuery() {
  router.replace({ query: {
    ...route.query,
    view: 'detail',
    ...(detailType.value !== 'all' ? { detail_type: detailType.value } : { detail_type: undefined }),
    ...(detailKeyword.value ? { keyword: detailKeyword.value } : { keyword: undefined }),
    ...(detailPage.value > 1 ? { page: detailPage.value } : { page: undefined }),
  } })
}

function resetFilters() {
  selectedBrand.value = '资生堂'
  monthRange.value = [defaultYear + '-01', defaultYear + '-12']
  selectedWarehouses.value = []
  selectedProductTypes.value = ['正装', '小样']
  detailType.value = 'all'
  detailKeyword.value = ''
  detailPage.value = 1
  fetchData()
}

onMounted(() => {
  loadBrandOptions()
  fetchData()
})
</script>

<template>
  <div class="flow-page" v-loading="loading">
    <section class="flow-toolbar">
      <el-select
        v-model="selectedBrand"
        filterable
        placeholder="选择品牌"
        class="brand-input"
        @change="fetchData"
      >
        <el-option v-for="item in brandOptions" :key="item" :label="item" :value="item" />
      </el-select>
      <el-date-picker
        v-model="monthRange"
        type="monthrange"
        value-format="YYYY-MM"
        format="YYYY年MM月"
        range-separator="至"
        start-placeholder="开始月份"
        end-placeholder="结束月份"
        :clearable="false"
        class="month-picker"
      />
      <el-select
        v-model="selectedProductTypes"
        multiple
        collapse-tags
        collapse-tags-tooltip
        placeholder="正装 + 小样"
        class="product-type-select"
      >
        <el-option label="正装" value="正装" />
        <el-option label="小样" value="小样" />
      </el-select>
      <el-select
        v-model="selectedWarehouses"
        multiple
        filterable
        collapse-tags
        collapse-tags-tooltip
        clearable
        placeholder="全部仓库"
        class="warehouse-select"
      >
        <el-option v-for="item in analysis.filter_options.warehouses" :key="item" :label="item" :value="item" />
      </el-select>
      <el-button type="primary" :icon="'Search'" :disabled="!canSearch" @click="fetchData">查询</el-button>
      <el-tooltip content="恢复默认筛选条件" placement="top">
        <el-button :icon="'RefreshLeft'" circle @click="resetFilters" />
      </el-tooltip>
    </section>

    <section class="flow-hero">
      <div class="hero-title">
        <span aria-hidden="true"></span>
        <div>
          <p>BRAND INVENTORY FLOW</p>
          <h1>{{ analysis.brand }} 进销存看板</h1>
          <small>{{ productTypeLabel }}的采购入库、销售、库存统一观察</small>
        </div>
      </div>
      <div class="hero-meta">
        <nav class="flow-pages" aria-label="品牌进销存分页">
          <button :class="{ active: activePage === 'overview' }" @click="switchPage('overview')">进销存总览</button>
          <button :class="{ active: activePage === 'turnover' }" @click="switchPage('turnover')">周转与动销</button>
          <button :class="{ active: activePage === 'detail' }" @click="switchPage('detail')">商品明细</button>
        </nav>
        <strong>{{ analysis.period }}</strong>
        <span :class="{ complete: analysis.freshness.snapshot_complete }">
          {{ analysis.freshness.snapshot_complete
            ? analysis.freshness.snapshot_batches + ' 个库存快照完整'
            : analysis.freshness.snapshot_batches + '/' + analysis.freshness.snapshot_expected + ' 个库存快照' }}
        </span>
        <small>数据更新 {{ formatDateTime(analysis.freshness.source_updated_at) }}</small>
      </div>
    </section>

    <template v-if="activePage === 'overview'">
    <div class="metric-grid">
      <section v-for="item in metricCards" :key="item.label" class="metric-card" :class="{ accent: item.accent }">
        <span>{{ item.label }}</span>
        <div><strong>{{ item.value === '-' ? item.value : formatNumber(item.value) }}</strong><em>{{ item.unit }}</em></div>
      </section>
    </div>

    <section class="flow-panel quantity-panel">
      <header>
        <div><small>月度进销存</small><h2>采购入库、销售与月末库存</h2></div>
        <span>{{ productTypeLabel }} · 数量口径：件</span>
      </header>
      <VChart class="quantity-chart" :option="quantityChartOption" autoresize />
    </section>

    <section class="flow-panel segment-section">
      <header>
        <div><small>分类观察</small><h2>正装与小样进销存</h2></div>
        <span>三个视角使用相同月份与仓库条件</span>
      </header>
      <div class="segment-grid">
        <article v-for="segment in analysis.segments" :key="segment.key" class="segment-card">
          <div class="segment-heading">
            <h3>{{ segment.label }}</h3>
            <span>可售消化率 {{ formatNumber(segment.summary.sell_through_rate, 1) }}%</span>
          </div>
          <div class="segment-metrics">
            <div><span>期初库存</span><strong>{{ formatNumber(segment.summary.opening_quantity) }}</strong></div>
            <div><span>净采购入库</span><strong>{{ formatNumber(segment.summary.inbound_quantity) }}</strong></div>
            <div><span>净销售</span><strong>{{ formatNumber(segment.summary.sales_quantity) }}</strong></div>
            <div><span>期末库存</span><strong>{{ formatNumber(segment.summary.ending_quantity) }}</strong></div>
          </div>
          <VChart class="segment-chart" :option="segmentChartOption(segment)" autoresize />
        </article>
      </div>
    </section>

    <section class="flow-panel notes-panel">
      <header><div><small>统计口径</small><h2>数据来源</h2></div></header>
      <div class="note-grid">
        <div><strong>采购入库</strong><span>{{ analysis.metric_notes.inbound }}</span></div>
        <div><strong>销售</strong><span>{{ analysis.metric_notes.sales }}</span></div>
        <div><strong>库存</strong><span>{{ analysis.metric_notes.stock }}</span></div>
      </div>
    </section>

    <section class="flow-panel table-panel">
      <header>
        <div><small>月度明细</small><h2>{{ analysis.period }}进销存明细</h2></div>
          <span>{{ productTypeLabel }} · 点击列头可排序 · 金额单位：元</span>
      </header>
      <el-table :data="analysis.months" stripe empty-text="暂无数据">
        <el-table-column prop="month" label="月份" width="105" fixed sortable />
        <el-table-column prop="opening_quantity" label="期初库存" min-width="120" align="right" sortable>
          <template #default="{ row }">{{ formatNumber(row.opening_quantity) }}</template>
        </el-table-column>
        <el-table-column prop="inbound_quantity" label="采购入库" min-width="120" align="right" sortable>
          <template #default="{ row }">{{ formatNumber(row.inbound_quantity) }}</template>
        </el-table-column>
        <el-table-column prop="sales_quantity" label="销售数量" min-width="120" align="right" sortable>
          <template #default="{ row }">{{ formatNumber(row.sales_quantity) }}</template>
        </el-table-column>
        <el-table-column prop="ending_quantity" label="期末库存" min-width="120" align="right" sortable>
          <template #default="{ row }"><strong>{{ formatNumber(row.ending_quantity) }}</strong></template>
        </el-table-column>
        <el-table-column prop="sell_through_rate" label="可售消化率" min-width="120" align="right" sortable>
          <template #default="{ row }">{{ formatNumber(row.sell_through_rate, 1) }}%</template>
        </el-table-column>
        <el-table-column prop="inbound_cost" label="采购入库成本" min-width="150" align="right" sortable>
          <template #default="{ row }">{{ formatNumber(row.inbound_cost, 2) }}</template>
        </el-table-column>
        <el-table-column prop="sales_amount" label="分摊销售额" min-width="145" align="right" sortable>
          <template #default="{ row }">{{ formatNumber(row.sales_amount, 2) }}</template>
        </el-table-column>
        <el-table-column prop="ending_stock_amount" label="期末库存金额" min-width="155" align="right" sortable>
          <template #default="{ row }">{{ formatNumber(row.ending_stock_amount, 2) }}</template>
        </el-table-column>
      </el-table>
    </section>
    </template>

    <template v-else-if="activePage === 'turnover'">
      <div class="turnover-metric-grid" v-loading="turnoverLoading">
        <section v-for="item in turnoverMetrics" :key="item.label" class="metric-card" :class="{ accent: item.accent }">
          <span>{{ item.label }}</span>
          <div><strong>{{ item.value }}</strong><em>{{ item.unit }}</em></div>
        </section>
      </div>

      <section class="flow-panel waterline-panel" v-loading="turnoverLoading">
        <header>
          <div><small>库存水位</small><h2>{{ turnoverAnalysis.brand }} {{ productTypeLabel }}月末库存水位线</h2></div>
          <span>{{ turnoverAnalysis.freshness.snapshot_count }}/{{ turnoverAnalysis.freshness.snapshot_expected }} 个库存快照 · 数量口径：件</span>
        </header>
        <VChart v-if="turnoverAnalysis.waterline.length" class="waterline-chart" :option="waterlineChartOption" autoresize />
        <el-empty v-else description="当前筛选暂无库存水位数据" />
      </section>

      <section class="turnover-section-grid" v-loading="turnoverLoading">
        <article class="flow-panel category-turnover-panel">
          <header><div><small>分类周转</small><h2>正装与小样周转效率</h2></div><span>周转天数越短，库存消化越快</span></header>
          <div class="category-turnover-list">
            <div v-for="item in turnoverAnalysis.category_summary" :key="item.product_type">
              <strong>{{ item.product_type }}</strong>
              <span><b>{{ turnoverRateText(item.turnover_rate) }}</b> 次</span>
              <span><b>{{ turnoverDaysText(item.turnover_days) }}</b> 天</span>
              <small>净销售 {{ formatNumber(item.sales_quantity) }} 件 · 月末平均库存 {{ formatNumber(item.average_inventory) }} 件</small>
            </div>
          </div>
        </article>

        <article class="flow-panel channel-mix-panel">
          <header><div><small>渠道观察</small><h2>线上与线下销售贡献</h2></div><span>渠道周转暂不重复分摊共享库存</span></header>
          <div class="channel-mix-list">
            <div v-for="item in turnoverAnalysis.channel_mix" :key="item.channel_kind">
              <span>{{ item.channel_kind }}</span><strong>{{ formatNumber(item.sales_quantity) }} 件</strong>
              <div><i :style="{ width: Math.max(0, Math.min(100, item.quantity_share)) + '%' }"></i></div>
              <small>数量占比 {{ formatNumber(item.quantity_share, 1) }}% · 分摊销售额 {{ formatCompact(item.sales_amount) }} 元</small>
            </div>
          </div>
          <p class="channel-limit-note">{{ turnoverAnalysis.channel_turnover.reason }}</p>
        </article>
      </section>

      <section class="ranking-grid" v-loading="turnoverLoading">
        <article class="flow-panel ranking-panel slow-ranking">
          <header><div><small>库存风险</small><h2>Top 滞销品</h2></div><span>无销售优先，其次按周转天数与库存金额</span></header>
          <el-table :data="turnoverAnalysis.slow_products" stripe empty-text="暂无滞销商品">
            <el-table-column type="index" label="#" width="54" />
            <el-table-column prop="product_name" label="商品" min-width="220" show-overflow-tooltip />
            <el-table-column prop="product_type" label="分类" width="74" />
            <el-table-column prop="ending_inventory" label="期末库存" width="110" align="right"><template #default="{ row }">{{ formatNumber(row.ending_inventory) }}</template></el-table-column>
            <el-table-column prop="turnover_days" label="周转状态" width="105" align="right"><template #default="{ row }">{{ row.status === '无销售' ? '无销售' : turnoverDaysText(row.turnover_days) }}</template></el-table-column>
            <el-table-column label="" width="68" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="openProductDetail(row)">明细</el-button></template></el-table-column>
          </el-table>
        </article>

        <article class="flow-panel ranking-panel hot-ranking">
          <header><div><small>销售动能</small><h2>Top 热销品</h2></div><span>按{{ periodYearLabel }}净销售数量降序</span></header>
          <el-table :data="turnoverAnalysis.hot_products" stripe empty-text="暂无热销商品">
            <el-table-column type="index" label="#" width="54" />
            <el-table-column prop="product_name" label="商品" min-width="220" show-overflow-tooltip />
            <el-table-column prop="product_type" label="分类" width="74" />
            <el-table-column prop="sales_quantity" label="净销售" width="110" align="right"><template #default="{ row }">{{ formatNumber(row.sales_quantity) }}</template></el-table-column>
            <el-table-column prop="turnover_rate" label="周转次数" width="105" align="right"><template #default="{ row }">{{ turnoverRateText(row.turnover_rate) }}</template></el-table-column>
            <el-table-column label="" width="68" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="openProductDetail(row)">明细</el-button></template></el-table-column>
          </el-table>
        </article>
      </section>

      <section class="flow-panel notes-panel">
        <header><div><small>统计口径</small><h2>周转指标说明</h2></div></header>
        <div class="note-grid">
          <div><strong>月末平均库存</strong><span>{{ turnoverAnalysis.metric_notes.average_inventory }}</span></div>
          <div><strong>周转计算</strong><span>{{ turnoverAnalysis.metric_notes.turnover }}</span></div>
          <div><strong>商品排行</strong><span>{{ turnoverAnalysis.metric_notes.ranking }}</span></div>
        </div>
      </section>
    </template>

    <template v-else>
      <section class="flow-panel product-detail-panel" v-loading="turnoverLoading">
        <header>
          <div><small>SKU 明细</small><h2>{{ turnoverAnalysis.brand }} 商品周转明细</h2></div>
          <div class="detail-controls">
            <div class="detail-tabs">
              <button v-for="item in [{ label: '全部', value: 'all' }, { label: '正装', value: '正装' }, { label: '小样', value: '小样' }]" :key="item.value" :class="{ active: detailType === item.value }" @click="changeDetailType(item.value)">{{ item.label }}</button>
            </div>
            <el-input v-model="detailKeyword" clearable placeholder="商品编号 / 名称" class="detail-search" @input="changeDetailKeyword" />
          </div>
        </header>
        <el-table :data="pagedDetailRows" stripe height="600" empty-text="暂无商品周转明细">
          <el-table-column prop="product_code" label="商品编号" width="145" fixed show-overflow-tooltip />
          <el-table-column prop="product_name" label="商品名称" min-width="260" fixed show-overflow-tooltip />
          <el-table-column prop="product_type" label="分类" width="80" sortable />
          <el-table-column prop="sales_quantity" label="净销售数量" width="130" align="right" sortable><template #default="{ row }">{{ formatNumber(row.sales_quantity) }}</template></el-table-column>
          <el-table-column prop="sales_amount" label="分摊销售额" width="145" align="right" sortable><template #default="{ row }">{{ formatNumber(row.sales_amount, 2) }}</template></el-table-column>
          <el-table-column prop="average_inventory" label="月末平均库存" width="140" align="right" sortable><template #default="{ row }">{{ formatNumber(row.average_inventory) }}</template></el-table-column>
          <el-table-column prop="ending_inventory" label="期末库存" width="120" align="right" sortable><template #default="{ row }">{{ formatNumber(row.ending_inventory) }}</template></el-table-column>
          <el-table-column prop="ending_inventory_amount" label="期末库存金额" width="150" align="right" sortable><template #default="{ row }">{{ formatNumber(row.ending_inventory_amount, 2) }}</template></el-table-column>
          <el-table-column prop="turnover_rate" label="周转次数" width="115" align="right" sortable><template #default="{ row }">{{ turnoverRateText(row.turnover_rate) }}</template></el-table-column>
          <el-table-column prop="turnover_days" label="周转天数" width="115" align="right" sortable><template #default="{ row }">{{ turnoverDaysText(row.turnover_days) }}</template></el-table-column>
          <el-table-column prop="last_sale_date" label="最近销售" width="115" sortable><template #default="{ row }">{{ row.last_sale_date || '-' }}</template></el-table-column>
          <el-table-column prop="status" label="状态" width="90" fixed="right" sortable />
        </el-table>
        <div class="detail-pagination">
          <span>共 {{ formatNumber(detailRows.length) }} 个 SKU</span>
          <el-pagination :current-page="detailPage" :page-size="detailPageSize" background layout="sizes, prev, pager, next" :page-sizes="[20, 50, 100]" :total="detailRows.length" @current-change="changeDetailPage" @size-change="changeDetailPageSize" />
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.flow-page { --flow-primary: var(--theme-primary); --flow-dark: var(--theme-strong); --flow-soft: var(--theme-soft); --flow-soft-strong: var(--theme-soft-strong); display: grid; gap: 14px; color: #172033; }
.flow-toolbar, .flow-hero, .flow-panel, .metric-card { border: 1px solid #f0dfe4; background: #fff; box-shadow: 0 1px 2px rgba(16, 24, 40, .03); }
.flow-toolbar { display: flex; align-items: center; gap: 9px; padding: 10px 14px; border-radius: 8px; }
.brand-input { width: 170px; }.flow-toolbar :deep(.month-picker) { width: 260px !important; flex: 0 0 260px !important; }.product-type-select { width: 175px; }.warehouse-select { width: 220px; }
.flow-hero { min-height: 118px; padding: 22px 28px; border-top: 3px solid var(--flow-primary); border-radius: 8px; display: flex; align-items: center; justify-content: space-between; background: linear-gradient(105deg, #fff 62%, var(--flow-soft)); }
.hero-title { display: flex; align-items: center; gap: 15px; }.hero-title > span { width: 4px; height: 54px; border-radius: 4px; background: var(--flow-primary); }
.hero-title p, .flow-panel header small { margin: 0 0 4px; color: var(--flow-primary); font-size: 10px; font-weight: 800; letter-spacing: .1em; }
.hero-title h1 { margin: 0 0 4px; font-size: 26px; letter-spacing: -.02em; }.hero-title small { color: #7a8699; font-size: 12px; }
.hero-meta { display: grid; justify-items: end; gap: 5px; }.hero-meta strong { color: var(--flow-primary); font-size: 14px; }.hero-meta span { padding: 4px 8px; border-radius: 999px; background: #fff1ec; color: #b5573a; font-size: 11px; font-weight: 700; }.hero-meta span.complete { background: var(--flow-soft); color: var(--flow-dark); }.hero-meta small { color: #82909f; }
.flow-pages, .detail-tabs { display: inline-flex; padding: 3px; border-radius: 7px; background: var(--flow-soft); }
.flow-pages button, .detail-tabs button { border: 0; border-radius: 5px; padding: 8px 12px; background: transparent; color: #657286; font: inherit; font-size: 11px; font-weight: 700; cursor: pointer; }
.flow-pages button.active, .detail-tabs button.active { background: #fff; color: var(--flow-primary); box-shadow: 0 1px 4px rgba(16, 24, 40, .12); }
.metric-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; }
.turnover-metric-grid { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 12px; }
.metric-card { min-width: 0; min-height: 108px; padding: 17px 18px; border-radius: 8px; display: grid; align-content: center; gap: 8px; border-top: 3px solid var(--flow-soft-strong); }.metric-card > span { color: #617083; font-size: 12px; font-weight: 700; }.metric-card div { display: flex; align-items: baseline; gap: 6px; min-width: 0; }.metric-card strong { font-size: clamp(18px, 1.3vw, 24px); line-height: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }.metric-card em { color: #7d8897; font-size: 11px; font-style: normal; }.metric-card small { color: #98a2b3; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.metric-card.accent { border-color: var(--flow-dark); background: linear-gradient(135deg, var(--flow-dark), var(--flow-primary)); color: #fff; }.metric-card.accent > span, .metric-card.accent em, .metric-card.accent small { color: rgba(255, 255, 255, .78); }
.flow-panel { min-width: 0; overflow: hidden; border-radius: 8px; }.flow-panel header { min-height: 62px; padding: 13px 16px; border-bottom: 1px solid #e7ece7; display: flex; align-items: center; justify-content: space-between; gap: 14px; }.flow-panel header h2 { margin: 0; font-size: 15px; }.flow-panel header > span { color: #98a2b3; font-size: 11px; }
.quantity-chart { height: 390px; }
.waterline-chart { height: 400px; }
.turnover-section-grid, .ranking-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.category-turnover-list { display: grid; gap: 10px; padding: 14px 16px 16px; }
.category-turnover-list > div { display: grid; grid-template-columns: minmax(90px, 1fr) repeat(2, minmax(90px, .75fr)); align-items: center; gap: 8px 14px; padding: 14px; border: 1px solid var(--flow-soft-strong); border-radius: 8px; background: #fffafb; }
.category-turnover-list > div > strong { font-size: 15px; }.category-turnover-list > div > span { color: #667085; font-size: 11px; }.category-turnover-list b { color: #263449; font-size: 18px; }.category-turnover-list small { grid-column: 1 / -1; color: #8b96a5; }
.channel-mix-list { display: grid; gap: 14px; padding: 15px 16px 10px; }
.channel-mix-list > div { display: grid; grid-template-columns: 1fr auto; gap: 7px 14px; align-items: center; }.channel-mix-list > div > span { color: #667085; font-size: 12px; font-weight: 700; }.channel-mix-list > div > strong { font-size: 17px; }
.channel-mix-list div div { grid-column: 1 / -1; height: 7px; overflow: hidden; border-radius: 999px; background: var(--flow-soft); }.channel-mix-list i { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg, var(--flow-dark), var(--theme-secondary)); }.channel-mix-list small { grid-column: 1 / -1; color: #8b96a5; }
.channel-limit-note { margin: 0 16px 15px; padding: 10px 12px; border-radius: 7px; background: #fff7e8; color: #946200; font-size: 11px; line-height: 1.5; }
.ranking-panel :deep(.el-table) { --el-table-header-bg-color: #fffafb; --el-table-row-hover-bg-color: var(--flow-soft); }.ranking-panel :deep(.el-table th.el-table__cell) { color: #526070; font-size: 11px; }.slow-ranking { border-top: 3px solid #c68a3a; }.hot-ranking { border-top: 3px solid var(--flow-primary); }
.detail-controls { display: flex; align-items: center; gap: 9px; }.detail-search { width: 220px; }.detail-pagination { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; color: #8a96a5; font-size: 12px; }
.product-detail-panel :deep(.el-table) { --el-table-header-bg-color: #fffafb; --el-table-row-hover-bg-color: var(--flow-soft); }.product-detail-panel :deep(.el-table th.el-table__cell) { color: #526070; font-size: 12px; font-weight: 700; }
.segment-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; padding: 12px; }.segment-card { min-width: 0; overflow: hidden; border: 1px solid var(--flow-soft-strong); border-radius: 8px; background: #fffafb; }.segment-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 13px 14px 10px; }.segment-heading h3 { margin: 0; font-size: 14px; }.segment-heading > span { color: var(--flow-primary); font-size: 11px; font-weight: 700; }
.segment-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; margin: 0 12px; overflow: hidden; border: 1px solid #e5eae3; border-radius: 6px; background: #e5eae3; }.segment-metrics div { min-width: 0; padding: 9px 8px; background: #fff; }.segment-metrics span { display: block; margin-bottom: 5px; color: #8994a2; font-size: 9px; white-space: nowrap; }.segment-metrics strong { display: block; overflow: hidden; color: #293548; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }.segment-chart { height: 230px; }
.note-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; padding: 12px 16px 16px; }.note-grid div { padding: 11px 13px; border-radius: 6px; background: #fffafb; }.note-grid strong { display: block; margin-bottom: 4px; color: var(--flow-dark); font-size: 12px; }.note-grid span { color: #687586; font-size: 11px; line-height: 1.55; }
.table-panel :deep(.el-table) { --el-table-header-bg-color: #fffafb; --el-table-row-hover-bg-color: var(--flow-soft); }.table-panel :deep(.el-table th.el-table__cell) { color: #526070; font-size: 12px; font-weight: 700; }
@media (max-width: 1180px) { .flow-toolbar { flex-wrap: wrap; }.segment-grid, .ranking-grid { grid-template-columns: 1fr; }.segment-chart { height: 260px; }.turnover-metric-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 900px) { .metric-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }.note-grid, .turnover-section-grid { grid-template-columns: 1fr; }.flow-hero { align-items: flex-start; flex-direction: column; gap: 18px; }.hero-meta { justify-items: start; }.detail-controls { align-items: stretch; flex-direction: column; }.detail-search { width: 100%; } }
@media (max-width: 680px) { .flow-toolbar { align-items: stretch; }.brand-input, .product-type-select, .warehouse-select, .flow-toolbar :deep(.month-picker) { width: 100% !important; flex: 1 1 100% !important; }.metric-grid, .turnover-metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }.flow-pages { max-width: 100%; overflow-x: auto; }.category-turnover-list > div { grid-template-columns: 1fr 1fr; }.category-turnover-list > div > strong { grid-column: 1 / -1; } }
</style>
