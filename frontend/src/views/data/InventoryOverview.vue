<script setup>
import { computed, onMounted, ref } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { useRoute, useRouter } from 'vue-router'
import MetricCard from '../../components/dashboard/MetricCard.vue'
import ExportExcelButton from '../../components/common/ExportExcelButton.vue'
import WarehouseFilter from '../../components/inventory/WarehouseFilter.vue'
import ProductTypeFilter from '../../components/inventory/ProductTypeFilter.vue'
import { getInventoryOverview, getInventoryWarehouses } from '../../api/inventory'
import { DEFAULT_INVENTORY_PRODUCT_TYPES, DEFAULT_INVENTORY_WAREHOUSES } from '../../constants/inventory'
import { inventoryQuery, productTypeParam, queryArray } from '../../utils/inventoryFilters'
import { getSavedTheme } from '../../utils/theme'

use([CanvasRenderer, BarChart, GridComponent, TooltipComponent])

const chartTheme = getSavedTheme()

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const warehouseLoading = ref(false)
const warehouseOptions = ref([])
const productTypeOptions = ref([...DEFAULT_INVENTORY_PRODUCT_TYPES])
const selectedWarehouses = ref(queryArray(route.query.warehouse, DEFAULT_INVENTORY_WAREHOUSES))
const selectedProductTypes = ref(
  route.query.product_type === '__all__' ? [] : queryArray(route.query.product_type, DEFAULT_INVENTORY_PRODUCT_TYPES),
)
const overview = ref({
  updated_at: '',
  metrics: {
    product_count: 0,
    warehouse_records: 0,
    batch_records: 0,
    stock_quantity: 0,
    available_stock: 0,
    stock_amount: 0,
    stock_amount_available: true,
    below_min_count: 0,
    above_max_count: 0,
    expiring_batch_count: 0,
  },
  source_tables: [],
  warehouses: [],
})

function formatNumber(value, digits = 0) {
  return Number(value || 0).toLocaleString('zh-CN', {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  })
}

function formatDate(value) {
  if (!value) return '-'
  return String(value).slice(0, 10)
}

const occupiedStock = computed(() => Number(overview.value.metrics.stock_quantity || 0) - Number(overview.value.metrics.available_stock || 0))
const availableRate = computed(() => {
  const stock = Number(overview.value.metrics.stock_quantity || 0)
  return stock ? Number(overview.value.metrics.available_stock || 0) / stock * 100 : 0
})
const metrics = computed(() => [
  { label: '可用库存', value: formatNumber(overview.value.metrics.available_stock), unit: '件', trend: `库存总量 ${formatNumber(overview.value.metrics.stock_quantity)} 件` },
  { label: '占用或不可用', value: formatNumber(occupiedStock.value), unit: '件', trend: '库存总量减去可用库存' },
  { label: '库存可用率', value: formatNumber(availableRate.value, 1), unit: '%', trend: '可用库存 / 库存总量' },
  {
    label: '库存金额',
    value: overview.value.metrics.stock_amount_available ? formatNumber(overview.value.metrics.stock_amount, 2) : '暂不可用',
    unit: overview.value.metrics.stock_amount_available ? '元' : '',
    trend: overview.value.metrics.stock_amount_available ? '库存快照成本金额' : '源数据成本字段当前为空',
  },
])
const riskMetrics = computed(() => [
  { label: '库存商品', value: formatNumber(overview.value.metrics.product_count), unit: '个', trend: '按货品编号去重' },
  { label: '低于库存下限', value: formatNumber(overview.value.metrics.below_min_count), unit: '项', trend: '建议优先检查补货设置' },
  { label: '高于库存上限', value: formatNumber(overview.value.metrics.above_max_count), unit: '项', trend: '建议检查库存积压' },
  { label: '30天内临期批次', value: formatNumber(overview.value.metrics.expiring_batch_count), unit: '批', trend: '按批次到期日期统计' },
])
const warehouseExportColumns = [{ key: 'warehouse', label: '仓库' }, { key: 'records', label: '记录数', kind: 'integer' }, { key: 'stock_quantity', label: '库存数量', kind: 'integer' }, { key: 'available_stock', label: '可用库存', kind: 'integer' }, { key: 'stock_amount', label: '库存金额', kind: 'number' }]

