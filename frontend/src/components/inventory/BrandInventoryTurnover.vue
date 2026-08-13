<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import WarehouseFilter from './WarehouseFilter.vue'
import ProductTypeFilter from './ProductTypeFilter.vue'
import { getBrandInventoryTurnover, getBrandInventoryTurnoverAnalysis, getInventoryWarehouses } from '../../api/inventory'
import { DEFAULT_INVENTORY_PRODUCT_TYPES } from '../../constants/inventory'
import { inventoryQuery, productTypeParam, queryArray } from '../../utils/inventoryFilters'
import { getSavedTheme } from '../../utils/theme'
import ExportExcelButton from '../common/ExportExcelButton.vue'

use([CanvasRenderer, BarChart, GridComponent, TooltipComponent])

const chartTheme = getSavedTheme()

const route = useRoute()
const router = useRouter()
const pageOptions = [
  { label: '周转概览', value: 'overview' },
  { label: '品牌对比', value: 'comparison' },
  { label: '数据明细', value: 'detail' },
]
const supportedPages = pageOptions.map((item) => item.value)
const activePage = ref(supportedPages.includes(String(route.query.turnover_view)) ? String(route.query.turnover_view) : 'overview')
const now = new Date()
const completedQuarter = Math.floor(now.getMonth() / 3)
const defaultYear = completedQuarter > 0 ? now.getFullYear() : now.getFullYear() - 1
const defaultQuarter = completedQuarter > 0 ? completedQuarter : 4
const loading = ref(false)
const contractError = ref('')
const warehouseLoading = ref(false)
const warehouseOptions = ref([])
const brandOptions = ref([])
const productTypeOptions = ref([...DEFAULT_INVENTORY_PRODUCT_TYPES])
const yearOptions = Array.from({ length: 3 }, (_, index) => defaultYear - index)
const quarterOptions = [1, 2, 3, 4].map((value) => ({ label: `Q${value}`, value }))
const periodModeOptions = [
  { label: '季度', value: 'quarter' },
  { label: '自定义', value: 'custom' },
]

function quarterDateRange(year, quarter) {
  const startMonth = (quarter - 1) * 3
  const start = new Date(year, startMonth, 1)
  const end = new Date(year, startMonth + 3, 0)
  const format = (value) => [
    value.getFullYear(),
    String(value.getMonth() + 1).padStart(2, '0'),
    String(value.getDate()).padStart(2, '0'),
  ].join('-')
  return [format(start), format(end)]
}

const routeStartDate = String(route.query.start_date || '')
const routeEndDate = String(route.query.end_date || '')
const stockMinimumOptions = [
  { label: '可用库存不限', value: 0 },
  { label: '可用库存 ≥ 100 件', value: 100 },
  { label: '可用库存 ≥ 500 件', value: 500 },
  { label: '可用库存 ≥ 1,000 件', value: 1000 },
  { label: '可用库存 ≥ 5,000 件', value: 5000 },
]
const productDetailOptions = [
  { label: '正装 + 小样', value: 'combined' },
  { label: '正装', value: 'regular' },
  { label: '小样', value: 'sample' },
]
const activeProductDetail = ref('combined')
const productDetailPage = ref(1)
const productDetailPageSize = ref(20)
const query = reactive({
  keyword: String(route.query.brand_keyword || ''),
  periodMode: routeStartDate && routeEndDate ? 'custom' : 'quarter',
  year: Number(route.query.year || defaultYear),
  quarter: Number(route.query.quarter || defaultQuarter),
  dateRange: routeStartDate && routeEndDate
    ? [routeStartDate, routeEndDate]
    : quarterDateRange(defaultYear, defaultQuarter),
  minStock: Number(route.query.min_stock ?? 100),
  warehouses: queryArray(route.query.warehouse, []),
  productTypes: route.query.product_type === '__all__' ? [] : queryArray(route.query.product_type, DEFAULT_INVENTORY_PRODUCT_TYPES),
  page: Number(route.query.page || 1),
  pageSize: Number(route.query.page_size || 50),
})
const analysis = ref({
  period: `${defaultYear} Q${defaultQuarter}`,
  start_date: '',
  end_date: '',
  snapshot_at: '',
  summary: { brand_count: 0, ending_stock: 0, available_stock: 0, net_sales_quantity: 0, turnover_rate: null, turnover_days: null, attention_brands: 0 },
  pagination: { page: 1, page_size: 50, total: 0 },
  chart_rows: [],
  product_turnover_panels: [],
  product_turnover_rows: [],
  rows: [],
})
const turnoverExportColumns = [{ key: 'rank', label: '排名', kind: 'integer' }, { key: 'brand', label: '品牌' }, { key: 'net_sales_quantity', label: '期间净销售数量', kind: 'integer' }, { key: 'ending_stock', label: '期末库存数量', kind: 'integer' }, { key: 'average_inventory', label: '期间平均库存', kind: 'number' }, { key: 'net_sales_amount', label: '期间分摊销售额', kind: 'number' }, { key: 'turnover_rate', label: '库存周转次数', kind: 'number' }, { key: 'turnover_days', label: '库存周转天数', kind: 'number' }, { key: 'status', label: '状态' }]

const isHistoricalBasis = computed(() => analysis.value.basis === 'monthly_average_inventory')

