<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowRight, Download, InfoFilled, RefreshLeft, Search } from '@element-plus/icons-vue'
import { useAuthStore } from '../../stores/auth'
import { exportSalesProfitAnalysis, getSalesProfitAnalysis } from '../../api/salesProfit'
import MonthlyProfitReview from '../../components/reports/MonthlyProfitReview.vue'
import ProfitPageTabs from '../../components/reports/ProfitPageTabs.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const canExport = computed(() => auth.hasPermission('data.export'))
const viewOptions = [{ label: '经营毛利', value: 'review' }, { label: '毛利分析', value: 'profit' }, { label: '客户分析', value: 'prices' }]
const activeView = computed(() => ['profit', 'prices'].includes(route.query.view) ? route.query.view : 'review')
const groupOptions = [
  { label: '销售人', value: 'owner' }, { label: '品牌', value: 'brand' },
  { label: '渠道', value: 'channel' }, { label: '客户', value: 'customer' }, { label: '商品', value: 'product' },
]
const defaultTypes = ['正装', '小样']
const sortKeys = ['owner', 'customer_name', 'product_code', 'product_name', 'brand', 'product_type', 'channel', 'channel_type', 'quantity', 'sale_quantity', 'paid_amount', 'avg_price', 'core_cost', 'estimated_cost', 'estimated_profit', 'margin_rate', 'reference_price', 'price_delta', 'price_delta_rate', 'price_effect_amount']
const filters = reactive({})
const applied = ref(null)
const data = ref({ summary: {}, breakdown: [], rows: [], options: {}, pagination: { total: 0 } })
const loading = ref(false)
const exporting = ref(false)
const error = ref('')
let requestSequence = 0

function values(value) { return (Array.isArray(value) ? value : value ? [value] : []).map(String).filter(Boolean) }
function one(value, fallback = '') { return values(value)[0] || fallback }
function choice(value, options, fallback) { return options.includes(one(value)) ? one(value) : fallback }
function positiveInt(value, fallback) { const number = Number(one(value)); return Number.isInteger(number) && number > 0 ? number : fallback }
function readQuery(query) {
  const view = choice(query.view, ['profit', 'prices'], 'profit')
  return {
    view, range: query.start_date && query.end_date ? 'custom' : choice(query.range, ['month', 'custom'], 'month'),
    dates: query.start_date && query.end_date ? [one(query.start_date), one(query.end_date)] : [],
    owner: one(query.owner), brands: values(query.brand), channels: values(query.channel),
    channelType: choice(query.channel_type, ['all', 'online', 'offline'], 'all'),
    productTypes: one(query.product_type) === '__all__' ? [] : values(query.product_type).length ? values(query.product_type) : [...defaultTypes],
    customerKeyword: one(query.customer_keyword), keyword: one(query.keyword),
    costStatus: choice(query.cost_status, ['all', 'priced', 'missing', 'loss'], 'all'),
    groupBy: choice(query.group_by, groupOptions.map((item) => item.value), 'owner'),
    benchmark: view === 'prices' ? choice(query.benchmark, ['company', 'peers', 'previous'], 'company') : 'company',
    priceDirection: view === 'prices' ? choice(query.price_direction, ['all', 'above', 'below', 'unmatched'], 'all') : 'all',
    page: positiveInt(query.page, 1), pageSize: [20, 50, 100].includes(Number(one(query.page_size))) ? Number(one(query.page_size)) : 50,
    sortBy: choice(query.sort_by, sortKeys, view === 'prices' ? 'price_effect_amount' : 'estimated_profit'),
    sortOrder: choice(query.sort_order, ['asc', 'desc'], view === 'prices' ? 'asc' : 'desc'),
  }
}
function copyFilters(value) { return { ...value, dates: [...(value.dates || [])], brands: [...value.brands], channels: [...value.channels], productTypes: [...value.productTypes] } }
function paramsFor(value, withPagination = true) {
  const params = {
    view: value.view, range: value.range, owner: value.owner.trim(), brand: value.brands,
    channel_type: value.channelType, channel: value.channels, product_type: value.productTypes.length ? value.productTypes : ['__all__'],
    customer_keyword: value.customerKeyword.trim(), keyword: value.keyword.trim(), cost_status: value.costStatus,
    group_by: value.groupBy, benchmark: value.benchmark, price_direction: value.priceDirection,
    sort_by: value.sortBy, sort_order: value.sortOrder,
  }
  if (value.range === 'custom') {
    params.start_date = value.dates[0]
    params.end_date = value.dates[1]
  }
  if (withPagination) { params.page = value.page; params.page_size = value.pageSize }
  return params
}
function urlFor(value) {
  const query = {}
  Object.entries(paramsFor(value)).forEach(([key, item]) => {
    if (item === '' || item == null || (Array.isArray(item) && !item.length)) return
    query[key] = Array.isArray(item) ? item : String(item)
  })
  return query
}
function validDates(value) {
  return value.range !== 'custom' || (Array.isArray(value.dates) && value.dates.length === 2 && value.dates.every((date) => /^\d{4}-\d{2}-\d{2}$/.test(date)) && value.dates[0] <= value.dates[1])
}
const canSearch = computed(() => validDates(filters))
function disabledDate(date) {
  const day = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
  return Boolean((data.value.source_start_date && day < data.value.source_start_date) || (data.value.as_of && day > data.value.as_of))
}