const warehouseBarOption = computed(() => ({
  color: [chartTheme.primary],
  tooltip: {
    trigger: 'axis',
    axisPointer: { type: 'shadow' },
    backgroundColor: '#111827',
    borderWidth: 0,
    textStyle: { color: '#ffffff' },
    formatter: (params) => {
      const item = params[0]
      const row = overview.value.warehouses[item.dataIndex]
      return [
        `${row.warehouse}`,
        `可用库存：${formatNumber(row.available_stock)} 件`,
        `库存数量：${formatNumber(row.stock_quantity)} 件`,
        overview.value.metrics.stock_amount_available
          ? `库存金额：${formatNumber(row.stock_amount, 2)} 元`
          : '库存金额：源数据暂不可用',
      ].join('<br/>')
    },
  },
  grid: { top: 14, left: 132, right: 34, bottom: 20 },
  xAxis: {
    type: 'value',
    splitLine: { lineStyle: { color: '#edf1f6' } },
    axisLabel: { color: '#98a2b3' },
  },
  yAxis: {
    type: 'category',
    inverse: true,
    data: overview.value.warehouses.slice(0, 8).map((item) => item.warehouse),
    axisTick: { show: false },
    axisLine: { show: false },
    axisLabel: {
      color: '#475467',
      width: 118,
      overflow: 'truncate',
    },
  },
  series: [
    {
      name: '可用库存',
      type: 'bar',
      barWidth: 12,
      itemStyle: {
        borderRadius: [0, 8, 8, 0],
        color: {
          type: 'linear',
          x: 0,
          y: 0,
          x2: 1,
          y2: 0,
          colorStops: [
            { offset: 0, color: chartTheme.primary },
            { offset: 1, color: chartTheme.secondary },
          ],
        },
      },
      label: {
        show: true,
        position: 'right',
        color: '#667085',
        fontSize: 11,
        formatter: (params) => formatNumber(params.value),
      },
      data: overview.value.warehouses.slice(0, 8).map((item) => item.available_stock),
    },
  ],
}))

async function fetchOverview() {
  router.replace({ query: inventoryQuery({
    warehouse: selectedWarehouses.value,
    product_type: selectedProductTypes.value.length ? selectedProductTypes.value : '__all__',
  }) })
  loading.value = true
  try {
    const result = await getInventoryOverview({
      warehouse: selectedWarehouses.value,
      product_type: productTypeParam(selectedProductTypes.value),
    })
    overview.value = result.data
  } finally {
    loading.value = false
  }
}

function restoreDefaults() {
  selectedWarehouses.value = [...DEFAULT_INVENTORY_WAREHOUSES]
  selectedProductTypes.value = [...DEFAULT_INVENTORY_PRODUCT_TYPES]
  fetchOverview()
}

