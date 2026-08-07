<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import WarehouseFilter from '../../components/inventory/WarehouseFilter.vue'
import ProductTypeFilter from '../../components/inventory/ProductTypeFilter.vue'
import ProductInventoryDrawer from '../../components/inventory/ProductInventoryDrawer.vue'
import BrandInventoryTurnover from '../../components/inventory/BrandInventoryTurnover.vue'
import { getInventoryTurnover, getInventoryWarehouses } from '../../api/inventory'
import { DEFAULT_INVENTORY_PRODUCT_TYPES, DEFAULT_INVENTORY_WAREHOUSES } from '../../constants/inventory'
import { inventoryQuery, productTypeParam, queryArray } from '../../utils/inventoryFilters'
import { getSavedTheme } from '../../utils/theme'

use([CanvasRenderer, BarChart, GridComponent, TooltipComponent])

const chartTheme = getSavedTheme()

const route = useRoute()
const router = useRouter()
const activeView = ref(route.query.view === 'product' ? 'product' : 'brand')
const viewOptions = [
  { label: '品牌周转', value: 'brand' },
  { label: '商品周转', value: 'product' },
]
const stockMinimumOptions = [
  { label: '库存不限', value: 0 },
  { label: '库存 ≥ 100 件', value: 100 },
  { label: '库存 ≥ 500 件', value: 500 },
  { label: '库存 ≥ 1,000 件', value: 1000 },
  { label: '库存 ≥ 5,000 件', value: 5000 },
]
const loading = ref(false)
const warehouseLoading = ref(false)
const warehouseOptions = ref([])
const productTypeOptions = ref([...DEFAULT_INVENTORY_PRODUCT_TYPES])
const query = reactive({
  keyword: String(route.query.keyword || ''),
  barcode: String(route.query.barcode || ''),
  warehouses: queryArray(route.query.warehouse, DEFAULT_INVENTORY_WAREHOUSES),
  productTypes: route.query.product_type === '__all__' ? [] : queryArray(route.query.product_type, DEFAULT_INVENTORY_PRODUCT_TYPES),
  minStock: Number(route.query.min_stock ?? 100),
  page: Number(route.query.page || 1),
  pageSize: Number(route.query.page_size || 50),
})
const rows = ref([])
const total = ref(0)
const productDrawer = ref(null)

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
  if (status === '正常') return 'success'
  if (status === '偏慢') return 'warning'
  return 'danger'
}

function turnoverText(days) {
  return days === null || days === undefined ? '无销量' : `${formatNumber(days, 1)} 天`
}

function openProduct(row) {
  productDrawer.value?.open(row.product_code, query.warehouses)
}

const finiteTurnoverRows = computed(() => rows.value
  .filter((row) => row.turnover_days !== null && row.turnover_days !== undefined)
  .slice(0, 10))

const noSalesRows = computed(() => rows.value
  .filter((row) => row.turnover_days === null || row.turnover_days === undefined)
  .slice()
  .sort((a, b) => Number(b.stock || 0) - Number(a.stock || 0))
  .slice(0, 10))

const chartMode = computed(() => finiteTurnoverRows.value.length > 0 ? 'turnover' : 'noSales')
const chartTitle = computed(() => chartMode.value === 'turnover' ? '周转天数 Top' : '无销量库存 Top')
const chartSourceNote = computed(() => chartMode.value === 'turnover' ? '越长表示卖得越慢' : '当前页无可计算周转天数，按库存数量展示')

const turnoverChartRows = computed(() => (
  chartMode.value === 'turnover' ? finiteTurnoverRows.value : noSalesRows.value
).slice().reverse())

const noSalesCount = computed(() => rows.value.filter((row) => row.turnover_days === null || row.turnover_days === undefined).length)
const slowCount = computed(() => rows.value.filter((row) => row.turnover_days !== null && row.turnover_days > 180).length)

