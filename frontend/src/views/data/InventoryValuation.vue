<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '../../stores/auth'
import WarehouseFilter from '../../components/inventory/WarehouseFilter.vue'
import ProductTypeFilter from '../../components/inventory/ProductTypeFilter.vue'
import { DEFAULT_INVENTORY_PRODUCT_TYPES } from '../../constants/inventory'
import { inventoryQuery, productTypeParam, queryArray } from '../../utils/inventoryFilters'
import { getInventoryWarehouses, getInventoryValuation, exportInventoryValuation, getCoreCostPrices, exportCoreCostPrices, getCoreCostHistory, saveCoreCostPrice, deleteCoreCostPrice, restoreCoreCostPrice, previewCoreCostImport, importCoreCostPrices, previewCoreCostBatch, saveCoreCostBatch } from '../../api/inventory'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const canManage = computed(() => auth.hasPermission('inventory.price.manage'))
const tab = ref(route.query.tab === 'prices' && canManage.value ? 'prices' : route.query.tab === 'split' ? 'split' : 'total')
const loading = ref(false)
const warehouseOptions = ref([])
const productTypeOptions = ref([...DEFAULT_INVENTORY_PRODUCT_TYPES])
const brandOptions = ref([])
const result = ref({ rows: [], pagination: { total: 0 }, metrics: {}, stock: 0, available_stock: 0 })
const filters = reactive({
  keyword: String(route.query.keyword || ''), brands: queryArray(route.query.brand),
  warehouses: queryArray(route.query.warehouse),
  productTypes: route.query.product_type === '__all__' ? [] : queryArray(route.query.product_type, DEFAULT_INVENTORY_PRODUCT_TYPES),
  missingPrice: String(route.query.missing_price || 'all'),
  page: Number(route.query.page || 1), pageSize: Number(route.query.page_size || 50),
})
const prices = ref([])
const pricePagination = reactive({ page: Number(route.query.price_page || 1), pageSize: 50, total: 0 })
const priceSort = reactive({ prop: String(route.query.price_sort || 'barcode'), order: String(route.query.price_order || 'asc') })
const priceFilters = reactive({
  keyword: String(route.query.price_keyword || ''),
  brands: queryArray(route.query.price_brand),
  source: ['all', 'priced', 'missing', 'delete'].includes(String(route.query.price_source)) ? String(route.query.price_source) : 'priced',
  productTypes: queryArray(route.query.price_product_type),
  minPrice: route.query.price_min ? Number(route.query.price_min) : null,
  maxPrice: route.query.price_max ? Number(route.query.price_max) : null,
  minDiscount: route.query.discount_min != null ? Number(route.query.discount_min) : null,
  maxDiscount: route.query.discount_max != null ? Number(route.query.discount_max) : null,
})
const editorVisible = ref(false)
const savingPrice = ref(false)
const editingCode = ref('')
const editor = reactive({ product_code: '', product_name: '', price: null, pricing_mode: 'fixed', discount: null, retail_price: null, tax_price: null, brand: '', product_type: '', id: null, retail_price_conflict: false })
const calculatedPrice = computed(() => editor.retail_price > 0 && editor.discount > 0 ? Math.round((Number(editor.retail_price) * Number(editor.discount) / 10 + Number.EPSILON) * 100) / 100 : null)
const batchVisible = ref(false)
const batchDiscount = ref(null)
const overwriteFixed = ref(false)
const batchPreview = ref(null)
const savingBatch = ref(false)
const historyVisible = ref(false)
const history = ref([])
const historyCode = ref('')
const importVisible = ref(false)
const importPreview = ref({ rows: [], errors: [], blank_price_count: 0 })
const importing = ref(false)