function formatNumber(value, digits = 0) {
  return Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

function turnoverText(value) {
  return value === null || value === undefined ? '暂不可算' : `${formatNumber(value, 1)} 天`
}

function turnoverRateText(value) {
  return value === null || value === undefined ? '暂不可算' : `${formatNumber(value, 2)} 次`
}

function statusType(status) {
  if (status === '正常') return 'success'
  if (status === '偏慢') return 'warning'
  return 'danger'
}

function snapshotText(value) {
  return value ? String(value).replace('T', ' ').slice(0, 19) : '暂无快照时间'
}

const metrics = computed(() => [
  {
    label: '周期净销售数量', alias: '(VOLUME)', value: formatNumber(analysis.value.summary.net_sales_quantity),
    unit: '件', note: `${analysis.value.period} 净销售`, accent: true,
  },
  {
    label: isHistoricalBasis.value ? '期间平均库存' : '当前可用库存',
    value: formatNumber(isHistoricalBasis.value ? analysis.value.summary.average_inventory : analysis.value.summary.available_stock), unit: '件',
    note: isHistoricalBasis.value
      ? `${analysis.value.freshness?.monthly_average_count || 0}个月月初/月末均值`
      : `快照 ${snapshotText(analysis.value.snapshot_at)}`,
  },
  {
    label: isHistoricalBasis.value ? '库存周转次数' : '估算周转次数',
    value: turnoverRateText(analysis.value.summary.turnover_rate), unit: '',
    note: isHistoricalBasis.value ? '周期净销售数量 / 期间平均库存' : '周期净销售数量 / 当前可用库存',
  },
  {
    label: isHistoricalBasis.value ? '库存周转天数' : '估算周转天数',
    value: turnoverText(analysis.value.summary.turnover_days), unit: '',
    note: `${analysis.value.period_days || 0} 天 / ${isHistoricalBasis.value ? '库存周转次数' : '估算周转次数'}`,
  },
])

const focusRow = computed(() => analysis.value.rows[0] || null)
const availabilityPercent = computed(() => {
  const stock = Number(focusRow.value?.ending_stock || analysis.value.summary.ending_stock || 0)
  const available = Number(focusRow.value?.available_stock || 0)
  return stock > 0 ? available / stock * 100 : 0
})
const snapshotCompletenessPercent = computed(() => {
  const expected = Number(analysis.value.freshness?.snapshot_expected || 0)
  const actual = Number(analysis.value.freshness?.snapshot_count || 0)
  return expected > 0 ? actual / expected * 100 : 0
})
const periodDateText = computed(() => `${analysis.value.start_date} 至 ${analysis.value.end_date}`)

const chartRows = computed(() => (analysis.value.chart_rows || analysis.value.rows)
  .filter((row) => row.brand !== '未归类')
  .filter((row) => row.turnover_days !== null && row.turnover_days !== undefined)
  .reverse())
const chartHeight = computed(() => `${Math.max(350, chartRows.value.length * 34 + 70)}px`)
const productTurnoverPanels = computed(() => query.keyword.trim() ? (analysis.value.product_turnover_panels || []) : [])
const productDetailRows = computed(() => {
  const rows = analysis.value.product_turnover_rows || []
  if (activeProductDetail.value === 'regular') return rows.filter((row) => row.product_type === '正装')
  if (activeProductDetail.value === 'sample') return rows.filter((row) => row.product_type === '小样')
  return rows.filter((row) => ['正装', '小样'].includes(row.product_type))
})
const pagedProductDetailRows = computed(() => {
  const start = (productDetailPage.value - 1) * productDetailPageSize.value
  return productDetailRows.value.slice(start, start + productDetailPageSize.value)
})

function switchProductDetail() {
  productDetailPage.value = 1
}

function changeProductDetailPageSize(size) {
  productDetailPageSize.value = size
  productDetailPage.value = 1
}

function productShortName(value) {
  const text = String(value || '未命名商品')
  return text.length > 12 ? `${text.slice(0, 12)}...` : text
}

function productPanelChartOption(panel) {
  const rows = [...(panel.rows || [])].reverse()
  return {
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'shadow' }, backgroundColor: '#111217', borderWidth: 0,
      textStyle: { color: '#ffffff' },
      formatter: (params) => {
        const row = rows[params[0].dataIndex]
        return `${row.product}<br/>货品编号：${row.product_code || '暂无'}<br/>${isHistoricalBasis.value ? '周转天数' : '估算周转'}：${turnoverText(row.turnover_days)}`
      },
    },
    grid: { top: 16, left: 112, right: 64, bottom: 14 },
    xAxis: {
      type: 'value', axisLabel: { show: false }, axisTick: { show: false }, axisLine: { show: false },
      splitLine: { lineStyle: { color: '#f0f2f5' } },
    },
    yAxis: {
      type: 'category', data: rows.map((row) => productShortName(row.product)),
      axisTick: { show: false }, axisLine: { show: false },
      axisLabel: { color: '#5f6879', width: 102, overflow: 'truncate', fontSize: 10 },
    },
    series: [{
      name: isHistoricalBasis.value ? '期间平均库存' : '可用库存', type: 'bar', barWidth: 9,
      itemStyle: {
        borderRadius: [0, 5, 5, 0],
        color: {
          type: 'linear', x: 0, y: 0, x2: 1, y2: 0,
          colorStops: [
            { offset: 0, color: chartTheme.primary },
            { offset: 1, color: chartTheme.secondary },
          ],
        },
      },
      label: {
        show: true, position: 'right', color: '#697386', fontSize: 10,
        formatter: ({ dataIndex }) => turnoverText(rows[dataIndex].turnover_days),
      },
      data: rows.map((row) => isHistoricalBasis.value ? row.average_inventory : row.available_stock),
    }],
  }
}

