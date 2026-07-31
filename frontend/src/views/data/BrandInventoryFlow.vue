<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { getBrandInventoryFlow, getInventoryWarehouses } from '../../api/inventory'

use([CanvasRenderer, BarChart, LineChart, GridComponent, LegendComponent, TooltipComponent])

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const brandOptions = ref([])
const selectedBrand = ref(route.query.brand || '资生堂')

async function loadBrandOptions() {
  try {
    const res = await getInventoryWarehouses()
    brandOptions.value = res.data?.brands || []
  } catch { /* silent */ }
}

const defaultYear = new Date().getFullYear()
const monthRange = ref([
  String(route.query.start_date || defaultYear + '-01-01').slice(0, 7),
  String(route.query.end_date || defaultYear + '-12-31').slice(0, 7),
])
const selectedWarehouses = ref(
  Array.isArray(route.query.warehouse)
    ? route.query.warehouse.map(String)
    : route.query.warehouse ? [String(route.query.warehouse)] : [],
)
const analysis = ref({
  brand: selectedBrand.value,
  start_date: '2025-01-01',
  end_date: '2025-12-31',
  opening_snapshot_date: '2024-12-31',
  ending_snapshot_date: '2025-12-31',
  period: '2025年01月—2025年12月',
  summary: {
    opening_quantity: 0,
    inbound_quantity: 0,
    sales_quantity: 0,
    ending_quantity: 0,
    sell_through_rate: 0,
    inbound_cost: 0,
    sales_amount: 0,
    ending_stock_amount: 0,
  },
  months: [],
  segments: [],
  filter_options: { warehouses: [] },
  freshness: {},
  metric_notes: {},
})

