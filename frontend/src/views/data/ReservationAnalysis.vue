<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { getReservationAnalysis } from '../../api/inventory'
import { getSavedTheme } from '../../utils/theme'

use([CanvasRenderer, BarChart, LineChart, PieChart, GridComponent, LegendComponent, TooltipComponent])

const chartTheme = getSavedTheme()
const route = useRoute()
const router = useRouter()
const loading = ref(false)
const activePage = ref(['overview', 'applicants', 'details'].includes(String(route.query.view)) ? String(route.query.view) : 'overview')
const dateRange = ref(route.query.start_date && route.query.end_date ? [String(route.query.start_date), String(route.query.end_date)] : [])
const statuses = ref(toArray(route.query.status))
const warehouses = ref(toArray(route.query.warehouse))
const brands = ref(toArray(route.query.brand))
const productTypes = ref(toArray(route.query.product_type))
const departments = ref(toArray(route.query.department))
const applicants = ref([])
const keyword = ref('')
const page = ref(Number(route.query.page || 1))
const pageSize = ref(Number(route.query.page_size || 20))
const analysis = ref({
  scope: {},
  filter_options: { statuses: [], warehouses: [], brands: [], product_types: [], departments: [], applicants: [] },
  summary: { order_count: 0, active_order_count: 0, sku_count: 0, reserved_quantity: 0, remaining_quantity: 0, used_quantity: 0, released_quantity: 0 },
  statuses: [], warehouses: [], brands: [], product_types: [], applicants: [], applicant_products: [], trend: [], expiry: [],
  pagination: { page: 1, page_size: 20, total: 0 }, details: [],
})

function toArray(value) {
  if (Array.isArray(value)) return value.map(String)
  return value ? [String(value)] : []
}