const chartOption = computed(() => ({
  color: [chartTheme.primary],
  tooltip: {
    trigger: 'axis', axisPointer: { type: 'shadow' }, backgroundColor: '#111217', borderWidth: 0,
    textStyle: { color: '#ffffff' },
    formatter: (params) => {
      const row = chartRows.value[params[0].dataIndex]
      return `${row.brand}<br/>${isHistoricalBasis.value ? '库存周转' : '估算周转'}：${turnoverRateText(row.turnover_rate)}<br/>${isHistoricalBasis.value ? '周转天数' : '估算周转天数'}：${turnoverText(row.turnover_days)}<br/>净销售：${formatNumber(row.net_sales_quantity)} 件<br/>${isHistoricalBasis.value ? '期间平均库存' : '可用库存'}：${formatNumber(isHistoricalBasis.value ? row.average_inventory : row.available_stock)} 件`
    },
  },
  grid: { top: 18, left: 120, right: 70, bottom: 24 },
  xAxis: {
    type: 'value', splitLine: { lineStyle: { color: '#eceef3' } },
    axisLabel: { color: '#9aa0aa', formatter: (value) => `${formatNumber(value)}天` },
  },
  yAxis: {
    type: 'category', data: chartRows.value.map((row) => row.brand), axisTick: { show: false },
    axisLine: { show: false }, axisLabel: { color: '#6f7480', width: 110, overflow: 'truncate' },
  },
  series: [{
    name: isHistoricalBasis.value ? '库存周转天数' : '估算周转天数', type: 'bar', barWidth: 14,
    itemStyle: { borderRadius: [0, 8, 8, 0] },
    label: { show: true, position: 'right', color: '#6f7480', fontSize: 11, formatter: ({ value }) => `${formatNumber(value, 1)}天` },
    data: chartRows.value.map((row) => row.turnover_days),
  }],
}))

function buildParams() {
  const params = {
    min_stock: query.minStock, page: query.page, page_size: query.pageSize,
  }
  if (query.periodMode === 'custom') {
    params.start_date = query.dateRange?.[0]
    params.end_date = query.dateRange?.[1]
  } else {
    params.year = query.year
    params.quarter = query.quarter
  }
  if (query.keyword.trim()) params.keyword = query.keyword.trim()
  if (query.warehouses.length) params.warehouse = query.warehouses
  params.product_type = productTypeParam(query.productTypes)
  return params
}

function buildHistoricalParams() {
  const [startDate, endDate] = query.periodMode === 'custom'
    ? query.dateRange
    : quarterDateRange(query.year, query.quarter)
  return {
    brand: query.keyword.trim(),
    start_date: startDate,
    end_date: endDate,
    warehouse: query.warehouses,
    product_type: productTypeParam(query.productTypes),
    ranking_limit: 10,
  }
}

function turnoverStatus(turnoverDays, salesQuantity, endingInventory) {
  if (Number(salesQuantity || 0) <= 0 && Number(endingInventory || 0) > 0) return '无销售'
  if (turnoverDays === null || turnoverDays === undefined) return '暂不可算'
  if (turnoverDays > 180) return '滞销'
  if (turnoverDays > 90) return '偏慢'
  return '正常'
}

function normalizeHistoricalAnalysis(data) {
  if (data.basis !== 'monthly_opening_closing_average_v1') {
    throw new Error('品牌周转后端仍是旧口径，请完成后端发布并重启服务后重试')
  }
  const details = (data.details || []).map((row) => ({
    product: row.product_name,
    product_code: row.product_code,
    product_type: row.product_type,
    average_inventory: row.average_inventory,
    available_stock: row.average_inventory,
    ending_stock: row.ending_inventory,
    net_sales_quantity: row.sales_quantity,
    net_sales_amount: row.sales_amount,
    turnover_rate: row.turnover_rate,
    turnover_days: row.turnover_days,
    status: row.status,
  }))
  const panelDefinitions = [
    ['正装 + 小样', ['正装', '小样']],
    ['正装', ['正装']],
    ['小样', ['小样']],
  ]
  const productPanels = panelDefinitions.map(([label, types]) => {
    const rows = details
      .filter((row) => types.includes(row.product_type))
      .sort((left, right) => Number(right.average_inventory || 0) - Number(left.average_inventory || 0))
    const totalAverageInventory = rows.reduce((sum, row) => sum + Number(row.average_inventory || 0), 0)
    const totalSales = rows.reduce((sum, row) => sum + Number(row.net_sales_quantity || 0), 0)
    const averageTurnoverDays = totalSales > 0
      ? Number(data.period_days || 0) * totalAverageInventory / totalSales
      : null
    return {
      label,
      total_available_stock: totalAverageInventory,
      total_average_inventory: totalAverageInventory,
      average_turnover_days: averageTurnoverDays,
      rows: rows.slice(0, 10),
    }
  })
  const summaryStatus = turnoverStatus(data.summary.turnover_days, data.summary.sales_quantity, data.summary.ending_inventory)
  const summaryRow = {
    rank: 1,
    brand: data.brand,
    ending_stock: data.summary.ending_inventory,
    average_inventory: data.summary.average_inventory,
    available_stock: data.summary.average_inventory,
    net_sales_quantity: data.summary.sales_quantity,
    net_sales_amount: data.summary.sales_amount,
    turnover_rate: data.summary.turnover_rate,
    turnover_days: data.summary.turnover_days,
    status: summaryStatus,
  }
  return {
    ...data,
    basis: 'monthly_average_inventory',
    period: `${data.start_date} 至 ${data.end_date}`,
    snapshot_at: data.freshness?.snapshot_updated_at,
    summary: {
      ...data.summary,
      ending_stock: data.summary.ending_inventory,
      available_stock: data.summary.average_inventory,
      net_sales_quantity: data.summary.sales_quantity,
      net_sales_amount: data.summary.sales_amount,
      brand_count: 1,
      attention_brands: summaryStatus === '正常' ? 0 : 1,
    },
    pagination: { page: 1, page_size: 50, total: 1 },
    chart_rows: [summaryRow],
    rows: [summaryRow],
    product_turnover_panels: productPanels,
    product_turnover_rows: details,
  }
}

