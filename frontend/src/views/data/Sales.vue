<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import MetricCard from '../../components/dashboard/MetricCard.vue'
import { getSalesDetail } from '../../api/sales'

const loading = ref(false)
const selectedRange = ref('last_30')
const dateRange = ref([])
const rangeOptions = [
  { label: '近30天', value: 'last_30' },
  { label: '本月', value: 'this_month' },
]
const query = reactive({
  keyword: '',
  channel: '',
  status: '',
})
const pagination = reactive({
  page: 1,
  pageSize: 20,
})
const detail = ref({
  period: '近30天',
  start_date: '',
  end_date: '',
  summary: {
    paid_amount: 0,
    orders: 0,
    quantity: 0,
  },
  rows: [],
  total: 0,
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

const dateRangeLabel = computed(() => {
  const start = formatDate(detail.value.start_date)
  const end = formatDate(detail.value.end_date)
  return start === '-' || end === '-' ? '-' : `${start} 至 ${end}`
})

const canSearch = computed(() => selectedRange.value !== 'custom' || dateRange.value.length === 2)

const metrics = computed(() => [
  { label: '销售额', value: formatNumber(detail.value.summary.paid_amount), unit: '元', trend: detail.value.period },
  { label: '订单数', value: formatNumber(detail.value.summary.orders), unit: '单', trend: '正向订单去重' },
  { label: '销售数量', value: formatNumber(detail.value.summary.quantity), unit: '件', trend: '当前筛选结果' },
])

function buildParams() {
  const params = selectedRange.value === 'custom'
    ? { start_date: dateRange.value[0], end_date: dateRange.value[1] }
    : { range: selectedRange.value }
  params.page = pagination.page
  params.page_size = pagination.pageSize
  if (query.keyword.trim()) params.keyword = query.keyword.trim()
  if (query.channel.trim()) params.channel = query.channel.trim()
  if (query.status.trim()) params.status = query.status.trim()
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

async function fetchDetail(resetPage = false) {
  if (!canSearch.value) return
  if (resetPage) pagination.page = 1
  loading.value = true
  try {
    const result = await getSalesDetail(buildParams())
    detail.value = result.data
    dateRange.value = [detail.value.start_date, detail.value.end_date]
  } finally {
    loading.value = false
  }
}

function handleSizeChange(size) {
  pagination.pageSize = size
  fetchDetail(true)
}

function handlePageChange(page) {
  pagination.page = page
  fetchDetail()
}

onMounted(() => fetchDetail())
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
        <el-input v-model="query.keyword" class="filter-input" clearable placeholder="订单号 / 商品" />
        <el-input v-model="query.channel" class="filter-input" clearable placeholder="销售渠道" />
        <el-input v-model="query.status" class="filter-input" clearable placeholder="订单状态" />
        <el-button type="primary" :disabled="!canSearch" @click="fetchDetail(true)">查询</el-button>
      </div>
      <div class="range-summary">
        <strong>{{ detail.period }}</strong>
        <span>{{ dateRangeLabel }}</span>
      </div>
    </section>

    <div class="metric-grid compact-metrics">
      <MetricCard v-for="item in metrics" :key="item.label" v-bind="item" />
    </div>

    <section class="panel">
      <header>
        <h2>销售明细<span class="panel-source">（销售单查询）</span></h2>
        <el-button :icon="'Refresh'" circle @click="fetchDetail()" />
      </header>
      <el-table :data="detail.rows" height="520">
        <el-table-column prop="date" label="日期" width="120" />
        <el-table-column prop="order_no" label="订单编号" width="180" />
        <el-table-column prop="channel" label="销售渠道" width="150" />
        <el-table-column prop="product" label="商品摘要" min-width="260" show-overflow-tooltip />
        <el-table-column prop="quantity" label="数量" width="100">
          <template #default="{ row }">{{ formatNumber(row.quantity) }}</template>
        </el-table-column>
        <el-table-column prop="paid_amount" label="实付金额" width="140">
          <template #default="{ row }">{{ formatNumber(row.paid_amount, 2) }}</template>
        </el-table-column>
        <el-table-column prop="receivable_amount" label="应收合计" width="140">
          <template #default="{ row }">{{ formatNumber(row.receivable_amount, 2) }}</template>
        </el-table-column>
        <el-table-column prop="status" label="订单状态" width="120">
          <template #default="{ row }">
            <el-tag effect="plain">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="settlement_status" label="结算状态" width="120" />
        <el-table-column prop="city" label="城市" width="110" />
      </el-table>
      <div class="table-footer">
        <el-pagination
          background
          layout="total, sizes, prev, pager, next"
          :total="detail.total"
          :current-page="pagination.page"
          :page-size="pagination.pageSize"
          :page-sizes="[20, 50, 100]"
          @size-change="handleSizeChange"
          @current-change="handlePageChange"
        />
      </div>
    </section>
  </div>
</template>