async function load(value) {
  const sequence = ++requestSequence
  loading.value = true
  error.value = ''
  try {
    const response = await getSalesProfitAnalysis(paramsFor(value))
    if (sequence !== requestSequence) return
    const result = response.data || {}
    data.value = { ...result, summary: result.summary || {}, breakdown: result.breakdown || [], rows: result.rows || [], options: result.options || {}, pagination: result.pagination || { total: 0 } }
  } catch (failure) {
    if (sequence !== requestSequence) return
    error.value = failure.response?.data?.detail || failure.response?.data?.message || '数据加载失败，请重试'
    if (typeof error.value !== 'string') error.value = '筛选条件无效，请调整后重试'
  } finally {
    if (sequence === requestSequence) loading.value = false
  }
}
async function commit(value, replace = false) {
  if (!validDates(value)) { ElMessage.warning('请选择完整的起止日期'); return }
  const query = urlFor(value)
  const target = router.resolve({ path: route.path, query })
  if (target.fullPath === route.fullPath) await load(applied.value)
  else await router[replace ? 'replace' : 'push']({ path: route.path, query })
}
function search() { commit({ ...copyFilters(filters), page: 1 }) }
function reset() { commit(readQuery({ view: filters.view }), true) }
function changeView(view) {
  if (view === 'review') { router.push({ path: route.path, query: { view } }); return }
  if (activeView.value === 'review') { commit(readQuery({ view })); return }
  commit({ ...copyFilters(applied.value), view, page: 1, benchmark: view === 'profit' ? 'company' : applied.value.benchmark, priceDirection: view === 'profit' ? 'all' : applied.value.priceDirection, sortBy: view === 'prices' ? 'price_effect_amount' : 'estimated_profit', sortOrder: view === 'prices' ? 'asc' : 'desc' })
}
function changeGroup(groupBy) { commit({ ...copyFilters(applied.value), groupBy, page: 1 }) }
function changePage(page) { commit({ ...copyFilters(applied.value), page }) }
function changePageSize(pageSize) { commit({ ...copyFilters(applied.value), pageSize, page: 1 }) }
function changeSort({ prop, order }) {
  if (!applied.value) return
  const view = applied.value.view
  commit({ ...copyFilters(applied.value), page: 1, sortBy: order && sortKeys.includes(prop) ? prop : view === 'prices' ? 'price_effect_amount' : 'estimated_profit', sortOrder: order ? order === 'ascending' ? 'asc' : 'desc' : view === 'prices' ? 'asc' : 'desc' })
}
function drillDown(row) {
  if (!canDrill(row)) return
  const next = { ...copyFilters(applied.value), page: 1 }
  const group = next.groupBy
  if (group === 'owner') { next.owner = row.key; next.groupBy = 'brand' }
  if (group === 'brand') { next.brands = [row.key]; next.groupBy = 'customer' }
  if (group === 'channel') { next.channels = [row.key]; next.groupBy = 'customer' }
  if (group === 'customer') { next.customerKeyword = row.key; next.groupBy = 'product' }
  if (group === 'product') next.keyword = row.key
  commit(next)
}
function canDrill(row) { return Boolean(row.key && row.key !== '-') }
async function exportRows() {
  exporting.value = true
  try {
    const snapshot = copyFilters(applied.value)
    const dates = [data.value.start_date, data.value.end_date]
    const blob = await exportSalesProfitAnalysis(paramsFor(snapshot, false))
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${snapshot.view === 'prices' ? '客户价格对比' : '销售预估毛利'}_${dates[0]}_${dates[1]}.xlsx`
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch {
    ElMessage.error('导出失败，请稍后重试')
  } finally { exporting.value = false }
}
function number(value, digits = 0) {
  if (value == null || !Number.isFinite(Number(value))) return '-'
  return Number(value).toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}
function money(value) { return number(value, 2) }
function percent(value) { return value == null ? '-' : `${number(value, 1)}%` }
function signed(value, isPercent = false) {
  if (value == null) return '-'
  return `${Number(value) > 0 ? '+' : ''}${isPercent ? percent(value) : money(value)}`
}
function optionValues(key) {
  const items = data.value.options[key] || (key === 'product_types' ? defaultTypes : [])
  return items.map((item) => typeof item === 'string' ? { label: item, value: item } : { label: item.label || item.name || item.value, value: item.value || item.name || item.label })
}
const summary = computed(() => data.value.summary)
const metrics = computed(() => [
  { label: '正向销售额', value: money(summary.value.sale_amount), unit: '元', hint: '正常正向交易的分摊销售额，不包含退货红冲。' },
  { label: '预估毛利', value: money(summary.value.estimated_profit), unit: '元', primary: true, hint: '已匹配成本的正向销售额减正向销售数量乘当前核心成本价；退货红冲不参与毛利计算。' },
  { label: '预估毛利率', value: percent(summary.value.margin_rate), hint: '预估毛利除以已匹配核心成本的正向销售额；退货红冲和缺成本商品不计入分母。' },
  { label: '成本覆盖率', value: percent(summary.value.cost_coverage_rate), hint: '按正向销售额计算成本匹配覆盖；缺成本商品不按零成本计算。' },
  { label: '低于成本销售额', value: money(summary.value.loss_sales_amount), unit: '元', hint: '按客户、货品和具体渠道的正向成交加权均价判断；均价低于当前核心成本的正向销售额，不代表逐笔亏损金额。' },
  { label: '缺成本销售额', value: money(summary.value.missing_cost_amount), unit: '元', hint: '当前筛选范围内未匹配核心成本价的正向销售额。' },
])
const periodLabel = computed(() => data.value.start_date && data.value.end_date ? `${data.value.start_date} 至 ${data.value.end_date}` : '本月')
const groupLabel = computed(() => groupOptions.find((item) => item.value === applied.value?.groupBy)?.label || '销售人')
const benchmarkLabel = computed(() => ({ company: '公司同渠道均价', peers: '自己其他客户均价', previous: '自己上期均价' })[applied.value?.benchmark] || '')
const detailColumns = computed(() => {
  const identity = [
    { key: 'owner', label: '销售人', width: 105 }, { key: 'customer_name', label: '客户', width: 170 },
    { key: 'product_code', label: '货品编号', width: 140 }, { key: 'product_name', label: '货品名称', width: 270 },
    { key: 'brand', label: '品牌', width: 110 }, { key: 'product_type', label: '分类', width: 85 }, { key: 'channel', label: '渠道', width: 150 },
  ]
  if (applied.value?.view === 'prices') return [...identity,
    { key: 'sale_quantity', label: '成交数量', width: 115, kind: 'integer', strong: true },
    { key: 'avg_price', label: '成交均价', width: 120, kind: 'money', strong: true },
    { key: 'reference_price', label: '参考均价', width: 120, kind: 'money' },
    { key: 'price_delta', label: '价差', width: 115, kind: 'signed' },
    { key: 'price_delta_rate', label: '价差比例', width: 115, kind: 'signedPercent' },
    { key: 'price_effect_amount', label: '价差金额', width: 135, kind: 'signed' },
    { key: 'core_cost', label: '核心成本价', width: 125, kind: 'money' },
    { key: 'margin_rate', label: '预估毛利率', width: 125, kind: 'percent' },
  ]
  return [...identity,
    { key: 'sale_quantity', label: '正向销售数量', width: 125, kind: 'integer', strong: true },
    { key: 'sale_amount', label: '正向销售额', width: 150, kind: 'money', strong: true },
    { key: 'core_cost', label: '核心成本价', width: 125, kind: 'money' },
    { key: 'estimated_cost', label: '预估成本', width: 145, kind: 'money' },
    { key: 'estimated_profit', label: '预估毛利', width: 145, kind: 'money', strong: true },
    { key: 'margin_rate', label: '预估毛利率', width: 125, kind: 'percent' },
  ]
})
function cellValue(row, column) {
  const value = row[column.key]
  if (column.kind === 'money') return money(value)
  if (column.kind === 'integer') return number(value)
  if (column.kind === 'percent') return percent(value)
  if (column.kind === 'signed') return signed(value)
  if (column.kind === 'signedPercent') return signed(value, true)
  return value || '-'
}
function rowKey(row) { return JSON.stringify([row.owner, row.customer_code, row.product_code, row.brand, row.channel, row.product_type]) }
watch(() => route.fullPath, () => {
  if (activeView.value === 'review') { ++requestSequence; loading.value = false; return }
  const next = readQuery(route.query)
  Object.assign(filters, copyFilters(next))
  applied.value = copyFilters(next)
  if (validDates(next)) load(next)
  else { ++requestSequence; loading.value = false; error.value = '请选择完整的起止日期' }
}, { immediate: true })
onBeforeUnmount(() => { ++requestSequence })
</script>

<template>
  <MonthlyProfitReview v-if="activeView === 'review'"><template #pages><ProfitPageTabs :view="activeView" @change="changeView" /></template></MonthlyProfitReview>
  <div v-else class="page-stack sales-profit-page">
    <section class="toolbar-panel profit-toolbar" aria-label="销售毛利与价格筛选">
      <div class="filter-controls">
        <el-segmented v-model="filters.range" :options="[{ label: '本月', value: 'month' }, { label: '自定义', value: 'custom' }]" aria-label="统计区间" @change="(value) => { if (value === 'month') filters.dates = [] }" />
        <el-date-picker v-model="filters.dates" class="profit-dates" type="daterange" value-format="YYYY-MM-DD" range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" :disabled-date="disabledDate" unlink-panels aria-label="起止日期" @change="filters.range = 'custom'" />
        <el-select v-model="filters.owner" class="filter-owner" filterable clearable placeholder="全部销售人" aria-label="销售人"><el-option v-for="item in optionValues('owners')" :key="item.value" :label="item.label" :value="item.value" /></el-select>
        <el-select v-model="filters.brands" class="filter-multi" multiple collapse-tags collapse-tags-tooltip :max-collapse-tags="1" filterable clearable placeholder="全部品牌" aria-label="品牌">
          <el-option v-for="item in optionValues('brands')" :key="item.value" :label="item.label" :value="item.value"><span class="filter-option-content"><el-checkbox :model-value="filters.brands.includes(item.value)" tabindex="-1" /><span>{{ item.label }}</span></span></el-option>
        </el-select>
        <el-select v-model="filters.channelType" class="filter-type" aria-label="线上线下"><el-option label="线上 / 线下" value="all" /><el-option label="线上" value="online" /><el-option label="线下" value="offline" /></el-select>
        <el-select v-model="filters.channels" class="filter-multi" multiple collapse-tags collapse-tags-tooltip :max-collapse-tags="1" filterable clearable placeholder="全部渠道" aria-label="具体渠道">
          <el-option v-for="item in optionValues('channels')" :key="item.value" :label="item.label" :value="item.value"><span class="filter-option-content"><el-checkbox :model-value="filters.channels.includes(item.value)" tabindex="-1" /><span>{{ item.label }}</span></span></el-option>
        </el-select>
        <el-select v-model="filters.productTypes" class="filter-multi" multiple collapse-tags collapse-tags-tooltip :max-collapse-tags="1" clearable placeholder="全部分类" aria-label="货品分类">
          <el-option v-for="item in optionValues('product_types')" :key="item.value" :label="item.label" :value="item.value"><span class="filter-option-content"><el-checkbox :model-value="filters.productTypes.includes(item.value)" tabindex="-1" /><span>{{ item.label }}</span></span></el-option>
        </el-select>
        <el-input v-model="filters.customerKeyword" class="filter-keyword" clearable placeholder="客户名称 / 编号" aria-label="客户" @keyup.enter="search" />
        <el-input v-model="filters.keyword" class="filter-keyword" clearable placeholder="货品名称 / 编号" aria-label="商品" @keyup.enter="search" />
        <el-select v-model="filters.costStatus" class="filter-type" aria-label="成本状态"><el-option label="全部成本" value="all" /><el-option label="已匹配成本" value="priced" /><el-option label="缺核心成本" value="missing" /><el-option label="低于成本" value="loss" /></el-select>
        <template v-if="filters.view === 'prices'">
          <el-select v-model="filters.benchmark" class="filter-benchmark" aria-label="参考价口径"><el-option label="公司同渠道均价" value="company" /><el-option label="自己其他客户均价" value="peers" /><el-option label="自己上期均价" value="previous" /></el-select>
          <el-select v-model="filters.priceDirection" class="filter-type" aria-label="价格偏差"><el-option label="全部价差" value="all" /><el-option label="高于参考价" value="above" /><el-option label="低于参考价" value="below" /><el-option label="无可比价格" value="unmatched" /></el-select>
        </template>
        <div class="filter-actions">
          <el-button type="primary" :icon="Search" :disabled="!canSearch" @click="search">查询</el-button>
          <el-tooltip content="重置筛选"><el-button :icon="RefreshLeft" circle aria-label="重置筛选" @click="reset" /></el-tooltip>
        </div>
      </div>
    </section>

    <section class="profit-heading">
      <div class="heading-title">
        <h1>销售毛利与价格分析</h1>
        <el-popover placement="bottom-start" :width="380" trigger="click">
          <template #reference><el-button :icon="InfoFilled" text circle aria-label="查看统计口径" /></template>
          <div class="profit-definitions">
            <strong>统计口径</strong>
            <p>销售人按渠道当前负责人归属，不等同于订单成交业务员。</p>
            <p>预估毛利使用正向销售额减正向销售数量乘当前核心成本价；退货红冲仅保留数量、金额展示，不参与毛利及成交价格计算；缺成本商品不按零成本计算。该结果不代表历史实际毛利或扣除平台费用后的净利润。</p>
            <p>成交均价只计算正向销售。价格比较按同品牌、货品、分类、线上或线下及同一时期进行，不混合不同商品。</p>
            <p>公司参考价使用同品牌、商品、分类和线上 / 线下范围内已识别客户的正向成交，保留当前具体渠道筛选，不受销售人、客户及成本状态筛选限制；其他客户参考价排除该客户。</p>
            <p>上期参考价对应同销售人、客户、品牌、商品、分类和线上 / 线下。低于参考价不直接认定异常，需结合采购量、促销和客户条件判断。</p>
            <p>销售额与核心成本的含税口径尚未核实，结果仅作预估分析。</p>
            <p v-if="data.previous_start_date">上期：{{ data.previous_start_date }} 至 {{ data.previous_end_date }}</p>
            <p v-if="data.cost_as_of">成本取价日期：{{ data.cost_as_of }}</p>
            <p v-if="summary.identified_customer_rate != null">客户识别覆盖：{{ percent(summary.identified_customer_rate) }}</p>
          </div>
        </el-popover>
      </div>
      <div class="heading-right"><ProfitPageTabs :view="activeView" @change="changeView" /><span class="period-label">{{ periodLabel }}</span><span v-if="data.updated_at" class="data-update">数据更新 {{ String(data.updated_at).replace('T', ' ').slice(0, 19) }}</span></div>
    </section>

    <section v-if="error" class="load-error" role="alert"><span>{{ error }}</span><el-button :icon="RefreshLeft" @click="load(applied)">重试</el-button></section>
    <template v-else>
      <div class="profit-metrics" v-loading="loading">
        <section v-for="metric in metrics" :key="metric.label" class="metric-card profit-metric" :class="{ 'profit-metric--primary': metric.primary }">
          <div class="metric-label"><span>{{ metric.label }}</span><el-tooltip :content="metric.hint" placement="top"><el-icon tabindex="0" :aria-label="metric.hint"><InfoFilled /></el-icon></el-tooltip></div>
          <div class="metric-value"><strong>{{ metric.value }}</strong><span v-if="metric.unit">{{ metric.unit }}</span></div>
        </section>
      </div>

      <section v-if="applied.view === 'profit'" class="panel profit-breakdown" v-loading="loading">
        <header><h2>{{ groupLabel }}毛利汇总<span v-if="data.breakdown_total > data.breakdown.length" class="breakdown-limit">毛利前 {{ data.breakdown.length }} 项 / 共 {{ number(data.breakdown_total) }} 项</span></h2><el-segmented :model-value="applied.groupBy" :options="groupOptions" aria-label="汇总维度" @change="changeGroup" /></header>
        <el-table :data="data.breakdown" :max-height="340" stripe empty-text="暂无符合条件的销售数据" :default-sort="{ prop: 'estimated_profit', order: 'descending' }">
          <el-table-column prop="label" :label="groupLabel" min-width="220" sortable show-overflow-tooltip />
          <el-table-column prop="sale_quantity" label="正向销售数量" min-width="120" align="right" sortable><template #default="{ row }"><span class="number-strong">{{ number(row.sale_quantity) }}</span></template></el-table-column>
          <el-table-column prop="sale_amount" label="正向销售额" min-width="155" align="right" sortable><template #default="{ row }">{{ money(row.sale_amount) }}</template></el-table-column>
          <el-table-column prop="estimated_profit" label="预估毛利" min-width="155" align="right" sortable><template #default="{ row }"><span class="number-strong">{{ money(row.estimated_profit) }}</span></template></el-table-column>
          <el-table-column prop="margin_rate" label="预估毛利率" min-width="125" align="right" sortable><template #default="{ row }">{{ percent(row.margin_rate) }}</template></el-table-column>
          <el-table-column prop="cost_coverage_rate" label="成本覆盖率" min-width="125" align="right" sortable><template #default="{ row }">{{ percent(row.cost_coverage_rate) }}</template></el-table-column>
          <el-table-column label="" width="60" align="center" fixed="right"><template #default="{ row }"><el-tooltip :content="canDrill(row) ? `查看${row.label}明细` : '编号缺失，无法筛选'"><el-button :icon="ArrowRight" circle text :disabled="!canDrill(row)" :aria-label="`查看${row.label}明细`" @click="drillDown(row)" /></el-tooltip></template></el-table-column>
        </el-table>
      </section>

      <section class="panel profit-detail" v-loading="loading">
        <header><div class="table-heading"><h2>{{ applied.view === 'prices' ? '客户成交价格明细' : '销售预估毛利明细' }}</h2><span>{{ number(data.pagination.total || 0) }} 行</span><el-tooltip v-if="applied.view === 'prices'" :content="benchmarkLabel"><el-icon tabindex="0" :aria-label="benchmarkLabel"><InfoFilled /></el-icon></el-tooltip></div><el-button v-if="canExport" :icon="Download" :loading="exporting" :disabled="loading || !data.pagination.total" @click="exportRows">导出 Excel</el-button></header>
        <el-table :key="`${applied.view}:${applied.sortBy}:${applied.sortOrder}`" :data="data.rows" :row-key="rowKey" stripe :max-height="620" empty-text="暂无符合条件的销售数据" :default-sort="{ prop: applied.sortBy, order: applied.sortOrder === 'asc' ? 'ascending' : 'descending' }" @sort-change="changeSort">
          <el-table-column type="expand" width="38"><template #default="{ row }"><div class="transaction-split"><dl><dt>客户编号</dt><dd>{{ row.customer_code || '-' }}</dd></dl><dl><dt>线上 / 线下</dt><dd>{{ row.channel_type || '-' }}</dd></dl><dl><dt>正向销售数量</dt><dd>{{ number(row.sale_quantity) }}</dd></dl><dl><dt>正向销售额</dt><dd>{{ money(row.sale_amount) }}</dd></dl><dl><dt>退货数量</dt><dd>{{ number(row.return_quantity) }}</dd></dl><dl><dt>退货金额</dt><dd>{{ money(row.return_amount) }}</dd></dl><dl v-if="applied.view === 'prices'"><dt>参考成交数量</dt><dd>{{ number(row.reference_quantity) }}</dd></dl></div></template></el-table-column>
          <el-table-column v-for="column in detailColumns" :key="column.key" :prop="column.key" :label="column.label" :min-width="column.width" :align="column.kind ? 'right' : 'left'" sortable="custom" show-overflow-tooltip><template #default="{ row }"><span :class="{ 'number-strong': column.strong, 'price-offset': column.kind === 'signed' || column.kind === 'signedPercent', 'is-muted': row[column.key] == null }">{{ cellValue(row, column) }}</span></template></el-table-column>
        </el-table>
        <footer class="table-pagination"><span>{{ number(data.pagination.total || 0) }} 条</span><el-pagination :current-page="applied.page" :page-size="applied.pageSize" :page-sizes="[20, 50, 100]" :total="data.pagination.total || 0" background layout="sizes, prev, pager, next" :pager-count="5" @current-change="changePage" @size-change="changePageSize" /></footer>
      </section>
    </template>
  </div>
</template>

<style scoped>
.profit-view-navigation { display: flex; justify-content: flex-end; padding: 12px 16px; margin-bottom: 16px; background: var(--surface, #fff); border: 1px solid var(--border, #e5e7eb); border-radius: 8px; }
.profit-view-navigation :deep(.el-segmented) { max-width: 100%; }
.sales-profit-page {
  --profit-accent: var(--theme-primary);
  --profit-ink: var(--theme-strong);
  --el-color-primary: var(--theme-primary);
  --el-color-primary-light-3: color-mix(in srgb, var(--theme-primary) 70%, white);
  --el-color-primary-light-5: color-mix(in srgb, var(--theme-primary) 50%, white);
  --el-color-primary-light-7: color-mix(in srgb, var(--theme-primary) 30%, white);
  --el-color-primary-light-9: var(--theme-soft);
  --el-color-primary-dark-2: var(--theme-strong);
  gap: 12px;
  min-width: 0;
}
.profit-toolbar { padding: 10px 12px; border-radius: 6px; }
.profit-toolbar .filter-controls { gap: 8px; width: 100%; }
.profit-toolbar :deep(.profit-dates) { flex: 0 0 264px; width: 264px; max-width: 264px; }
.filter-owner, .filter-multi { width: 155px; }
.filter-type { width: 132px; }
.filter-keyword { width: 160px; }
.filter-benchmark { width: 175px; }
.filter-actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.filter-actions .el-button + .el-button { margin-left: 0; }
.profit-heading { display: flex; justify-content: space-between; align-items: center; gap: 24px; min-width: 0; min-height: 116px; padding: 18px 22px; border: 1px solid var(--border); border-top: 3px solid var(--profit-accent); border-radius: 6px; background: var(--surface); }
.heading-title { display: flex; align-items: center; gap: 4px; min-width: 0; border-left: 4px solid var(--profit-accent); padding: 8px 0 8px 12px; }
.heading-title h1 { margin: 0; color: var(--text); font-size: 22px; font-weight: 700; line-height: 1.3; }
.heading-right { display: flex; align-items: flex-end; flex-direction: column; gap: 9px; min-width: 0; }
.profit-pages { --el-border-radius-base: 5px; --el-segmented-item-selected-color: var(--profit-ink); border: 1px solid var(--border); font-size: 12px; font-weight: 600; }
.profit-pages :deep(.el-segmented__item-label) { padding: 0 10px; }
.period-label { font-size: 12px; font-weight: 600; color: var(--profit-ink); }
.data-update { font-size: 12px; color: var(--muted); }
.profit-definitions { font-size: 12px; line-height: 1.7; color: var(--text-soft); }
.profit-definitions strong { color: var(--text); }
.profit-definitions p { margin: 10px 0 0; }
.profit-metrics { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 8px; }
.profit-metric { min-height: 108px; padding: 14px; border-top: 2px solid var(--profit-accent); border-radius: 5px; }
.profit-metric .metric-label { display: flex; align-items: center; justify-content: space-between; gap: 4px; color: var(--muted); font-size: 12px; }
.profit-metric .metric-label .el-icon { color: var(--muted); font-size: 12px; }
.profit-metric .metric-value { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px; margin-top: 7px; min-width: 0; }
.profit-metric .metric-value strong { color: var(--text); font-size: 20px; font-weight: 700; font-variant-numeric: tabular-nums; line-height: 1.25; overflow-wrap: anywhere; }
.profit-metric .metric-value span { color: var(--muted); font-size: 11px; }
.profit-metric--primary { background: var(--profit-accent); border-color: var(--profit-accent); }
.profit-metric--primary .metric-label, .profit-metric--primary .metric-label .el-icon, .profit-metric--primary .metric-value strong, .profit-metric--primary .metric-value span { color: #fff; }
.profit-breakdown header, .profit-detail header { min-height: 72px; gap: 12px; flex-wrap: wrap; padding: 12px 18px; }
.profit-breakdown h2, .profit-detail h2 { font-size: 16px; line-height: 1.4; font-weight: 700; }
.profit-breakdown header :deep(.el-segmented) { font-size: 12px; font-weight: 600; }
.table-heading { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.table-heading > span { color: var(--muted); font-size: 12px; font-weight: 500; }
.breakdown-limit { margin-left: 12px; color: var(--muted); font-size: 12px; font-weight: 400; }
.table-heading .el-icon { color: var(--muted); font-size: 13px; }
.profit-detail :deep(.el-table th.el-table__cell), .profit-breakdown :deep(.el-table th.el-table__cell) { background: var(--el-fill-color-light); }
.profit-detail :deep(.el-table .cell), .profit-breakdown :deep(.el-table .cell) { padding-left: 12px; padding-right: 12px; }
.number-strong { color: var(--text-soft); font-weight: 600; font-variant-numeric: tabular-nums; }
.price-offset { font-variant-numeric: tabular-nums; color: var(--profit-ink); }
.is-muted { color: var(--muted); }
.transaction-split { display: flex; flex-wrap: wrap; gap: 18px 30px; padding: 16px 24px; background: var(--surface-soft); }
.transaction-split dl { display: grid; gap: 6px; margin: 0; min-width: 100px; }
.transaction-split dt { color: var(--muted); font-size: 12px; }
.transaction-split dd { margin: 0; color: var(--text-soft); font-size: 12px; font-variant-numeric: tabular-nums; }
.table-pagination { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 12px 14px; border-top: 1px solid var(--border); overflow-x: auto; }
.table-pagination > span { color: var(--muted); font-size: 12px; white-space: nowrap; }
.load-error { display: flex; align-items: center; justify-content: center; flex-wrap: wrap; gap: 16px; min-height: 200px; padding: 24px; color: var(--text-soft); background: var(--surface); border: 1px solid var(--border); border-radius: 6px; }
:global(:root[data-appearance='dark'] .sales-profit-page) { --profit-ink: var(--theme-secondary); }
@media (max-width: 1280px) { .profit-metrics { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 820px) { .profit-heading { align-items: flex-start; flex-direction: column; padding: 14px; } .heading-right { align-items: flex-start; width: 100%; } .profit-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); } .profit-breakdown header { align-items: flex-start; flex-direction: column; } .profit-breakdown header :deep(.el-segmented) { max-width: 100%; overflow-x: auto; } }
@media (max-width: 560px) { .profit-toolbar .filter-controls { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); } .profit-toolbar .filter-controls > * { width: 100%; min-width: 0; } .profit-toolbar :deep(.profit-dates) { grid-column: 1 / -1; width: 100%; max-width: none; } .profit-toolbar .filter-actions { grid-column: 1 / -1; } .filter-actions .el-button:first-child { flex: 1; } .profit-metric .metric-value strong { font-size: 17px; } .heading-title h1 { font-size: 17px; } .profit-detail header { padding: 10px 12px; } .table-pagination { padding: 10px 8px; } .table-pagination > span { display: none; } }
</style>
