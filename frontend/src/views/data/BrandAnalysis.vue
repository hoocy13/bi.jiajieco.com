<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import MetricCard from '../../components/dashboard/MetricCard.vue'
import { getSalesBrandAnalysis } from '../../api/sales'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
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
const rangeOptions = [
  { label: '近30天', value: 'last_30' },
  { label: '本月', value: 'this_month' },
  { label: '本年', value: 'this_year' },
]

function queryValues(value) {
  if (Array.isArray(value)) return value.map(String).filter(Boolean)
  return value ? [String(value)] : []
}

const productTypeOptions = ['正装', '小样']
const query = reactive({
  keyword: String(route.query.keyword || ''),
  limit: [10, 30, 50, 100].includes(Number(route.query.limit)) ? Number(route.query.limit) : 30,
  productTypes: queryValues(route.query.product_type).filter((item) => productTypeOptions.includes(item)),
})
const analysis = ref({
  period: '本年',
  start_date: '',
  end_date: '',
  summary: {
    paid_amount: 0,
    orders: 0,
    quantity: 0,
  },
  rows: [],
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

function formatPercent(value) {
  return `${formatNumber(value, 1)}%`
}

const dateRangeLabel = computed(() => {
  const start = formatDate(analysis.value.start_date)
  const end = formatDate(analysis.value.end_date)
  return start === '-' || end === '-' ? '-' : `${start} 至 ${end}`
})

const canSearch = computed(() => selectedRange.value !== 'custom' || dateRange.value.length === 2)

const metrics = computed(() => [
  { label: '明细分摊销售额', value: formatNumber(analysis.value.summary.paid_amount), unit: '元', trend: analysis.value.period },
  { label: '订单数', value: formatNumber(analysis.value.summary.orders), unit: '单', trend: '正向订单去重' },
  { label: '销售数量', value: formatNumber(analysis.value.summary.quantity), unit: '件', trend: '当前筛选结果' },
])

function buildParams() {
  const params = selectedRange.value === 'custom'
    ? { start_date: dateRange.value[0], end_date: dateRange.value[1] }
    : { range: selectedRange.value }
  params.limit = query.limit
  if (query.keyword.trim()) params.keyword = query.keyword.trim()
  if (query.productTypes.length) params.product_type = query.productTypes
  return params
}

function handleRangeChange() {
  dateRange.value = []
}

function handleDateRangeChange(value) {
  if (value?.length === 2) {
    selectedRange.value = 'custom'
  }
}

async function fetchAnalysis() {
  if (!canSearch.value) return
  loading.value = true
  try {
    const result = await getSalesBrandAnalysis(buildParams())
    analysis.value = result.data
    dateRange.value = [analysis.value.start_date, analysis.value.end_date]
    const routeQuery = selectedRange.value === 'custom'
      ? { start_date: analysis.value.start_date, end_date: analysis.value.end_date }
      : { range: selectedRange.value }
    if (query.keyword.trim()) routeQuery.keyword = query.keyword.trim()
    if (query.limit !== 30) routeQuery.limit = String(query.limit)
    if (query.productTypes.length) routeQuery.product_type = query.productTypes
    await router.replace({ query: routeQuery })
  } finally {
    loading.value = false
  }
}

function openBrand(row) {
  const rangeQuery = selectedRange.value === 'custom'
    ? {
        start_date: analysis.value.start_date,
        end_date: analysis.value.end_date,
      }
    : { range: selectedRange.value }
  if (query.productTypes.length) rangeQuery.product_type = query.productTypes
  router.push({
    path: `/sales/brand-analysis/${encodeURIComponent(row.brand)}`,
    query: rangeQuery,
  })
}

onMounted(fetchAnalysis)
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
        <el-select
          v-model="query.productTypes"
          class="filter-select multi-filter-select"
          clearable
          multiple
          collapse-tags
          collapse-tags-tooltip
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
        <el-input v-model="query.keyword" class="filter-input" clearable placeholder="商品 / 品牌关键词" />
        <el-select v-model="query.limit" class="filter-select" placeholder="排行数量">
          <el-option label="Top 10" :value="10" />
          <el-option label="Top 30" :value="30" />
          <el-option label="Top 50" :value="50" />
          <el-option label="Top 100" :value="100" />
        </el-select>
        <el-button type="primary" :disabled="!canSearch" @click="fetchAnalysis">查询</el-button>
      </div>
      <div class="range-summary">
        <strong>{{ analysis.period }}</strong>
        <span>{{ dateRangeLabel }}</span>
      </div>
    </section>

    <div class="metric-grid compact-metrics">
      <MetricCard v-for="item in metrics" :key="item.label" v-bind="item" />
    </div>

    <section class="panel">
      <header>
        <h2>品牌销售分析<span class="panel-source">（商品明细分摊金额口径）</span></h2>
        <el-button :icon="'Refresh'" circle @click="fetchAnalysis" />
      </header>
      <el-table :data="analysis.rows" height="560">
        <el-table-column label="排名" width="74" align="center">
          <template #default="{ row }">
            <span class="rank-badge">{{ row.rank }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="brand" label="品牌" min-width="240">
          <template #default="{ row }">
            <div class="channel-cell">
              <strong>{{ row.brand }}</strong>
              <span>
                <i :style="{ width: `${Math.min(row.share || 0, 100)}%` }"></i>
              </span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="share" label="分摊金额占比" width="120">
          <template #default="{ row }">{{ formatPercent(row.share) }}</template>
        </el-table-column>
        <el-table-column prop="orders" label="订单数" width="120">
          <template #default="{ row }">{{ formatNumber(row.orders) }}</template>
        </el-table-column>
        <el-table-column prop="quantity" label="销售数量" width="130">
          <template #default="{ row }">{{ formatNumber(row.quantity) }}</template>
        </el-table-column>
        <el-table-column prop="product_count" label="商品数" width="110">
          <template #default="{ row }">{{ formatNumber(row.product_count) }}</template>
        </el-table-column>
        <el-table-column prop="paid_amount" label="分摊销售额" width="160">
          <template #default="{ row }">{{ formatNumber(row.paid_amount, 2) }}</template>
        </el-table-column>
        <el-table-column prop="avg_unit_price" label="件均价" width="140">
          <template #default="{ row }">{{ formatNumber(row.avg_unit_price, 2) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link @click="openBrand(row)">查看</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>