async function fetchRows(resetPage = false) {
  if (resetPage) {
    query.page = 1
    productDetailPage.value = 1
  }
  router.replace({
    query: inventoryQuery({
      view: 'brand', brand_keyword: query.keyword.trim(),
      year: query.periodMode === 'quarter' ? query.year : undefined,
      quarter: query.periodMode === 'quarter' ? query.quarter : undefined,
      start_date: query.periodMode === 'custom' ? query.dateRange?.[0] : undefined,
      end_date: query.periodMode === 'custom' ? query.dateRange?.[1] : undefined,
      min_stock: query.minStock,
      turnover_view: activePage.value,
      warehouse: query.warehouses, product_type: query.productTypes.length ? query.productTypes : '__all__',
      page: query.page, page_size: query.pageSize,
    }),
  })
  loading.value = true
  contractError.value = ''
  try {
    if (query.keyword.trim()) {
      const result = await getBrandInventoryTurnoverAnalysis(buildHistoricalParams())
      analysis.value = normalizeHistoricalAnalysis(result.data)
    } else {
      const result = await getBrandInventoryTurnover(buildParams())
      analysis.value = result.data
    }
  } catch (error) {
    contractError.value = error?.message || '品牌周转数据加载失败'
    ElMessage.error(contractError.value)
  } finally {
    loading.value = false
  }
}

function switchPage(value) {
  activePage.value = value
  router.replace({ query: { ...route.query, view: 'brand', turnover_view: value } })
}

function restoreDefaults() {
  Object.assign(query, {
    keyword: '', periodMode: 'quarter', year: defaultYear, quarter: defaultQuarter,
    dateRange: quarterDateRange(defaultYear, defaultQuarter), minStock: 100,
    warehouses: [], productTypes: [...DEFAULT_INVENTORY_PRODUCT_TYPES],
    page: 1, pageSize: 50,
  })
  fetchRows()
}

function clearFilters() {
  Object.assign(query, { keyword: '', minStock: 0, warehouses: [], productTypes: [], page: 1, pageSize: 50 })
  fetchRows()
}

function changePeriodMode(value) {
  query.periodMode = value
  if (value === 'custom' && (!query.dateRange || query.dateRange.length !== 2)) {
    query.dateRange = quarterDateRange(query.year, query.quarter)
  }
}

function changePage(page) {
  query.page = page
  fetchRows()
}

function changePageSize(pageSize) {
  query.pageSize = pageSize
  query.page = 1
  fetchRows()
}

async function fetchOptions() {
  warehouseLoading.value = true
  try {
    const result = await getInventoryWarehouses()
    warehouseOptions.value = result.data.warehouses
    productTypeOptions.value = result.data.product_types || [...DEFAULT_INVENTORY_PRODUCT_TYPES]
    brandOptions.value = result.data.brands || []
  } finally {
    warehouseLoading.value = false
  }
}

onMounted(() => Promise.all([fetchOptions(), fetchRows()]))
</script>

