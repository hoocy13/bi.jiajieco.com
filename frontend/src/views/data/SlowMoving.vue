<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import WarehouseFilter from '../../components/inventory/WarehouseFilter.vue'
import ProductTypeFilter from '../../components/inventory/ProductTypeFilter.vue'
import ProductInventoryDrawer from '../../components/inventory/ProductInventoryDrawer.vue'
import { getInventoryWarehouses, getSlowMovingInventory } from '../../api/inventory'
import { DEFAULT_INVENTORY_PRODUCT_TYPES, DEFAULT_INVENTORY_WAREHOUSES } from '../../constants/inventory'
import { inventoryQuery, productTypeParam, queryArray } from '../../utils/inventoryFilters'

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

function openProduct(row) {
  productDrawer.value?.open(row.product_code, query.warehouses)
}

async function fetchRows(resetPage = false) {
  if (resetPage) query.page = 1
  router.replace({
    query: inventoryQuery({
      keyword: query.keyword.trim(),
      barcode: query.barcode.trim(),
      warehouse: query.warehouses,
      product_type: query.productTypes.length ? query.productTypes : '__all__',
      page: query.page,
      page_size: query.pageSize,
    }),
  })
  loading.value = true
  try {
    const params = { page: query.page, page_size: query.pageSize }
    if (query.keyword.trim()) params.keyword = query.keyword.trim()
    if (query.barcode.trim()) params.barcode = query.barcode.trim()
    if (query.warehouses.length) params.warehouse = query.warehouses
    params.product_type = productTypeParam(query.productTypes)
    const result = await getSlowMovingInventory(params)
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
    page: 1,
    pageSize: 50,
  })
  fetchRows()
}

function clearFilters() {
  Object.assign(query, { keyword: '', barcode: '', warehouses: [], productTypes: [], page: 1, pageSize: 50 })
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

onMounted(() => Promise.all([fetchWarehouses(), fetchRows()]))
</script>

<template>
  <div class="page-stack" v-loading="loading">
    <section class="toolbar-panel inventory-filter-panel">
      <div class="inventory-filter-grid">
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

    <section class="panel">
      <header>
        <h2>滞销商品<span class="panel-source">（分仓库查询）</span></h2>
        <el-button :icon="'Refresh'" circle @click="fetchRows" />
      </header>
      <el-table :data="rows" height="560">
        <el-table-column label="排名" width="74" align="center">
          <template #default="{ row }">
            <span class="rank-badge">{{ row.rank }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="product" label="商品" min-width="300" show-overflow-tooltip>
          <template #default="{ row }">
            <el-button link type="primary" class="inventory-product-link" @click="openProduct(row)">{{ row.product }}</el-button>
          </template>
        </el-table-column>
        <el-table-column prop="barcode" label="货品条码" width="170" show-overflow-tooltip />
        <el-table-column prop="brand" label="品牌" width="150" show-overflow-tooltip />
        <el-table-column prop="product_type" label="货品分类" width="110" show-overflow-tooltip />
        <el-table-column prop="warehouse_count" label="仓库数" width="110">
          <template #default="{ row }">{{ formatNumber(row.warehouse_count) }}</template>
        </el-table-column>
        <el-table-column prop="stock" label="库存数量" width="130">
          <template #default="{ row }">{{ formatNumber(row.stock) }}</template>
        </el-table-column>
        <el-table-column prop="available_stock" label="可用库存" width="130">
          <template #default="{ row }">{{ formatNumber(row.available_stock) }}</template>
        </el-table-column>
        <el-table-column prop="sales30" label="近30天销量" width="140">
          <template #default="{ row }">{{ formatNumber(row.sales30) }}</template>
        </el-table-column>
        <el-table-column prop="sales90" label="近90天销量" width="140">
          <template #default="{ row }">{{ formatNumber(row.sales90) }}</template>
        </el-table-column>
        <el-table-column prop="stock_amount" label="库存金额" width="160">
          <template #default="{ row }">{{ formatNumber(row.stock_amount, 2) }}</template>
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
  </div>
</template>
