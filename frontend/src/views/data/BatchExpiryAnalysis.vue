<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import MetricCard from '../../components/dashboard/MetricCard.vue'
import WarehouseFilter from '../../components/inventory/WarehouseFilter.vue'
import ProductTypeFilter from '../../components/inventory/ProductTypeFilter.vue'
import ProductInventoryDrawer from '../../components/inventory/ProductInventoryDrawer.vue'
import { getBatchExpiryAnalysis, getInventoryWarehouses } from '../../api/inventory'
import { DEFAULT_INVENTORY_PRODUCT_TYPES, DEFAULT_INVENTORY_WAREHOUSES } from '../../constants/inventory'
import { inventoryQuery, productTypeParam, queryArray } from '../../utils/inventoryFilters'

use([CanvasRenderer, BarChart, GridComponent, TooltipComponent])

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const warehouseLoading = ref(false)
const warehouseOptions = ref([])
const productTypeOptions = ref([...DEFAULT_INVENTORY_PRODUCT_TYPES])
const query = reactive({
  keyword: String(route.query.keyword || ''),
  barcode: String(route.query.barcode || ''),
  warehouses: queryArray(route.query.warehouse, DEFAULT_INVENTORY_WAREHOUSES),
  productTypes: route.query.product_type === '__all__' ? [] : queryArray(route.query.product_type, DEFAULT_INVENTORY_PRODUCT_TYPES),
  expiryRange: String(route.query.expiry_range || 'all'),
  page: Number(route.query.page || 1),
  longPage: Number(route.query.long_page || 1),
  pageSize: Number(route.query.page_size || 50),
})
const analysis = ref({
  updated_at: '',
  metrics: {
    batch_count: 0,
    product_count: 0,
    available_stock: 0,
    expired_stock: 0,
    within_6_months_stock: 0,
    within_12_months_stock: 0,
    over_24_months_stock: 0,
    missing_expiry_stock: 0,
  },
  fefo_rows: [],
  long_expiry_rows: [],
})
const productDrawer = ref(null)
const total = ref(0)
const longTotal = ref(0)

function formatNumber(value, digits = 0) {
  return Number(value || 0).toLocaleString('zh-CN', {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  })
}

function shortName(value) {
  const text = String(value || '未命名商品')
  return text.length > 18 ? `${text.slice(0, 18)}...` : text
}

function statusType(status) {
  if (status === '已过期' || status === '缺少到期日期') return 'danger'
  if (status === '6个月内') return 'warning'
  if (status === '6-12个月') return 'primary'
  return 'success'
}

function remainingText(days) {
  if (days === null || days === undefined) return '-'
  if (days < 0) return `已过期 ${formatNumber(Math.abs(days))} 天`
  return `${formatNumber(days)} 天`
}

function openProduct(row) {
  productDrawer.value?.open(row.product_code, query.warehouses)
}

const metrics = computed(() => [
  {
    label: '在库批次',
    value: formatNumber(analysis.value.metrics.batch_count),
    unit: '批',
    trend: `${formatNumber(analysis.value.metrics.product_count)} 个商品`,
  },
  {
    label: '批次可用库存',
    value: formatNumber(analysis.value.metrics.available_stock),
    unit: '件',
    trend: '当前筛选范围',
  },
  {
    label: '6个月内到期',
    value: formatNumber(analysis.value.metrics.within_6_months_stock),
    unit: '件',
    trend: `已过期 ${formatNumber(analysis.value.metrics.expired_stock)} 件`,
  },
  {
    label: '24个月以上',
    value: formatNumber(analysis.value.metrics.over_24_months_stock),
    unit: '件',
    trend: `缺日期 ${formatNumber(analysis.value.metrics.missing_expiry_stock)} 件`,
  },
])

const fefoChartRows = computed(() => analysis.value.fefo_rows
  .filter((row) => row.remaining_days !== null && row.remaining_days !== undefined)
  .slice(0, 10)
  .slice()
  .reverse())

const longExpiryChartRows = computed(() => analysis.value.long_expiry_rows
  .slice(0, 10)
  .slice()
  .reverse())

