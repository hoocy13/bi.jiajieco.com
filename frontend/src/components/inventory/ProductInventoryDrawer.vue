<script setup>
import { computed, ref } from 'vue'
import MetricCard from '../dashboard/MetricCard.vue'
import { getInventoryProductDetail } from '../../api/inventory'

const visible = ref(false)
const loading = ref(false)
const detail = ref(null)

function formatNumber(value, digits = 0) {
  return Number(value || 0).toLocaleString('zh-CN', {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  })
}

function remainingText(days) {
  if (days === null || days === undefined) return '-'
  if (days < 0) return `已过期 ${formatNumber(Math.abs(days))} 天`
  return `${formatNumber(days)} 天`
}

const metrics = computed(() => {
  if (!detail.value) return []
  return [
    { label: '可用库存', value: formatNumber(detail.value.metrics.available_stock), unit: '件', trend: `总库存 ${formatNumber(detail.value.metrics.stock)} 件` },
    { label: '近30天销量', value: formatNumber(detail.value.metrics.sales30), unit: '件', trend: `近90天 ${formatNumber(detail.value.metrics.sales90)} 件` },
    { label: '库存金额', value: formatNumber(detail.value.metrics.stock_amount, 2), unit: '元', trend: `${formatNumber(detail.value.metrics.warehouse_count)} 个仓库` },
    { label: '在库批次', value: formatNumber(detail.value.metrics.batch_count), unit: '批', trend: '按到期日期排序' },
  ]
})

async function open(productCode, warehouses = []) {
  visible.value = true
  loading.value = true
  detail.value = null
  try {
    const result = await getInventoryProductDetail(productCode, { warehouse: warehouses })
    detail.value = result.data
  } finally {
    loading.value = false
  }
}

defineExpose({ open })
</script>

<template>
  <el-drawer v-model="visible" size="78%" class="inventory-detail-drawer">
    <template #header>
      <div class="inventory-detail-title">
        <strong>{{ detail?.product || '商品库存详情' }}</strong>
        <span v-if="detail">{{ detail.brand }} · {{ detail.barcode }} · {{ detail.product_code }}</span>
      </div>
    </template>

    <div v-loading="loading" class="inventory-detail-body">
      <template v-if="detail">
        <div class="metric-grid inventory-detail-metrics">
          <MetricCard v-for="item in metrics" :key="item.label" v-bind="item" />
        </div>

        <section class="panel">
          <header><h2>分仓库存<span class="panel-source">（分仓库查询）</span></h2></header>
          <el-table :data="detail.warehouse_rows" height="280">
            <el-table-column prop="warehouse" label="仓库" min-width="180" />
            <el-table-column prop="stock" label="库存数量" width="120">
              <template #default="{ row }">{{ formatNumber(row.stock) }}</template>
            </el-table-column>
            <el-table-column prop="available_stock" label="可用库存" width="120">
              <template #default="{ row }">{{ formatNumber(row.available_stock) }}</template>
            </el-table-column>
            <el-table-column prop="sales30" label="近30天销量" width="130">
              <template #default="{ row }">{{ formatNumber(row.sales30) }}</template>
            </el-table-column>
            <el-table-column prop="sales90" label="近90天销量" width="130">
              <template #default="{ row }">{{ formatNumber(row.sales90) }}</template>
            </el-table-column>
            <el-table-column prop="stock_amount" label="库存金额" width="150">
              <template #default="{ row }">{{ formatNumber(row.stock_amount, 2) }}</template>
            </el-table-column>
          </el-table>
        </section>

        <section class="panel">
          <header><h2>批次 FEFO 顺序<span class="panel-source">（批次货品库存查询）</span></h2></header>
          <el-table :data="detail.batch_rows" height="340">
            <el-table-column prop="fefo_rank" label="顺位" width="80" align="center" />
            <el-table-column prop="warehouse" label="仓库" min-width="180" />
            <el-table-column prop="batch" label="批次" width="150" />
            <el-table-column prop="production_date" label="生产日期" width="120" />
            <el-table-column prop="expiry_date" label="到期日期" width="120" />
            <el-table-column label="剩余效期" width="150">
              <template #default="{ row }">{{ remainingText(row.remaining_days) }}</template>
            </el-table-column>
            <el-table-column prop="available_stock" label="可用库存" width="120">
              <template #default="{ row }">{{ formatNumber(row.available_stock) }}</template>
            </el-table-column>
          </el-table>
        </section>
      </template>
    </div>
  </el-drawer>
</template>

<style scoped>
.inventory-detail-title {
  display: grid;
  gap: 5px;
}

.inventory-detail-title strong {
  color: #111827;
  font-size: 18px;
}

.inventory-detail-title span {
  color: #98a2b3;
  font-size: 12px;
}

.inventory-detail-body {
  display: grid;
  min-height: 420px;
  gap: 18px;
}

.inventory-detail-metrics {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

@media (max-width: 960px) {
  .inventory-detail-metrics {
    grid-template-columns: 1fr;
  }
}
</style>