const turnoverChartOption = computed(() => {
  const isNoSalesMode = chartMode.value === 'noSales'
  const valueKey = isNoSalesMode ? 'stock' : 'turnover_days'
  const seriesName = isNoSalesMode ? '无销量库存' : '周转天数'
  const unit = isNoSalesMode ? '件' : '天'

  return {
    color: [isNoSalesMode ? '#d94a4a' : chartTheme.primary],
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: '#111217',
      borderWidth: 0,
      textStyle: { color: '#ffffff' },
      formatter: (params) => {
        const item = params[0]
        const row = turnoverChartRows.value[item.dataIndex]
        return `${row.product}<br/>周转天数：${turnoverText(row.turnover_days)}<br/>库存：${formatNumber(row.stock)} 件<br/>近30天销量：${formatNumber(row.sales30)} 件`
      },
    },
    grid: { top: 16, left: 150, right: 58, bottom: 22 },
    xAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: '#eceef3' } },
      axisLabel: { color: '#9aa0aa', formatter: (value) => `${formatNumber(value)}${unit}` },
    },
    yAxis: {
      type: 'category',
      data: turnoverChartRows.value.map((item) => shortName(item.product)),
      axisTick: { show: false },
      axisLine: { show: false },
      axisLabel: { color: '#6f7480', width: 140, overflow: 'truncate' },
    },
    series: [
      {
        name: seriesName,
        type: 'bar',
        barWidth: 12,
        itemStyle: { borderRadius: [0, 8, 8, 0] },
        label: {
          show: true,
          position: 'right',
          color: '#6f7480',
          fontSize: 11,
          formatter: (params) => `${formatNumber(params.value, isNoSalesMode ? 0 : 1)}${unit}`,
        },
        data: turnoverChartRows.value.map((item) => item[valueKey]),
      },
    ],
  }
})

async function fetchRows(resetPage = false) {
  if (resetPage) query.page = 1
  router.replace({
    query: inventoryQuery({
      view: 'product',
      keyword: query.keyword.trim(),
      barcode: query.barcode.trim(),
      warehouse: query.warehouses,
      product_type: query.productTypes.length ? query.productTypes : '__all__',
      min_stock: query.minStock,
      page: query.page,
      page_size: query.pageSize,
    }),
  })
  loading.value = true
  try {
    const params = { min_stock: query.minStock, page: query.page, page_size: query.pageSize }
    if (query.keyword.trim()) params.keyword = query.keyword.trim()
    if (query.barcode.trim()) params.barcode = query.barcode.trim()
    if (query.warehouses.length) params.warehouse = query.warehouses
    params.product_type = productTypeParam(query.productTypes)
    const result = await getInventoryTurnover(params)
    rows.value = result.data.rows
    total.value = result.data.pagination.total
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
    minStock: 100,
    page: 1,
    pageSize: 50,
  })
  fetchRows()
}

