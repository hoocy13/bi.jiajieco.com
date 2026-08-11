<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import WarehouseFilter from '../../components/inventory/WarehouseFilter.vue'
import ProductTypeFilter from '../../components/inventory/ProductTypeFilter.vue'
import ProductInventoryDrawer from '../../components/inventory/ProductInventoryDrawer.vue'
import { getInventoryWarehouses, getSlowMovingInventory } from '../../api/inventory'
import { DEFAULT_INVENTORY_PRODUCT_TYPES, DEFAULT_INVENTORY_WAREHOUSES } from '../../constants/inventory'
import { inventoryQuery, productTypeParam, queryArray } from '../../utils/inventoryFilters'
import { getSavedTheme } from '../../utils/theme'

use([CanvasRenderer, BarChart, LineChart, GridComponent, LegendComponent, TooltipComponent])
const chartTheme = getSavedTheme()

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const loaded = ref(false)
const errorMessage = ref('')
const warehouseLoading = ref(false)
const warehouseOptions = ref([])
const productTypeOptions = ref([...DEFAULT_INVENTORY_PRODUCT_TYPES])
const snapshotOptions = ref([])
const rows = ref([])
const total = ref(0)
const productDrawer = ref(null)
const DEFAULT_SLOW_MOVING_PRODUCT_TYPES = ['正装']
const summary = ref({
  stock_quantity: 0,
  stock_sku_count: 0,
  slow_stock_quantity: 0,
  slow_stock_share: 0,
  slow_sku_count: 0,
  slow_sku_share: 0,
  no_sales_stock_quantity: 0,
})
const riskDistribution = ref([])
const trend = ref([])
const analysisMeta = ref({ snapshot_date: '', period_start: '', period_days: 90, updated_at: '' })
const allowedPeriods = [30, 60, 90, 180]
const routePeriod = Number(route.query.period_days || 90)
const allowedSortFields = ['stock', 'period_sales', 'estimated_days', 'ending_stock_ratio']
const allowedRetentionScopes = ['all', 'ge90', '70_90', '50_70', 'lt50']
const routeSortBy = String(route.query.sort_by || 'stock')
const routeRetentionScope = String(route.query.retention_scope || 'all')
const query = reactive({
  keyword: String(route.query.keyword || ''),
  barcode: String(route.query.barcode || ''),
  warehouses: queryArray(route.query.warehouse, DEFAULT_INVENTORY_WAREHOUSES),
  productTypes: route.query.product_type === '__all__' ? [] : queryArray(route.query.product_type, DEFAULT_SLOW_MOVING_PRODUCT_TYPES),
  snapshotDate: String(route.query.snapshot_date || ''),
  periodDays: allowedPeriods.includes(routePeriod) ? routePeriod : 90,
  riskScope: String(route.query.risk_scope || 'slow_all'),
  retentionScope: allowedRetentionScopes.includes(routeRetentionScope) ? routeRetentionScope : 'all',
  sortBy: allowedSortFields.includes(routeSortBy) ? routeSortBy : 'stock',
  sortOrder: String(route.query.sort_order || 'desc'),
  page: Number(route.query.page || 1),
  pageSize: Number(route.query.page_size || 50),
})

function formatNumber(value, digits = 0) {
  return Number(value || 0).toLocaleString('zh-CN', {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  })
}

function formatDateTime(value) {
  if (!value) return '-'
  return String(value).replace('T', ' ').slice(0, 16)
}

function riskTagType(code) {
  if (code === 'no_sales') return 'danger'
  if (code === 'critical') return 'warning'
  if (code === 'slow') return 'warning'
  return 'info'
}

function syncUrl() {
  return router.replace({
    query: inventoryQuery({
      keyword: query.keyword.trim(),
      barcode: query.barcode.trim(),
      warehouse: query.warehouses,
      product_type: query.productTypes.length ? query.productTypes : '__all__',
      snapshot_date: query.snapshotDate,
      period_days: query.periodDays,
      risk_scope: query.riskScope,
      retention_scope: query.retentionScope,
      sort_by: query.sortBy,
      sort_order: query.sortOrder,
      page: query.page,
      page_size: query.pageSize,
    }),
  })
}