const fefoChartOption = computed(() => ({
  color: ['#d94a4a'],
  tooltip: {
    trigger: 'axis',
    axisPointer: { type: 'shadow' },
    backgroundColor: '#111217',
    borderWidth: 0,
    textStyle: { color: '#ffffff' },
    formatter: (params) => {
      const item = params[0]
      const row = fefoChartRows.value[item.dataIndex]
      return `${row.product}<br/>仓库：${row.warehouse}<br/>剩余效期：${remainingText(row.remaining_days)}<br/>可用库存：${formatNumber(row.available_stock)} 件`
    },
  },
  grid: { top: 16, left: 150, right: 48, bottom: 22 },
  xAxis: {
    type: 'value',
    splitLine: { lineStyle: { color: '#eceef3' } },
    axisLabel: { color: '#9aa0aa', formatter: (value) => `${formatNumber(value)}天` },
  },
  yAxis: {
    type: 'category',
    data: fefoChartRows.value.map((item) => shortName(item.product)),
    axisTick: { show: false },
    axisLine: { show: false },
    axisLabel: { color: '#6f7480', width: 140, overflow: 'truncate' },
  },
  series: [
    {
      name: '剩余天数',
      type: 'bar',
      barWidth: 12,
      itemStyle: { borderRadius: [0, 8, 8, 0] },
      label: {
        show: true,
        position: 'right',
        color: '#6f7480',
        fontSize: 11,
        formatter: (params) => `${formatNumber(params.value)}天`,
      },
      data: fefoChartRows.value.map((item) => item.remaining_days),
    },
  ],
}))

const longExpiryChartOption = computed(() => ({
  color: ['#5e6ad2'],
  tooltip: {
    trigger: 'axis',
    axisPointer: { type: 'shadow' },
    backgroundColor: '#111217',
    borderWidth: 0,
    textStyle: { color: '#ffffff' },
    formatter: (params) => {
      const item = params[0]
      const row = longExpiryChartRows.value[item.dataIndex]
      return `${row.product}<br/>最近到期剩余：${formatNumber(row.remaining_months, 1)} 个月<br/>可用库存：${formatNumber(row.available_stock)} 件<br/>批次数：${formatNumber(row.batch_count)}`
    },
  },
  grid: { top: 16, left: 150, right: 58, bottom: 22 },
  xAxis: {
    type: 'value',
    splitLine: { lineStyle: { color: '#eceef3' } },
    axisLabel: { color: '#9aa0aa' },
  },
  yAxis: {
    type: 'category',
    data: longExpiryChartRows.value.map((item) => shortName(item.product)),
    axisTick: { show: false },
    axisLine: { show: false },
    axisLabel: { color: '#6f7480', width: 140, overflow: 'truncate' },
  },
  series: [
    {
      name: '可用库存',
      type: 'bar',
      barWidth: 12,
      itemStyle: { borderRadius: [0, 8, 8, 0] },
      label: {
        show: true,
        position: 'right',
        color: '#6f7480',
        fontSize: 11,
        formatter: (params) => formatNumber(params.value),
      },
      data: longExpiryChartRows.value.map((item) => item.available_stock),
    },
  ],
}))

async function fetchWarehouses() {
  warehouseLoading.value = true
  try {
    const result = await getInventoryWarehouses()
    warehouseOptions.value = result.data.warehouses
    productTypeOptions.value = result.data.product_types || [...DEFAULT_INVENTORY_PRODUCT_TYPES]
  } finally {
    warehouseLoading.value = false
  }
}

async function fetchAnalysis(resetPages = false) {
  if (resetPages) {
    query.page = 1
    query.longPage = 1
  }
  router.replace({
    query: inventoryQuery({
      keyword: query.keyword.trim(),
      barcode: query.barcode.trim(),
      warehouse: query.warehouses,
      product_type: query.productTypes.length ? query.productTypes : '__all__',
      expiry_range: query.expiryRange,
      page: query.page,
      long_page: query.longPage,
      page_size: query.pageSize,
    }),
  })
  loading.value = true
  try {
    const params = {
      warehouse: query.warehouses,
      product_type: productTypeParam(query.productTypes),
      expiry_range: query.expiryRange,
      page: query.page,
      long_page: query.longPage,
      page_size: query.pageSize,
    }
    if (query.keyword.trim()) params.keyword = query.keyword.trim()
    if (query.barcode.trim()) params.barcode = query.barcode.trim()
    const result = await getBatchExpiryAnalysis(params)
    analysis.value = result.data
    total.value = result.data.pagination.total
    longTotal.value = result.data.long_pagination.total
  } finally {
    loading.value = false
  }
}

