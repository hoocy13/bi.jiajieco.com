<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import ExportExcelButton from '../../components/common/ExportExcelButton.vue'
import { getSalesCustomerChurnAlerts } from '../../api/sales'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const page = ref(Number(route.query.alert_page) || 1)
const pageSize = ref(Number(route.query.alert_page_size) || 20)
const initialDirection = ['channel', 'owner'].includes(route.query.alert_direction) ? route.query.alert_direction : 'brand'
const query = reactive({
  direction: initialDirection,
  brand: String(route.query.alert_brand || (initialDirection === 'brand' ? '资生堂' : '')),
  channel: String(route.query.alert_channel || ''),
  channelType: String(route.query.alert_channel_type || ''),
  owner: String(route.query.alert_owner || ''),
  keyword: String(route.query.alert_keyword || ''),
  inactiveMonths: [3, 6, 12].includes(Number(route.query.inactive_months)) ? Number(route.query.inactive_months) : 3,
  minHistoricalOrders: Math.max(2, Number(route.query.min_historical_orders) || 4),
})
const options = reactive({ brands: query.brand ? [query.brand] : [], channels: [], channelTypes: [], owners: [] })
const data = ref({
  scope_required: true,
  summary: { alert_customers: 0, critical_customers: 0, high_value_customers: 0, historical_amount: 0 },
  rows: [], pagination: { total: 0 },
})

const scopeText = computed(() => query.direction === 'brand' ? (query.brand || '全部品牌') : query.direction === 'channel' ? (query.channel || query.channelType || '全部渠道') : (query.owner || '全部负责人'))
const periodText = computed(() => data.value.history_start ? `历史高频期 ${data.value.history_start} 至 ${data.value.history_end}` : '历史高频期按失联窗口前 12 个月计算')

function number(value, digits = 0) { return Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits }) }
function money(value) { return `¥ ${number(value, 2)}` }
function intervalText(value) { return value === null || value === undefined ? '-' : `${number(value, 1)} 天` }
function mergeOptions(current, incoming, selected) { return [...new Set([...(incoming || []), ...(current || []), ...(selected ? [selected] : [])])] }
function levelText(level) { return ({ critical: '严重流失', high: '高度预警', watch: '待维护' })[level] || '待维护' }
function levelType(level) { return ({ critical: 'danger', high: 'warning', watch: 'info' })[level] || 'info' }

function params() {
  return {
    direction: query.direction,
    brand: query.direction === 'brand' ? query.brand || undefined : undefined,
    channel: query.direction === 'channel' ? query.channel || undefined : undefined,
    channel_type: query.direction === 'channel' ? query.channelType || undefined : undefined,
    owner: query.direction === 'owner' ? query.owner || undefined : undefined,
    keyword: query.keyword.trim() || undefined,
    inactive_months: query.inactiveMonths,
    min_historical_orders: query.minHistoricalOrders,
    page: page.value,
    page_size: pageSize.value,
  }
}
const exportFilters = computed(() => {
  const { page: currentPage, page_size: currentPageSize, ...filters } = params()
  return filters
})
function urlParams() {
  const values = params()
  return {
    view: 'churn', alert_direction: values.direction, alert_brand: values.brand,
    alert_channel: values.channel, alert_channel_type: values.channel_type, alert_owner: values.owner,
    alert_keyword: values.keyword, inactive_months: values.inactive_months,
    min_historical_orders: values.min_historical_orders, alert_page: values.page, alert_page_size: values.page_size,
  }
}
async function load() {
  loading.value = true
  try {
    const result = await getSalesCustomerChurnAlerts(params())
    data.value = result.data
    options.brands = mergeOptions(options.brands, result.data.options?.brands, query.brand)
    options.channels = mergeOptions(options.channels, result.data.options?.channels, query.channel)
    options.channelTypes = mergeOptions(options.channelTypes, result.data.options?.channel_types, query.channelType)
    options.owners = mergeOptions(options.owners, result.data.options?.owners, query.owner)
    router.replace({ query: Object.fromEntries(Object.entries(urlParams()).filter(([, value]) => value !== undefined && value !== '')) })
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '客户流失预警加载失败')
  } finally { loading.value = false }
}
function switchDirection(value) {
  query.direction = value
  if (value === 'brand' && !query.brand) query.brand = '资生堂'
  query.keyword = ''; page.value = 1; load()
}
function search() { page.value = 1; load() }
function reset() {
  query.inactiveMonths = 3; query.minHistoricalOrders = 4; query.brand = query.direction === 'brand' ? '资生堂' : ''
  query.channel = ''; query.channelType = ''; query.owner = ''; query.keyword = ''; page.value = 1; load()
}
function changePage(value) { page.value = value; load() }
function changePageSize(value) { pageSize.value = value; page.value = 1; load() }
onMounted(load)
</script>