function openProduct(row) {
  productDrawer.value?.open(row.product_code, query.warehouses)
}

async function fetchRows(resetPage = false) {
  if (resetPage) query.page = 1
  await syncUrl()
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await getSlowMovingInventory({
      keyword: query.keyword.trim(),
      barcode: query.barcode.trim(),
      warehouse: query.warehouses,
      product_type: productTypeParam(query.productTypes),
      snapshot_date: query.snapshotDate,
      period_days: query.periodDays,
      risk_scope: query.riskScope,
      retention_scope: query.retentionScope,
      sort_by: query.sortBy,
      sort_order: query.sortOrder,
      page: query.page,
      page_size: query.pageSize,
    })
    const data = result.data
    rows.value = data.rows || []
    total.value = data.pagination?.total || 0
    summary.value = data.summary || summary.value
    riskDistribution.value = data.risk_distribution || []
    trend.value = data.trend || []
    snapshotOptions.value = data.snapshot_options || []
    analysisMeta.value = {
      snapshot_date: data.snapshot_date,
      period_start: data.period_start,
      period_days: data.period_days,
      updated_at: data.updated_at,
    }
    if (!query.snapshotDate && data.snapshot_date) {
      query.snapshotDate = data.snapshot_date
      await syncUrl()
    }
    loaded.value = true
  } catch (error) {
    errorMessage.value = error?.response?.data?.detail || '滞销分析加载失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

function restoreDefaults() {
  Object.assign(query, {
    keyword: '',
    barcode: '',
    warehouses: [...DEFAULT_INVENTORY_WAREHOUSES],
    productTypes: [...DEFAULT_SLOW_MOVING_PRODUCT_TYPES],
    snapshotDate: snapshotOptions.value[0]?.value || '',
    periodDays: 90,
    riskScope: 'slow_all',
    retentionScope: 'all',
    sortBy: 'stock',
    sortOrder: 'desc',
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
    snapshotDate: snapshotOptions.value[0]?.value || '',
    periodDays: 90,
    riskScope: 'slow_all',
    retentionScope: 'all',
    sortBy: 'stock',
    sortOrder: 'desc',
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

function changeSort({ prop, order }) {
  if (!prop || !order) {
    query.sortBy = 'stock'
    query.sortOrder = 'desc'
  } else {
    query.sortBy = prop
    query.sortOrder = order === 'ascending' ? 'asc' : 'desc'
  }
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

const metrics = computed(() => [
  { label: '滞销库存数量', value: formatNumber(summary.value.slow_stock_quantity), unit: '件' },
  { label: '库存数量占比', value: `${formatNumber(summary.value.slow_stock_share, 1)}%`, accent: true },
  { label: '滞销 SKU', value: formatNumber(summary.value.slow_sku_count), unit: '项' },
  { label: 'SKU 占比', value: `${formatNumber(summary.value.slow_sku_share, 1)}%`, accent: true },
  { label: '无销售库存数量', value: formatNumber(summary.value.no_sales_stock_quantity), unit: '件' },
  { label: '截止库存数量', value: formatNumber(summary.value.stock_quantity), unit: '件' },
])

const trendOption = computed(() => ({
  animation: false,
  color: [chartTheme.primary, chartTheme.secondary],
  grid: { left: 54, right: 62, top: 50, bottom: 34 },
  legend: { top: 4, right: 8, itemWidth: 12, itemHeight: 8, textStyle: { color: '#667085' } },
  tooltip: {
    trigger: 'axis',
    formatter(params) {
      const item = trend.value[params[0]?.dataIndex] || {}
      return [
        `<strong>${item.snapshot_date || ''}</strong>`,
        `滞销库存数量：${formatNumber(item.slow_stock_quantity)} 件`,
        `库存数量占比：${formatNumber(item.slow_stock_share, 1)}%`,
        `滞销 SKU：${formatNumber(item.slow_sku_count)}`,
      ].join('<br>')
    },
  },
  xAxis: {
    type: 'category',
    data: trend.value.map((item) => item.snapshot_date.slice(0, 7)),
    axisLine: { lineStyle: { color: '#d7e2db' } },
    axisTick: { show: false },
    axisLabel: { color: '#667085' },
  },
  yAxis: [
    {
      type: 'value',
      name: '库存数量',
      nameTextStyle: { color: '#98a2b3' },
      splitLine: { lineStyle: { color: '#edf2ee' } },
      axisLabel: { color: '#667085' },
    },
    {
      type: 'value',
      name: '占比',
      min: 0,
      max: 100,
      nameTextStyle: { color: '#98a2b3' },
      splitLine: { show: false },
      axisLabel: { color: '#667085', formatter: '{value}%' },
    },
  ],
  series: [
    {
      name: '滞销库存数量',
      type: 'bar',
      barMaxWidth: 26,
      data: trend.value.map((item) => Number(item.slow_stock_quantity || 0)),
      itemStyle: { borderRadius: [3, 3, 0, 0] },
    },
    {
      name: '库存数量占比',
      type: 'line',
      yAxisIndex: 1,
      smooth: 0.25,
      symbolSize: 7,
      data: trend.value.map((item) => Number(item.slow_stock_share || 0).toFixed(1)),
      lineStyle: { width: 2 },
    },
  ],
}))

onMounted(() => Promise.all([fetchWarehouses(), fetchRows()]))
</script>

<template>
  <div class="page-stack slow-moving-page">
    <section class="toolbar-panel inventory-filter-panel">
      <div class="inventory-filter-grid slow-moving-filter-grid">
        <label class="inventory-filter-field inventory-filter-field--date">
          <span>截止快照日</span>
          <el-select v-model="query.snapshotDate" placeholder="最新完成快照">
            <el-option v-for="item in snapshotOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </label>
        <label class="inventory-filter-field inventory-filter-field--compact">
          <span>观察周期</span>
          <el-select v-model="query.periodDays">
            <el-option v-for="days in allowedPeriods" :key="days" :label="`近 ${days} 天`" :value="days" />
          </el-select>
        </label>
        <label class="inventory-filter-field inventory-filter-field--compact">
          <span>风险范围</span>
          <el-select v-model="query.riskScope">
            <el-option label="全部滞销" value="slow_all" />
            <el-option label="无销售" value="no_sales" />
            <el-option label="严重滞销" value="critical" />
            <el-option label="滞销" value="slow" />
            <el-option label="关注" value="watch" />
            <el-option label="全部库存" value="all" />
          </el-select>
        </label>
        <label class="inventory-filter-field inventory-filter-field--compact">
          <span>留存率</span>
          <el-select v-model="query.retentionScope">
            <el-option label="全部" value="all" />
            <el-option label="90%及以上" value="ge90" />
            <el-option label="70%-90%" value="70_90" />
            <el-option label="50%-70%" value="50_70" />
            <el-option label="50%以下" value="lt50" />
          </el-select>
        </label>
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

    <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon :closable="false">
      <template #default><el-button link type="primary" @click="fetchRows">重新加载</el-button></template>
    </el-alert>

    <el-skeleton v-if="loading && !loaded" :rows="5" animated />
    <template v-else>
      <section class="panel slow-moving-overview" aria-label="滞销概览">
        <div class="slow-moving-kpi-strip">
          <div v-for="item in metrics" :key="item.label" class="slow-moving-kpi">
            <span>{{ item.label }}</span>
            <strong :class="{ 'percentage-value': item.accent }">
              {{ item.value }}<small v-if="item.unit">{{ item.unit }}</small>
            </strong>
          </div>
        </div>
        <p class="slow-moving-basis-note">
          <strong>统计口径：</strong>{{ analysisMeta.period_start }} 至 {{ analysisMeta.snapshot_date }}，采用历史月末账面库存；风险按无销售、超过 180 天、90-180 天划分。数据更新于 {{ formatDateTime(analysisMeta.updated_at) }}。
        </p>
      </section>

      <div class="content-grid slow-moving-analysis-grid">
        <section class="panel trend-panel">
          <header>
            <h2>滞销趋势<span class="panel-source">（最近 6 个已完成月末快照，更新于 {{ formatDateTime(analysisMeta.updated_at) }}）</span></h2>
          </header>
          <VChart v-if="trend.length" class="slow-moving-chart" :option="trendOption" autoresize />
          <el-empty v-else description="当前筛选下暂无趋势数据" :image-size="72" />
        </section>

        <section class="panel risk-panel">
          <header><h2>风险构成<span class="panel-source">（按库存数量）</span></h2></header>
          <div v-if="riskDistribution.length" class="risk-list">
            <button
              v-for="item in riskDistribution"
              :key="item.risk_code"
              type="button"
              :class="{ active: query.riskScope === item.risk_code }"
              @click="query.riskScope = item.risk_code; fetchRows(true)"
            >
              <span><el-tag :type="riskTagType(item.risk_code)" effect="plain">{{ item.risk_label }}</el-tag></span>
              <strong>{{ formatNumber(item.stock_quantity) }} 件</strong>
              <small>{{ formatNumber(item.stock_quantity_share, 1) }}% / {{ formatNumber(item.sku_count) }} SKU</small>
            </button>
          </div>
          <el-empty v-else description="暂无风险分布" :image-size="72" />
        </section>
      </div>

      <section class="panel" v-loading="loading">
        <header class="slow-moving-detail-header">
          <div>
            <h2>滞销分析明细<span class="panel-source">（历史库存快照 + 周期净销量）</span></h2>
            <p>库存留存率 = 截止库存 /（截止库存 + 周期净销量），期间补货会影响该参考值。</p>
          </div>
          <el-button :icon="'Refresh'" circle @click="fetchRows" />
        </header>
        <el-table
          :data="rows"
          height="560"
          :default-sort="{ prop: query.sortBy, order: query.sortOrder === 'asc' ? 'ascending' : 'descending' }"
          @sort-change="changeSort"
        >
          <el-table-column label="序号" width="72" align="center">
            <template #default="{ row }"><span class="rank-badge">{{ row.rank }}</span></template>
          </el-table-column>
          <el-table-column label="风险" width="112" fixed="left">
            <template #default="{ row }"><el-tag :type="riskTagType(row.risk_code)" effect="plain">{{ row.risk_label }}</el-tag></template>
          </el-table-column>
          <el-table-column prop="product" label="商品" min-width="280" show-overflow-tooltip fixed="left">
            <template #default="{ row }">
              <el-tooltip content="查看当前分仓库存" placement="top">
                <el-button link type="primary" class="inventory-product-link" @click="openProduct(row)">{{ row.product }}</el-button>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column prop="barcode" label="货品条码" width="160" show-overflow-tooltip />
          <el-table-column prop="brand" label="品牌" width="140" show-overflow-tooltip />
          <el-table-column prop="product_type" label="分类" width="90" />
          <el-table-column prop="warehouse_count" label="仓库数" width="90" align="right">
            <template #default="{ row }">{{ formatNumber(row.warehouse_count) }}</template>
          </el-table-column>
          <el-table-column prop="stock" label="截止库存" width="120" align="right" sortable="custom">
            <template #default="{ row }">{{ formatNumber(row.stock) }}</template>
          </el-table-column>
          <el-table-column prop="period_sales" :label="`${query.periodDays}天净销量`" width="130" align="right" sortable="custom">
            <template #default="{ row }">{{ formatNumber(row.period_sales) }}</template>
          </el-table-column>
          <el-table-column prop="estimated_days" label="预计库存天数" width="140" align="right" sortable="custom">
            <template #default="{ row }">{{ row.estimated_days === null ? '无销售' : formatNumber(row.estimated_days, 1) }}</template>
          </el-table-column>
          <el-table-column prop="ending_stock_ratio" label="库存留存率" width="130" align="right" sortable="custom">
            <template #default="{ row }"><strong class="percentage-value">{{ formatNumber(row.ending_stock_ratio, 1) }}%</strong></template>
          </el-table-column>
          <template #empty><el-empty description="当前筛选下没有符合条件的商品" :image-size="72" /></template>
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
    </template>

    <ProductInventoryDrawer ref="productDrawer" />
  </div>
</template>

<style scoped>
.slow-moving-filter-grid {
  grid-template-columns: minmax(170px, 1.1fr) minmax(120px, .65fr) minmax(135px, .75fr) repeat(4, minmax(160px, 1fr));
}

.slow-moving-overview { overflow: hidden; }
.slow-moving-kpi-strip { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); }
.slow-moving-kpi {
  display: flex;
  min-width: 0;
  min-height: 70px;
  padding: 11px 14px;
  flex-direction: column;
  justify-content: center;
  border-right: 1px solid var(--border);
  box-sizing: border-box;
}
.slow-moving-kpi:last-child { border-right: 0; }
.slow-moving-kpi > span { color: var(--muted); font-size: 12px; line-height: 1.4; }
.slow-moving-kpi > strong { margin-top: 4px; color: var(--text); font-size: 19px; line-height: 1.2; white-space: nowrap; }
.slow-moving-kpi > strong small { margin-left: 3px; color: var(--muted); font-size: 11px; font-weight: 500; }
.slow-moving-kpi > strong.percentage-value { color: var(--accent-strong); }
.slow-moving-basis-note {
  margin: 0;
  padding: 8px 14px;
  border-top: 1px solid var(--border);
  color: var(--muted);
  background: var(--surface-soft);
  font-size: 12px;
  line-height: 1.6;
}
.slow-moving-basis-note strong { color: var(--text); font-weight: 600; }
.slow-moving-analysis-grid { grid-template-columns: minmax(0, 2fr) minmax(320px, 1fr); }
.trend-panel, .risk-panel { min-height: 360px; }
.slow-moving-chart { width: 100%; height: 292px; padding: 10px 14px 14px; box-sizing: border-box; }
.risk-list { display: grid; padding: 0 18px; }
.risk-list button {
  display: grid;
  grid-template-columns: 105px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  min-height: 58px;
  padding: 10px 2px;
  border: 0;
  border-bottom: 1px solid var(--border);
  color: inherit;
  background: transparent;
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.risk-list button:last-child { border-bottom: 0; }
.risk-list button:hover, .risk-list button.active { background: var(--accent-soft); }
.risk-list button:active { transform: translateY(1px); }
.risk-list strong { color: var(--text); font-size: 14px; }
.risk-list small { color: var(--muted); font-size: 12px; white-space: nowrap; }
.slow-moving-detail-header { min-height: 64px !important; }
.panel header p { margin: 5px 0 0; color: var(--muted); font-size: 12px; font-weight: 400; }
.percentage-value { color: var(--accent-strong); }

@media (max-width: 1380px) {
  .slow-moving-filter-grid { grid-template-columns: repeat(4, minmax(150px, 1fr)); }
  .slow-moving-kpi-strip { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .slow-moving-kpi:nth-child(3) { border-right: 0; }
  .slow-moving-kpi:nth-child(-n + 3) { border-bottom: 1px solid var(--border); }
}

@media (max-width: 1180px) {
  .slow-moving-analysis-grid { grid-template-columns: 1fr; }
}

@media (max-width: 720px) {
  .slow-moving-filter-grid { grid-template-columns: 1fr; }
  .slow-moving-kpi-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .slow-moving-kpi { min-height: 64px; padding: 9px 12px; border-bottom: 1px solid var(--border); }
  .slow-moving-kpi:nth-child(3) { border-right: 1px solid var(--border); }
  .slow-moving-kpi:nth-child(2n) { border-right: 0; }
  .slow-moving-kpi:nth-last-child(-n + 2) { border-bottom: 0; }
  .slow-moving-analysis-grid { grid-template-columns: 1fr; }
  .risk-list button { grid-template-columns: 96px 1fr; }
  .risk-list small { grid-column: 2; }
}
</style>