function money(value) {
  return value == null ? '-' : Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
function mutedMoney(value) { return value == null ? '-' : money(value) }
function pricedRatio(value) {
  const stock = Number(result.value.stock || 0)
  return `${(stock ? Number(value || 0) / stock * 100 : 0).toFixed(1)}%`
}
function operatorName(value) { return value === 'initial-import' ? '历史导入（账号未记录）' : value }
function integer(value) { return Number(value || 0).toLocaleString('zh-CN') }
function resetFilters() {
  Object.assign(filters, { keyword: '', brands: [], warehouses: [], productTypes: [...DEFAULT_INVENTORY_PRODUCT_TYPES], missingPrice: 'all', page: 1 })
  loadValuation()
}
function resetPriceFilters() {
  Object.assign(priceFilters, { keyword: '', brands: [], productTypes: [], source: 'priced', minPrice: null, maxPrice: null, minDiscount: null, maxDiscount: null })
  loadPrices(true)
}
function priceParams() {
  return {
    keyword: priceFilters.keyword.trim(), brand: priceFilters.brands, source: priceFilters.source,
    min_price: priceFilters.minPrice, max_price: priceFilters.maxPrice, min_discount: priceFilters.minDiscount, max_discount: priceFilters.maxDiscount, product_type: priceFilters.productTypes,
  }
}
function metric(key) { return result.value.metrics?.[key] || { amount: 0, priced_rows: 0, missing_rows: 0, missing_stock: 0 } }
function syncUrl() {
  router.replace({ query: inventoryQuery({
    tab: tab.value, keyword: filters.keyword.trim(), brand: filters.brands,
    warehouse: filters.warehouses, product_type: filters.productTypes.length ? filters.productTypes : '__all__',
    missing_price: filters.missingPrice, page: filters.page, page_size: filters.pageSize,
    price_keyword: priceFilters.keyword.trim(), price_brand: priceFilters.brands, price_source: priceFilters.source,
    price_min: priceFilters.minPrice, price_max: priceFilters.maxPrice, discount_min: priceFilters.minDiscount, discount_max: priceFilters.maxDiscount, price_product_type: priceFilters.productTypes,
    price_page: pricePagination.page, price_sort: priceSort.prop, price_order: priceSort.order,
  }) })
}
async function loadValuation(reset = false) {
  if (reset) filters.page = 1
  syncUrl()
  loading.value = true
  try {
    const response = await getInventoryValuation({
      keyword: filters.keyword.trim(), brand: filters.brands, warehouse: tab.value === 'split' ? filters.warehouses : [], scope: tab.value === 'split' ? 'split' : 'total',
      product_type: productTypeParam(filters.productTypes), missing_price: filters.missingPrice,
      page: filters.page, page_size: filters.pageSize,
    })
    result.value = response.data
  } finally { loading.value = false }
}
async function exportRows() {
  const blob = await exportInventoryValuation({
    keyword: filters.keyword.trim(), brand: filters.brands, warehouse: tab.value === 'split' ? filters.warehouses : [], scope: tab.value === 'split' ? 'split' : 'total',
    product_type: productTypeParam(filters.productTypes), missing_price: filters.missingPrice,
  })
  downloadBlob(blob, `${tab.value === 'split' ? '分仓库存' : '总库存'}价格估算_${new Date().toLocaleDateString('sv-SE')}.xlsx`)
}
function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}
async function exportPrices() {
  downloadBlob(await exportCoreCostPrices(priceParams()), `核心成本价_${new Date().toLocaleDateString('sv-SE')}.xlsx`)
}
async function loadPrices(reset = false) {
  if (reset === true) pricePagination.page = 1
  if (!canManage.value) return
  if (priceFilters.minPrice != null && priceFilters.maxPrice != null && priceFilters.minPrice > priceFilters.maxPrice) {
    ElMessage.warning('最低价格不能高于最高价格')
    return
  }
  if (priceFilters.minDiscount != null && priceFilters.maxDiscount != null && priceFilters.minDiscount > priceFilters.maxDiscount) {
    ElMessage.warning('最低折扣不能高于最高折扣')
    return
  }
  syncUrl()
  loading.value = true
  try {
    const data = (await getCoreCostPrices({ ...priceParams(), page: pricePagination.page, page_size: pricePagination.pageSize, sort_by: priceSort.prop, sort_order: priceSort.order })).data
    prices.value = data.rows
    pricePagination.total = data.pagination.total
  }
  finally { loading.value = false }
}
function changeTab(value) {
  if (tab.value === value) return
  tab.value = value
  filters.page = 1
  syncUrl()
  if (value === 'prices') loadPrices()
  else loadValuation()
}
function openEditor(item = null) {
  editingCode.value = item?.product_code || ''
  Object.assign(editor, { product_code: '', product_name: '', price: null, pricing_mode: 'fixed', discount: null, retail_price: null, tax_price: null, brand: '', product_type: '', id: null, retail_price_conflict: false }, item || {})
  editorVisible.value = true
}
async function lookupEditor() {
  const data = (await getCoreCostPrices({ keyword: editor.product_code.trim(), page: 1, page_size: 100 })).data
  const item = data.rows.find(row => row.product_code === editor.product_code.trim())
  if (item) openEditor(item)
  else ElMessage.warning('未找到库存商品，可直接填写成本价，不能按折扣计算')
}
function sortPrices({ prop, order }) {
  priceSort.prop = prop || 'product_code'
  priceSort.order = order === 'descending' ? 'desc' : 'asc'
  loadPrices(true)
}
function openBatch() {
  batchPreview.value = null
  batchDiscount.value = null
  overwriteFixed.value = false
  batchVisible.value = true
}
async function previewBatch() {
  if (!(batchDiscount.value > 0 && batchDiscount.value <= 10)) return ElMessage.warning('请输入大于 0、不超过 10 的折扣')
  savingBatch.value = true
  batchPreview.value = null
  try {
    batchPreview.value = (await previewCoreCostBatch({ keyword: priceFilters.keyword.trim(), brand: priceFilters.brands, product_type: priceFilters.productTypes, discount: batchDiscount.value, overwrite_fixed: overwriteFixed.value })).data
  } finally { savingBatch.value = false }
}
async function confirmBatch() {
  if (!batchPreview.value?.rows.length) return
  savingBatch.value = true
  try {
    const result = (await saveCoreCostBatch(batchPreview.value.rows)).data
    ElMessage.success(`已保存 ${result.saved} 项，未变化 ${result.skipped} 项`)
    batchVisible.value = false
    await loadPrices()
  } finally { savingBatch.value = false }
}
async function deletePrice() {
  if (!editingCode.value) return
  const code = editingCode.value
  await ElMessageBox.confirm(`删除 ${code} 的当前核心成本价？该货品将不再计入核心成本估值，历史记录仍可还原。`, '确认删除', { type: 'warning', confirmButtonText: '删除价格', confirmButtonClass: 'el-button--danger' })
  await deleteCoreCostPrice(code)
  editorVisible.value = false
  ElMessage.success('已删除当前价格，历史记录仍可还原')
  await Promise.all([loadPrices(), loadValuation()])
}
async function savePrice() {
  if (savingPrice.value) return
  if (!editor.product_code.trim()) return ElMessage.warning('请填写商品编号')
  if (editor.pricing_mode === 'discount' && (!(editor.discount > 0 && editor.discount <= 10) || editor.retail_price == null || editor.retail_price_conflict)) return ElMessage.warning('按折扣需要唯一有效零售价及大于 0、不超过 10 的折扣')
  if (editor.pricing_mode === 'fixed' && !(editor.price > 0)) return ElMessage.warning('请输入大于 0 的核心成本价')
  savingPrice.value = true
  try {
    await saveCoreCostPrice({ product_code: editor.product_code.trim(), product_name: editor.product_name, pricing_mode: editor.pricing_mode, price: editor.pricing_mode === 'fixed' ? editor.price : null, discount: editor.pricing_mode === 'discount' ? editor.discount : null, base_retail_price: editor.pricing_mode === 'discount' ? editor.retail_price : null, expected_revision_id: editor.id, effective_date: new Date().toLocaleDateString('sv-SE') })
    editorVisible.value = false
    ElMessage.success('价格版本已保存')
    await loadPrices()
  } finally { savingPrice.value = false }
}
async function openHistory(code) {
  historyCode.value = code
  history.value = (await getCoreCostHistory(code)).data
  historyVisible.value = true
}
async function restore(item) {
  await ElMessageBox.confirm(`将 ${historyCode.value} 还原到 ${money(item.price)} 元？这会新增一个当前生效版本。`, '确认还原')
  await restoreCoreCostPrice(historyCode.value, item.id)
  history.value = (await getCoreCostHistory(historyCode.value)).data
  ElMessage.success('已还原并保留操作记录')
  await Promise.all([loadPrices(), loadValuation()])
}
async function previewFile(file) {
  importing.value = true
  try {
    importPreview.value = (await previewCoreCostImport(file)).data
    importVisible.value = true
  } finally { importing.value = false }
  return false
}
async function confirmImport() {
  if (importPreview.value.errors.length || !importPreview.value.rows.length) return
  importing.value = true
  try {
    const response = await importCoreCostPrices(importPreview.value.rows)
    importVisible.value = false
    ElMessage.success(`新增 ${response.data.saved} 条价格版本，跳过 ${response.data.skipped} 条未变化记录`)
    await Promise.all([loadPrices(), loadValuation()])
  } finally { importing.value = false }
}
onMounted(async () => {
  const options = (await getInventoryWarehouses()).data
  warehouseOptions.value = options.warehouses || []
  productTypeOptions.value = options.product_types || [...DEFAULT_INVENTORY_PRODUCT_TYPES]
  brandOptions.value = options.brands || []
  if (tab.value === 'prices') await loadPrices()
  else await loadValuation()
})
</script>