<template>
  <div class="churn-page" v-loading="loading">
    <section class="churn-hero">
      <div><p>RETENTION WATCHLIST</p><h1>客户流失预警</h1><span>追踪曾经高频下单、近期停止购买的老客户</span></div>
      <div class="hero-side"><strong>{{ scopeText }}</strong><span>数据截至 {{ data.as_of || '-' }}</span></div>
    </section>

    <section class="churn-toolbar">
      <el-segmented :model-value="query.direction" :options="[{ label: '品牌客户', value: 'brand' }, { label: '渠道客户', value: 'channel' }, { label: '负责人客户', value: 'owner' }]" @change="switchDirection" />
      <el-select v-if="query.direction === 'brand'" v-model="query.brand" clearable filterable placeholder="选择品牌" class="scope-select"><el-option v-for="item in options.brands" :key="item" :label="item" :value="item" /></el-select>
      <el-select v-else-if="query.direction === 'channel'" v-model="query.channel" clearable filterable placeholder="全部渠道" class="scope-select"><el-option v-for="item in options.channels" :key="item" :label="item" :value="item" /></el-select>
      <el-select v-if="query.direction === 'channel'" v-model="query.channelType" clearable filterable placeholder="渠道分类" class="type-select"><el-option v-for="item in options.channelTypes" :key="item" :label="item" :value="item" /></el-select>
      <el-select v-if="query.direction === 'owner'" v-model="query.owner" clearable filterable placeholder="选择负责人" class="scope-select"><el-option v-for="item in options.owners" :key="item" :label="item" :value="item" /></el-select>
      <el-select v-model="query.inactiveMonths" class="period-select"><el-option label="近3个月未下单" :value="3" /><el-option label="近6个月未下单" :value="6" /><el-option label="近12个月未下单" :value="12" /></el-select>
      <el-input-number v-model="query.minHistoricalOrders" :min="2" :max="100" controls-position="right" class="orders-input" />
      <span class="orders-label">历史至少下单</span>
      <el-input v-model="query.keyword" clearable placeholder="客户编号 / 客户名称" class="keyword-input" @keyup.enter="search" />
      <el-button type="primary" @click="search">查询</el-button><el-button @click="reset">重置</el-button>
    </section>

    <section v-if="data.scope_required && !loading" class="scope-empty">
      <strong>请选择{{ query.direction === 'brand' ? '品牌' : query.direction === 'channel' ? '渠道或渠道分类' : '负责人' }}后查看流失预警</strong><span>历史客户明细需要限定业务范围，以保证查询速度。</span>
    </section>
    <template v-else>
      <section class="rule-strip"><strong>识别规则</strong><span>{{ periodText }}，至少 {{ query.minHistoricalOrders }} 单；从 {{ data.cutoff_date || '-' }} 起没有新订单。</span></section>
      <section class="metric-grid">
        <article class="accent"><span>待维护客户</span><strong>{{ number(data.summary.alert_customers) }} <small>人</small></strong></article>
        <article><span>严重流失（≥365天）</span><strong>{{ number(data.summary.critical_customers) }} <small>人</small></strong></article>
        <article><span>高价值客户</span><strong>{{ number(data.summary.high_value_customers) }} <small>人</small></strong></article>
        <article><span>历史贡献金额</span><strong>{{ money(data.summary.historical_amount) }}</strong></article>
      </section>
      <section class="panel alert-table">
        <header>
          <div><small>CHURN ALERT DETAIL</small><h2>重点维护名单</h2></div>
          <div class="header-actions"><span>高价值按当前名单历史金额平均值识别</span><ExportExcelButton dataset="customer-churn-alerts" :filters="exportFilters" :total="data.pagination.total" :disabled="data.scope_required" /></div>
        </header>
        <el-table :data="data.rows" height="540">
          <el-table-column label="预警" width="105"><template #default="{ row }"><el-tag :type="levelType(row.alert_level)" effect="light">{{ levelText(row.alert_level) }}</el-tag></template></el-table-column>
          <el-table-column prop="customer_code" label="客户编号" min-width="145" show-overflow-tooltip sortable />
          <el-table-column prop="customer_name" label="客户名称" min-width="180" show-overflow-tooltip sortable />
          <el-table-column prop="historical_orders" label="历史订单" width="105" sortable />
          <el-table-column prop="avg_interval_days" label="平均间隔" width="110" sortable><template #default="{ row }">{{ intervalText(row.avg_interval_days) }}</template></el-table-column>
          <el-table-column prop="last_order_date" label="最近下单" width="120" sortable />
          <el-table-column prop="inactive_days" label="未下单天数" width="120" sortable><template #default="{ row }"><strong class="inactive">{{ number(row.inactive_days) }} 天</strong></template></el-table-column>
          <el-table-column prop="historical_amount" label="历史销售额" width="145" sortable><template #default="{ row }"><strong class="amount">{{ money(row.historical_amount) }}</strong><el-tag v-if="row.is_high_value" size="small" type="danger" effect="plain">高价值</el-tag></template></el-table-column>
        </el-table>
        <footer><span>共 {{ number(data.pagination.total) }} 位待维护客户</span><el-pagination background layout="sizes, prev, pager, next" :total="data.pagination.total" :current-page="page" :page-size="pageSize" :page-sizes="[20, 50, 100]" @current-change="changePage" @size-change="changePageSize" /></footer>
      </section>
    </template>
  </div>
