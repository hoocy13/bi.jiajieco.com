<script setup>
import { onMounted, ref } from 'vue'
import WarehouseFilter from '../../components/inventory/WarehouseFilter.vue'
import { getInventoryDecisions } from '../../api/ai'
import { getInventoryWarehouses } from '../../api/inventory'
import { DEFAULT_INVENTORY_WAREHOUSES } from '../../constants/inventory'

const summaryLoading = ref(false)
const warehouseLoading = ref(false)
const warehouseOptions = ref([])
const selectedWarehouses = ref([...DEFAULT_INVENTORY_WAREHOUSES])
const result = ref({
  ai_status: '',
  ai_summary: '',
  generated_at: '',
})

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
  summaryLoading.value = true
  try {
    const response = await getInventoryDecisions({
      warehouse: selectedWarehouses.value,
      refresh,
    })
    result.value = response.data
  } finally {
    summaryLoading.value = false
  }
}

onMounted(() => Promise.all([fetchWarehouses(), fetchDecisions()]))
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
          <el-button type="primary" :icon="'MagicStick'" :loading="summaryLoading" @click="fetchDecisions(true)">
            重新生成
          </el-button>
          <el-button :icon="'Refresh'" circle :loading="summaryLoading" @click="fetchDecisions(false)" />
        </div>
      </div>
    </section>

    <section class="panel ai-summary-panel">
      <header>
        <h2>AI运营信息<span class="panel-source">（销售与库存标准口径）</span></h2>
        <el-tag :type="result.ai_status === 'ready' ? 'success' : 'warning'" effect="plain">
          {{ summaryLoading ? '生成中' : result.ai_status === 'ready' ? 'AI已分析' : '规则模式' }}
        </el-tag>
      </header>
      <div class="ai-summary-content">
        {{ result.ai_summary || '正在根据销售与库存数据生成运营建议…' }}
      </div>
    </section>
  </div>
</template>
