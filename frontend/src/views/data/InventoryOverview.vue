<script setup>
import { computed, onMounted, ref } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { useRoute, useRouter } from 'vue-router'
import MetricCard from '../../components/dashboard/MetricCard.vue'
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

const metrics = computed(() => [
  { label: '库存商品', value: formatNumber(overview.value.metrics.product_count), unit: '个', trend: '按货品编号去重' },
  { label: '可用库存', value: formatNumber(overview.value.metrics.available_stock), unit: '件', trend: `总库存 ${formatNumber(overview.value.metrics.stock_quantity)} 件` },
  {
    label: '库存金额',
    value: overview.value.metrics.stock_amount_available ? formatNumber(overview.value.metrics.stock_amount, 2) : '暂不可用',
    unit: overview.value.metrics.stock_amount_available ? '元' : '',
    trend: overview.value.metrics.stock_amount_available ? '库存快照成本金额' : '源数据成本字段当前为空',
  },
  { label: '临期批次', value: formatNumber(overview.value.metrics.expiring_batch_count), unit: '批', trend: `更新 ${formatDate(overview.value.updated_at)}` },
])

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
      <MetricCard label="分仓库存记录" :value="formatNumber(overview.metrics.warehouse_records)" unit="条" trend="当前库存发布快照" />
      <MetricCard label="批次库存记录" :value="formatNumber(overview.metrics.batch_records)" unit="条" trend="批次库存发布快照" />
      <MetricCard label="低于下限" :value="formatNumber(overview.metrics.below_min_count)" unit="项" trend="可用库存低于库存下限" />
      <MetricCard label="高于上限" :value="formatNumber(overview.metrics.above_max_count)" unit="项" trend="可用库存高于库存上限" />
    </div>

    <section class="panel">
      <header>
        <h2>仓库可用库存排行<span class="panel-source">（最新库存发布版本）</span></h2>
        <el-button :icon="'Refresh'" circle @click="fetchOverview" />
      </header>
      <v-chart class="chart chart-compact" :option="warehouseBarOption" autoresize />
      <el-table :data="overview.warehouses" height="360">
        <el-table-column prop="warehouse" label="仓库" min-width="220" />
        <el-table-column prop="records" label="记录数" width="120">
          <template #default="{ row }">{{ formatNumber(row.records) }}</template>
        </el-table-column>
        <el-table-column prop="stock_quantity" label="库存数量" width="150">
          <template #default="{ row }">{{ formatNumber(row.stock_quantity) }}</template>
        </el-table-column>
        <el-table-column prop="available_stock" label="可用库存" width="150">
          <template #default="{ row }">{{ formatNumber(row.available_stock) }}</template>
        </el-table-column>
        <el-table-column prop="stock_amount" label="库存金额" width="180">
          <template #default="{ row }">{{ formatNumber(row.stock_amount, 2) }}</template>
        </el-table-column>
      </el-table>
    </section>

    <section class="panel">
      <header><h2>库存数据源</h2></header>
      <el-table :data="overview.source_tables" height="320">
        <el-table-column prop="table" label="数据表" width="190" />
        <el-table-column prop="records" label="记录数" width="130">
          <template #default="{ row }">{{ formatNumber(row.records) }}</template>
        </el-table-column>
        <el-table-column prop="usage" label="用途" />
        <el-table-column prop="key_fields" label="关键字段" />
      </el-table>
    </section>
  </div>
</template>
