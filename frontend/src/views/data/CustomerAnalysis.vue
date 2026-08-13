<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import ExportExcelButton from '../../components/common/ExportExcelButton.vue'
import { getSalesCustomerAnalysis } from '../../api/sales'
import CustomerChurnAlerts from './CustomerChurnAlerts.vue'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const activeView = ref(route.query.view === 'churn' ? 'churn' : 'overview')
const page = ref(Number(route.query.page) || 1)
const pageSize = ref(Number(route.query.page_size) || 20)
const initialDirection = ['channel', 'owner'].includes(route.query.direction) ? route.query.direction : 'brand'
function formatLocalDate(value) {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}
function recent30Dates() {
  const end = new Date()
  const start = new Date(end)
  start.setDate(start.getDate() - 29)
  return [formatLocalDate(start), formatLocalDate(end)]
}
const query = reactive({
  direction: initialDirection,
  range: route.query.range || 'last_30',
  dates: route.query.start_date && route.query.end_date ? [route.query.start_date, route.query.end_date] : recent30Dates(),
  brand: String(route.query.brand || (initialDirection === 'brand' ? '资生堂' : '')),
  channel: String(route.query.channel || ''),
  channelType: String(route.query.channel_type || ''),
  owner: String(route.query.owner || ''),
  keyword: String(route.query.keyword || ''),
  frequency: ['first', 'stable', 'high'].includes(route.query.frequency) ? route.query.frequency : 'all',
})
const options = reactive({
  brands: query.brand ? [query.brand] : [],
  channels: query.channel ? [query.channel] : [],
  channelTypes: query.channelType ? [query.channelType] : [],
  owners: query.owner ? [query.owner] : [],
})
const data = ref({
  scope_required: true,
  summary: { customers: 0, repeat_customers: 0, repeat_rate: 0, orders: 0, quantity: 0, paid_amount: 0, identified_amount_rate: 0, avg_order_amount: 0 },
  quality: { identified_orders: 0, unidentified_orders: 0, identified_order_rate: 0, grade: 'C' },
  frequency: [], top_products: [], rows: [], pagination: { total: 0 },
})

const title = computed(() => query.direction === 'brand' ? '品牌客户分析' : query.direction === 'channel' ? '渠道客户分析' : '渠道负责人客户分析')
const scopeText = computed(() => query.direction === 'brand' ? (query.brand || '全部品牌') : query.direction === 'channel' ? (query.channel || query.channelType || '全部渠道') : (query.owner || '全部负责人'))
const description = computed(() => query.direction === 'owner' ? '按渠道档案负责人查看客户频次、销售金额与 Top 商品' : '基于可识别客户监控销售金额、复购频次、购买周期与 Top 商品')
const maxFrequencyCustomers = computed(() => Math.max(1, ...data.value.frequency.map((item) => item.customers)))
const customerListTitle = computed(() => ({ all: '全部客户列表', first: '首购客户列表', stable: '稳定客户列表', high: '高频客户列表' })[query.frequency])

function number(value, digits = 0) {
  return Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}
function money(value) { return `¥ ${number(value, 2)}` }
function intervalText(value) { return value === null || value === undefined ? '仅1单' : `${number(value, 1)} 天` }

function mergeOptions(current, incoming, selected) {
  return [...new Set([...(incoming || []), ...(current || []), ...(selected ? [selected] : [])])]
}

function params() {
  const defaultRecent30 = recent30Dates()
  const usesDefaultRecent30 = query.range === 'last_30' && query.dates.length === 2
    && query.dates[0] === defaultRecent30[0] && query.dates[1] === defaultRecent30[1]
  return {
    direction: query.direction,
    range: usesDefaultRecent30 ? 'last_30' : query.dates.length === 2 ? 'custom' : query.range,
    start_date: usesDefaultRecent30 ? undefined : query.dates[0] || undefined,
    end_date: usesDefaultRecent30 ? undefined : query.dates[1] || undefined,
    brand: query.direction === 'brand' ? query.brand || undefined : undefined,
    channel: query.direction === 'channel' ? query.channel || undefined : undefined,
    channel_type: query.direction === 'channel' ? query.channelType || undefined : undefined,
    owner: query.direction === 'owner' ? query.owner || undefined : undefined,
    keyword: query.keyword.trim() || undefined,
    frequency: query.frequency,
    page: page.value,
    page_size: pageSize.value,
  }
}

