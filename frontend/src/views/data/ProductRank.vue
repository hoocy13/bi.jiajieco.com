<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import MetricCard from '../../components/dashboard/MetricCard.vue'
import ExportExcelButton from '../../components/common/ExportExcelButton.vue'
import { getSalesProductRank } from '../../api/sales'
import { getSavedTheme } from '../../utils/theme'

use([CanvasRenderer, BarChart, GridComponent, TooltipComponent])

const chartTheme = getSavedTheme()
const route = useRoute()
const router = useRouter()

const loading = ref(false)
const supportedRanges = ['last_30', 'this_month', 'q1', 'q2', 'q3', 'q4']
const initialRange = String(route.query.range || '')
const selectedRange = ref(route.query.start_date && route.query.end_date ? 'custom' : supportedRanges.includes(initialRange) ? initialRange : 'last_30')
const dateRange = ref(route.query.start_date && route.query.end_date ? [String(route.query.start_date), String(route.query.end_date)] : [])
const currentQuarter = Math.floor(new Date().getMonth() / 3) + 1
const rangeOptions = [
  { label: '近30天', value: 'last_30' },
  { label: '本月', value: 'this_month' },
  ...[1, 2, 3, 4].map((quarter) => ({ label: `Q${quarter}`, value: `q${quarter}`, disabled: quarter > currentQuarter })),
]
const query = reactive({
  keyword: String(route.query.keyword || ''),
  limit: [10, 30, 50, 100].includes(Number(route.query.limit)) ? Number(route.query.limit) : 30,
  productTypes: (Array.isArray(route.query.product_type) ? route.query.product_type : route.query.product_type ? [route.query.product_type] : [])
    .map(String).filter((item) => ['正装', '小样'].includes(item)),
  brands: (Array.isArray(route.query.brand) ? route.query.brand : route.query.brand ? [route.query.brand] : []).map(String).filter(Boolean),
})
const rank = ref({
  period: '近30天',
  start_date: '',
  end_date: '',
  summary: {
    paid_amount: 0,
    orders: 0,
    quantity: 0,
  },
  rows: [],
  quantity_rows: [],
  filter_options: { brands: [] },
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

function shortProductName(value) {
  const text = String(value || '未命名商品')
  return text.length > 18 ? `${text.slice(0, 18)}...` : text
}

const dateRangeLabel = computed(() => {
  const start = formatDate(rank.value.start_date)
  const end = formatDate(rank.value.end_date)
  return start === '-' || end === '-' ? '-' : `${start} 至 ${end}`
})
const productTypeLabel = computed(() => query.productTypes.length ? query.productTypes.join(' + ') : '全部')
const brandLabel = computed(() => query.brands.length ? query.brands.join('、') : '全部')

const canSearch = computed(() => selectedRange.value !== 'custom' || dateRange.value.length === 2)

const metrics = computed(() => [
  { label: '明细分摊销售额', value: formatNumber(rank.value.summary.paid_amount), unit: '元', trend: rank.value.period },
  { label: '订单数', value: formatNumber(rank.value.summary.orders), unit: '单', trend: '正向订单去重' },
  { label: '销售数量', value: formatNumber(rank.value.summary.quantity), unit: '件', trend: '当前筛选结果' },
])

const amountChartRows = computed(() => rank.value.rows.slice(0, 10).toReversed())
const rankExportColumns = [{ key: 'rank', label: '排名', kind: 'integer' }, { key: 'product', label: '商品摘要', width: 42 }, { key: 'share', label: '占比', kind: 'percent' }, { key: 'orders', label: '订单数', kind: 'integer' }, { key: 'quantity', label: '销售数量', kind: 'integer' }, { key: 'paid_amount', label: '分摊销售额', kind: 'number' }, { key: 'avg_unit_price', label: '件均价', kind: 'number' }]
const quantityChartRows = computed(() => rank.value.quantity_rows.slice(0, 10).toReversed())

function buildBarOption(rows, valueKey, unit, digits = 0) {
  return {
    color: [chartTheme.primary],
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: '#111217',
      borderWidth: 0,
      textStyle: { color: '#ffffff' },
      formatter: (params) => {
        const item = params[0]
        const row = rows[item.dataIndex]
        return `${row.product}<br/>${item.seriesName}: ${formatNumber(item.value, digits)} ${unit}`
      },
    },
    grid: { top: 16, left: 150, right: 54, bottom: 22 },
    xAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: '#eceef3' } },
      axisLabel: { color: '#9aa0aa' },
    },
    yAxis: {
      type: 'category',
      data: rows.map((item) => shortProductName(item.product)),
      axisTick: { show: false },
      axisLine: { show: false },
      axisLabel: { color: '#6f7480', width: 140, overflow: 'truncate' },
    },
    series: [
      {
        name: unit === '元' ? '明细分摊销售额' : '销售数量',
        type: 'bar',
        barWidth: 12,
        itemStyle: {
          borderRadius: [0, 8, 8, 0],
        },
        label: {
          show: true,
          position: 'right',
          color: '#6f7480',
          fontSize: 11,
          formatter: (params) => formatNumber(params.value, digits),
        },
        data: rows.map((item) => item[valueKey]),
      },
    ],
  }
}

const amountChartOption = computed(() => buildBarOption(amountChartRows.value, 'paid_amount', '元', 0))
const quantityChartOption = computed(() => buildBarOption(quantityChartRows.value, 'quantity', '件', 0))

