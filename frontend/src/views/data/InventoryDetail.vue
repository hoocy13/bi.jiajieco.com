<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ExportExcelButton from '../../components/common/ExportExcelButton.vue'
import MetricCard from '../../components/dashboard/MetricCard.vue'
import ProductInventoryDrawer from '../../components/inventory/ProductInventoryDrawer.vue'
import ProductTypeFilter from '../../components/inventory/ProductTypeFilter.vue'
import WarehouseFilter from '../../components/inventory/WarehouseFilter.vue'
import { getInventoryDetail, getInventoryOverview, getInventoryWarehouses } from '../../api/inventory'
import { DEFAULT_INVENTORY_PRODUCT_TYPES, DEFAULT_INVENTORY_WAREHOUSES } from '../../constants/inventory'
import { inventoryQuery, productTypeParam, queryArray } from '../../utils/inventoryFilters'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const warehouseLoading = ref(false)
const warehouseOptions = ref([])
const productTypeOptions = ref([...DEFAULT_INVENTORY_PRODUCT_TYPES])
const productDrawer = ref(null)
const rows = ref([])
const total = ref(0)
const overviewMetrics = ref({ product_count: 0, stock_quantity: 0, available_stock: 0, stock_amount: 0 })
const query = reactive({
  keyword: String(route.query.keyword || ''),
  barcode: String(route.query.barcode || ''),
  warehouses: queryArray(route.query.warehouse, DEFAULT_INVENTORY_WAREHOUSES),
  productTypes: route.query.product_type === '__all__' ? [] : queryArray(route.query.product_type, DEFAULT_INVENTORY_PRODUCT_TYPES),
  page: Number(route.query.page || 1),
  pageSize: Number(route.query.page_size || 50),
})

const occupiedStock = computed(() => Number(overviewMetrics.value.stock_quantity || 0) - Number(overviewMetrics.value.available_stock || 0))
const stockAmountAvailable = computed(() => overviewMetrics.value.stock_amount_available !== false)
const exportFilters = computed(() => ({
  keyword: query.keyword.trim() || undefined,
  barcode: query.barcode.trim() || undefined,
  warehouse: query.warehouses,
  product_type: productTypeParam(query.productTypes),
}))
const metrics = computed(() => [
  { label: '库存商品', value: formatNumber(overviewMetrics.value.product_count), unit: '个', trend: '按货品编号去重' },
  { label: '库存数量', value: formatNumber(overviewMetrics.value.stock_quantity), unit: '件', trend: `占用或不可用 ${formatNumber(occupiedStock.value)} 件` },
  { label: '可用库存', value: formatNumber(overviewMetrics.value.available_stock), unit: '件', trend: '当前可直接销售库存' },
  { label: '库存金额', value: stockAmountAvailable.value ? formatNumber(overviewMetrics.value.stock_amount, 2) : '暂不可用', unit: stockAmountAvailable.value ? '元' : '', trend: stockAmountAvailable.value ? '按库存快照成本金额' : '源数据成本字段当前为空' },
])