function formatNumber(value, digits = 0) {
  return Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

function compactNumber(value) {
  const number = Number(value || 0)
  if (Math.abs(number) >= 100000000) return `${formatNumber(number / 100000000, 2)}亿`
  if (Math.abs(number) >= 10000) return `${formatNumber(number / 10000, 1)}万`
  return formatNumber(number)
}

function formatDate(value, withTime = false) {
  if (!value) return '-'
  return String(value).replace('T', ' ').slice(0, withTime ? 16 : 10)
}

const metrics = computed(() => [
  { label: '当前剩余预留', value: formatNumber(analysis.value.summary.remaining_quantity), unit: '件', note: '尚未使用或释放的数量', accent: true },
  { label: '执行中预留单', value: formatNumber(analysis.value.summary.active_order_count), unit: '单', note: `筛选范围共 ${formatNumber(analysis.value.summary.order_count)} 单` },
  { label: '已用数量', value: formatNumber(analysis.value.summary.used_quantity), unit: '件', note: '来源字段“已用数量”' },
  { label: '已释放数量', value: formatNumber(analysis.value.summary.released_quantity), unit: '件', note: `涉及 ${formatNumber(analysis.value.summary.sku_count)} 个 SKU` },
])

const applicantMetrics = computed(() => [
  { label: '申请人数', value: formatNumber(analysis.value.applicants.length), unit: '人', note: '当前筛选范围内' },
  { label: '涉及预留单', value: formatNumber(analysis.value.summary.order_count), unit: '单', note: `其中执行中 ${formatNumber(analysis.value.summary.active_order_count)} 单` },
  { label: '预留总量', value: formatNumber(analysis.value.summary.reserved_quantity), unit: '件', note: '按申请人关联明细汇总' },
  { label: '当前剩余预留', value: formatNumber(analysis.value.summary.remaining_quantity), unit: '件', note: '尚未使用或释放的数量', accent: true },
])

const filterOptions = computed(() => analysis.value.filter_options)
const activeBrandRows = computed(() => analysis.value.brands.filter((item) => Number(item.remaining_quantity) > 0).slice(0, 10))
const applicantRows = computed(() => analysis.value.applicants.filter((item) => Number(item.remaining_quantity) > 0).slice(0, 12))
const selectedApplicantLabel = computed(() => applicants.value.length === 1 ? applicants.value[0] : applicants.value.length > 1 ? `${applicants.value.length} 位申请人` : '')

const statusOption = computed(() => ({
  color: [chartTheme.primary, '#9aa8b5'],
  tooltip: {
    trigger: 'item', backgroundColor: '#172033', borderWidth: 0, textStyle: { color: '#fff' },
    formatter: ({ name, value, data }) => `<strong>${name}</strong><br/>预留单：${formatNumber(value)} 单<br/>当前剩余：${formatNumber(data.remaining_quantity)} 件`,
  },
  legend: { bottom: 0, icon: 'circle', itemWidth: 9, itemHeight: 9 },
  series: [{
    type: 'pie', radius: ['48%', '70%'], center: ['50%', '45%'],
    label: { formatter: ({ name, value }) => `${name}\n${compactNumber(value)}单`, color: '#475467' },
    data: analysis.value.statuses.map((item) => ({ name: item.name, value: item.order_count, remaining_quantity: item.remaining_quantity })),
  }],
}))

const brandOption = computed(() => ({
  tooltip: {
    trigger: 'axis', axisPointer: { type: 'shadow' }, backgroundColor: '#172033', borderWidth: 0, textStyle: { color: '#fff' },
    formatter: (items) => {
      const row = activeBrandRows.value[items[0]?.dataIndex]
      return row ? `<strong>${row.name}</strong><br/>当前剩余：${formatNumber(row.remaining_quantity)} 件<br/>预留单：${formatNumber(row.order_count)} 单` : ''
    },
  },
  grid: { top: 14, left: 88, right: 42, bottom: 28 },
  xAxis: { type: 'value', axisLabel: { color: '#98a2b3', formatter: compactNumber }, splitLine: { lineStyle: { color: '#edf1f4', type: 'dashed' } } },
  yAxis: { type: 'category', inverse: true, data: activeBrandRows.value.map((item) => item.name), axisTick: { show: false }, axisLine: { show: false }, axisLabel: { color: '#475467' } },
  series: [{
    type: 'bar', barWidth: 14, data: activeBrandRows.value.map((item) => item.remaining_quantity),
    itemStyle: { borderRadius: [0, 8, 8, 0], color: chartTheme.primary },
    label: { show: true, position: 'right', color: '#667085', formatter: ({ value }) => compactNumber(value) },
  }],
}))

const applicantOption = computed(() => ({
  tooltip: {
    trigger: 'axis', axisPointer: { type: 'shadow' }, backgroundColor: '#172033', borderWidth: 0, textStyle: { color: '#fff' },
    formatter: (items) => {
      const row = applicantRows.value[items[0]?.dataIndex]
      return row ? `<strong>${row.name}</strong><br/>当前剩余：${formatNumber(row.remaining_quantity)} 件<br/>涉及预留单：${formatNumber(row.order_count)} 单<br/>预留总量：${formatNumber(row.reserved_quantity)} 件` : ''
    },
  },
  grid: { top: 12, left: 108, right: 54, bottom: 28 },
  xAxis: { type: 'value', axisLabel: { color: '#98a2b3', formatter: compactNumber }, splitLine: { lineStyle: { color: '#edf1f4', type: 'dashed' } } },
  yAxis: { type: 'category', inverse: true, data: applicantRows.value.map((item) => item.name), axisTick: { show: false }, axisLine: { show: false }, axisLabel: { color: '#475467', width: 96, overflow: 'truncate' } },
  series: [{
    type: 'bar', barWidth: 13, data: applicantRows.value.map((item) => item.remaining_quantity),
    itemStyle: { borderRadius: [0, 7, 7, 0], color: chartTheme.secondary },
    label: { show: true, position: 'right', color: '#667085', formatter: ({ value }) => compactNumber(value) },
  }],
}))

const trendOption = computed(() => ({
  color: [chartTheme.primary, '#6e9d7f'],
  tooltip: {
    trigger: 'axis', backgroundColor: '#172033', borderWidth: 0, textStyle: { color: '#fff' },
    formatter: (items) => `<strong>${items[0]?.axisValue || ''}</strong>${items.map((item) => `<div>${item.marker}${item.seriesName}：${formatNumber(item.value)} 件</div>`).join('')}`,
  },
  legend: { top: 0, right: 8, icon: 'roundRect', itemWidth: 10, itemHeight: 10 },
  grid: { top: 42, left: 70, right: 28, bottom: 38 },
  xAxis: { type: 'category', boundaryGap: false, data: analysis.value.trend.map((item) => item.month), axisLabel: { color: '#667085', hideOverlap: true }, axisTick: { show: false } },
  yAxis: { type: 'value', axisLabel: { color: '#98a2b3', formatter: compactNumber }, splitLine: { lineStyle: { color: '#edf1f4', type: 'dashed' } } },
  series: [
    { name: '预留数量', type: 'line', symbol: 'circle', symbolSize: 5, data: analysis.value.trend.map((item) => item.reserved_quantity) },
    { name: '当前剩余', type: 'line', symbol: 'circle', symbolSize: 5, data: analysis.value.trend.map((item) => item.remaining_quantity) },
  ],
}))

const expiryOption = computed(() => ({
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, backgroundColor: '#172033', borderWidth: 0, textStyle: { color: '#fff' }, formatter: (items) => `${items[0]?.marker || ''}${items[0]?.name}：${formatNumber(items[0]?.value)} 件` },
  grid: { top: 18, left: 64, right: 24, bottom: 42 },
  xAxis: { type: 'category', data: analysis.value.expiry.map((item) => item.name), axisTick: { show: false }, axisLabel: { color: '#667085', interval: 0 } },
  yAxis: { type: 'value', axisLabel: { color: '#98a2b3', formatter: compactNumber }, splitLine: { lineStyle: { color: '#edf1f4', type: 'dashed' } } },
  series: [{
    type: 'bar', barMaxWidth: 42, data: analysis.value.expiry.map((item, index) => ({ value: item.remaining_quantity, itemStyle: { color: index === 0 ? '#d96b73' : index === 1 ? '#d99b4d' : chartTheme.primary, borderRadius: [7, 7, 0, 0] } })),
    label: { show: true, position: 'top', color: '#667085', formatter: ({ value }) => compactNumber(value) },
  }],
}))