const exportFilters = computed(() => {
  const { page: currentPage, page_size: currentPageSize, ...filters } = params()
  return filters
})

async function load() {
  loading.value = true
  try {
    const result = await getSalesCustomerAnalysis(params())
    data.value = result.data
    options.brands = mergeOptions(options.brands, result.data.options?.brands, query.brand)
    options.channels = mergeOptions(options.channels, result.data.options?.channels, query.channel)
    options.channelTypes = mergeOptions(options.channelTypes, result.data.options?.channel_types, query.channelType)
    options.owners = mergeOptions(options.owners, result.data.options?.owners, query.owner)
    router.replace({ query: Object.fromEntries(Object.entries(params()).filter(([, value]) => value !== undefined && value !== '')) })
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '客户分析加载失败')
  } finally {
    loading.value = false
  }
}

function switchDirection(value) {
  query.direction = value
  if (value === 'brand' && !query.brand) query.brand = '资生堂'
  query.keyword = ''
  query.frequency = 'all'
  page.value = 1
  load()
}
function search() { page.value = 1; load() }
function reset() {
  query.range = 'last_30'; query.dates = recent30Dates(); query.brand = query.direction === 'brand' ? '资生堂' : ''; query.channel = ''; query.channelType = ''; query.owner = ''; query.keyword = ''; query.frequency = 'all'; page.value = 1; load()
}
function changePage(value) { page.value = value; load() }
function changePageSize(value) { pageSize.value = value; page.value = 1; load() }
function selectFrequency(value) { query.frequency = value; page.value = 1; load() }
function switchView(value) {
  activeView.value = value
  router.replace({ query: { ...route.query, view: value === 'churn' ? 'churn' : undefined } })
  if (value === 'overview') load()
}

onMounted(() => { if (activeView.value === 'overview') load() })
</script>