<template>
  <div class="brand-turnover-stack" v-loading="loading">
    <el-alert
      v-if="contractError"
      :title="contractError"
      type="error"
      show-icon
      :closable="false"
    />
    <section class="toolbar-panel brand-turnover-filter">
      <div class="brand-filter-controls">
        <el-select
          v-model="query.keyword"
          class="brand-filter-brand"
          filterable
          clearable
          placeholder="选择品牌"
        >
          <el-option v-for="brand in brandOptions" :key="brand" :label="brand" :value="brand" />
        </el-select>
        <el-segmented
          v-model="query.periodMode"
          class="brand-filter-period-mode"
          :options="periodModeOptions"
          @change="changePeriodMode"
        />
        <el-select v-if="query.periodMode === 'quarter'" v-model="query.year" class="brand-filter-year">
          <el-option v-for="year in yearOptions" :key="year" :label="`${year}年`" :value="year" />
        </el-select>
        <el-segmented v-if="query.periodMode === 'quarter'" v-model="query.quarter" class="brand-filter-quarter" :options="quarterOptions" />
        <el-date-picker
          v-else
          v-model="query.dateRange"
          class="brand-filter-date-range"
          type="daterange"
          value-format="YYYY-MM-DD"
          format="YYYY-MM-DD"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          :clearable="false"
        />
        <el-select v-model="query.minStock" class="brand-filter-stock" placeholder="当前库存门槛">
          <el-option
            v-for="item in stockMinimumOptions"
            :key="item.value"
            :label="item.label"
            :value="item.value"
          />
        </el-select>
        <WarehouseFilter
          v-model="query.warehouses"
          class="brand-filter-warehouse"
          :options="warehouseOptions"
          :loading="warehouseLoading"
        />
        <ProductTypeFilter
          v-model="query.productTypes"
          class="brand-filter-type"
          :options="productTypeOptions"
          :loading="warehouseLoading"
        />
        <div class="brand-filter-actions">
          <el-button type="primary" :icon="'Search'" @click="fetchRows(true)">查询</el-button>
          <el-tooltip content="恢复全部品牌与最近完整季度" placement="top">
            <el-button :icon="'RefreshLeft'" circle @click="restoreDefaults" />
          </el-tooltip>
          <el-tooltip content="清空筛选" placement="top">
            <el-button :icon="'Delete'" circle @click="clearFilters" />
          </el-tooltip>
        </div>
      </div>
    </section>

    <section class="brand-turnover-hero">
      <div class="turnover-title-group">
        <span class="turnover-title-mark" aria-hidden="true"></span>
        <div>
          <span class="turnover-eyebrow">INVENTORY PERFORMANCE</span>
          <h1>{{ query.keyword || '全部品牌' }} 品牌周转看板</h1>
          <p>所选期间销售、库存水位与周转效率集中查看</p>
        </div>
      </div>
      <div class="turnover-hero-actions">
        <nav class="turnover-pages" aria-label="品牌周转页面">
          <button
            v-for="page in pageOptions"
            :key="page.value"
            type="button"
            :class="{ active: activePage === page.value }"
            @click="switchPage(page.value)"
          >
            {{ page.label }}
          </button>
        </nav>
        <div class="turnover-period">
          <span>{{ analysis.period }}</span>
          <strong v-if="analysis.period !== periodDateText">{{ periodDateText }}</strong>
        </div>
      </div>
    </section>

    <section class="brand-turnover-metrics">
      <article v-for="item in metrics" :key="item.label" :class="{ accent: item.accent }">
        <div class="metric-label">
          <span>{{ item.label }}</span>
          <small v-if="item.alias">{{ item.alias }}</small>
        </div>
        <strong>{{ item.value }} <small v-if="item.unit">{{ item.unit }}</small></strong>
        <p>{{ item.note }}</p>
      </article>
    </section>

    <template v-if="activePage === 'overview'">
    <section class="turnover-overview-grid">
      <article class="panel turnover-chart-panel">
        <header>
          <div>
            <span class="panel-kicker">周转趋势</span>
            <h2>{{ isHistoricalBasis ? '品牌库存周转天数' : '品牌估算周转天数' }}<span class="panel-source">（越长表示周转越慢）</span></h2>
          </div>
          <el-button :icon="'Refresh'" circle @click="fetchRows" />
        </header>
        <div v-if="chartRows.length" class="rank-chart-scroll">
          <v-chart class="rank-chart" :style="{ height: chartHeight }" :option="chartOption" autoresize />
        </div>
        <el-empty v-else description="当前筛选暂无可计算的周转数据" />
      </article>

      <aside class="panel turnover-insight-panel">
        <header>
          <div>
            <span class="panel-kicker">结构洞察</span>
            <h2>库存周转状态</h2>
          </div>
        </header>
        <div class="turnover-insight-content">
          <div class="insight-focus">
            <span>当前关注品牌</span>
            <strong>{{ focusRow?.brand || query.keyword || '暂无品牌' }}</strong>
            <el-tag v-if="focusRow" :type="statusType(focusRow.status)">{{ focusRow.status }}</el-tag>
          </div>
          <div class="insight-stat-list">
            <div>
              <span>{{ isHistoricalBasis ? '历史快照完整度' : '可用库存率' }}</span>
              <strong>{{ formatNumber(isHistoricalBasis ? snapshotCompletenessPercent : availabilityPercent, 1) }}%</strong>
            </div>
            <div>
              <span>需关注品牌</span>
              <strong>{{ formatNumber(analysis.summary.attention_brands) }}</strong>
            </div>
            <div>
              <span>库存快照</span>
              <strong>{{ snapshotText(analysis.snapshot_at) }}</strong>
            </div>
          </div>
          <div class="turnover-basis-card">
            <strong>{{ isHistoricalBasis ? '期间平均库存正式口径' : '期末库存估算口径' }}</strong>
            <span>{{ isHistoricalBasis ? '各月（月初库存 + 月末库存）÷ 2 后求平均' : '周期净销售数量 / 当前可用库存' }}</span>
            <p v-if="isHistoricalBasis">周转天数 = 期间天数 × 期间平均库存 ÷ 周期净销售数量；历史快照完整时用于正式期间分析。</p>
            <p v-else>未选择具体品牌时，暂以当前可用库存作为期末库存代理，仅用于全品牌经营观察。</p>
          </div>
        </div>
      </aside>
    </section>

    <section class="panel product-type-turnover-panel">
      <header>
        <div>
          <span class="panel-kicker">分类周转</span>
          <h2>{{ query.keyword.trim() || '品牌' }} 货品分类周转<span class="panel-source">（{{ isHistoricalBasis ? '期间平均库存' : '可用库存' }}口径）</span></h2>
        </div>
      </header>
      <div v-if="productTurnoverPanels.length" class="product-type-turnover-grid">
        <article v-for="panel in productTurnoverPanels" :key="panel.label" class="product-type-chart-card">
          <div class="product-type-chart-title">
            <strong>{{ panel.label }}</strong>
            <span class="product-type-chart-summary">
              {{ isHistoricalBasis ? '期间平均库存' : '可用库存汇总' }} <b>{{ formatNumber(panel.total_available_stock) }} 件</b>
              <i aria-hidden="true"></i>
              平均周转天数 <b>{{ turnoverText(panel.average_turnover_days) }}</b>
            </span>
          </div>
          <v-chart
            v-if="panel.rows.length"
            class="product-type-chart"
            :option="productPanelChartOption(panel)"
            autoresize
          />
          <el-empty v-else description="暂无数据" :image-size="54" />
        </article>
      </div>
      <el-empty v-else :description="query.keyword.trim() ? '当前品牌暂无分类周转数据' : '请先选择或输入品牌，查看正装与小样周转'" />
    </section>
    </template>

    <template v-else-if="activePage === 'comparison'">
      <section class="turnover-guide brand-turnover-guide">
        <div>
          <strong>周转判断标准</strong>
          <p>基于{{ isHistoricalBasis ? '历史期间平均库存' : '当前可用库存估算' }}判断品牌库存效率，数字越小表示库存消化越快。</p>
        </div>
        <div><span>不超过 90 天</span><strong>正常</strong></div>
        <div><span>90 至 180 天</span><strong>偏慢</strong></div>
        <div><span>超过 180 天或无销售</span><strong>需关注</strong></div>
        <div><span>关注品牌</span><strong>{{ formatNumber(analysis.summary.attention_brands) }}</strong></div>
      </section>
      <section class="panel turnover-comparison-panel">
        <header>
          <div>
            <span class="panel-kicker">品牌对比</span>
            <h2>{{ isHistoricalBasis ? '品牌库存周转天数' : '品牌估算周转天数' }}<span class="panel-source">（展示当前筛选结果）</span></h2>
          </div>
          <el-button :icon="'Refresh'" circle @click="fetchRows" />
        </header>
        <div v-if="chartRows.length" class="rank-chart-scroll rank-chart-scroll--large">
          <v-chart class="rank-chart" :style="{ height: chartHeight }" :option="chartOption" autoresize />
        </div>
        <el-empty v-else description="当前筛选暂无可计算的周转数据" />
      </section>
    </template>

    <template v-else>
    <section class="panel turnover-detail-panel">
      <header>
        <div>
          <span class="panel-kicker">数据明细</span>
          <h2>品牌周转明细<span class="panel-source">（销售单明细账 + {{ isHistoricalBasis ? '历史月末库存快照' : '当前分仓库存' }}）</span></h2>
        </div>
        <div class="header-actions"><ExportExcelButton title="品牌周转明细" :rows="analysis.chart_rows || analysis.rows" :columns="turnoverExportColumns" :total="analysis.pagination.total" /><el-button :icon="'Refresh'" circle @click="fetchRows" /></div>
      </header>
      <el-table :data="analysis.rows" height="520">
        <el-table-column prop="rank" label="排名" width="74" align="center">
          <template #default="{ row }"><span class="rank-badge">{{ row.rank }}</span></template>
        </el-table-column>
        <el-table-column prop="brand" label="品牌" min-width="170" />
        <el-table-column prop="net_sales_quantity" label="期间净销售数量" width="160">
          <template #default="{ row }">{{ formatNumber(row.net_sales_quantity) }}</template>
        </el-table-column>
        <el-table-column prop="ending_stock" :label="isHistoricalBasis ? '期末库存数量' : '当前库存数量'" width="150">
          <template #default="{ row }">{{ formatNumber(row.ending_stock) }}</template>
        </el-table-column>
        <el-table-column prop="available_stock" :label="isHistoricalBasis ? '期间平均库存' : '当前可用库存'" width="150">
          <template #default="{ row }">{{ formatNumber(isHistoricalBasis ? row.average_inventory : row.available_stock) }}</template>
        </el-table-column>
        <el-table-column v-if="!isHistoricalBasis" prop="orders" label="订单数" width="120">
          <template #default="{ row }">{{ formatNumber(row.orders) }}</template>
        </el-table-column>
        <el-table-column prop="net_sales_amount" label="期间明细分摊销售额" width="190">
          <template #default="{ row }">{{ formatNumber(row.net_sales_amount, 2) }}</template>
        </el-table-column>
        <el-table-column prop="turnover_rate" :label="isHistoricalBasis ? '库存周转次数' : '估算周转次数'" width="150">
          <template #default="{ row }">{{ turnoverRateText(row.turnover_rate) }}</template>
        </el-table-column>
        <el-table-column prop="turnover_days" :label="isHistoricalBasis ? '库存周转天数' : '估算周转天数'" width="150">
          <template #default="{ row }">{{ turnoverText(row.turnover_days) }}</template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="110">
          <template #default="{ row }"><el-tag :type="statusType(row.status)">{{ row.status }}</el-tag></template>
        </el-table-column>
      </el-table>
      <div class="table-footer">
        <el-pagination
          background layout="total, sizes, prev, pager, next"
          :total="analysis.pagination.total" :current-page="query.page" :page-size="query.pageSize"
          :page-sizes="[20, 50, 100]" @current-change="changePage" @size-change="changePageSize"
        />
      </div>
    </section>

    <section class="panel product-detail-panel">
      <header>
        <div>
          <span class="panel-kicker">货品分类明细</span>
          <h2>{{ query.keyword.trim() || '品牌' }} 货品周转明细<span class="panel-source">（{{ isHistoricalBasis ? '期间平均库存' : '可用库存' }}口径）</span></h2>
        </div>
        <el-segmented
          v-model="activeProductDetail"
          :options="productDetailOptions"
          @change="switchProductDetail"
        />
      </header>
      <el-table v-if="query.keyword.trim()" :data="pagedProductDetailRows" height="520">
        <el-table-column prop="product" label="货品名称" min-width="260" show-overflow-tooltip sortable />
        <el-table-column prop="product_code" label="货品编号" width="190" show-overflow-tooltip sortable />
        <el-table-column prop="product_type" label="货品分类" width="110" sortable />
        <el-table-column prop="available_stock" :label="isHistoricalBasis ? '期间平均库存' : '可用库存'" width="130" sortable>
          <template #default="{ row }">{{ formatNumber(isHistoricalBasis ? row.average_inventory : row.available_stock) }}</template>
        </el-table-column>
        <el-table-column prop="net_sales_quantity" label="期间净销售" width="140" sortable>
          <template #default="{ row }">{{ formatNumber(row.net_sales_quantity) }}</template>
        </el-table-column>
        <el-table-column prop="turnover_days" :label="isHistoricalBasis ? '库存周转天数' : '估算周转天数'" width="150" sortable>
          <template #default="{ row }">{{ turnoverText(row.turnover_days) }}</template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="110" sortable>
          <template #default="{ row }"><el-tag :type="statusType(row.status)">{{ row.status }}</el-tag></template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="请先在筛选栏选择品牌，查看三个分类维度的货品明细" />
      <div v-if="query.keyword.trim()" class="table-footer">
        <el-pagination
          background
          layout="total, sizes, prev, pager, next"
          :total="productDetailRows.length"
          :current-page="productDetailPage"
          :page-size="productDetailPageSize"
          :page-sizes="[20, 50, 100]"
          @current-change="productDetailPage = $event"
          @size-change="changeProductDetailPageSize"
        />
      </div>
    </section>
    </template>
  </div>