function clearFilters() {
  Object.assign(query, { keyword: '', barcode: '', warehouses: [], productTypes: [], minStock: 0, page: 1, pageSize: 50 })
  fetchRows()
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

function switchView(value) {
  activeView.value = value
  router.replace({ query: { view: value } })
  if (value === 'product' && !rows.value.length) {
    Promise.all([fetchWarehouses(), fetchRows()])
  }
}

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

onMounted(() => {
  if (activeView.value === 'product') return Promise.all([fetchWarehouses(), fetchRows()])
  return undefined
})
</script>

<template>
  <div class="page-stack" :class="{ 'is-brand-turnover': activeView === 'brand' }" v-loading="loading">
    <section class="inventory-turnover-tabs">
      <div>
        <strong>库存周转</strong>
        <span>按商品或品牌查看库存消化速度</span>
      </div>
      <el-segmented v-model="activeView" :options="viewOptions" @change="switchView" />
    </section>

    <template v-if="activeView === 'product'">
    <section class="toolbar-panel inventory-filter-panel">
      <div class="inventory-filter-grid inventory-filter-grid--turnover">
        <label class="inventory-filter-field">
          <span>商品信息</span>
          <el-input v-model="query.keyword" clearable placeholder="商品 / 品牌 / 条码" @keyup.enter="fetchRows(true)" />
        </label>
        <label class="inventory-filter-field">
          <span>货品条码</span>
          <el-input v-model="query.barcode" clearable placeholder="输入货品条码" @keyup.enter="fetchRows(true)" />
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
        <label class="inventory-filter-field inventory-filter-field--stock">
          <span>当前库存门槛</span>
          <el-select v-model="query.minStock">
            <el-option
              v-for="item in stockMinimumOptions"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
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
          <el-button type="primary" :icon="'Search'" @click="fetchRows(true)">查询</el-button>
          <el-tooltip content="恢复默认筛选" placement="top">
            <el-button :icon="'RefreshLeft'" circle @click="restoreDefaults" />
          </el-tooltip>
          <el-tooltip content="清空筛选" placement="top">
            <el-button :icon="'Delete'" circle @click="clearFilters" />
          </el-tooltip>
        </div>
      </div>
    </section>

    <section class="turnover-guide">
      <div>
        <strong>库存周转怎么看</strong>
        <p>库存周转天数 = 当前库存 / 近30天日均销量。它表示按最近销量速度，这批库存大约还够卖多少天。</p>
      </div>
      <div>
        <span>≤ 90 天</span>
        <strong>正常</strong>
      </div>
      <div>
        <span>90-180 天</span>
        <strong>偏慢</strong>
      </div>
      <div>
        <span>&gt; 180 天 / 无销量</span>
        <strong>需关注</strong>
      </div>
      <div>
        <span>当前页过慢</span>
        <strong>{{ formatNumber(slowCount + noSalesCount) }}</strong>
      </div>
    </section>

    <section class="panel">
      <header>
        <h2>{{ chartTitle }}<span class="panel-source">（{{ chartSourceNote }}）</span></h2>
      </header>
      <v-chart class="rank-chart" :option="turnoverChartOption" autoresize />
    </section>

    <section class="panel">
      <header>
        <h2>库存周转<span class="panel-source">（分仓库查询）</span></h2>
        <el-button :icon="'Refresh'" circle @click="fetchRows" />
      </header>
      <el-table :data="rows" height="560">
        <el-table-column label="排名" width="74" align="center">
          <template #default="{ row }">
            <span class="rank-badge">{{ row.rank }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="product" label="商品" min-width="280" show-overflow-tooltip>
          <template #default="{ row }">
            <el-button link type="primary" class="inventory-product-link" @click="openProduct(row)">{{ row.product }}</el-button>
          </template>
        </el-table-column>
        <el-table-column prop="barcode" label="货品条码" width="170" show-overflow-tooltip />
        <el-table-column prop="brand" label="品牌" width="150" show-overflow-tooltip />
        <el-table-column prop="product_type" label="货品分类" width="110" show-overflow-tooltip />
        <el-table-column prop="warehouse" label="仓库" width="160" show-overflow-tooltip />
        <el-table-column prop="stock" label="库存数量" width="130">
          <template #default="{ row }">{{ formatNumber(row.stock) }}</template>
        </el-table-column>
        <el-table-column prop="available_stock" label="可用库存" width="130">
          <template #default="{ row }">{{ formatNumber(row.available_stock) }}</template>
        </el-table-column>
        <el-table-column prop="sales30" label="近30天销量" width="140">
          <template #default="{ row }">{{ formatNumber(row.sales30) }}</template>
        </el-table-column>
        <el-table-column prop="turnover_days" label="周转天数" width="130">
          <template #default="{ row }">{{ turnoverText(row.turnover_days) }}</template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="120">
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

    <ProductInventoryDrawer ref="productDrawer" />
    </template>

    <BrandInventoryTurnover v-else />
  </div>
</template>

<style scoped>
.page-stack.is-brand-turnover {
  --accent: var(--theme-primary);
  --accent-strong: var(--theme-strong);
  --accent-soft: var(--theme-soft);
  --el-color-primary: var(--theme-primary);
  --el-color-primary-light-3: color-mix(in srgb, var(--theme-primary) 70%, white);
  --el-color-primary-light-5: color-mix(in srgb, var(--theme-primary) 50%, white);
  --el-color-primary-light-7: color-mix(in srgb, var(--theme-primary) 30%, white);
  --el-color-primary-light-9: var(--theme-soft);
  --el-color-primary-dark-2: var(--theme-strong);
}
.inventory-turnover-tabs {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 14px 16px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 10px;
}
.inventory-turnover-tabs > div { display: grid; gap: 4px; }
.inventory-turnover-tabs strong { color: var(--text); font-size: 16px; }
.inventory-turnover-tabs span { color: var(--muted); font-size: 12px; }
.inventory-filter-grid--turnover {
  grid-template-columns:
    minmax(150px, 1fr)
    minmax(120px, .7fr)
    minmax(190px, 1.3fr)
    minmax(130px, .75fr)
    minmax(145px, .72fr)
    minmax(100px, .55fr)
    auto;
}
.is-brand-turnover .inventory-turnover-tabs { border-top: 3px solid var(--accent); }
@media (max-width: 1180px) {
  .inventory-filter-grid--turnover { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 640px) {
  .inventory-turnover-tabs { align-items: stretch; flex-direction: column; }
  .inventory-filter-grid--turnover { grid-template-columns: 1fr; }
}
</style>