<template>
  <div class="customer-page" v-loading="loading">
    <section class="view-tabs">
      <el-segmented :model-value="activeView" :options="[{ label: '客户概览', value: 'overview' }, { label: '流失预警', value: 'churn' }]" @change="switchView" />
      <span>识别曾经高频、近期停止下单的老客户</span>
    </section>
    <template v-if="activeView === 'overview'">
    <section class="customer-hero">
      <div>
        <p>CUSTOMER VALUE & FREQUENCY</p>
        <h1>{{ title }}</h1>
        <span>{{ description }}</span>
      </div>
      <div class="hero-side">
        <strong>{{ scopeText }}</strong>
        <span>{{ data.start_date || '-' }} 至 {{ data.end_date || '-' }}</span>
      </div>
    </section>

    <section class="customer-toolbar">
      <el-segmented :model-value="query.direction" :options="[{ label: '品牌客户分析', value: 'brand' }, { label: '渠道客户分析', value: 'channel' }, { label: '渠道负责人客户分析', value: 'owner' }]" @change="switchDirection" />
      <el-select v-if="query.direction === 'brand'" v-model="query.brand" clearable filterable placeholder="全部品牌" class="scope-select">
        <el-option v-for="item in options.brands" :key="item" :label="item" :value="item" />
      </el-select>
      <el-select v-else-if="query.direction === 'channel'" v-model="query.channel" clearable filterable placeholder="全部渠道" class="scope-select">
        <el-option v-for="item in options.channels" :key="item" :label="item" :value="item" />
      </el-select>
      <el-select v-if="query.direction === 'channel'" v-model="query.channelType" clearable filterable placeholder="渠道分类" class="channel-type-select">
        <el-option v-for="item in options.channelTypes" :key="item" :label="item" :value="item" />
      </el-select>
      <el-select v-if="query.direction === 'owner'" v-model="query.owner" clearable filterable placeholder="选择渠道负责人" class="scope-select">
        <el-option v-for="item in options.owners" :key="item" :label="item" :value="item" />
      </el-select>
      <el-date-picker v-model="query.dates" type="daterange" value-format="YYYY-MM-DD" range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" class="date-filter" />
      <el-input v-model="query.keyword" clearable placeholder="客户编号 / 客户名称" class="keyword-input" @keyup.enter="search" />
      <el-button type="primary" @click="search">查询</el-button>
      <el-button @click="reset">重置</el-button>
    </section>

    <section v-if="data.scope_required && !loading" class="scope-empty">
      <strong>请选择{{ query.direction === 'brand' ? '品牌' : query.direction === 'owner' ? '渠道负责人' : '渠道或渠道分类' }}后开始分析</strong>
      <span>为避免在客户明细上进行无范围的全量扫描，第一版需要指定分析范围。</span>
    </section>

    <template v-else>
    <section class="quality-strip" :class="`grade-${data.quality.grade.toLowerCase()}`">
      <div><span>客户数据可信等级</span><strong>{{ data.quality.grade }}</strong></div>
      <div><span>订单识别率</span><strong>{{ number(data.quality.identified_order_rate, 1) }}%</strong></div>
      <div><span>销售额识别率</span><strong>{{ number(data.summary.identified_amount_rate, 1) }}%</strong></div>
      <p>复购率和客户排行仅统计有稳定客户编号的订单，未识别订单不会合并成同一个客户。</p>
    </section>

    <section class="metric-grid">
      <article><span>可识别客户</span><strong>{{ number(data.summary.customers) }} <small>人</small></strong></article>
      <article><span>复购客户</span><strong>{{ number(data.summary.repeat_customers) }} <small>人</small></strong></article>
      <article class="accent"><span>复购率</span><strong>{{ number(data.summary.repeat_rate, 1) }}%</strong></article>
      <article><span>客户订单数</span><strong>{{ number(data.summary.orders) }} <small>单</small></strong></article>
      <article><span>客户销售额</span><strong>{{ money(data.summary.paid_amount) }}</strong></article>
    </section>

    <section class="overview-grid">
      <article class="panel frequency-panel">
        <header><div><small>ORDER FREQUENCY</small><h2>客户下单频次</h2></div><span>按当前统计期间</span></header>
        <div class="frequency-list">
          <div v-for="item in data.frequency" :key="item.label" class="frequency-item" :class="{ active: query.frequency === item.bucket }" role="button" tabindex="0" @click="selectFrequency(item.bucket)" @keyup.enter="selectFrequency(item.bucket)">
            <span>{{ item.label }}</span><strong>{{ number(item.customers) }} 人</strong>
            <div><i :style="{ width: `${item.customers / maxFrequencyCustomers * 100}%` }"></i></div>
            <small>{{ money(item.paid_amount) }}</small>
          </div>
          <el-empty v-if="!data.frequency.length" description="暂无可识别客户" :image-size="64" />
        </div>
      </article>

      <article class="panel">
        <header><div><small>TOP PRODUCTS</small><h2>客户 Top 商品</h2></div><span>按客户销售额排序</span></header>
        <el-table :data="data.top_products" height="310">
          <el-table-column prop="product_name" label="货品" min-width="210" show-overflow-tooltip />
          <el-table-column prop="customers" label="客户" width="80" sortable />
          <el-table-column prop="orders" label="订单" width="80" sortable />
          <el-table-column prop="quantity" label="数量" width="90" sortable />
          <el-table-column prop="paid_amount" label="销售额" width="130" sortable><template #default="{ row }">{{ money(row.paid_amount) }}</template></el-table-column>
        </el-table>
      </article>
    </section>

    <section class="panel customer-table-panel">
      <header>
        <div><small>CUSTOMER DETAIL</small><h2>{{ customerListTitle }}</h2></div>
        <div class="header-actions">
          <el-segmented :model-value="query.frequency" :options="[{ label: '全部', value: 'all' }, { label: '首购', value: 'first' }, { label: '稳定', value: 'stable' }, { label: '高频', value: 'high' }]" @change="selectFrequency" />
          <ExportExcelButton dataset="customer-analysis" :filters="exportFilters" :total="data.pagination.total" :disabled="data.scope_required" />
        </div>
      </header>
      <el-table :data="data.rows" height="520">
        <el-table-column prop="customer_code" label="客户编号" min-width="150" show-overflow-tooltip sortable />
        <el-table-column prop="customer_name" label="客户名称" min-width="180" show-overflow-tooltip sortable />
        <el-table-column prop="orders" label="订单数" width="95" sortable />
        <el-table-column prop="active_days" label="下单天数" width="105" sortable />
        <el-table-column prop="avg_interval_days" label="平均间隔" width="110" sortable><template #default="{ row }">{{ intervalText(row.avg_interval_days) }}</template></el-table-column>
        <el-table-column prop="last_order_date" label="最近下单" width="120" sortable />
        <el-table-column prop="quantity" label="净销售数量" width="120" sortable />
        <el-table-column prop="paid_amount" label="销售额" width="145" sortable><template #default="{ row }"><strong class="amount">{{ money(row.paid_amount) }}</strong></template></el-table-column>
      </el-table>
      <footer><span>共 {{ number(data.pagination.total) }} 位可识别客户</span><el-pagination background layout="sizes, prev, pager, next" :total="data.pagination.total" :current-page="page" :page-size="pageSize" :page-sizes="[20, 50, 100]" @current-change="changePage" @size-change="changePageSize" /></footer>
    </section>
    </template>
    </template>
    <CustomerChurnAlerts v-else />
  </div>