function restoreDefaults() {
  Object.assign(query, {
    keyword: '',
    barcode: '',
    warehouses: [...DEFAULT_INVENTORY_WAREHOUSES],
    productTypes: [...DEFAULT_INVENTORY_PRODUCT_TYPES],
    expiryRange: 'all',
    page: 1,
    longPage: 1,
    pageSize: 50,
  })
  fetchAnalysis()
}

function clearFilters() {
  Object.assign(query, {
    keyword: '',
    barcode: '',
    warehouses: [],
    productTypes: [],
    expiryRange: 'all',
    page: 1,
    longPage: 1,
    pageSize: 50,
  })
  fetchAnalysis()
}

function changePage(page) {
  query.page = page
  fetchAnalysis()
}

function changeLongPage(page) {
  query.longPage = page
  fetchAnalysis()
}

function changePageSize(pageSize) {
  query.pageSize = pageSize
  query.page = 1
  query.longPage = 1
  fetchAnalysis()
}

onMounted(() => Promise.all([fetchWarehouses(), fetchAnalysis()]))
</script>

<template>
  <div class="page-stack" v-loading="loading">
    <section class="toolbar-panel inventory-filter-panel">
      <div class="inventory-filter-grid inventory-filter-grid--batch">
        <label class="inventory-filter-field">
          <span>商品信息</span>
          <el-input v-model="query.keyword" clearable placeholder="商品 / 品牌 / 条码" @keyup.enter="fetchAnalysis(true)" />
        </label>
        <label class="inventory-filter-field">
          <span>货品条码</span>
          <el-input v-model="query.barcode" clearable placeholder="输入货品条码" @keyup.enter="fetchAnalysis(true)" />
        </label>
        <label class="inventory-filter-field">
          <span>仓库名称</span>
          <WarehouseFilter
            v-model="query.warehouses"
            :options="warehouseOptions"
            :loading="warehouseLoading"
          />
        </label>
        <label class="inventory-filter-field">
          <span>货品分类</span>
          <ProductTypeFilter v-model="query.productTypes" :options="productTypeOptions" :loading="warehouseLoading" />
        </label>
        <label class="inventory-filter-field inventory-filter-field--compact">
          <span>剩余效期</span>
          <el-select v-model="query.expiryRange">
            <el-option label="全部效期" value="all" />
            <el-option label="已过期" value="expired" />
            <el-option label="0-6个月" value="0_6" />
            <el-option label="6-12个月" value="6_12" />
            <el-option label="12-24个月" value="12_24" />
            <el-option label="24个月以上" value="gt_24" />
            <el-option label="缺少到期日期" value="missing" />
          </el-select>
        </label>
        <label class="inventory-filter-field inventory-filter-field--compact">
          <span>每页数量</span>
          <el-select v-model="query.pageSize">
            <el-option label="20 条" :value="20" />
            <el-option label="50 条" :value="50" />
            <el-option label="100 条" :value="100" />
          </el-select>
        </label>
        <div class="inventory-filter-actions">
          <el-button type="primary" :icon="'Search'" @click="fetchAnalysis(true)">查询</el-button>
          <el-tooltip content="恢复默认筛选" placement="top">
            <el-button :icon="'RefreshLeft'" circle @click="restoreDefaults" />
          </el-tooltip>
          <el-tooltip content="清空筛选" placement="top">
            <el-button :icon="'Delete'" circle @click="clearFilters" />
          </el-tooltip>
        </div>
      </div>
    </section>

    <div class="metric-grid">
      <MetricCard v-for="item in metrics" :key="item.label" v-bind="item" />
    </div>

    <section class="panel">
      <header>
        <h2>FEFO 出库优先级<span class="panel-source">（批次货品库存查询）</span></h2>
        <el-button :icon="'Refresh'" circle @click="fetchAnalysis" />
      </header>
      <v-chart class="rank-chart" :option="fefoChartOption" autoresize />
      <el-table :data="analysis.fefo_rows" height="560">
        <el-table-column label="顺序" width="76" align="center">
          <template #default="{ row }"><span class="rank-badge">{{ row.rank }}</span></template>
        </el-table-column>
        <el-table-column prop="warehouse" label="仓库" width="170" show-overflow-tooltip />
        <el-table-column prop="product" label="商品" min-width="260" show-overflow-tooltip>
          <template #default="{ row }">
            <el-button link type="primary" class="inventory-product-link" @click="openProduct(row)">{{ row.product }}</el-button>
          </template>
        </el-table-column>
        <el-table-column prop="barcode" label="货品条码" width="170" show-overflow-tooltip />
        <el-table-column prop="brand" label="品牌" width="130" show-overflow-tooltip />
        <el-table-column prop="product_type" label="货品分类" width="110" show-overflow-tooltip />
        <el-table-column prop="batch" label="批次" width="150" show-overflow-tooltip />
        <el-table-column prop="production_date" label="生产日期" width="120" />
        <el-table-column prop="expiry_date" label="到期日期" width="120" />
        <el-table-column label="剩余效期" width="140">
          <template #default="{ row }">{{ remainingText(row.remaining_days) }}</template>
        </el-table-column>
        <el-table-column prop="available_stock" label="可用库存" width="120">
          <template #default="{ row }">{{ formatNumber(row.available_stock) }}</template>
        </el-table-column>
        <el-table-column label="FEFO建议" width="130">
          <template #default="{ row }">
            <el-tag :type="row.fefo_rank === 1 ? 'danger' : 'info'" effect="plain">
              {{ row.fefo_rank === 1 ? '优先出库' : `第 ${row.fefo_rank} 顺位` }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="效期状态" width="130">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
      <div class="table-footer">
        <el-pagination
          background
          layout="total, sizes, prev, pager, next"
          :total="total"
          :current-page="query.page"
          :page-size="query.pageSize"
          :page-sizes="[20, 50, 100]"
          @current-change="changePage"
          @size-change="changePageSize"
        />
      </div>
    </section>

    <section class="panel">
      <header>
        <h2>剩余效期超过24个月商品排行<span class="panel-source">（按长期库存占用）</span></h2>
      </header>
      <v-chart class="rank-chart" :option="longExpiryChartOption" autoresize />
      <el-table :data="analysis.long_expiry_rows" height="420">
        <el-table-column label="排名" width="76" align="center">
          <template #default="{ row }"><span class="rank-badge">{{ row.rank }}</span></template>
        </el-table-column>
        <el-table-column prop="warehouse" label="仓库" width="190" show-overflow-tooltip />
        <el-table-column prop="product" label="商品" min-width="320" show-overflow-tooltip>
          <template #default="{ row }">
            <el-button link type="primary" class="inventory-product-link" @click="openProduct(row)">{{ row.product }}</el-button>
          </template>
        </el-table-column>
        <el-table-column prop="barcode" label="货品条码" width="170" show-overflow-tooltip />
        <el-table-column prop="brand" label="品牌" width="150" show-overflow-tooltip />
        <el-table-column prop="product_type" label="货品分类" width="110" show-overflow-tooltip />
        <el-table-column prop="batch_count" label="批次数" width="100">
          <template #default="{ row }">{{ formatNumber(row.batch_count) }}</template>
        </el-table-column>
        <el-table-column prop="nearest_expiry_date" label="最近到期日" width="130" />
        <el-table-column prop="remaining_months" label="最近到期剩余月数" width="160">
          <template #default="{ row }">{{ formatNumber(row.remaining_months, 1) }}</template>
        </el-table-column>
        <el-table-column prop="available_stock" label="可用库存" width="130">
          <template #default="{ row }">{{ formatNumber(row.available_stock) }}</template>
        </el-table-column>
      </el-table>
      <div class="table-footer">
        <el-pagination
          background
          layout="total, prev, pager, next"
          :total="longTotal"
          :current-page="query.longPage"
          :page-size="query.pageSize"
          @current-change="changeLongPage"
        />
      </div>
    </section>

    <ProductInventoryDrawer ref="productDrawer" />
  </div>
</template>
