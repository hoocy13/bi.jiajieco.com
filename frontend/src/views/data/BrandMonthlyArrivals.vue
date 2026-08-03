<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { getBrandMonthlyArrivals } from '../../api/inventory'

use([CanvasRenderer, BarChart, LineChart, GridComponent, LegendComponent, TooltipComponent])

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const today = new Date()
const todayText = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`
const yearStartText = `${today.getFullYear()}-01-01`
const activePage = ref(route.query.view === 'detail' ? 'detail' : 'overview')
const selectedRange = ref(route.query.start_date && route.query.end_date ? 'custom' : 'this_year')
const dateRange = ref(
  route.query.start_date && route.query.end_date
    ? [String(route.query.start_date), String(route.query.end_date)]
    : [yearStartText, todayText],
)
const selectedBrands = ref(
  Array.isArray(route.query.brand) ? route.query.brand.map(String) : route.query.brand ? [String(route.query.brand)] : [],
)
const selectedProductTypes = ref(
  Array.isArray(route.query.product_type)
    ? route.query.product_type.map(String)
    : route.query.product_type ? [String(route.query.product_type)] : [],
)
const selectedWarehouses = ref(
  Array.isArray(route.query.warehouse)
    ? route.query.warehouse.map(String)
    : route.query.warehouse ? [String(route.query.warehouse)] : [],
)
const detailType = ref(['正装', '小样'].includes(String(route.query.detail_type)) ? String(route.query.detail_type) : 'all')
const page = ref(Number(route.query.page || 1))
const pageSize = ref(20)
const analysis = ref({
  year: today.getFullYear(), period: '本年', start_date: yearStartText, end_date: todayText, updated_at: '',
  filter_options: { years: [], brands: [], product_types: [], warehouses: [] },
  summary: { net_quantity: 0, net_cost_amount: 0, brand_count: 0, document_count: 0, sku_count: 0, supplier_count: 0 },
  trend: [], product_type_summary: [], products: [], brands: [],
  pagination: { page: 1, page_size: 20, total: 0 }, details: [],
})

function formatNumber(value, digits = 0) {
  return Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

function formatCompact(value) {
  const amount = Number(value || 0)
  if (Math.abs(amount) >= 100000000) return `${formatNumber(amount / 100000000, 2)}亿`
  if (Math.abs(amount) >= 10000) return `${formatNumber(amount / 10000, 1)}万`
  return formatNumber(amount)
}

function formatDate(value, withTime = false) {
  if (!value) return '-'
  const text = String(value).replace('T', ' ')
  return text.slice(0, withTime ? 16 : 10)
}

const canSearch = computed(() => selectedRange.value === 'this_year' || dateRange.value.length === 2)
const metrics = computed(() => [
  { label: '净到货成本金额', value: formatNumber(analysis.value.summary.net_cost_amount, 2), unit: '元', note: '按入库明细成本金额汇总', accent: true },
  { label: '净到货数量', value: formatNumber(analysis.value.summary.net_quantity), unit: '件', note: analysis.value.period },
  { label: '入库单数', value: formatNumber(analysis.value.summary.document_count), unit: '单', note: `涉及 ${formatNumber(analysis.value.summary.sku_count)} 个 SKU` },
  { label: '到货品牌', value: formatNumber(analysis.value.summary.brand_count), unit: '个', note: `涉及 ${formatNumber(analysis.value.summary.supplier_count)} 个供应商` },
])

const sizeSummary = computed(() => ['正装', '小样'].map((type) => {
  const row = analysis.value.product_type_summary.find((item) => item.product_type === type)
  return {
    product_type: type,
    net_quantity: Number(row?.net_quantity || 0),
    net_cost_amount: Number(row?.net_cost_amount || 0),
    document_count: Number(row?.document_count || 0),
    sku_count: Number(row?.sku_count || 0),
  }
}))

const selectedBrandLabel = computed(() => {
  if (selectedBrands.value.length === 1) return selectedBrands.value[0]
  if (selectedBrands.value.length > 1) return '所选品牌'
  return '全部品牌'
})

const arrivalTypeMetrics = computed(() => {
  const quantities = sizeSummary.value.map((item) => ({
    key: `${item.product_type}-quantity`,
    label: `${selectedBrandLabel.value}${item.product_type}到货数量`,
    value: formatNumber(item.net_quantity),
    unit: '件',
    note: `${formatNumber(item.sku_count)} 个 SKU · ${formatNumber(item.document_count)} 张入库单`,
    kind: 'quantity',
    productType: item.product_type,
  }))
  const amounts = sizeSummary.value.map((item) => ({
    key: `${item.product_type}-amount`,
    label: `${selectedBrandLabel.value}${item.product_type}到货金额`,
    value: formatNumber(item.net_cost_amount, 2),
    unit: '元',
    note: '按入库明细成本金额汇总',
    kind: 'amount',
    productType: item.product_type,
  }))
  return [...quantities, ...amounts]
})

const productRows = computed(() => analysis.value.products.slice(0, 12))
const productChartOption = computed(() => ({
  tooltip: {
    trigger: 'axis', axisPointer: { type: 'shadow' }, backgroundColor: '#172033', borderWidth: 0,
    textStyle: { color: '#fff' },
    formatter: (params) => {
      const row = productRows.value[params[0]?.dataIndex]
      if (!row) return ''
      const receiptDate = row.first_receipt_date === row.last_receipt_date
        ? formatDate(row.last_receipt_date)
        : `${formatDate(row.first_receipt_date)} 至 ${formatDate(row.last_receipt_date)}`
      return `<strong>${row.product}</strong><br/>货品分类：${row.product_type}<br/>净到货数量：${formatNumber(row.net_quantity)} 件<br/>入库日期：${receiptDate}`
    },
  },
  grid: { top: 12, left: 176, right: 150, bottom: 20 },
  xAxis: { type: 'value', axisLabel: { color: '#98a2b3', formatter: (value) => formatCompact(value) }, splitLine: { lineStyle: { color: '#edf1f4', type: 'dashed' } } },
  yAxis: {
    type: 'category', inverse: true, data: productRows.value.map((item) => item.product),
    axisTick: { show: false }, axisLine: { show: false },
    axisLabel: { color: '#344054', width: 164, overflow: 'truncate', fontSize: 11 },
  },
  series: [{
    type: 'bar', barWidth: 11, data: productRows.value.map((item) => item.net_quantity),
    itemStyle: {
      borderRadius: [0, 7, 7, 0],
      color: { type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{ offset: 0, color: '#4f7f2d' }, { offset: 1, color: '#aacb63' }] },
    },
    label: {
      show: true, position: 'right', color: '#667085', fontSize: 11,
      formatter: (params) => {
        const row = productRows.value[params.dataIndex]
        return `${formatNumber(params.value)}件 · ${formatDate(row.last_receipt_date).slice(5)}`
      },
    },
  }],
}))

const typeTrendOption = computed(() => ({
  color: ['#4f7f2d', '#a6c95a'],
  tooltip: {
    trigger: 'axis', backgroundColor: '#172033', borderWidth: 0, textStyle: { color: '#fff' },
    formatter: (params) => `<strong>${params[0]?.axisValueLabel || ''}</strong>${params.map((item) => `<div style="display:flex;gap:16px;margin-top:6px;min-width:180px">${item.marker}<span>${item.seriesName}</span><strong style="margin-left:auto">${formatNumber(item.value)} 件</strong></div>`).join('')}`,
  },
  legend: { top: 0, right: 4, icon: 'roundRect', itemWidth: 10, itemHeight: 10, textStyle: { color: '#64748b' } },
  grid: { top: 42, left: 70, right: 28, bottom: 42 },
  xAxis: {
    type: 'category', boundaryGap: false, data: analysis.value.trend.map((item) => formatDate(item.receipt_date).slice(5)),
    axisTick: { show: false }, axisLine: { lineStyle: { color: '#dce3e9' } }, axisLabel: { color: '#64748b', hideOverlap: true },
  },
  yAxis: { type: 'value', axisLabel: { color: '#94a3b8', formatter: (value) => formatCompact(value) }, splitLine: { lineStyle: { color: '#edf1f4', type: 'dashed' } } },
  series: [
    { name: '正装', type: 'line', smooth: false, symbol: 'circle', symbolSize: 6, lineStyle: { width: 2.5 }, areaStyle: { opacity: .05 }, data: analysis.value.trend.map((item) => item.full_size_quantity) },
    { name: '小样', type: 'line', smooth: false, symbol: 'circle', symbolSize: 6, lineStyle: { width: 2.5 }, areaStyle: { opacity: .05 }, data: analysis.value.trend.map((item) => item.sample_quantity) },
  ],
}))

function resolveDateRange() {
  if (selectedRange.value === 'this_year') return [yearStartText, todayText]
  return dateRange.value
}

async function fetchData(resetPage = false) {
  if (!canSearch.value) return
  if (resetPage) page.value = 1
  const [startDate, endDate] = resolveDateRange()
  loading.value = true
  try {
    const response = await getBrandMonthlyArrivals({
      start_date: startDate, end_date: endDate, brand: selectedBrands.value,
      product_type: selectedProductTypes.value,
      warehouse: selectedWarehouses.value,
      detail_product_type: detailType.value === 'all' ? undefined : detailType.value,
      page: page.value, page_size: pageSize.value,
    })
    analysis.value = response.data
    router.replace({ query: {
      view: activePage.value,
      ...(selectedRange.value === 'custom' ? { start_date: startDate, end_date: endDate } : {}),
      ...(selectedBrands.value.length ? { brand: selectedBrands.value } : {}),
      ...(selectedProductTypes.value.length ? { product_type: selectedProductTypes.value } : {}),
      ...(selectedWarehouses.value.length ? { warehouse: selectedWarehouses.value } : {}),
      ...(detailType.value !== 'all' ? { detail_type: detailType.value } : {}),
      ...(page.value > 1 ? { page: page.value } : {}),
    } })
  } finally {
    loading.value = false
  }
}

function setRange(value) {
  selectedRange.value = value
  if (value === 'this_year') {
    dateRange.value = [yearStartText, todayText]
    fetchData(true)
  }
}

function setPage(value) {
  activePage.value = value
  page.value = 1
  fetchData()
}

function setDetailType(value) {
  detailType.value = value
  fetchData(true)
}

function resetFilters() {
  selectedRange.value = 'this_year'
  dateRange.value = [yearStartText, todayText]
  selectedBrands.value = []
  selectedProductTypes.value = []
  selectedWarehouses.value = []
  detailType.value = 'all'
  fetchData(true)
}

function handlePageChange(value) {
  page.value = value
  fetchData()
}

onMounted(() => fetchData())
</script>

<template>
  <div class="arrival-page" v-loading="loading">
    <section class="arrival-toolbar">
      <div class="range-switch">
        <button :class="{ active: selectedRange === 'this_year' }" @click="setRange('this_year')">本年</button>
        <button :class="{ active: selectedRange === 'custom' }" @click="setRange('custom')">自定义</button>
      </div>
      <div class="date-picker-shell">
        <el-date-picker
          v-model="dateRange" type="daterange" value-format="YYYY-MM-DD" format="YYYY-MM-DD"
          range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期"
          :disabled="selectedRange !== 'custom'" class="date-picker"
        />
      </div>
      <el-select v-model="selectedBrands" multiple filterable collapse-tags collapse-tags-tooltip clearable placeholder="全部品牌" class="brand-select">
        <el-option v-for="item in analysis.filter_options.brands" :key="item" :label="item" :value="item" />
      </el-select>
      <el-select v-model="selectedProductTypes" multiple filterable collapse-tags collapse-tags-tooltip clearable placeholder="全部货品分类" class="type-select">
        <el-option v-for="item in analysis.filter_options.product_types" :key="item" :label="item" :value="item" />
      </el-select>
      <el-select v-model="selectedWarehouses" multiple filterable collapse-tags collapse-tags-tooltip clearable placeholder="全部入库仓库" class="warehouse-select">
        <el-option v-for="item in analysis.filter_options.warehouses" :key="item" :label="item" :value="item" />
      </el-select>
      <el-button type="primary" :icon="'Search'" :disabled="!canSearch" @click="fetchData(true)">查询</el-button>
      <el-tooltip content="恢复默认筛选" placement="top"><el-button :icon="'RefreshLeft'" circle @click="resetFilters" /></el-tooltip>
    </section>

    <section class="arrival-hero">
      <div class="hero-title-group">
        <span class="hero-mark" aria-hidden="true"></span>
        <div><p>INBOUND PERFORMANCE</p><h1>品牌月度到货看板</h1><span>品牌、货品分类与入库日期一屏掌握</span></div>
      </div>
      <div class="hero-side">
        <nav class="hero-pages" aria-label="品牌月度到货分页">
          <button :class="{ active: activePage === 'overview' }" @click="setPage('overview')">到货看板</button>
          <button :class="{ active: activePage === 'detail' }" @click="setPage('detail')">数据明细</button>
        </nav>
        <strong>{{ analysis.period }}</strong><span>{{ analysis.start_date }} 至 {{ analysis.end_date }}</span>
      </div>
    </section>

    <template v-if="activePage === 'overview'">
      <div class="arrival-metrics">
        <section v-for="item in metrics" :key="item.label" class="arrival-metric" :class="{ 'is-accent': item.accent }">
          <span>{{ item.label }}</span><div><strong>{{ item.value }}</strong><em>{{ item.unit }}</em></div><small>{{ item.note }}</small>
        </section>
      </div>

      <section class="arrival-panel product-panel">
        <header><div><small>货品到货</small><h2>到货货品数量 Top 12</h2></div><span>条形末端显示净到货数量与最近入库日期</span></header>
        <VChart v-if="productRows.length" class="product-chart" :option="productChartOption" autoresize />
        <el-empty v-else description="当前筛选暂无货品到货数据" />
      </section>

      <section class="arrival-panel type-trend-panel">
        <header><div><small>分类趋势</small><h2>正装与小样入库数量趋势</h2></div><span>按实际入库日期统计</span></header>
        <div class="type-metrics-grid">
          <article v-for="item in arrivalTypeMetrics" :key="item.key" class="type-metric" :class="[`is-${item.kind}`, `is-${item.productType === '正装' ? 'full' : 'sample'}`]">
            <span>{{ item.label }}</span><strong>{{ item.value }} <em>{{ item.unit }}</em></strong><small>{{ item.note }}</small>
          </article>
        </div>
        <VChart v-if="analysis.trend.length" class="type-trend-chart" :option="typeTrendOption" autoresize />
        <el-empty v-else description="当前筛选暂无正装或小样数据" />
      </section>

      <section class="arrival-panel table-panel">
        <header><div><small>品牌汇总</small><h2>品牌到货表现</h2></div><span>点击列头可排序</span></header>
        <el-table :data="analysis.brands" stripe height="360" empty-text="暂无数据">
          <el-table-column prop="rank" label="排名" width="72" sortable />
          <el-table-column prop="brand" label="品牌" min-width="150" sortable show-overflow-tooltip />
          <el-table-column prop="net_quantity" label="净到货数量" min-width="130" align="right" sortable><template #default="scope">{{ formatNumber(scope.row.net_quantity) }}</template></el-table-column>
          <el-table-column prop="net_cost_amount" label="净到货成本金额" min-width="160" align="right" sortable><template #default="scope">{{ formatNumber(scope.row.net_cost_amount, 2) }}</template></el-table-column>
          <el-table-column prop="share" label="成本占比" width="110" align="right" sortable><template #default="scope"><strong class="share-value">{{ formatNumber(scope.row.share, 2) }}%</strong></template></el-table-column>
          <el-table-column prop="gross_quantity" label="毛到货数量" min-width="125" align="right" sortable><template #default="scope">{{ formatNumber(scope.row.gross_quantity) }}</template></el-table-column>
          <el-table-column prop="reversal_quantity" label="红冲数量" min-width="115" align="right" sortable><template #default="scope">{{ formatNumber(scope.row.reversal_quantity) }}</template></el-table-column>
          <el-table-column prop="brand_document_count" label="入库单数" min-width="110" align="right" sortable />
        </el-table>
      </section>
    </template>

    <section v-else class="arrival-panel detail-panel">
      <header>
        <div><small>到货明细</small><h2>入库单与货品明细</h2></div>
        <div class="detail-tabs">
          <button v-for="item in [{label:'全部明细',value:'all'},{label:'正装明细',value:'正装'},{label:'小样明细',value:'小样'}]" :key="item.value" :class="{ active: detailType === item.value }" @click="setDetailType(item.value)">{{ item.label }}</button>
        </div>
      </header>
      <div class="type-metrics-grid is-detail-summary">
        <article v-for="item in arrivalTypeMetrics" :key="item.key" class="type-metric" :class="[`is-${item.kind}`, `is-${item.productType === '正装' ? 'full' : 'sample'}`]">
          <span>{{ item.label }}</span><strong>{{ item.value }} <em>{{ item.unit }}</em></strong><small>{{ item.note }}</small>
        </article>
      </div>
      <el-table :data="analysis.details" stripe height="590" empty-text="暂无数据">
        <el-table-column prop="receipt_time" label="入库时间" width="150" sortable><template #default="scope">{{ formatDate(scope.row.receipt_time, true) }}</template></el-table-column>
        <el-table-column prop="receipt_number" label="入库单号" width="175" show-overflow-tooltip />
        <el-table-column prop="brand" label="品牌" width="110" sortable show-overflow-tooltip />
        <el-table-column prop="product" label="货品名称" min-width="240" show-overflow-tooltip />
        <el-table-column prop="product_type" label="货品分类" width="100" sortable />
        <el-table-column prop="warehouse" label="入库仓库" width="150" show-overflow-tooltip />
        <el-table-column prop="supplier" label="供应商" width="170" show-overflow-tooltip />
        <el-table-column prop="quantity" label="到货数量" width="110" align="right" sortable><template #default="scope">{{ formatNumber(scope.row.quantity) }}</template></el-table-column>
        <el-table-column prop="unit_cost" label="成本单价" width="115" align="right" sortable><template #default="scope">{{ formatNumber(scope.row.unit_cost, 2) }}</template></el-table-column>
        <el-table-column prop="cost_amount" label="到货成本金额" width="140" align="right" sortable><template #default="scope">{{ formatNumber(scope.row.cost_amount, 2) }}</template></el-table-column>
        <el-table-column prop="batch" label="批次" width="130" show-overflow-tooltip />
        <el-table-column prop="expiry_date" label="到期日期" width="115" sortable><template #default="scope">{{ formatDate(scope.row.expiry_date) }}</template></el-table-column>
      </el-table>
      <div class="pagination-row"><span>共 {{ formatNumber(analysis.pagination.total) }} 条明细</span><el-pagination background layout="prev, pager, next" :current-page="page" :page-size="pageSize" :total="analysis.pagination.total" @current-change="handlePageChange" /></div>
    </section>
  </div>
</template>

<style scoped>
.arrival-page { display: grid; gap: 14px; color: #172033; }
.arrival-toolbar, .arrival-hero, .arrival-panel, .arrival-metric { border: 1px solid #e4e9ed; background: #fff; box-shadow: 0 1px 2px rgba(16, 24, 40, .03); }
.arrival-toolbar { display: flex; align-items: center; gap: 9px; padding: 10px 14px; border-radius: 8px; }
.range-switch, .hero-pages, .detail-tabs { display: inline-flex; padding: 3px; border-radius: 7px; background: #f1f4f2; }
.range-switch { flex: 0 0 auto; }
.range-switch button, .hero-pages button, .detail-tabs button { border: 0; border-radius: 5px; padding: 8px 13px; background: transparent; color: #64748b; font: inherit; font-size: 12px; font-weight: 700; white-space: nowrap; cursor: pointer; }
.range-switch button.active, .hero-pages button.active, .detail-tabs button.active { background: #fff; color: #4f7f2d; box-shadow: 0 1px 4px rgba(16, 24, 40, .12); }
.date-picker-shell {
  flex: 0 0 280px !important;
  width: 280px !important;
  max-width: 280px !important;
}
.date-picker-shell :deep(.date-picker) {
  flex: none !important;
  width: 100% !important;
  max-width: 100% !important;
}
.brand-select { width: min(250px, 20vw); }.type-select { width: min(190px, 16vw); }.warehouse-select { width: min(220px, 18vw); }
.arrival-hero { min-height: 116px; padding: 22px 28px; border-top: 3px solid #4f7f2d; border-radius: 8px; display: flex; align-items: center; justify-content: space-between; background: linear-gradient(105deg, #fff 65%, #f6f9ef); }
.hero-title-group { display: flex; align-items: center; gap: 15px; }.hero-mark { width: 4px; height: 52px; border-radius: 2px; background: #4f7f2d; }
.hero-title-group p, .arrival-panel header small { margin: 0 0 4px; color: #4f7f2d; font-size: 10px; font-weight: 800; letter-spacing: .1em; }
.hero-title-group h1 { margin: 0 0 4px; font-size: 26px; letter-spacing: -.02em; }.hero-title-group span { color: #7a8699; font-size: 12px; }
.hero-side { display: grid; justify-items: end; gap: 5px; }.hero-side strong { color: #4f7f2d; font-size: 13px; }.hero-side > span { font-weight: 700; font-size: 12px; }
.arrival-metrics { display: grid; grid-template-columns: 1.35fr repeat(3, 1fr); gap: 12px; }
.arrival-metric { min-width: 0; min-height: 104px; padding: 17px 20px; border-radius: 8px; display: grid; align-content: center; gap: 7px; }.arrival-metric > span { color: #607086; font-size: 12px; font-weight: 700; }.arrival-metric div { display: flex; align-items: baseline; gap: 7px; min-width: 0; }.arrival-metric strong { font-size: clamp(22px, 1.7vw, 30px); line-height: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }.arrival-metric em { color: #667085; font-size: 12px; font-style: normal; }.arrival-metric small { color: #98a2b3; }.arrival-metric.is-accent { border-color: #4f7f2d; background: #4f7f2d; color: #fff; }.arrival-metric.is-accent > span, .arrival-metric.is-accent em, .arrival-metric.is-accent small { color: rgba(255,255,255,.78); }
.arrival-panel { min-width: 0; overflow: hidden; border-radius: 8px; }.arrival-panel header { min-height: 62px; padding: 13px 16px; border-bottom: 1px solid #e7ebef; display: flex; align-items: center; justify-content: space-between; gap: 16px; }.arrival-panel header h2 { margin: 0; font-size: 15px; }.arrival-panel header > span { color: #98a2b3; font-size: 11px; white-space: nowrap; }
.product-chart { height: 430px; }.type-trend-chart { height: 330px; }
.type-metrics-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; padding: 14px 16px 0; }
.type-metrics-grid.is-detail-summary { padding-bottom: 14px; border-bottom: 1px solid #e7ebef; background: #fbfcfb; }
.type-metric { min-width: 0; display: grid; gap: 7px; padding: 14px 16px; border: 1px solid #e5e9e2; border-top: 3px solid #4f7f2d; border-radius: 7px; background: #fafcf8; }
.type-metric.is-sample { border-top-color: #a6c95a; }
.type-metric.is-amount { background: #f6f9ef; }
.type-metric span { overflow: hidden; color: #667085; font-size: 12px; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
.type-metric strong { overflow: hidden; font-size: 20px; line-height: 1.1; text-overflow: ellipsis; white-space: nowrap; }
.type-metric em { color: #667085; font-size: 11px; font-style: normal; }
.type-metric small { color: #98a2b3; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.table-panel :deep(.el-table), .detail-panel :deep(.el-table) { --el-table-header-bg-color: #f8faf9; --el-table-row-hover-bg-color: #f6f9ef; }.table-panel :deep(.el-table th.el-table__cell), .detail-panel :deep(.el-table th.el-table__cell) { color: #526070; font-size: 12px; font-weight: 700; }.share-value { color: #4f7f2d; }.pagination-row { padding: 12px 16px; display: flex; align-items: center; justify-content: space-between; color: #98a2b3; font-size: 12px; }
@media (max-width: 1180px) { .arrival-toolbar { flex-wrap: wrap; }.arrival-metrics, .type-metrics-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }.brand-select, .type-select, .warehouse-select { width: 220px; } }
@media (max-width: 760px) { .arrival-toolbar { align-items: stretch; }.date-picker-shell, .brand-select, .type-select, .warehouse-select { flex-basis: 100% !important; width: 100% !important; max-width: 100% !important; }.arrival-hero { align-items: flex-start; gap: 20px; flex-direction: column; }.hero-side { justify-items: start; }.arrival-metrics, .type-metrics-grid { grid-template-columns: 1fr; } }
</style>