</template>

<style scoped>
.customer-page { display: grid; gap: 14px; color: #172033; }
.view-tabs { display: flex; align-items: center; justify-content: space-between; padding: 10px 12px; background: #fff; border: 1px solid var(--border); border-radius: 8px; }.view-tabs > span { color: #7a8699; font-size: 12px; }
.customer-hero, .customer-toolbar, .panel, .metric-grid article { background: #fff; border: 1px solid var(--border); border-radius: 8px; }
.customer-hero { display: flex; align-items: center; justify-content: space-between; min-height: 116px; padding: 22px 28px; border-top: 3px solid var(--theme-primary); background: linear-gradient(108deg, #fff 65%, var(--theme-soft)); }
.customer-hero p, .panel header small { margin: 0 0 5px; color: var(--theme-primary); font-size: 10px; font-weight: 800; letter-spacing: .1em; }
.customer-hero h1 { margin: 0 0 5px; font-size: 27px; }.customer-hero > div > span, .hero-side span { color: #7a8699; font-size: 12px; }
.hero-side { display: grid; justify-items: end; gap: 6px; }.hero-side strong { color: var(--theme-strong); }
.customer-toolbar { display: flex; align-items: center; gap: 9px; padding: 10px 12px; }.customer-toolbar :deep(.scope-select) { flex: 0 0 190px; width: 190px; }.customer-toolbar :deep(.channel-type-select) { flex: 0 0 150px; width: 150px; }.customer-toolbar :deep(.date-filter) { flex: 0 0 238px !important; width: 238px !important; max-width: 238px; }.customer-toolbar :deep(.keyword-input) { flex: 0 0 210px; width: 210px; }
.scope-empty { display: grid; place-items: center; gap: 8px; min-height: 260px; padding: 32px; text-align: center; background: #fff; border: 1px dashed var(--theme-soft-strong); border-radius: 8px; }.scope-empty strong { color: var(--theme-strong); font-size: 18px; }.scope-empty span { color: #7a8699; font-size: 12px; }
.quality-strip { display: grid; grid-template-columns: 150px 150px 150px 1fr; align-items: center; gap: 14px; padding: 13px 18px; background: var(--theme-soft); border: 1px solid var(--theme-soft-strong); border-radius: 8px; }
.quality-strip div { display: grid; gap: 3px; }.quality-strip span, .quality-strip p { color: #667085; font-size: 11px; }.quality-strip strong { color: var(--theme-strong); font-size: 19px; }.quality-strip p { margin: 0; line-height: 1.55; }
.quality-strip.grade-c { background: #fff7e8; border-color: #f1d69c; }.quality-strip.grade-c strong { color: #946200; }
.metric-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; }.metric-grid article { display: grid; align-content: center; gap: 9px; min-width: 0; min-height: 100px; padding: 16px 18px; border-top: 3px solid var(--theme-soft-strong); }.metric-grid span { color: #667085; font-size: 12px; }.metric-grid strong { overflow: hidden; font-size: 21px; text-overflow: ellipsis; white-space: nowrap; }.metric-grid small { color: #98a2b3; font-size: 11px; }.metric-grid .accent { color: #fff; background: linear-gradient(135deg, var(--theme-strong), var(--theme-primary)); border-color: var(--theme-strong); }.metric-grid .accent :is(span, strong) { color: #fff; }
.overview-grid { display: grid; grid-template-columns: minmax(300px, .72fr) minmax(0, 1.28fr); gap: 12px; }.panel { min-width: 0; overflow: hidden; }.panel header { display: flex; align-items: center; justify-content: space-between; min-height: 62px; padding: 12px 16px; border-bottom: 1px solid var(--border); }.panel header h2 { margin: 0; font-size: 15px; }.panel header > span { color: #98a2b3; font-size: 11px; }
.frequency-list { display: grid; gap: 10px; padding: 14px; }.frequency-list > div { display: grid; grid-template-columns: 1fr auto; gap: 7px 12px; }.frequency-list span { color: #667085; font-size: 12px; font-weight: 700; }.frequency-list strong { font-size: 14px; }.frequency-list div div { grid-column: 1 / -1; height: 7px; overflow: hidden; background: var(--theme-soft); border-radius: 999px; }.frequency-list i { display: block; height: 100%; background: linear-gradient(90deg, var(--theme-strong), var(--theme-secondary)); border-radius: inherit; }.frequency-list small { grid-column: 1 / -1; color: #8a96a5; }.frequency-item { padding: 10px; cursor: pointer; border: 1px solid transparent; border-radius: 7px; transition: .18s ease; }.frequency-item:hover, .frequency-item.active { background: var(--theme-soft); border-color: var(--theme-soft-strong); }.frequency-item:focus-visible { outline: 2px solid var(--theme-primary); outline-offset: 2px; }
.customer-table-panel footer { display: flex; align-items: center; justify-content: space-between; min-height: 58px; padding: 10px 16px; color: #8a96a5; font-size: 12px; border-top: 1px solid var(--border); }.amount { color: var(--theme-strong); }
@media (max-width: 1180px) { .customer-toolbar { flex-wrap: wrap; }.metric-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }.quality-strip { grid-template-columns: repeat(3, 1fr); }.quality-strip p { grid-column: 1 / -1; } }
@media (max-width: 800px) { .view-tabs { align-items: flex-start; flex-direction: column; gap: 8px; }.customer-hero { align-items: flex-start; flex-direction: column; gap: 14px; }.hero-side { justify-items: start; }.overview-grid { grid-template-columns: 1fr; }.metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }.customer-toolbar > * { width: 100% !important; }.quality-strip { grid-template-columns: 1fr; }.customer-table-panel footer { align-items: flex-start; flex-direction: column; gap: 10px; } }
</style>