function clearFilters() {
  selectedWarehouses.value = []
  selectedProductTypes.value = []
  fetchOverview()
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

onMounted(() => Promise.all([fetchWarehouses(), fetchOverview()]))
</script>

<template>
  <div class="page-stack" v-loading="loading">
    <section class="inventory-overview-hero">
      <div>
        <span>库存总览</span>
        <h2>当前库存水位与仓库分布</h2>
        <p>库存数据来自每日同步快照，优先使用可用库存判断当前可销售数量。</p>
      </div>
      <div class="inventory-overview-hero__actions">
        <el-button type="primary" @click="router.push('/inventory/detail')">查看库存明细</el-button>
      </div>
    </section>

    <section class="toolbar-panel inventory-filter-panel">
      <div class="inventory-filter-grid inventory-filter-grid--overview">
        <label class="inventory-filter-field">
          <span>仓库名称</span>
          <WarehouseFilter
            v-model="selectedWarehouses"
            :options="warehouseOptions"
            :loading="warehouseLoading"
          />
        </label>
        <label class="inventory-filter-field">
          <span>货品分类</span>
          <ProductTypeFilter
            v-model="selectedProductTypes"
            :options="productTypeOptions"
            :loading="warehouseLoading"
          />
        </label>
        <div class="inventory-filter-actions">
          <el-button type="primary" :icon="'Search'" @click="fetchOverview">查询</el-button>
          <el-tooltip content="恢复默认筛选" placement="top">
            <el-button :icon="'RefreshLeft'" circle @click="restoreDefaults" />
          </el-tooltip>
          <el-tooltip content="清空筛选" placement="top">
            <el-button :icon="'Delete'" circle @click="clearFilters" />
          </el-tooltip>
        </div>
      </div>
    </section>

    <div class="metric-grid inventory-overview-metrics">
      <MetricCard v-for="item in metrics" :key="item.label" v-bind="item" />
    </div>

    <div class="metric-grid compact-metrics inventory-overview-metrics">
      <MetricCard v-for="item in riskMetrics" :key="item.label" v-bind="item" />
    </div>

    <section class="panel inventory-warehouse-panel">
      <header>
        <div><h2>仓库库存结构<span class="panel-source">（按可用库存排序）</span></h2><p>查看不同仓库的库存水位和可用数量。</p></div>
        <div class="header-actions"><ExportExcelButton title="库存概览_仓库排行" :rows="overview.warehouses" :columns="warehouseExportColumns" :total="overview.warehouses.length" :filters="{ 数据更新时间: overview.updated_at }" /><el-button :icon="'Refresh'" circle @click="fetchOverview" /></div>
      </header>
      <div class="inventory-warehouse-content">
        <v-chart class="chart chart-compact" :option="warehouseBarOption" autoresize />
        <el-table :data="overview.warehouses" height="420" stripe>
          <el-table-column prop="warehouse" label="仓库" min-width="190" show-overflow-tooltip />
          <el-table-column prop="stock_quantity" label="库存数量" width="130" sortable><template #default="{ row }">{{ formatNumber(row.stock_quantity) }}</template></el-table-column>
          <el-table-column prop="available_stock" label="可用库存" width="130" sortable><template #default="{ row }">{{ formatNumber(row.available_stock) }}</template></el-table-column>
          <el-table-column prop="stock_amount" label="库存金额" width="150" sortable><template #default="{ row }">{{ formatNumber(row.stock_amount, 2) }}</template></el-table-column>
        </el-table>
      </div>
      <footer class="inventory-overview-note">页面展示每日同步库存快照，不等同于吉客云实时库存。涉及调拨、锁定或采购操作时，请返回业务系统复核。</footer>
    </section>
  </div>
</template>

<style scoped>
.inventory-overview-hero { display: flex; align-items: center; justify-content: space-between; gap: 24px; min-height: 118px; padding: 21px 23px; border: 1px solid var(--theme-soft-strong); border-radius: var(--radius); background: linear-gradient(120deg, var(--surface) 0%, var(--accent-soft) 100%); }
.inventory-overview-hero > div:first-child { display: grid; gap: 6px; }
.inventory-overview-hero span { color: var(--accent-strong); font-size: 11px; font-weight: 750; }
.inventory-overview-hero h2 { margin: 0; color: var(--text); font-size: 24px; }
.inventory-overview-hero p, .inventory-warehouse-panel header p { margin: 0; color: var(--muted-2); font-size: 12px; }
.inventory-overview-hero__actions { display: flex; align-items: center; gap: 18px; }
.inventory-warehouse-panel > header { min-height: 66px; }
.inventory-warehouse-panel header > div:first-child { display: grid; gap: 4px; }
.inventory-warehouse-panel h2 { margin: 0; }
.inventory-warehouse-content { display: grid; grid-template-columns: minmax(420px, .9fr) minmax(620px, 1.1fr); min-width: 0; }
.inventory-warehouse-content .chart { min-width: 0; height: 420px; border-right: 1px solid var(--border); }
.inventory-overview-note { padding: 11px 18px; color: var(--muted-2); background: var(--accent-soft); border-top: 1px solid var(--theme-soft-strong); font-size: 11px; }
@media (max-width: 1180px) { .inventory-warehouse-content { grid-template-columns: 1fr; } .inventory-warehouse-content .chart { border-right: 0; border-bottom: 1px solid var(--border); } }
@media (max-width: 720px) { .inventory-overview-hero { align-items: flex-start; flex-direction: column; } .inventory-overview-hero__actions { width: 100%; align-items: flex-start; flex-direction: column; } }
</style>