function formatNumber(value, digits = 0) {
  return Number(value || 0).toLocaleString('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

function formatCompact(value) {
  const amount = Number(value || 0)
  if (Math.abs(amount) >= 100000000) return formatNumber(amount / 100000000, 2) + '亿'
  if (Math.abs(amount) >= 10000) return formatNumber(amount / 10000, 1) + '万'
  return formatNumber(amount)
}

function formatDateTime(value) {
  return value ? String(value).replace('T', ' ').slice(0, 16) : '-'
}

function monthLastDay(month) {
  const [year, monthNumber] = month.split('-').map(Number)
  return month + '-' + String(new Date(year, monthNumber, 0).getDate()).padStart(2, '0')
}

const canSearch = computed(() => (
  selectedBrand.value && monthRange.value?.length === 2 && monthRange.value[0] <= monthRange.value[1]
))


// 入销比：采购入库 / 销售
const inboundSalesRatio = computed(() => {
  const inbound = analysis.value.summary.inbound_quantity || 0
  const sales = analysis.value.summary.sales_quantity || 0
  if (sales <= 0) return null
  return (inbound / sales).toFixed(2)
})

const metricCards = computed(() => [
  {
    label: '期初库存',
    value: analysis.value.summary.opening_quantity,
    unit: '件',
    note: analysis.value.opening_snapshot_date + ' 月末快照',
  },
  {
    label: '净采购入库',
    value: analysis.value.summary.inbound_quantity,
    unit: '件',
    note: '成本 ' + formatCompact(analysis.value.summary.inbound_cost) + ' 元',
    accent: true,
  },
  {
    label: '净销售',
    value: analysis.value.summary.sales_quantity,
    unit: '件',
    note: '销售额 ' + formatCompact(analysis.value.summary.sales_amount) + ' 元',
  },
  {
    label: '期末库存',
    value: analysis.value.summary.ending_quantity,
    unit: '件',
    note: '库存金额 ' + formatCompact(analysis.value.summary.ending_stock_amount) + ' 元',
  },

  {
    label: '入销比',
    value: inboundSalesRatio.value || '-',
    unit: '倍',
    note: inboundSalesRatio.value
      ? '入库' + analysis.value.summary.inbound_quantity + '件 / 销售' + analysis.value.summary.sales_quantity + '件'
      : '暂无销售数据',
  },
])

const quantityChartOption = computed(() => ({
  color: ['#6f9946', '#334155', '#a6c76d'],
  tooltip: {
    trigger: 'axis',
    backgroundColor: '#172033',
    borderWidth: 0,
    textStyle: { color: '#fff' },
    formatter: function(params) {
      var html = '<strong>' + (params[0]?.axisValue || '') + '</strong>'
      params.forEach(function(item) {
        html += '<div style="display:flex;gap:18px;margin-top:7px;min-width:220px">' + item.marker + '<span>' + item.seriesName + '</span><strong style="margin-left:auto">' + formatNumber(item.value) + ' 件</strong></div>'
      })
      return html
    },
  },
  legend: { top: 4, right: 8, icon: 'roundRect', itemWidth: 10, itemHeight: 10 },
  grid: { top: 48, left: 76, right: 36, bottom: 44 },
  xAxis: {
    type: 'category',
    data: analysis.value.months.map(function(item) { return item.month.slice(2).replace('-', '年') + '月' }),
    axisTick: { show: false },
    axisLine: { lineStyle: { color: '#dce3e9' } },
    axisLabel: { color: '#64748b', hideOverlap: true },
  },
  yAxis: {
    type: 'value',
    axisLabel: { color: '#94a3b8', formatter: formatCompact },
    splitLine: { lineStyle: { color: '#edf1f4', type: 'dashed' } },
  },
  series: [
    {
      name: '采购入库',
      type: 'bar',
      barMaxWidth: 18,
      itemStyle: { borderRadius: [4, 4, 0, 0] },
      data: analysis.value.months.map(function(item) { return item.inbound_quantity }),
    },
    {
      name: '销售',
      type: 'bar',
      barMaxWidth: 18,
      itemStyle: { borderRadius: [4, 4, 0, 0] },
      data: analysis.value.months.map(function(item) { return item.sales_quantity }),
    },
    {
      name: '月末库存',
      type: 'line',
      symbol: 'circle',
      symbolSize: 6,
      lineStyle: { width: 2.5 },
      data: analysis.value.months.map(function(item) { return item.ending_quantity }),
    },
  ],
}))

function segmentChartOption(segment) {
  return {
    color: ['#6f9946', '#344054', '#a6c76d'],
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#172033',
      borderWidth: 0,
      textStyle: { color: '#fff' },
      formatter: function(params) {
        var html = '<strong>' + (params[0]?.axisValue || '') + '</strong>'
        params.forEach(function(item) {
          html += '<div style="display:flex;gap:12px;margin-top:5px;min-width:170px">' + item.marker + '<span>' + item.seriesName + '</span><strong style="margin-left:auto">' + formatNumber(item.value) + '</strong></div>'
        })
        return html
      },
    },
    grid: { top: 16, left: 56, right: 18, bottom: 32 },
    xAxis: {
      type: 'category',
      data: segment.months.map(function(item) { return item.month.slice(5) + '月' }),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#dce3e9' } },
      axisLabel: { color: '#8a96a5', fontSize: 10, hideOverlap: true },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#9aa5b3', fontSize: 10, formatter: formatCompact },
      splitLine: { lineStyle: { color: '#edf1f4', type: 'dashed' } },
    },
    series: [
      { name: '入库', type: 'bar', barMaxWidth: 10, data: segment.months.map(function(item) { return item.inbound_quantity }) },
      { name: '销售', type: 'bar', barMaxWidth: 10, data: segment.months.map(function(item) { return item.sales_quantity }) },
      { name: '库存', type: 'line', symbol: 'none', lineStyle: { width: 2 }, data: segment.months.map(function(item) { return item.ending_quantity }) },
    ],
  }
}

async function fetchData() {
  if (!canSearch.value) return
  const startDate = monthRange.value[0] + '-01'
  const endDate = monthLastDay(monthRange.value[1])
  loading.value = true
  try {
    const response = await getBrandInventoryFlow({
      brand: selectedBrand.value,
      start_date: startDate,
      end_date: endDate,
      warehouse: selectedWarehouses.value,
    })
    analysis.value = response.data
    router.replace({
      query: {
        brand: selectedBrand.value,
        start_date: startDate,
        end_date: endDate,
        ...(selectedWarehouses.value.length ? { warehouse: selectedWarehouses.value } : {}),
      },
    })
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  selectedBrand.value = '资生堂'
  monthRange.value = [defaultYear + '-01', defaultYear + '-12']
  selectedWarehouses.value = []
  fetchData()
}

onMounted(() => {
  loadBrandOptions()
  fetchData()
})
</script>

<template>
  <div class="flow-page" v-loading="loading">
    <section class="flow-toolbar">
      <el-select
        v-model="selectedBrand"
        filterable
        placeholder="选择品牌"
        class="brand-input"
        @change="fetchData"
      >
        <el-option v-for="item in brandOptions" :key="item" :label="item" :value="item" />
      </el-select>
      <el-date-picker
        v-model="monthRange"
        type="monthrange"
        value-format="YYYY-MM"
        format="YYYY年MM月"
        range-separator="至"
        start-placeholder="开始月份"
        end-placeholder="结束月份"
        :clearable="false"
        class="month-picker"
      />
      <el-select
        v-model="selectedWarehouses"
        multiple
        filterable
        collapse-tags
        collapse-tags-tooltip
        clearable
        placeholder="全部仓库"
        class="warehouse-select"
      >
        <el-option v-for="item in analysis.filter_options.warehouses" :key="item" :label="item" :value="item" />
      </el-select>
      <el-button type="primary" :icon="'Search'" :disabled="!canSearch" @click="fetchData">查询</el-button>
      <el-tooltip content="恢复默认筛选条件" placement="top">
        <el-button :icon="'RefreshLeft'" circle @click="resetFilters" />
      </el-tooltip>
    </section>

    <section class="flow-hero">
      <div class="hero-title">
        <span aria-hidden="true"></span>
        <div>
          <p>BRAND INVENTORY FLOW</p>
          <h1>{{ analysis.brand }} 进销存看板</h1>
          <small>正装与小样的采购入库、销售、库存统一观察</small>
        </div>
      </div>
      <div class="hero-meta">
        <strong>{{ analysis.period }}</strong>
        <span :class="{ complete: analysis.freshness.snapshot_complete }">
          {{ analysis.freshness.snapshot_complete
            ? analysis.freshness.snapshot_batches + ' 个库存快照完整'
            : analysis.freshness.snapshot_batches + '/' + analysis.freshness.snapshot_expected + ' 个库存快照' }}
        </span>
        <small>数据更新 {{ formatDateTime(analysis.freshness.source_updated_at) }}</small>
      </div>
    </section>

    <div class="metric-grid">
      <section v-for="item in metricCards" :key="item.label" class="metric-card" :class="{ accent: item.accent }">
        <span>{{ item.label }}</span>
        <div><strong>{{ item.value === '-' ? item.value : formatNumber(item.value) }}</strong><em>{{ item.unit }}</em></div>
        <small>{{ item.note }}</small>
      </section>
    </div>

    <section class="flow-panel quantity-panel">
      <header>
        <div><small>月度进销存</small><h2>采购入库、销售与月末库存</h2></div>
        <span>正装 + 小样 · 数量口径：件</span>
      </header>
      <VChart class="quantity-chart" :option="quantityChartOption" autoresize />
    </section>

    <section class="flow-panel segment-section">
      <header>
        <div><small>分类观察</small><h2>正装与小样进销存</h2></div>
        <span>三个视角使用相同月份与仓库条件</span>
      </header>
      <div class="segment-grid">
        <article v-for="segment in analysis.segments" :key="segment.key" class="segment-card">
          <div class="segment-heading">
            <h3>{{ segment.label }}</h3>
            <span>可售消化率 {{ formatNumber(segment.summary.sell_through_rate, 1) }}%</span>
          </div>
          <div class="segment-metrics">
            <div><span>期初库存</span><strong>{{ formatNumber(segment.summary.opening_quantity) }}</strong></div>
            <div><span>净采购入库</span><strong>{{ formatNumber(segment.summary.inbound_quantity) }}</strong></div>
            <div><span>净销售</span><strong>{{ formatNumber(segment.summary.sales_quantity) }}</strong></div>
            <div><span>期末库存</span><strong>{{ formatNumber(segment.summary.ending_quantity) }}</strong></div>
          </div>
          <VChart class="segment-chart" :option="segmentChartOption(segment)" autoresize />
        </article>
      </div>
    </section>

    <section class="flow-panel notes-panel">
      <header><div><small>统计口径</small><h2>数据来源</h2></div></header>
      <div class="note-grid">
        <div><strong>采购入库</strong><span>{{ analysis.metric_notes.inbound }}</span></div>
        <div><strong>销售</strong><span>{{ analysis.metric_notes.sales }}</span></div>
        <div><strong>库存</strong><span>{{ analysis.metric_notes.stock }}</span></div>
      </div>
    </section>

    <section class="flow-panel table-panel">
      <header>
        <div><small>月度明细</small><h2>{{ analysis.period }}进销存明细</h2></div>
        <span>正装 + 小样 · 点击列头可排序 · 金额单位：元</span>
      </header>
      <el-table :data="analysis.months" stripe empty-text="暂无数据">
        <el-table-column prop="month" label="月份" width="105" fixed sortable />
        <el-table-column prop="opening_quantity" label="期初库存" min-width="120" align="right" sortable>
          <template #default="{ row }">{{ formatNumber(row.opening_quantity) }}</template>
        </el-table-column>
        <el-table-column prop="inbound_quantity" label="采购入库" min-width="120" align="right" sortable>
          <template #default="{ row }">{{ formatNumber(row.inbound_quantity) }}</template>
        </el-table-column>
        <el-table-column prop="sales_quantity" label="销售数量" min-width="120" align="right" sortable>
          <template #default="{ row }">{{ formatNumber(row.sales_quantity) }}</template>
        </el-table-column>
        <el-table-column prop="ending_quantity" label="期末库存" min-width="120" align="right" sortable>
          <template #default="{ row }"><strong>{{ formatNumber(row.ending_quantity) }}</strong></template>
        </el-table-column>
        <el-table-column prop="sell_through_rate" label="可售消化率" min-width="120" align="right" sortable>
          <template #default="{ row }">{{ formatNumber(row.sell_through_rate, 1) }}%</template>
        </el-table-column>
        <el-table-column prop="inbound_cost" label="采购入库成本" min-width="150" align="right" sortable>
          <template #default="{ row }">{{ formatNumber(row.inbound_cost, 2) }}</template>
        </el-table-column>
        <el-table-column prop="sales_amount" label="销售额" min-width="145" align="right" sortable>
          <template #default="{ row }">{{ formatNumber(row.sales_amount, 2) }}</template>
        </el-table-column>
        <el-table-column prop="ending_stock_amount" label="期末库存金额" min-width="155" align="right" sortable>
          <template #default="{ row }">{{ formatNumber(row.ending_stock_amount, 2) }}</template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<style scoped>
.flow-page { display: grid; gap: 14px; color: #172033; }
.flow-toolbar, .flow-hero, .flow-panel, .metric-card { border: 1px solid #e3e9e3; background: #fff; box-shadow: 0 1px 2px rgba(16, 24, 40, .03); }
.flow-toolbar { display: flex; align-items: center; gap: 9px; padding: 10px 14px; border-radius: 8px; }
.brand-input { width: 150px; }.month-picker { min-width: 200px; flex: 1; }.warehouse-select { width: 240px; }
.flow-hero { min-height: 118px; padding: 22px 28px; border-top: 3px solid #587f3a; border-radius: 8px; display: flex; align-items: center; justify-content: space-between; background: linear-gradient(105deg, #fff 62%, #f3f7ee); }
.hero-title { display: flex; align-items: center; gap: 15px; }.hero-title > span { width: 4px; height: 54px; border-radius: 4px; background: #587f3a; }
.hero-title p, .flow-panel header small { margin: 0 0 4px; color: #587f3a; font-size: 10px; font-weight: 800; letter-spacing: .1em; }
.hero-title h1 { margin: 0 0 4px; font-size: 26px; letter-spacing: -.02em; }.hero-title small { color: #7a8699; font-size: 12px; }
.hero-meta { display: grid; justify-items: end; gap: 5px; }.hero-meta strong { color: #587f3a; font-size: 14px; }.hero-meta span { padding: 4px 8px; border-radius: 999px; background: #fff1ec; color: #b5573a; font-size: 11px; font-weight: 700; }.hero-meta span.complete { background: #ebf5e6; color: #507b35; }.hero-meta small { color: #82909f; }
.metric-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; }
.metric-card { min-width: 0; min-height: 108px; padding: 17px 18px; border-radius: 8px; display: grid; align-content: center; gap: 8px; border-top: 3px solid #dce6d6; }.metric-card > span { color: #617083; font-size: 12px; font-weight: 700; }.metric-card div { display: flex; align-items: baseline; gap: 6px; min-width: 0; }.metric-card strong { font-size: clamp(18px, 1.3vw, 24px); line-height: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }.metric-card em { color: #7d8897; font-size: 11px; font-style: normal; }.metric-card small { color: #98a2b3; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.metric-card.accent { border-color: #587f3a; background: #587f3a; color: #fff; }.metric-card.accent > span, .metric-card.accent em, .metric-card.accent small { color: rgba(255, 255, 255, .78); }
.flow-panel { min-width: 0; overflow: hidden; border-radius: 8px; }.flow-panel header { min-height: 62px; padding: 13px 16px; border-bottom: 1px solid #e7ece7; display: flex; align-items: center; justify-content: space-between; gap: 14px; }.flow-panel header h2 { margin: 0; font-size: 15px; }.flow-panel header > span { color: #98a2b3; font-size: 11px; }
.quantity-chart { height: 390px; }
.segment-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; padding: 12px; }.segment-card { min-width: 0; overflow: hidden; border: 1px solid #e2e8df; border-radius: 8px; background: #fbfcfa; }.segment-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 13px 14px 10px; }.segment-heading h3 { margin: 0; font-size: 14px; }.segment-heading > span { color: #587f3a; font-size: 11px; font-weight: 700; }
.segment-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; margin: 0 12px; overflow: hidden; border: 1px solid #e5eae3; border-radius: 6px; background: #e5eae3; }.segment-metrics div { min-width: 0; padding: 9px 8px; background: #fff; }.segment-metrics span { display: block; margin-bottom: 5px; color: #8994a2; font-size: 9px; white-space: nowrap; }.segment-metrics strong { display: block; overflow: hidden; color: #293548; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }.segment-chart { height: 230px; }
.note-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; padding: 12px 16px 16px; }.note-grid div { padding: 11px 13px; border-radius: 6px; background: #f7f9f6; }.note-grid strong { display: block; margin-bottom: 4px; color: #4f663f; font-size: 12px; }.note-grid span { color: #687586; font-size: 11px; line-height: 1.55; }
.table-panel :deep(.el-table) { --el-table-header-bg-color: #f7faf6; --el-table-row-hover-bg-color: #f3f7ee; }.table-panel :deep(.el-table th.el-table__cell) { color: #526070; font-size: 12px; font-weight: 700; }
@media (max-width: 1180px) { .flow-toolbar { flex-wrap: wrap; }.segment-grid { grid-template-columns: 1fr; }.segment-chart { height: 260px; } }
@media (max-width: 900px) { .metric-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }.note-grid { grid-template-columns: 1fr; } }
@media (max-width: 680px) { .flow-toolbar { align-items: stretch; }.brand-input, .month-picker, .warehouse-select { width: 100% !important; flex: 1 1 100% !important; }.flow-hero { align-items: flex-start; flex-direction: column; gap: 18px; }.hero-meta { justify-items: start; }.metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>