function formatNumber(value, digits = 0) {
  return Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

function openProduct(row) {
  productDrawer.value?.open(row.product_code, query.warehouses)
}

async function fetchOptions() {
  warehouseLoading.value = true
  try {
    const result = await getInventoryWarehouses()
    warehouseOptions.value = result.data.warehouses
    productTypeOptions.value = result.data.product_types || [...DEFAULT_INVENTORY_PRODUCT_TYPES]
  } finally {
    warehouseLoading.value = false
  }
}

async function fetchRows(resetPage = false) {
  if (resetPage) query.page = 1
  router.replace({ query: inventoryQuery({
    keyword: query.keyword.trim(), barcode: query.barcode.trim(), warehouse: query.warehouses,
    product_type: query.productTypes.length ? query.productTypes : '__all__',
    page: query.page, page_size: query.pageSize,
  }) })
  loading.value = true
  try {
    const params = {
      keyword: query.keyword.trim(), barcode: query.barcode.trim(), warehouse: query.warehouses,
      product_type: productTypeParam(query.productTypes), page: query.page, page_size: query.pageSize,
    }
    const [detailResult, overviewResult] = await Promise.all([
      getInventoryDetail(params),
      getInventoryOverview({ warehouse: query.warehouses, product_type: productTypeParam(query.productTypes) }),
    ])
    rows.value = detailResult.data.rows
    total.value = detailResult.data.pagination.total
    overviewMetrics.value = {
      ...detailResult.data.metrics,
      stock_amount_available: overviewResult.data.metrics.stock_amount_available,
    }
  } finally {
    loading.value = false
  }
}

function restoreDefaults() {
  Object.assign(query, { keyword: '', barcode: '', warehouses: [...DEFAULT_INVENTORY_WAREHOUSES], productTypes: [...DEFAULT_INVENTORY_PRODUCT_TYPES], page: 1, pageSize: 50 })
  fetchRows()
}

function clearFilters() {
  Object.assign(query, { keyword: '', barcode: '', warehouses: [], productTypes: [], page: 1, pageSize: 50 })
  fetchRows()
}

function changePage(page) { query.page = page; fetchRows() }
function changePageSize(pageSize) { query.pageSize = pageSize; query.page = 1; fetchRows() }

onMounted(() => Promise.all([fetchOptions(), fetchRows()]))
</script>

<template>
  <div class="page-stack inventory-detail-page" v-loading="loading">
    <section class="inventory-detail-intro">
      <div>
        <span>库存查询</span>
        <h2>库存明细</h2>
        <p>按商品、仓库和货品分类查询最新库存快照。</p>
      </div>
      <div class="inventory-detail-update">
        <span>业务操作前请以吉客云实时库存为准</span>
      </div>
    </section>

    <section class="toolbar-panel inventory-filter-panel">
      <div class="inventory-detail-filters">
        <label class="inventory-filter-field inventory-detail-keyword"><span>商品信息</span><el-input v-model="query.keyword" clearable placeholder="商品名称 / 编号 / 品牌" @keyup.enter="fetchRows(true)" /></label>
        <label class="inventory-filter-field"><span>货品条码</span><el-input v-model="query.barcode" clearable placeholder="输入条码" @keyup.enter="fetchRows(true)" /></label>
        <label class="inventory-filter-field"><span>仓库名称</span><WarehouseFilter v-model="query.warehouses" :options="warehouseOptions" :loading="warehouseLoading" /></label>
        <label class="inventory-filter-field"><span>货品分类</span><ProductTypeFilter v-model="query.productTypes" :options="productTypeOptions" :loading="warehouseLoading" /></label>
        <div class="inventory-filter-actions">
          <el-button type="primary" :icon="'Search'" @click="fetchRows(true)">查询</el-button>
          <el-tooltip content="恢复默认筛选" placement="top"><el-button :icon="'RefreshLeft'" circle @click="restoreDefaults" /></el-tooltip>
          <el-tooltip content="清空筛选" placement="top"><el-button :icon="'Delete'" circle @click="clearFilters" /></el-tooltip>
        </div>
      </div>
    </section>

    <div class="metric-grid inventory-overview-metrics"><MetricCard v-for="item in metrics" :key="item.label" v-bind="item" /></div>

    <section class="panel inventory-detail-table-panel">
      <header>
        <div><h2>库存明细<span class="panel-source">（共 {{ formatNumber(total) }} 条）</span></h2><p>按商品和仓库展示当前库存快照</p></div>
        <div class="header-actions"><ExportExcelButton dataset="inventory-detail" :filters="exportFilters" :total="total" /><el-button :icon="'Refresh'" circle @click="fetchRows" /></div>
      </header>
      <el-table :data="rows" height="590" stripe>
        <el-table-column prop="product_code" label="货品编号" width="150" show-overflow-tooltip />
        <el-table-column prop="product" label="商品名称" min-width="300" show-overflow-tooltip><template #default="{ row }"><el-button link type="primary" class="inventory-product-link" @click="openProduct(row)">{{ row.product }}</el-button></template></el-table-column>
        <el-table-column prop="barcode" label="条码" width="160" show-overflow-tooltip />
        <el-table-column prop="brand" label="品牌" width="130" show-overflow-tooltip />
        <el-table-column prop="product_type" label="分类" width="90" />
        <el-table-column prop="warehouse" label="仓库" width="180" show-overflow-tooltip />
        <el-table-column prop="stock" label="库存数量" width="125" sortable><template #default="{ row }">{{ formatNumber(row.stock) }}</template></el-table-column>
        <el-table-column prop="available_stock" label="可用库存" width="125" sortable><template #default="{ row }"><strong :class="{ 'is-stock-warning': row.available_stock <= 0 }">{{ formatNumber(row.available_stock) }}</strong></template></el-table-column>
        <el-table-column prop="stock_amount" label="库存金额" width="150" sortable><template #default="{ row }">{{ stockAmountAvailable ? formatNumber(row.stock_amount, 2) : '暂不可用' }}</template></el-table-column>
        <el-table-column prop="sales30" label="近30天销量" width="130" sortable><template #default="{ row }">{{ formatNumber(row.sales30) }}</template></el-table-column>
        <el-table-column prop="sales90" label="近90天销量" width="130" sortable><template #default="{ row }">{{ formatNumber(row.sales90) }}</template></el-table-column>
      </el-table>
      <div class="table-footer"><el-pagination background layout="total, sizes, prev, pager, next" :total="total" :current-page="query.page" :page-size="query.pageSize" :page-sizes="[20, 50, 100]" @current-change="changePage" @size-change="changePageSize" /></div>
    </section>
    <ProductInventoryDrawer ref="productDrawer" />
  </div>
</template>

<style scoped>
.inventory-detail-intro { display: flex; align-items: center; justify-content: space-between; gap: 24px; min-height: 112px; padding: 20px 22px; border: 1px solid var(--theme-soft-strong); border-radius: var(--radius); background: linear-gradient(120deg, var(--surface) 0%, var(--accent-soft) 100%); }
.inventory-detail-intro > div:first-child { display: grid; gap: 5px; }
.inventory-detail-intro span { color: var(--accent-strong); font-size: 11px; font-weight: 750; }
.inventory-detail-intro h2 { margin: 0; color: var(--text); font-size: 24px; }
.inventory-detail-intro p, .inventory-detail-table-panel header p { margin: 0; color: var(--muted-2); font-size: 12px; }
.inventory-detail-update { display: grid; justify-items: end; gap: 5px; text-align: right; }
.inventory-detail-update span { color: var(--muted-2); font-weight: 500; }
.inventory-detail-filters { display: grid; grid-template-columns: minmax(240px, 1.3fr) minmax(160px, .8fr) minmax(220px, 1fr) minmax(190px, .9fr) auto; align-items: end; gap: 12px; }
.inventory-detail-table-panel > header { min-height: 66px; }
.inventory-detail-table-panel header > div:first-child { display: grid; gap: 4px; }
.inventory-detail-table-panel h2 { margin: 0; }
.is-stock-warning { color: var(--warning); }
@media (max-width: 1280px) { .inventory-detail-filters { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 720px) { .inventory-detail-intro { align-items: flex-start; flex-direction: column; } .inventory-detail-update { justify-items: start; text-align: left; } .inventory-detail-filters { grid-template-columns: 1fr; } }
</style>