<template>
  <div class="page-stack inventory-valuation-page" v-loading="loading">
    <section v-if="tab !== 'prices'" class="toolbar-panel valuation-toolbar" aria-label="库存估算筛选">
      <el-input v-model="filters.keyword" class="filter-keyword" clearable placeholder="名称 / 编号 / 条码" aria-label="商品信息" @keyup.enter="loadValuation(true)" />
      <el-select v-model="filters.brands" class="filter-brand" multiple collapse-tags collapse-tags-tooltip filterable clearable placeholder="全部品牌" aria-label="品牌"><el-option v-for="brand in brandOptions" :key="brand" :label="brand" :value="brand" /></el-select>
      <div v-if="tab === 'split'" class="filter-select" aria-label="仓库"><WarehouseFilter v-model="filters.warehouses" :options="warehouseOptions" /></div>
      <div class="filter-select" aria-label="货品分类"><ProductTypeFilter v-model="filters.productTypes" :options="productTypeOptions" /></div>
      <el-select v-model="filters.missingPrice" class="filter-missing" aria-label="缺价筛选"><el-option label="全部价格" value="all" /><el-option label="缺零售价" value="retail" /><el-option label="缺含税价" value="tax" /><el-option label="缺核心成本价" value="core" /></el-select>
      <el-button type="primary" :icon="'Search'" @click="loadValuation(true)">查询</el-button>
      <el-tooltip content="重置筛选"><el-button :icon="'RefreshLeft'" circle aria-label="重置筛选" @click="resetFilters" /></el-tooltip>
    </section>
    <section v-else class="toolbar-panel valuation-toolbar price-toolbar" aria-label="核心成本价筛选">
      <el-input v-model="priceFilters.keyword" class="filter-keyword" clearable placeholder="条码 / 编号 / 名称" aria-label="条码编号或名称" @keyup.enter="loadPrices(true)" />
      <el-select v-model="priceFilters.brands" class="filter-brand" multiple collapse-tags collapse-tags-tooltip clearable filterable placeholder="全部品牌" aria-label="核心成本价品牌"><el-option v-for="brand in brandOptions" :key="brand" :label="brand" :value="brand" /></el-select>
      <el-select v-model="priceFilters.productTypes" class="filter-select" multiple clearable collapse-tags placeholder="全部分类" aria-label="核心成本价分类"><el-option v-for="value in productTypeOptions" :key="value" :label="value" :value="value" /></el-select>
      <el-select v-model="priceFilters.source" class="filter-source" aria-label="成本维护状态"><el-option label="全部商品" value="all" /><el-option label="已维护成本" value="priced" /><el-option label="未维护成本" value="missing" /><el-option label="已删除" value="delete" /></el-select>
      <el-input-number v-model="priceFilters.minPrice" class="filter-price" :min="0" :precision="2" :controls="false" placeholder="最低价" aria-label="最低价格" />
      <span class="filter-range-separator">至</span>
      <el-input-number v-model="priceFilters.maxPrice" class="filter-price" :min="0" :precision="2" :controls="false" placeholder="最高价" aria-label="最高价格" />
      <span class="filter-range-separator">折扣（%）</span>
      <el-input-number v-model="priceFilters.minDiscount" class="filter-price" :min="0" :precision="0" :controls="false" placeholder="最低折扣%" aria-label="最低核心成本折扣百分比" />
      <span class="filter-range-separator">至</span>
      <el-input-number v-model="priceFilters.maxDiscount" class="filter-price" :min="0" :precision="0" :controls="false" placeholder="最高折扣%" aria-label="最高核心成本折扣百分比" />
      <el-button type="primary" :icon="'Search'" @click="loadPrices(true)">查询</el-button>
      <el-tooltip content="重置筛选"><el-button :icon="'RefreshLeft'" circle aria-label="重置筛选" @click="resetPriceFilters" /></el-tooltip>
    </section>
    <section class="valuation-hero" :class="{ 'valuation-hero--compact': tab === 'prices' }">
      <div class="valuation-hero-title"><span>INVENTORY VALUATION</span><h1>库存价格估算</h1><p v-if="tab !== 'prices'">{{ tab === 'split' ? '分仓库查询' : '总库存查询' }} · 估值按库存数量计算</p></div>
      <div class="valuation-hero-side">
        <nav class="valuation-pages" aria-label="库存价格页面">
          <button type="button" :class="{ active: tab === 'total' }" @click="changeTab('total')">总库存估算</button>
          <button type="button" :class="{ active: tab === 'split' }" @click="changeTab('split')">分仓库存估算</button>
          <button v-if="canManage" type="button" :class="{ active: tab === 'prices' }" @click="changeTab('prices')">核心成本价维护</button>
        </nav>
        <span v-if="tab !== 'prices'">库存更新时间 {{ result.updated_at || '暂无' }}</span><span v-else>零售价、含税价直接读取库存快照</span>
      </div>
    </section>
    <template v-if="tab !== 'prices'">
        <div class="valuation-summary">
          <div class="valuation-summary-item"><span>库存数量</span><strong>{{ integer(result.stock) }} <em>件</em></strong></div>
          <div class="valuation-summary-item"><span>可用库存</span><strong>{{ integer(result.available_stock) }} <em>件</em></strong></div>
          <div v-for="[key, label] in [['retail', '零售价估值'], ['tax', '含税价估值'], ['core', '核心成本估值']]" :key="key" class="valuation-summary-item" :class="{ 'valuation-summary-item--accent': key === 'core' }">
            <span>{{ label }}</span><strong>¥{{ money(metric(key).amount) }}</strong><small>已定价库存 {{ integer(metric(key).priced_stock) }} 件 · 覆盖 {{ pricedRatio(metric(key).priced_stock) }}<br>缺价库存 {{ integer(metric(key).missing_stock) }} 件</small>
          </div>
        </div>
        <section class="panel inventory-detail-table-panel">
          <header class="valuation-panel-header"><div class="valuation-panel-heading"><h2>{{ tab === 'total' ? '总库存' : '分仓库存' }}价格明细<span class="panel-source">{{ integer(result.pagination.total) }} 行</span></h2></div><el-button v-if="auth.hasPermission('data.export')" :icon="'Download'" @click="exportRows">导出 Excel</el-button></header>
          <el-table :data="result.rows" height="720" stripe>
            <el-table-column prop="product_code" label="货品编号" width="145" show-overflow-tooltip />
            <el-table-column prop="product_name" label="货品名称" min-width="260" show-overflow-tooltip />
            <el-table-column prop="brand" label="品牌" width="120" show-overflow-tooltip />
            <el-table-column prop="product_type" label="分类" width="90" />
            <el-table-column v-if="tab === 'split'" prop="warehouse" label="仓库" width="150" show-overflow-tooltip />
            <el-table-column prop="stock" label="库存数量" width="115" sortable align="right"><template #default="{ row }"><span class="emphasized-value">{{ integer(row.stock) }}</span></template></el-table-column>
            <el-table-column prop="available_stock" label="可用库存" width="115" sortable align="right"><template #default="{ row }">{{ integer(row.available_stock) }}</template></el-table-column>
            <el-table-column v-for="[key, label] in [['retail', '零售价'], ['tax', '含税价'], ['core', '核心成本价']]" :key="key" :prop="`${key}_price`" :label="label" width="130" sortable align="right"><template #default="{ row }"><span :class="{ 'missing-value': row[`${key}_price`] == null }">{{ mutedMoney(row[`${key}_price`]) }}</span></template></el-table-column>
            <el-table-column v-for="[key, label] in [['retail', '零售价估值'], ['tax', '含税价估值'], ['core', '核心成本估值']]" :key="key" :prop="`${key}_amount`" :label="label" width="155" sortable align="right"><template #default="{ row }"><span :class="{ 'missing-value': row[`${key}_amount`] == null, 'emphasized-value': key === 'tax' && row[`${key}_amount`] != null }">{{ mutedMoney(row[`${key}_amount`]) }}</span></template></el-table-column>
          </el-table>
          <div class="table-footer"><el-pagination background layout="total, sizes, prev, pager, next" :total="result.pagination.total" :current-page="filters.page" :page-size="filters.pageSize" :page-sizes="[20, 50, 100]" @current-change="value => { filters.page = value; loadValuation() }" @size-change="value => { filters.pageSize = value; loadValuation(true) }" /></div>
        </section>
    </template>
    <template v-else-if="canManage">
      <section class="panel inventory-detail-table-panel">
        <header class="valuation-panel-header price-panel-header"><div class="valuation-panel-heading"><h2>核心成本价<span class="panel-source">{{ integer(pricePagination.total) }} 项</span></h2><p class="cost-rule">核心成本价 = 零售价 × 折扣 ÷ 10；已有成本保持保存时的金额。</p></div><div class="header-actions"><el-button @click="openEditor()">新增价格</el-button><el-button type="primary" @click="openBatch">批量设置折扣</el-button><el-upload :show-file-list="false" :before-upload="previewFile" accept=".xlsx"><el-button :loading="importing">导入 Excel</el-button></el-upload><el-button :icon="'Download'" @click="exportPrices">导出 Excel</el-button></div></header>
        <el-table :data="prices" height="640" stripe @sort-change="sortPrices" :default-sort="{ prop: priceSort.prop, order: priceSort.order === 'desc' ? 'descending' : 'ascending' }">
          <el-table-column prop="barcode" label="条码" width="170" sortable="custom" show-overflow-tooltip><template #default="{ row }">{{ row.barcode || '-' }}</template></el-table-column>
          <el-table-column prop="product_name" label="商品名称" min-width="260" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="brand" label="品牌" width="130" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="product_type" label="分类" width="110" sortable="custom" show-overflow-tooltip />
          <el-table-column v-for="[key, label] in [['retail_price', '零售价'], ['tax_price', '含税价']]" :key="key" :prop="key" :label="label" width="135" align="right" sortable="custom"><template #default="{ row }"><el-tag v-if="row[`${key}_conflict`]" type="warning" size="small">价格冲突</el-tag><span v-else>{{ mutedMoney(row[key]) }}</span></template></el-table-column>
          <el-table-column prop="discount" label="核心成本折扣" width="145" align="right" sortable="custom"><template #default="{ row }"><template v-if="row.source !== 'delete' && (row.discount ?? row.reference_discount) != null"><span>{{ (Number(row.discount ?? row.reference_discount) * 10).toLocaleString('zh-CN', { maximumFractionDigits: 0 }) }}%</span></template><span v-else>-</span></template></el-table-column>
          <el-table-column prop="price" label="核心成本价" width="160" align="right" sortable="custom"><template #default="{ row }"><strong>{{ row.source === 'delete' ? '-' : money(row.price) }}</strong><el-tag v-if="row.base_changed" class="basis-tag" size="small" type="warning">零售价已变化</el-tag></template></el-table-column>
          <el-table-column label="操作" width="145" fixed="right"><template #default="{ row }"><el-button v-if="row.source !== 'delete'" link type="primary" @click="openEditor(row)">{{ row.id ? '修改' : '维护' }}</el-button><el-button v-if="row.id" link @click="openHistory(row.product_code)">历史</el-button></template></el-table-column>
        </el-table>
        <div class="table-footer"><el-pagination background layout="total, sizes, prev, pager, next" :total="pricePagination.total" :current-page="pricePagination.page" :page-size="pricePagination.pageSize" :page-sizes="[20, 50, 100]" @current-change="value => { pricePagination.page = value; loadPrices() }" @size-change="value => { pricePagination.pageSize = value; loadPrices(true) }" /></div>
      </section>
    </template>
    <el-dialog v-model="editorVisible" title="维护核心成本价" width="min(560px, 94vw)">
      <el-form label-position="top">
        <el-form-item label="商品编号"><div class="editor-code"><el-input v-model="editor.product_code" :disabled="Boolean(editingCode)" /><el-button v-if="!editingCode" @click="lookupEditor">读取商品资料</el-button></div></el-form-item>
        <el-form-item label="商品名称"><el-input v-model="editor.product_name" :readonly="Boolean(editingCode)" /></el-form-item>
        <p class="cost-rule">{{ editor.brand || '未匹配品牌' }} · {{ editor.product_type || '未匹配分类' }} · 零售价 {{ editor.retail_price_conflict ? '冲突' : mutedMoney(editor.retail_price) }} 元 · 含税价 {{ mutedMoney(editor.tax_price) }} 元</p>
        <el-form-item label="定价方式"><el-radio-group v-model="editor.pricing_mode"><el-radio-button value="fixed">直接填价</el-radio-button><el-radio-button value="discount">按折扣计算</el-radio-button></el-radio-group></el-form-item>
        <template v-if="editor.pricing_mode === 'discount'"><el-form-item label="核心成本折扣（例如 3.5 表示 3.5 折）"><el-input-number v-model="editor.discount" :min="0.0001" :max="10" :precision="4" :step="0.1" /><span class="discount-unit">折</span></el-form-item><p>计算结果：{{ editor.retail_price_conflict ? '零售价冲突，无法计算' : money(calculatedPrice) }} 元</p></template>
        <el-form-item v-else label="核心成本价（元）"><el-input-number v-model="editor.price" :min="0.01" :precision="2" :step="1" controls-position="right" /></el-form-item>
      </el-form>
      <template #footer><div class="editor-actions"><el-button v-if="editor.id" type="danger" plain @click="deletePrice">删除价格</el-button><span class="editor-actions-spacer" /><el-button @click="editorVisible = false">取消</el-button><el-button type="primary" :loading="savingPrice" @click="savePrice">保存版本</el-button></div></template>
    </el-dialog>
    <el-dialog v-model="batchVisible" title="批量设置核心成本折扣" width="min(880px, 96vw)">
      <p class="cost-rule">范围：{{ priceFilters.brands.join('、') || '全部品牌' }} / {{ priceFilters.productTypes.join('、') || '全部分类' }}{{ priceFilters.keyword ? ` / ${priceFilters.keyword}` : '' }}。按品牌、分类、关键词匹配全部商品，不限当前分页；其他状态、价格区间筛选不参与批量范围。</p>
      <div class="batch-controls"><el-input-number aria-label="批量核心成本折扣" :disabled="savingBatch" v-model="batchDiscount" :min="0.0001" :max="10" :precision="4" :step="0.1" @change="batchPreview = null" /><span>折</span><el-checkbox :disabled="savingBatch" v-model="overwriteFixed" @change="batchPreview = null">覆盖直接填价商品</el-checkbox><el-button type="primary" :loading="savingBatch" @click="previewBatch">预览变更</el-button></div>
      <template v-if="batchPreview"><p>匹配 {{ batchPreview.matched }} 项 · 可保存 {{ batchPreview.rows.length }} 项 · 跳过直接填价 {{ batchPreview.skipped }} 项 · 缺价或冲突 {{ batchPreview.errors.length }} 项</p><el-alert v-if="batchPreview.errors.length" :title="batchPreview.errors.slice(0, 8).join('；') + (batchPreview.errors.length > 8 ? '…' : '')" type="warning" :closable="false" /><el-table :data="batchPreview.rows.slice(0, 50)" max-height="360"><el-table-column prop="product_code" label="商品编号" width="150" /><el-table-column prop="product_name" label="商品名称" min-width="200" /><el-table-column prop="base_retail_price" label="零售价" width="110"><template #default="{ row }">{{ mutedMoney(row.base_retail_price) }}</template></el-table-column><el-table-column label="原成本" width="110"><template #default="{ row }">{{ mutedMoney(row.old_price) }}</template></el-table-column><el-table-column label="新成本" width="110"><template #default="{ row }">{{ money(row.price) }}</template></el-table-column></el-table><p class="cost-rule">仅展示前 50 项，确认后保存全部可保存项；缺价及冲突项跳过。</p></template>
      <template #footer><el-button @click="batchVisible = false">取消</el-button><el-button type="primary" :disabled="!batchPreview?.rows.length" :loading="savingBatch" @click="confirmBatch">确认保存 {{ batchPreview?.rows.length || 0 }} 项</el-button></template>
    </el-dialog>
    <el-dialog v-model="historyVisible" :title="`${historyCode} · 价格历史`" width="min(1060px, 96vw)"><el-table :data="history" max-height="420"><el-table-column prop="id" label="版本" width="70" /><el-table-column prop="price" label="价格" width="100"><template #default="{ row }">{{ money(row.price) }}</template></el-table-column><el-table-column prop="base_retail_price" label="基准零售价" width="120"><template #default="{ row }">{{ mutedMoney(row.base_retail_price) }}</template></el-table-column><el-table-column prop="discount" label="折扣" width="90"><template #default="{ row }">{{ row.discount == null ? '-' : `${row.discount} 折` }}</template></el-table-column><el-table-column prop="source" label="操作" width="90"><template #default="{ row }">{{ row.source === 'delete' ? '删除' : row.source === 'restore' ? '还原' : row.source === 'import' ? '导入' : row.source === 'batch' ? '批量折扣' : '修改' }}</template></el-table-column><el-table-column prop="effective_date" label="生效日期" width="115" /><el-table-column prop="created_at" label="记录时间" min-width="170" /><el-table-column prop="operator" label="操作人" min-width="165"><template #default="{ row }">{{ operatorName(row.operator) }}</template></el-table-column><el-table-column label="操作" width="80"><template #default="{ row }"><el-button v-if="row.source !== 'delete'" link type="primary" @click="restore(row)">还原</el-button></template></el-table-column></el-table></el-dialog>
    <el-dialog v-model="importVisible" title="导入预览" width="720px"><p>有效价格 {{ importPreview.rows.length }} 条 · 空价格 {{ importPreview.blank_price_count }} 条（跳过） · 错误 {{ importPreview.errors.length }} 条</p><p class="import-guide">新版为八列商品价格清单，兼容旧版四列。填写折扣（如 3.5 或 3.5折）或成本价；两者同时填写必须一致。商品资料以库存为准，空价格不覆盖已有成本。</p><el-alert v-if="importPreview.errors.length" type="error" :title="importPreview.errors.join('；')" :closable="false" /><el-table :data="importPreview.rows.slice(0, 20)" max-height="360"><el-table-column prop="product_code" label="货品编号" width="160" /><el-table-column prop="product_name" label="货品名称" min-width="230" /><el-table-column prop="brand" label="品牌" width="120" /><el-table-column prop="discount" label="折扣" width="90" /><el-table-column prop="price" label="核心成本价" width="120"><template #default="{ row }">{{ money(row.price) }}</template></el-table-column></el-table><template #footer><el-button @click="importVisible = false">取消</el-button><el-button type="primary" :disabled="Boolean(importPreview.errors.length) || !importPreview.rows.length" :loading="importing" @click="confirmImport">确认导入 {{ importPreview.rows.length }} 条</el-button></template></el-dialog>
  </div>