function buildParams() {
  const params = selectedRange.value === 'custom'
    ? { start_date: dateRange.value[0], end_date: dateRange.value[1] }
    : { range: selectedRange.value }
  params.limit = query.limit
  if (query.keyword.trim()) params.keyword = query.keyword.trim()
  if (query.productTypes.length) params.product_type = query.productTypes
  if (query.brands.length) params.brand = query.brands
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

async function fetchRank() {
  if (!canSearch.value) return
  loading.value = true
  try {
    const result = await getSalesProductRank(buildParams())
    rank.value = {
      ...result.data,
      quantity_rows: result.data.quantity_rows || [],
      filter_options: result.data.filter_options || { brands: [] },
    }
    dateRange.value = [rank.value.start_date, rank.value.end_date]
    const routeQuery = selectedRange.value === 'custom'
      ? { start_date: rank.value.start_date, end_date: rank.value.end_date }
      : { range: selectedRange.value }
    if (query.keyword.trim()) routeQuery.keyword = query.keyword.trim()
    if (query.limit !== 30) routeQuery.limit = String(query.limit)
    if (query.productTypes.length) routeQuery.product_type = query.productTypes
    if (query.brands.length) routeQuery.brand = query.brands
    await router.replace({ query: routeQuery })
  } finally {
    loading.value = false
  }
}

onMounted(fetchRank)
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
        <el-select v-model="query.productTypes" class="filter-select multi-filter-select" clearable multiple collapse-tags :max-collapse-tags="1" placeholder="正装 / 小样">
          <el-option label="正装" value="正装" />
          <el-option label="小样" value="小样" />
        </el-select>
        <el-select v-model="query.brands" class="filter-select multi-filter-select" clearable filterable multiple collapse-tags collapse-tags-tooltip :max-collapse-tags="1" placeholder="选择品牌">
          <el-option v-for="item in rank.filter_options.brands" :key="item" :label="item" :value="item" />
        </el-select>
        <el-input v-model="query.keyword" class="filter-input" clearable placeholder="商品关键字" />
        <el-select v-model="query.limit" class="filter-select" placeholder="排行数量">
          <el-option label="Top 10" :value="10" />
          <el-option label="Top 30" :value="30" />
          <el-option label="Top 50" :value="50" />
          <el-option label="Top 100" :value="100" />
        </el-select>
        <el-button type="primary" :disabled="!canSearch" @click="fetchRank">查询</el-button>
      </div>
      <div class="range-summary">
        <strong>{{ rank.period }}</strong>
        <span>{{ dateRangeLabel }}</span>
      </div>
    </section>

    <div class="metric-grid compact-metrics">
      <MetricCard v-for="item in metrics" :key="item.label" v-bind="item" />
    </div>

    <section class="panel">
      <header>
        <h2>商品销售排行榜<span class="panel-source">（按明细分摊金额）</span></h2>
        <ExportExcelButton title="商品销售排行" :rows="rank.rows" :columns="rankExportColumns" :total="rank.rows.length" :filters="{ 统计区间: dateRangeLabel, 货品分类: productTypeLabel, 品牌: brandLabel }" />
        <el-button :icon="'Refresh'" circle @click="fetchRank" />
      </header>
      <v-chart class="rank-chart" :option="amountChartOption" autoresize />
      <el-table :data="rank.rows" height="520">
        <el-table-column label="排名" width="74" align="center">
          <template #default="{ row }">
            <span class="rank-badge">{{ row.rank }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="product" label="商品摘要" min-width="320" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="channel-cell">
              <strong>{{ row.product }}</strong>
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
        <el-table-column prop="paid_amount" label="分摊销售额" width="160">
          <template #default="{ row }">{{ formatNumber(row.paid_amount, 2) }}</template>
        </el-table-column>
        <el-table-column prop="avg_unit_price" label="件均价" width="140">
          <template #default="{ row }">{{ formatNumber(row.avg_unit_price, 2) }}</template>
        </el-table-column>
      </el-table>
    </section>

    <section class="panel">
      <header>
        <h2>商品数量排行<span class="panel-source">（按销售数量）</span></h2>
        <ExportExcelButton title="商品数量排行" :rows="rank.quantity_rows" :columns="rankExportColumns" :total="rank.quantity_rows.length" :filters="{ 统计区间: dateRangeLabel, 货品分类: productTypeLabel, 品牌: brandLabel }" />
      </header>
      <v-chart class="rank-chart" :option="quantityChartOption" autoresize />
      <el-table :data="rank.quantity_rows" height="520">
        <el-table-column label="排名" width="74" align="center">
          <template #default="{ row }">
            <span class="rank-badge">{{ row.rank }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="product" label="商品摘要" min-width="320" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="channel-cell">
              <strong>{{ row.product }}</strong>
              <span>
                <i :style="{ width: `${Math.min(row.share || 0, 100)}%` }"></i>
              </span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="share" label="数量占比" width="120">
          <template #default="{ row }">{{ formatPercent(row.share) }}</template>
        </el-table-column>
        <el-table-column prop="quantity" label="销售数量" width="130">
          <template #default="{ row }">{{ formatNumber(row.quantity) }}</template>
        </el-table-column>
        <el-table-column prop="orders" label="订单数" width="120">
          <template #default="{ row }">{{ formatNumber(row.orders) }}</template>
        </el-table-column>
        <el-table-column prop="paid_amount" label="分摊销售额" width="160">
          <template #default="{ row }">{{ formatNumber(row.paid_amount, 2) }}</template>
        </el-table-column>
        <el-table-column prop="avg_unit_price" label="件均价" width="140">
          <template #default="{ row }">{{ formatNumber(row.avg_unit_price, 2) }}</template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>
