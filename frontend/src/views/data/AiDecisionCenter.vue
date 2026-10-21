<script setup>
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import WarehouseFilter from '../../components/inventory/WarehouseFilter.vue'
import MetricCard from '../../components/dashboard/MetricCard.vue'
import { getInventoryDecisions, startDecisionSummary, getDecisionSummary } from '../../api/ai'
import { getInventoryWarehouses } from '../../api/inventory'
import { DEFAULT_INVENTORY_WAREHOUSES } from '../../constants/inventory'

const summaryLoading = ref(false)
const dataLoading = ref(false)
const error = ref('')
const route = useRoute()
const router = useRouter()
let requestVersion = 0
let pollTimer
const warehouseLoading = ref(false)
const warehouseOptions = ref([])
const selectedWarehouses = ref(route.query.warehouse === '__all__' ? [] :
  Array.isArray(route.query.warehouse) ? [...route.query.warehouse] :
    route.query.warehouse ? [route.query.warehouse] : [...DEFAULT_INVENTORY_WAREHOUSES])
const result = ref({
  ai_status: '',
  ai_summary: '',
  generated_at: '',
  metrics: {},
  decisions: [],
})
const number = (value) => Number(value || 0).toLocaleString('zh-CN', { maximumFractionDigits: 0 })
const money = (value) => Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

async function fetchWarehouses() {
  warehouseLoading.value = true
  try {
    const response = await getInventoryWarehouses()
    warehouseOptions.value = response.data.warehouses
  } finally {
    warehouseLoading.value = false
  }
}

async function fetchDecisions(refresh = false) {
  const version = ++requestVersion
  clearTimeout(pollTimer)
  dataLoading.value = true
  summaryLoading.value = false
  error.value = ''
  result.value = { metrics: {}, decisions: [], ai_status: '', ai_summary: '' }
  const warehouses = [...selectedWarehouses.value]
  router.replace({ query: { ...route.query, warehouse: warehouses.length ? warehouses : '__all__' } })
  try {
    const response = await getInventoryDecisions({
      warehouse: warehouses,
      refresh,
    })
    if (version !== requestVersion) return
    result.value = response.data
    dataLoading.value = false
    summaryLoading.value = true
    const params = { evidence_id: response.data.evidence_id, warehouse: warehouses }
    const summary = await startDecisionSummary({ ...params, refresh })
    if (version !== requestVersion) return
    applySummary(summary.data, params, version)
  } catch {
    if (version !== requestVersion) return
    error.value = result.value.evidence_id ? 'AI 分析暂不可用，业务指标与规则决策仍可查看。' : '业务数据加载失败，请重新查询。'
    summaryLoading.value = false
  } finally {
    if (version === requestVersion) dataLoading.value = false
  }
}

function applySummary(data, params, version, attempts = 0) {
  Object.assign(result.value, data)
  summaryLoading.value = data.ai_status === 'pending'
  if (!summaryLoading.value) return
  if (attempts >= 120) {
    summaryLoading.value = false
    error.value = 'AI 分析仍在处理中，请稍后刷新；业务数据已可查看。'
    return
  }
  pollTimer = setTimeout(async () => {
    try {
      const response = await getDecisionSummary(params)
      if (version === requestVersion) applySummary(response.data, params, version, attempts + 1)
    } catch {
      if (version !== requestVersion) return
      summaryLoading.value = false
      error.value = 'AI 分析状态获取失败，请重新查询；业务数据已保留。'
    }
  }, 1500)
}

onMounted(() => Promise.all([fetchWarehouses(), fetchDecisions()]))
onBeforeUnmount(() => { requestVersion++; clearTimeout(pollTimer) })
</script>

<template>
  <div class="page-stack ai-decision-page">
    <section class="toolbar-panel inventory-filter-panel">
      <div class="inventory-filter-grid inventory-filter-grid--overview">
        <label class="inventory-filter-field">
          <span>决策仓库范围</span>
          <WarehouseFilter v-model="selectedWarehouses" :options="warehouseOptions" :loading="warehouseLoading" />
        </label>
        <div class="inventory-filter-actions">
          <el-button type="primary" :icon="'MagicStick'" :loading="dataLoading" @click="fetchDecisions(true)">
            重新生成
          </el-button>
          <el-button :icon="'Refresh'" circle :loading="dataLoading" @click="fetchDecisions(false)" />
        </div>
      </div>
    </section>

    <el-alert v-if="error" :title="error" type="warning" :closable="false" />
    <div v-if="result.evidence_id" class="decision-metrics" aria-label="业务指标">
      <MetricCard label="近30天销售额" :value="money(result.sales?.current?.paid_amount)" unit="元" />
      <MetricCard label="近30天订单数" :value="number(result.sales?.current?.orders)" />
      <MetricCard label="优先决策项" :value="number(result.metrics.decision_count)" />
      <MetricCard label="临期可用库存" :value="number(result.metrics.expiring_stock)" unit="件" />
    </div>
    <p v-if="result.evidence_id" class="decision-scope">
      销售范围：全部销售（{{ result.sales?.start_date }} 至 {{ result.sales?.end_date }}）；仓库筛选仅作用于库存。
      查询时间：{{ result.generated_at?.replace('T', ' ').slice(0, 19) }}。库存为每日同步快照。
    </p>
    <section class="panel ai-summary-panel" :aria-busy="summaryLoading">
      <header>
        <h2>智能运营信息<span class="panel-source">（销售与库存标准口径）</span></h2>
        <el-tag :type="result.ai_status === 'ready' ? 'success' : 'warning'" effect="plain">
          {{ dataLoading ? '数据加载中' : summaryLoading ? 'AI分析中' : result.ai_status === 'ready' ? 'AI已分析' : '规则模式' }}
        </el-tag>
      </header>
      <div class="ai-summary-content">
        {{ result.ai_summary || (dataLoading ? '正在加载业务数据…' : summaryLoading ? '业务数据已就绪，正在生成 AI 建议…' : '可先查看业务指标和规则决策。') }}
      </div>
    </section>
    <section v-if="result.evidence_id" class="panel">
      <header><h2>规则决策 <span class="panel-source">按风险优先展示前20项</span></h2></header>
      <el-table :data="result.decisions" row-key="id" :default-sort="{ prop: 'rank', order: 'ascending' }">
        <el-table-column prop="rank" label="优先级" width="90" sortable />
        <el-table-column prop="issue" label="问题" width="130" sortable />
        <el-table-column prop="product" label="货品" min-width="220" show-overflow-tooltip sortable />
        <el-table-column prop="warehouse" label="仓库" min-width="150" sortable />
        <el-table-column prop="available_stock" label="可用库存" width="130" sortable><template #default="{ row }">{{ number(row.available_stock) }}</template></el-table-column>
        <el-table-column prop="suggested_action" label="建议动作" min-width="230" />
      </el-table>
    </section>
  </div>
</template>

<style scoped>
.decision-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.decision-scope { margin: 0; color: var(--muted); font-size: 12px; line-height: 1.6; }
@media (max-width: 900px) { .decision-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 540px) { .decision-metrics { grid-template-columns: 1fr; } }
</style>