</template>

<style scoped>
.inventory-valuation-page { gap: 12px; }
.cost-rule { color: var(--muted); font-size: 12px; line-height: 1.6; margin: 8px 0; }
.basis-tag { display: block; width: fit-content; margin: 4px 0 0 auto; }
.editor-code, .batch-controls { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.editor-code { width: 100%; }
.editor-code .el-input { flex: 1; min-width: 160px; }
.discount-unit { margin-left: 8px; }
.valuation-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; padding: 10px 12px; border-radius: 6px; }
.valuation-toolbar .filter-keyword { width: 210px; }
.valuation-toolbar .filter-brand { width: 185px; }
.valuation-toolbar .filter-select { width: 178px; }
.valuation-toolbar .filter-missing { width: 155px; }
.price-toolbar .filter-source { width: 145px; }
.price-toolbar .filter-price { width: 105px; }
.filter-range-separator { color: var(--el-text-color-secondary); font-size: 12px; }
.valuation-hero { display: flex; justify-content: space-between; align-items: center; gap: 24px; min-height: 116px; padding: 18px 22px; border: 1px solid var(--el-border-color-light); border-top: 3px solid var(--theme-primary, #4f8b3c); border-radius: 6px; background: var(--el-bg-color); }
.valuation-hero--compact { min-height: 92px; }
.valuation-hero-title { border-left: 4px solid var(--theme-primary, #4f8b3c); padding-left: 12px; min-width: 0; }
.valuation-hero-title > span { color: var(--theme-primary, #4f8b3c); font-size: 10px; font-weight: 700; }
.valuation-hero-title h1 { font-size: 22px; line-height: 1.3; margin: 3px 0; color: var(--el-text-color-primary); }
.valuation-hero-title p { font-size: 12px; color: var(--el-text-color-secondary); margin: 0; }
.valuation-hero-side { display: flex; flex-direction: column; align-items: flex-end; gap: 9px; color: var(--el-text-color-secondary); font-size: 12px; text-align: right; }
.valuation-pages { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 2px; padding: 3px; border: 1px solid var(--el-border-color-light); border-radius: 5px; background: var(--el-fill-color-light); }
.valuation-pages button { border: 0; border-radius: 3px; padding: 6px 10px; background: transparent; color: var(--el-text-color-secondary); font: inherit; font-weight: 600; cursor: pointer; white-space: nowrap; }
.valuation-pages button.active { background: var(--el-bg-color); color: var(--theme-primary, #4f8b3c); box-shadow: 0 1px 3px rgb(0 0 0 / 8%); }
.valuation-pages button:focus-visible { outline: 2px solid var(--theme-primary, #4f8b3c); outline-offset: 2px; }
.valuation-summary { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 8px; }
.valuation-summary-item { border: 1px solid var(--el-border-color-light); border-top: 2px solid var(--theme-primary, #4f8b3c); border-radius: 5px; padding: 14px; background: var(--el-bg-color); display: flex; flex-direction: column; gap: 7px; min-width: 0; min-height: 108px; }
.valuation-summary-item span { color: var(--el-text-color-secondary); font-size: 12px; font-weight: 600; }
.valuation-summary-item strong { font-size: 20px; line-height: 1.25; font-weight: 700; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.valuation-summary-item strong em { font-size: 11px; font-style: normal; font-weight: 400; color: var(--el-text-color-secondary); }
.valuation-summary-item small { color: var(--el-text-color-secondary); font-size: 11px; line-height: 1.5; }
.valuation-summary-item--accent { background: var(--theme-primary, #4f8b3c); border-color: var(--theme-primary, #4f8b3c); }
.valuation-summary-item--accent span, .valuation-summary-item--accent strong, .valuation-summary-item--accent small { color: #fff; }
.missing-value { color: var(--el-text-color-placeholder); }
.emphasized-value { font-weight: 600; }
.editor-actions { display: flex; align-items: center; gap: 8px; }
.editor-actions-spacer { flex: 1; }
.import-guide { color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.5; }
.header-actions { display: flex; align-items: center; gap: 8px; }
.inventory-valuation-page .valuation-panel-header { min-height: 72px; padding: 12px 18px; align-items: center; }
.valuation-panel-heading { min-width: 225px; }
.inventory-valuation-page .valuation-panel-heading h2 { display: flex; align-items: baseline; flex-wrap: wrap; gap: 9px; margin: 0; color: var(--el-text-color-primary); font-size: 16px; line-height: 1.4; font-weight: 700; }
.inventory-valuation-page .valuation-panel-heading p { margin: 5px 0 0; color: var(--el-text-color-regular); font-size: 12px; line-height: 1.45; font-weight: 400; }
.inventory-valuation-page .valuation-panel-heading .panel-source { margin: 0; color: var(--el-text-color-secondary); font-size: 12px; line-height: inherit; font-weight: 500; vertical-align: baseline; }
.inventory-valuation-page .inventory-detail-table-panel { min-width: 0; overflow: hidden; }
.inventory-valuation-page .inventory-detail-table-panel > header { min-width: 0; gap: 12px; }
.inventory-valuation-page :deep(.el-table th.el-table__cell) { background: var(--el-fill-color-light); }
@media (max-width: 1180px) { .valuation-summary { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 1280px) { .inventory-valuation-page .price-panel-header { flex-wrap: wrap; } .header-actions { flex-wrap: wrap; } }
@media (max-width: 800px) { .valuation-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 600px) {
  :global(.app-shell:has(.inventory-valuation-page) .topbar) { height: auto; min-height: 68px; flex-wrap: wrap; gap: 10px; padding: 12px 18px; }
  :global(.app-shell:has(.inventory-valuation-page) .topbar > div:first-child) { flex-basis: 100%; min-width: 0; }
  :global(.app-shell:has(.inventory-valuation-page) .top-actions) { flex-wrap: wrap; gap: 6px; max-width: 100%; }
  .valuation-toolbar .filter-keyword, .valuation-toolbar .filter-brand, .valuation-toolbar .filter-select, .valuation-toolbar .filter-missing { width: 100%; }
  .price-toolbar .filter-source { width: 100%; }
  .price-toolbar .filter-price { width: calc((100% - 32px) / 2); }
  .valuation-hero { flex-direction: column; align-items: stretch; padding: 16px; gap: 16px; }
  .valuation-hero-side { align-items: flex-start; text-align: left; }
  .valuation-pages { justify-content: flex-start; }
  .valuation-summary { grid-template-columns: 1fr; }
  .inventory-valuation-page .inventory-detail-table-panel > header { display: flex; flex-direction: column; align-items: stretch; }
  .header-actions { width: 100%; min-width: 0; flex-wrap: wrap; }
}
</style>