function queryParams() {
  return {
    start_date: dateRange.value?.[0], end_date: dateRange.value?.[1], status: statuses.value,
    warehouse: warehouses.value, brand: brands.value, product_type: productTypes.value,
    department: departments.value, applicant: applicants.value, keyword: keyword.value.trim() || undefined,
    page: page.value, page_size: pageSize.value,
  }
}

async function fetchData(resetPage = false) {
  if (resetPage) page.value = 1
  loading.value = true
  try {
    const response = await getReservationAnalysis(queryParams())
    analysis.value = response.data
    router.replace({ query: {
      ...(activePage.value !== 'overview' ? { view: activePage.value } : {}),
      ...(dateRange.value?.length === 2 ? { start_date: dateRange.value[0], end_date: dateRange.value[1] } : {}),
      ...(statuses.value.length ? { status: statuses.value } : {}),
      ...(warehouses.value.length ? { warehouse: warehouses.value } : {}),
      ...(brands.value.length ? { brand: brands.value } : {}),
      ...(productTypes.value.length ? { product_type: productTypes.value } : {}),
      ...(departments.value.length ? { department: departments.value } : {}),
      ...(page.value > 1 ? { page: page.value } : {}),
      ...(pageSize.value !== 20 ? { page_size: pageSize.value } : {}),
    } })
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  dateRange.value = []
  statuses.value = []
  warehouses.value = []
  brands.value = []
  productTypes.value = []
  departments.value = []
  applicants.value = []
  keyword.value = ''
  page.value = 1
  pageSize.value = 20
  fetchData()
}

function changePage(value) { page.value = value; fetchData() }
function changePageSize(value) { pageSize.value = value; page.value = 1; fetchData() }
function changeView(value) {
  activePage.value = value
  page.value = 1
  fetchData()
}

function inspectApplicant(row) {
  applicants.value = [row.name]
  page.value = 1
  fetchData()
}

function clearApplicantInspection() {
  applicants.value = []
  page.value = 1
  fetchData()
}

onMounted(() => fetchData())
</script>

<template>
  <div class="reservation-page page-stack" v-loading="loading">
    <section class="toolbar-panel reservation-filter-panel">
      <div class="filter-grid">
        <label><span>申请日期</span><el-date-picker v-model="dateRange" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" unlink-panels /></label>
        <label><span>单据状态</span><el-select v-model="statuses" multiple collapse-tags clearable placeholder="全部状态"><el-option v-for="item in filterOptions.statuses" :key="item" :label="item" :value="item" /></el-select></label>
        <label><span>预留仓库</span><el-select v-model="warehouses" multiple filterable collapse-tags clearable placeholder="全部仓库"><el-option v-for="item in filterOptions.warehouses" :key="item" :label="item" :value="item" /></el-select></label>
        <label><span>品牌</span><el-select v-model="brands" multiple filterable collapse-tags clearable placeholder="全部品牌"><el-option v-for="item in filterOptions.brands" :key="item" :label="item" :value="item" /></el-select></label>
        <label><span>货品分类</span><el-select v-model="productTypes" multiple collapse-tags clearable placeholder="全部分类"><el-option v-for="item in filterOptions.product_types" :key="item" :label="item" :value="item" /></el-select></label>
        <label><span>申请部门</span><el-select v-model="departments" multiple filterable collapse-tags clearable placeholder="全部部门"><el-option v-for="item in filterOptions.departments" :key="item" :label="item" :value="item" /></el-select></label>
        <label><span>申请人</span><el-select v-model="applicants" multiple filterable collapse-tags clearable placeholder="全部申请人"><el-option v-for="item in filterOptions.applicants" :key="item" :label="item" :value="item" /></el-select></label>
        <label class="keyword-field"><span>单据 / 商品 / 申请人</span><el-input v-model="keyword" clearable placeholder="预留单号、申请人、货号、名称或条码" @keyup.enter="fetchData(true)" /></label>
        <div class="filter-actions"><el-button type="primary" :icon="'Search'" @click="fetchData(true)">查询</el-button><el-button :icon="'RefreshLeft'" @click="resetFilters">重置</el-button></div>
      </div>
      <div class="source-line">
        <span>数据更新时间：{{ formatDate(analysis.scope.updated_at, true) }}</span>
        <span>源数据申请日期：{{ formatDate(analysis.scope.source_min_date) }} 至 {{ formatDate(analysis.scope.source_max_date) }}</span>
        <span>来源：ODS 预留单查询、预留单货品明细</span>
      </div>
    </section>

    <section class="page-tabs-panel">
      <el-tabs v-model="activePage" @tab-change="changeView">
        <el-tab-pane label="总览" name="overview" />
        <el-tab-pane label="申请人分析" name="applicants" />
        <el-tab-pane label="数据明细" name="details" />
      </el-tabs>
    </section>

    <template v-if="activePage === 'overview'">
      <div class="metric-grid reservation-metrics">
        <article v-for="item in metrics" :key="item.label" class="metric-card" :class="{ accent: item.accent }">
          <span>{{ item.label }}</span><strong>{{ item.value }}<small>{{ item.unit }}</small></strong><p>{{ item.note }}</p>
        </article>
      </div>

      <section class="formula-note">
        <strong>数量口径</strong>
        <span>预留数量 = 已释放数量 + 已用数量 + 当前剩余预留。页面展示的是每日同步后的当前快照，不代表各历史月份当时的剩余量。</span>
      </section>

      <div class="chart-grid chart-grid--top">
        <section class="panel chart-panel"><header><div><h2>单据状态结构</h2><p>按预留单数</p></div></header><VChart class="chart" :option="statusOption" autoresize /></section>
        <section class="panel chart-panel chart-panel--wide"><header><div><h2>品牌占用</h2><p>当前剩余预留数量前 10 个品牌</p></div></header><VChart class="chart" :option="brandOption" autoresize /></section>
      </div>

      <div class="chart-grid">
        <section class="panel chart-panel"><header><div><h2>使用结束日期分布</h2><p>仅统计当前剩余数量大于 0 的明细</p></div></header><VChart class="chart" :option="expiryOption" autoresize /></section>
        <section class="panel chart-panel"><header><div><h2>按申请月份汇总</h2><p>预留数量及这些单据当前的剩余数量</p></div></header><VChart class="chart" :option="trendOption" autoresize /></section>
      </div>

      <section class="panel chart-panel applicant-panel"><header><div><h2>申请人预留占用</h2><p>按当前剩余预留数量排列，展示前 12 位申请人</p></div></header><VChart class="chart applicant-chart" :option="applicantOption" autoresize /></section>
    </template>

    <template v-else-if="activePage === 'applicants'">
      <div class="metric-grid reservation-metrics">
        <article v-for="item in applicantMetrics" :key="item.label" class="metric-card" :class="{ accent: item.accent }">
          <span>{{ item.label }}</span><strong>{{ item.value }}<small>{{ item.unit }}</small></strong><p>{{ item.note }}</p>
        </article>
      </div>

      <section class="panel chart-panel applicant-panel"><header><div><h2>申请人预留占用排行</h2><p>按当前剩余预留数量排列，图表展示前 12 位</p></div></header><VChart class="chart applicant-chart" :option="applicantOption" autoresize /></section>

      <section class="panel applicant-table-panel">
        <header><div><h2>申请人汇总</h2><p>汇总当前筛选范围内每位申请人的预留单和数量；总留存率 = 当前剩余 ÷ 预留总量</p></div></header>
        <el-table :data="analysis.applicants" empty-text="当前筛选条件下没有申请人数据" :default-sort="{ prop: 'remaining_quantity', order: 'descending' }">
          <el-table-column prop="name" label="申请人" min-width="140" sortable />
          <el-table-column prop="order_count" label="预留单数" min-width="120" align="right" sortable><template #default="{ row }">{{ formatNumber(row.order_count) }}</template></el-table-column>
          <el-table-column prop="reserved_quantity" label="预留总量" min-width="140" align="right" sortable><template #default="{ row }">{{ formatNumber(row.reserved_quantity) }}</template></el-table-column>
          <el-table-column prop="remaining_quantity" label="当前剩余" min-width="140" align="right" sortable><template #default="{ row }"><strong class="remaining-value">{{ formatNumber(row.remaining_quantity) }}</strong></template></el-table-column>
          <el-table-column prop="retention_rate" label="总留存率" min-width="120" align="right" sortable><template #default="{ row }"><strong class="retention-rate">{{ row.retention_rate == null ? '-' : `${formatNumber(row.retention_rate, 1)}%` }}</strong></template></el-table-column>
          <el-table-column prop="used_quantity" label="已用数量" min-width="140" align="right" sortable><template #default="{ row }">{{ formatNumber(row.used_quantity) }}</template></el-table-column>
          <el-table-column prop="released_quantity" label="已释放数量" min-width="140" align="right" sortable><template #default="{ row }">{{ formatNumber(row.released_quantity) }}</template></el-table-column>
          <el-table-column label="货品" width="110" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="inspectApplicant(row)">查看货品</el-button></template></el-table-column>
        </el-table>
      </section>

      <section class="panel applicant-table-panel">
        <header>
          <div><h2>{{ selectedApplicantLabel ? `${selectedApplicantLabel}的预留货品` : '申请人预留货品' }}</h2><p>{{ selectedApplicantLabel ? '按当前剩余预留数量排序；留存率 = 当前剩余 ÷ 预留总量' : '点击上方申请人行的“查看货品”，或在筛选区选择申请人' }}</p></div>
          <el-button v-if="applicants.length" @click="clearApplicantInspection">查看全部申请人</el-button>
        </header>
        <el-table v-if="applicants.length" :data="analysis.applicant_products" height="520" empty-text="当前申请人没有符合筛选条件的货品" :default-sort="{ prop: 'remaining_quantity', order: 'descending' }">
          <el-table-column prop="product" label="货品名称" min-width="260" fixed show-overflow-tooltip />
          <el-table-column prop="product_code" label="货品编号" width="140" show-overflow-tooltip />
          <el-table-column prop="brand" label="品牌" width="120" show-overflow-tooltip />
          <el-table-column prop="product_type" label="分类" width="90" />
          <el-table-column prop="order_count" label="预留单数" width="110" align="right" sortable><template #default="{ row }">{{ formatNumber(row.order_count) }}</template></el-table-column>
          <el-table-column prop="reserved_quantity" label="预留总量" width="125" align="right" sortable><template #default="{ row }">{{ formatNumber(row.reserved_quantity) }}</template></el-table-column>
          <el-table-column prop="remaining_quantity" label="当前剩余" width="125" align="right" sortable><template #default="{ row }"><strong class="remaining-value">{{ formatNumber(row.remaining_quantity) }}</strong></template></el-table-column>
          <el-table-column prop="retention_rate" label="留存率" width="105" align="right" sortable><template #default="{ row }"><strong class="retention-rate">{{ row.retention_rate == null ? '-' : `${formatNumber(row.retention_rate, 1)}%` }}</strong></template></el-table-column>
          <el-table-column prop="used_quantity" label="已用" width="110" align="right" sortable><template #default="{ row }">{{ formatNumber(row.used_quantity) }}</template></el-table-column>
          <el-table-column prop="released_quantity" label="已释放" width="110" align="right" sortable><template #default="{ row }">{{ formatNumber(row.released_quantity) }}</template></el-table-column>
        </el-table>
        <el-empty v-else description="请选择一位申请人查看其预留货品" :image-size="72" />
      </section>
    </template>

    <section v-else class="panel detail-panel">
      <header><div><h2>预留商品明细</h2><p>一行对应一条预留单商品明细</p></div><el-button :icon="'Refresh'" circle @click="fetchData" /></header>
      <el-table :data="analysis.details" height="560" empty-text="当前筛选条件下没有预留明细">
        <el-table-column prop="reservation_number" label="预留单号" width="170" fixed show-overflow-tooltip />
        <el-table-column prop="status" label="状态" width="90"><template #default="{ row }"><el-tag :type="row.status === '执行中' ? 'success' : 'info'">{{ row.status }}</el-tag></template></el-table-column>
        <el-table-column prop="application_time" label="申请时间" width="150"><template #default="{ row }">{{ formatDate(row.application_time, true) }}</template></el-table-column>
        <el-table-column prop="warehouse" label="预留仓库" width="160" show-overflow-tooltip />
        <el-table-column prop="department" label="申请部门" width="110" show-overflow-tooltip />
        <el-table-column prop="applicant" label="申请人" width="110" show-overflow-tooltip />
        <el-table-column prop="product" label="商品" min-width="260" show-overflow-tooltip />
        <el-table-column prop="product_code" label="货品编号" width="145" show-overflow-tooltip />
        <el-table-column prop="brand" label="品牌" width="110" show-overflow-tooltip />
        <el-table-column prop="product_type" label="分类" width="90" />
        <el-table-column prop="reserved_quantity" label="预留数量" width="110" align="right"><template #default="{ row }">{{ formatNumber(row.reserved_quantity) }}</template></el-table-column>
        <el-table-column prop="remaining_quantity" label="当前剩余" width="110" align="right"><template #default="{ row }"><strong class="remaining-value">{{ formatNumber(row.remaining_quantity) }}</strong></template></el-table-column>
        <el-table-column prop="used_quantity" label="已用" width="100" align="right"><template #default="{ row }">{{ formatNumber(row.used_quantity) }}</template></el-table-column>
        <el-table-column prop="released_quantity" label="已释放" width="100" align="right"><template #default="{ row }">{{ formatNumber(row.released_quantity) }}</template></el-table-column>
        <el-table-column prop="end_time" label="使用结束日期" width="130"><template #default="{ row }">{{ formatDate(row.end_time) }}</template></el-table-column>
      </el-table>
      <div class="table-footer"><el-pagination background layout="total, sizes, prev, pager, next" :total="analysis.pagination.total" :current-page="page" :page-size="pageSize" :page-sizes="[20, 50, 100]" @current-change="changePage" @size-change="changePageSize" /></div>
    </section>
  </div>
</template>

<style scoped>
.reservation-page { --reservation: #2f7d68; --reservation-soft: #eaf5f1; }
.reservation-filter-panel { padding: 18px 20px 14px; }
.filter-grid { display: grid; grid-template-columns: minmax(270px, 1.35fr) repeat(5, minmax(150px, .8fr)); gap: 14px; align-items: end; }
.filter-grid label { display: flex; min-width: 0; flex-direction: column; gap: 7px; color: #667085; font-size: 12px; }
.filter-grid :deep(.el-select), .filter-grid :deep(.el-date-editor), .filter-grid :deep(.el-input) { width: 100%; }
.keyword-field { grid-column: span 2; }
.filter-actions { display: flex; gap: 8px; align-items: end; }
.source-line { display: flex; flex-wrap: wrap; gap: 8px 22px; margin-top: 14px; padding-top: 12px; border-top: 1px solid #edf0f2; color: #7a8695; font-size: 12px; }
.page-tabs-panel { padding: 0 18px; border: 1px solid #e8edf0; border-radius: 12px; background: #fff; }
.page-tabs-panel :deep(.el-tabs__header) { margin: 0; }
.page-tabs-panel :deep(.el-tabs__nav-wrap::after) { height: 1px; background: #edf0f2; }
.page-tabs-panel :deep(.el-tabs__item) { height: 48px; padding: 0 26px; font-weight: 600; }
.reservation-metrics { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.metric-card { padding: 20px; border: 1px solid #e8edf0; border-radius: 14px; background: #fff; box-shadow: 0 3px 14px rgba(31, 52, 47, .04); }
.metric-card > span { color: #667085; font-size: 13px; }
.metric-card strong { display: block; margin-top: 10px; color: #22312d; font-size: 27px; line-height: 1.15; }
.metric-card strong small { margin-left: 5px; color: #7d8a86; font-size: 13px; font-weight: 500; }
.metric-card p { margin: 8px 0 0; color: #98a2b3; font-size: 12px; }
.metric-card.accent { border-color: #b9ddcf; background: linear-gradient(135deg, #f5fbf8, #fff); }
.metric-card.accent strong { color: var(--reservation); }
.formula-note { display: flex; align-items: center; gap: 12px; padding: 12px 16px; border: 1px solid #dcece6; border-radius: 10px; background: var(--reservation-soft); color: #42665b; font-size: 13px; }
.formula-note strong { flex: 0 0 auto; color: #256452; }
.chart-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.chart-grid--top { grid-template-columns: minmax(330px, .75fr) minmax(0, 1.25fr); }
.chart-panel { min-height: 390px; }
.chart-panel header, .detail-panel header, .applicant-table-panel header { display: flex; align-items: flex-start; justify-content: space-between; }
.chart-panel header h2, .detail-panel header h2, .applicant-table-panel header h2 { margin: 0; }
.chart-panel header p, .detail-panel header p, .applicant-table-panel header p { margin: 5px 0 0; color: #98a2b3; font-size: 12px; font-weight: 400; }
.chart { width: 100%; height: 315px; }
.applicant-chart { height: 400px; }
.detail-panel { overflow: hidden; }
.remaining-value { color: var(--reservation); }
.retention-rate { color: #7a9f35; }
.table-footer { display: flex; justify-content: flex-end; padding-top: 16px; }
@media (max-width: 1280px) { .filter-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } .reservation-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 760px) { .filter-grid, .reservation-metrics, .chart-grid, .chart-grid--top { grid-template-columns: 1fr; } .keyword-field { grid-column: auto; } .formula-note { align-items: flex-start; flex-direction: column; } }
</style>
