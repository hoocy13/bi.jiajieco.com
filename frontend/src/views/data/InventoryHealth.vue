<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import MetricCard from '../../components/dashboard/MetricCard.vue'
import ProductInventoryDrawer from '../../components/inventory/ProductInventoryDrawer.vue'
import WarehouseFilter from '../../components/inventory/WarehouseFilter.vue'
import ProductTypeFilter from '../../components/inventory/ProductTypeFilter.vue'
import { getInventoryHealth, getInventoryWarehouses } from '../../api/inventory'
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
const metricsData = ref({
  item_count: 0,
  negative_count: 0,
  missing_barcode_count: 0,
  out_of_stock_count: 0,
  no_sales_count: 0,
  shortage_count: 0,
  overstock_count: 0,
  healthy_count: 0,
})
const query = reactive({
  keyword: String(route.query.keyword || ''),
  barcode: String(route.query.barcode || ''),
  warehouses: queryArray(route.query.warehouse, DEFAULT_INVENTORY_WAREHOUSES),
  productTypes: route.query.product_type === '__all__' ? [] : queryArray(route.query.product_type, DEFAULT_INVENTORY_PRODUCT_TYPES),
  issueType: String(route.query.issue_type || 'all'),
  page: Number(route.query.page || 1),
  pageSize: Number(route.query.page_size || 50),
})

function formatNumber(value, digits = 0) {
  return Number(value || 0).toLocaleString('zh-CN', {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  })
}

const metrics = computed(() => [
  { label: '缺货风险', value: formatNumber(metricsData.value.shortage_count), unit: '项', trend: '预计可售不足14天' },
  { label: '90天无销量', value: formatNumber(metricsData.value.no_sales_count), unit: '项', trend: '有库存但无销量' },
  { label: '超储风险', value: formatNumber(metricsData.value.overstock_count), unit: '项', trend: '预计库存超过180天' },
  { label: '可用库存为零', value: formatNumber(metricsData.value.out_of_stock_count), unit: '项', trend: '存在库存但不可销售' },
  { label: '负库存', value: formatNumber(metricsData.value.negative_count), unit: '项', trend: '优先检查库存同步' },
  { label: '缺少条码', value: formatNumber(metricsData.value.missing_barcode_count), unit: '项', trend: '商品主数据待补充' },
])

function issueType(status) {
  if (status === 'negative' || status === 'out_of_stock') return 'danger'
  if (status === 'shortage' || status === 'missing_barcode') return 'warning'
  return 'info'
}

function openProduct(row) {
  productDrawer.value?.open(row.product_code, query.warehouses)
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

async function fetchRows(resetPage = false) {
  if (resetPage) query.page = 1
  router.replace({
    query: inventoryQuery({
      keyword: query.keyword.trim(),
      barcode: query.barcode.trim(),
      warehouse: query.warehouses,
      product_type: query.productTypes.length ? query.productTypes : '__all__',
      issue_type: query.issueType,
      page: query.page,
      page_size: query.pageSize,
    }),
  })
  loading.value = true
  try {
    const result = await getInventoryHealth({
      keyword: query.keyword.trim(),
      barcode: query.barcode.trim(),
      warehouse: query.warehouses,
      product_type: productTypeParam(query.productTypes),
      issue_type: query.issueType,
      page: query.page,
      page_size: query.pageSize,
    })
    rows.value = result.data.rows
    total.value = result.data.pagination.total
    metricsData.value = result.data.metrics
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
    issueType: 'all',
    page: 1,
    pageSize: 50,
  })
  fetchRows()
}

function clearFilters() {
  Object.assign(query, {
    keyword: '',
    barcode: '',
    warehouses: [],
    productTypes: [],
    issueType: 'all',
    page: 1,
    pageSize: 50,
  })
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

onMounted(() => Promise.all([fetchWarehouses(), fetchRows()]))
</script>

<template>
  <div class="page-stack" v-loading="loading">
    <section class="toolbar-panel inventory-filter-panel">
      <div class="inventory-filter-grid inventory-filter-grid--health">
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
          <WarehouseFilter v-model="query.warehouses" :options="warehouseOptions" :loading="warehouseLoading" />
        </label>
        <label class="inventory-filter-field">
          <span>货品分类</span>
          <ProductTypeFilter v-model="query.productTypes" :options="productTypeOptions" :loading="warehouseLoading" />
        </label>
        <label class="inventory-filter-field">
          <span>异常类型</span>
          <el-select v-model="query.issueType">
            <el-option label="全部异常" value="all" />
            <el-option label="缺货风险" value="shortage" />
            <el-option label="90天无销量" value="no_sales" />
            <el-option label="超储风险" value="overstock" />
            <el-option label="可用库存为零" value="out_of_stock" />
            <el-option label="负库存" value="negative" />
            <el-option label="缺少条码" value="missing_barcode" />
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

    <div class="metric-grid health-metrics inventory-overview-metrics">
      <MetricCard v-for="item in metrics" :key="item.label" v-bind="item" />
    </div>

    <section class="panel">
      <header>
        <h2>库存异常明细<span class="panel-source">（最新库存发布版本）</span></h2>
        <el-button :icon="'Refresh'" circle @click="fetchRows" />
      </header>
      <el-table :data="rows" height="560">
        <el-table-column label="序号" width="74" align="center">
          <template #default="{ row }"><span class="rank-badge">{{ row.rank }}</span></template>
        </el-table-column>
        <el-table-column prop="product" label="商品" min-width="280" show-overflow-tooltip>
          <template #default="{ row }">
            <el-button link type="primary" class="inventory-product-link" @click="openProduct(row)">{{ row.product }}</el-button>
          </template>
        </el-table-column>
        <el-table-column prop="barcode" label="货品条码" width="170" show-overflow-tooltip />
        <el-table-column prop="brand" label="品牌" width="130" show-overflow-tooltip />
        <el-table-column prop="product_type" label="货品分类" width="110" show-overflow-tooltip />
        <el-table-column prop="warehouse" label="仓库" width="170" show-overflow-tooltip />
        <el-table-column prop="available_stock" label="可用库存" width="120">
          <template #default="{ row }">{{ formatNumber(row.available_stock) }}</template>
        </el-table-column>
        <el-table-column prop="sales30" label="近30天销量" width="130">
          <template #default="{ row }">{{ formatNumber(row.sales30) }}</template>
        </el-table-column>
        <el-table-column prop="sales90" label="近90天销量" width="130">
          <template #default="{ row }">{{ formatNumber(row.sales90) }}</template>
        </el-table-column>
        <el-table-column label="预计可售天数" width="140">
          <template #default="{ row }">{{ row.available_days === null ? '-' : formatNumber(row.available_days, 1) }}</template>
        </el-table-column>
        <el-table-column label="异常类型" width="140">
          <template #default="{ row }"><el-tag :type="issueType(row.issue_type)">{{ row.issue_label }}</el-tag></template>
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