</template>

<style scoped>
.churn-page { display: grid; gap: 14px; color: #172033; }.churn-hero,.churn-toolbar,.panel,.metric-grid article { background:#fff; border:1px solid var(--border); border-radius:8px; }
.churn-hero { display:flex; align-items:center; justify-content:space-between; min-height:116px; padding:22px 28px; border-top:3px solid var(--theme-primary); background:linear-gradient(108deg,#fff 65%,var(--theme-soft)); }.churn-hero p,.panel header small { margin:0 0 5px; color:var(--theme-primary); font-size:10px; font-weight:800; letter-spacing:.1em; }.churn-hero h1 { margin:0 0 5px; font-size:27px; }.churn-hero span,.hero-side span { color:#7a8699; font-size:12px; }.hero-side { display:grid; justify-items:end; gap:6px; }.hero-side strong { color:var(--theme-strong); }
.churn-toolbar { display:flex; align-items:center; gap:8px; padding:10px 12px; }.scope-select { width:175px; }.type-select { width:140px; }.period-select { width:155px; }.orders-input { width:100px; }.orders-label { margin-left:-4px; color:#667085; font-size:11px; white-space:nowrap; }.keyword-input { width:195px; }
.rule-strip { display:flex; align-items:center; gap:12px; padding:13px 18px; color:#667085; font-size:12px; background:#fff7e8; border:1px solid #f1d69c; border-radius:8px; }.rule-strip strong { color:#946200; }
.metric-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; }.metric-grid article { display:grid; align-content:center; gap:9px; min-height:100px; padding:16px 18px; border-top:3px solid var(--theme-soft-strong); }.metric-grid span { color:#667085; font-size:12px; }.metric-grid strong { overflow:hidden; font-size:21px; text-overflow:ellipsis; white-space:nowrap; }.metric-grid small { color:#98a2b3; font-size:11px; }.metric-grid .accent { color:#fff; background:linear-gradient(135deg,var(--theme-strong),var(--theme-primary)); border-color:var(--theme-strong); }.metric-grid .accent :is(span,strong,small) { color:#fff; }
.panel { min-width:0; overflow:hidden; }.panel header { display:flex; align-items:center; justify-content:space-between; min-height:62px; padding:12px 16px; border-bottom:1px solid var(--border); }.panel header h2 { margin:0; font-size:15px; }.panel header > span { color:#98a2b3; font-size:11px; }.alert-table footer { display:flex; align-items:center; justify-content:space-between; min-height:58px; padding:10px 16px; color:#8a96a5; font-size:12px; border-top:1px solid var(--border); }.amount { display:inline-block; margin-right:6px; color:var(--theme-strong); }.inactive { color:#b54708; }
.scope-empty { display:grid; place-items:center; gap:8px; min-height:260px; padding:32px; text-align:center; background:#fff; border:1px dashed var(--theme-soft-strong); border-radius:8px; }.scope-empty strong { color:var(--theme-strong); font-size:18px; }.scope-empty span { color:#7a8699; font-size:12px; }
@media (max-width:1180px) { .churn-toolbar { flex-wrap:wrap; }.metric-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } }
@media (max-width:800px) { .churn-hero { align-items:flex-start; flex-direction:column; gap:14px; }.hero-side { justify-items:start; }.churn-toolbar > * { width:100% !important; }.orders-label { margin-left:0; }.metric-grid { grid-template-columns:1fr; }.alert-table footer { align-items:flex-start; flex-direction:column; gap:10px; } }
</style>