</template>

<style scoped>
.brand-turnover-stack {
  --turnover-primary: var(--theme-primary);
  --turnover-dark: var(--theme-strong);
  --turnover-soft: var(--theme-soft);
  --turnover-soft-strong: var(--theme-soft-strong);
  --turnover-ink: #172033;
  --turnover-muted: #8993a6;
  display: grid;
  gap: 14px;
  min-width: 0;
}

.brand-turnover-filter { padding: 10px 12px; }
.brand-filter-controls { display: flex; align-items: center; gap: 8px; min-width: 0; }
.brand-filter-brand { flex: 0 1 190px; }
.brand-filter-period-mode { flex: 0 0 auto; }
.brand-filter-year { flex: 0 0 112px; }
.brand-filter-quarter { flex: 0 0 auto; }
.brand-filter-date-range { flex: 0 0 250px; width: 250px; }
.brand-filter-stock { flex: 0 0 158px; }
.brand-filter-warehouse { flex: 1 1 220px; min-width: 180px; }
.brand-filter-type { flex: 0 1 190px; min-width: 160px; }
.brand-filter-actions { display: flex; align-items: center; gap: 2px; margin-left: auto; }

.brand-turnover-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 28px;
  min-height: 122px;
  padding: 22px 24px;
  background: linear-gradient(108deg, #ffffff 0%, #ffffff 68%, var(--turnover-soft) 100%);
  border: 1px solid var(--border);
  border-top: 4px solid var(--turnover-primary);
  border-radius: 9px;
}
.turnover-title-group { display: flex; align-items: center; gap: 16px; min-width: 0; }
.turnover-title-mark { width: 5px; height: 62px; flex: 0 0 auto; background: var(--turnover-primary); }
.turnover-eyebrow, .panel-kicker { color: var(--turnover-primary); font-size: 10px; font-weight: 800; letter-spacing: .12em; }
.brand-turnover-hero h1 { margin: 5px 0 6px; color: var(--turnover-ink); font-size: clamp(22px, 2vw, 30px); line-height: 1.15; }
.brand-turnover-hero p { margin: 0; color: var(--turnover-muted); font-size: 12px; }
.turnover-hero-actions { display: grid; justify-items: end; gap: 12px; flex: 0 0 auto; }
.turnover-pages { display: flex; padding: 4px; background: #f2f5f8; border-radius: 9px; }
.turnover-pages button { min-width: 86px; height: 36px; padding: 0 14px; color: #667187; font: inherit; font-size: 12px; font-weight: 700; background: transparent; border: 0; border-radius: 7px; cursor: pointer; }
.turnover-pages button:hover { color: var(--turnover-primary); }
.turnover-pages button.active { color: var(--turnover-primary); background: #fff; box-shadow: 0 2px 7px rgb(31 41 55 / 10%); }
.turnover-period { display: grid; justify-items: end; gap: 4px; }
.turnover-period span { color: var(--turnover-primary); font-size: 11px; font-weight: 800; }
.turnover-period strong { color: var(--turnover-ink); font-size: 12px; }

.brand-turnover-metrics { display: grid; grid-template-columns: 1.2fr repeat(3, minmax(0, 1fr)); gap: 12px; }
.brand-turnover-metrics article { display: grid; align-content: space-between; gap: 9px; min-width: 0; min-height: 112px; padding: 17px 19px; background: #fff; border: 1px solid var(--border); border-radius: 9px; }
.metric-label { display: flex; align-items: baseline; gap: 5px; min-width: 0; }
.metric-label span { color: #657086; font-size: 12px; font-weight: 750; }
.metric-label small { color: #a3abba; font-size: 10px; font-weight: 700; }
.brand-turnover-metrics article > strong { overflow: hidden; color: var(--turnover-ink); font-size: clamp(20px, 1.8vw, 27px); line-height: 1; text-overflow: ellipsis; white-space: nowrap; }
.brand-turnover-metrics article > strong small { color: var(--turnover-muted); font-size: 11px; font-weight: 600; }
.brand-turnover-metrics article p { margin: 0; overflow: hidden; color: #a0a8b7; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.brand-turnover-metrics article.accent { background: linear-gradient(135deg, var(--turnover-dark), var(--turnover-primary)); border-color: var(--turnover-dark); }
.brand-turnover-metrics article.accent :is(span, strong, p, small) { color: #fff; }
.brand-turnover-metrics article.accent p, .brand-turnover-metrics article.accent .metric-label small { opacity: .7; }

.turnover-overview-grid { display: grid; grid-template-columns: minmax(0, 1.65fr) minmax(300px, .65fr); gap: 12px; min-width: 0; }
.turnover-chart-panel, .turnover-insight-panel, .turnover-comparison-panel, .turnover-detail-panel { min-width: 0; overflow: hidden; }
.turnover-chart-panel > header, .turnover-insight-panel > header, .turnover-comparison-panel > header, .turnover-detail-panel > header { min-height: 68px; }
.turnover-chart-panel h2, .turnover-insight-panel h2, .turnover-comparison-panel h2, .turnover-detail-panel h2 { margin-top: 5px; }
.rank-chart { width: 100%; min-height: 350px; }
.rank-chart-scroll { max-height: 520px; overflow-y: auto; overscroll-behavior: contain; }
.rank-chart-scroll--large { max-height: 680px; }
.turnover-insight-content { display: grid; gap: 18px; padding: 20px; }
.insight-focus { display: grid; grid-template-columns: 1fr auto; align-items: center; gap: 7px 12px; padding-bottom: 16px; border-bottom: 1px solid var(--border); }
.insight-focus > span { grid-column: 1 / -1; color: var(--turnover-muted); font-size: 11px; font-weight: 700; }
.insight-focus > strong { overflow: hidden; color: var(--turnover-ink); font-size: 22px; text-overflow: ellipsis; white-space: nowrap; }
.insight-stat-list { display: grid; gap: 13px; }
.insight-stat-list > div { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
.insight-stat-list span { color: #69748a; font-size: 12px; }
.insight-stat-list strong { color: var(--turnover-primary); font-size: 15px; text-align: right; }
.insight-stat-list > div:last-child strong { color: var(--turnover-ink); font-size: 11px; font-weight: 650; }
.turnover-basis-card { display: grid; gap: 6px; padding: 15px; background: var(--turnover-soft); border-radius: 8px; }
.turnover-basis-card strong { color: var(--turnover-dark); font-size: 12px; }
.turnover-basis-card span { color: var(--turnover-ink); font-size: 13px; font-weight: 750; }
.turnover-basis-card p { margin: 2px 0 0; color: #8b7180; font-size: 11px; line-height: 1.65; }

.product-type-turnover-panel { min-width: 0; overflow: hidden; }
.product-type-turnover-panel > header { min-height: 68px; }
.product-type-turnover-panel h2 { margin-top: 5px; }
.product-type-turnover-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; padding: 18px; }
.product-type-chart-card { min-width: 0; overflow: hidden; background: #fff; border: 1px solid #f0dfe4; border-radius: 9px; }
.product-type-chart-title { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 15px 16px 4px; }
.product-type-chart-title strong { color: var(--turnover-ink); font-size: 13px; }
.product-type-chart-title span { color: #a0a8b7; font-size: 10px; }
.product-type-chart-title b { color: var(--turnover-primary); font-size: 12px; }
.product-type-chart-summary { display: flex; align-items: center; gap: 5px; white-space: nowrap; }
.product-type-chart-summary i { width: 1px; height: 12px; margin: 0 3px; background: #e7eaf0; }
.product-type-chart { width: 100%; height: 390px; }

.brand-turnover-guide { border-color: var(--turnover-soft-strong); }
.brand-turnover-guide > div:not(:first-child) strong { color: var(--turnover-primary); }
.brand-turnover-guide > div:first-child { background: var(--turnover-soft); }
.turnover-detail-panel :deep(.rank-badge) { color: var(--turnover-primary); background: var(--turnover-soft); }
.product-detail-panel { min-width: 0; overflow: hidden; }
.product-detail-panel > header { min-height: 68px; }
.product-detail-panel h2 { margin-top: 5px; }

:deep(.el-button--primary) { --el-button-bg-color: var(--turnover-primary); --el-button-border-color: var(--turnover-primary); --el-button-hover-bg-color: var(--turnover-dark); --el-button-hover-border-color: var(--turnover-dark); }
:deep(.el-segmented__item-selected) { color: var(--turnover-primary); }

@media (max-width: 1280px) {
  .brand-filter-controls { flex-wrap: wrap; }
  .brand-filter-warehouse { flex: 1 1 260px; }
  .brand-filter-actions { margin-left: 0; }
  .turnover-overview-grid { grid-template-columns: minmax(0, 1.45fr) minmax(280px, .75fr); }
}
@media (max-width: 960px) {
  .brand-turnover-hero { align-items: flex-start; flex-direction: column; }
  .turnover-hero-actions { width: 100%; justify-items: stretch; }
  .turnover-pages { width: 100%; }
  .turnover-pages button { flex: 1; }
  .turnover-period { justify-items: start; }
  .brand-turnover-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .turnover-overview-grid { grid-template-columns: 1fr; }
  .product-type-turnover-grid { grid-template-columns: 1fr; }
}
@media (max-width: 640px) {
  .brand-filter-controls > * { flex: 1 1 100%; width: 100%; }
  .brand-filter-actions { width: 100%; }
  .brand-filter-actions .el-button:first-child { flex: 1; }
  .brand-turnover-hero { padding: 18px; }
  .turnover-title-mark { height: 54px; }
  .turnover-pages button { min-width: 0; padding: 0 7px; }
  .brand-turnover-metrics { grid-template-columns: 1fr; }
  .rank-chart { min-height: 320px; }
}
</style>
