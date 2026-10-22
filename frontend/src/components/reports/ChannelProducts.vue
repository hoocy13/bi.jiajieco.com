<script setup>
import { ref, watch } from 'vue'
import { getSalesChannelProductAnalysis } from '../../api/sales'

const props = defineProps({ channel: Object, period: Object })
const visible = defineModel({ default: false })
const loading = ref(false)
const error = ref('')
const keyword = ref('')
const kind = ref('')
const page = ref(1)
const size = ref(50)
const sort = ref({ prop: 'quantity', order: 'descending' })
const result = ref({ rows: [], summary: {}, pagination: { total: 0 } })
let request = 0
const number = (v, digits = 0) => Number(v || 0).toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
async function load() {
  const id = ++request
  loading.value = true
  error.value = ''
  result.value = { rows: [], summary: {}, pagination: { total: 0 } }
  try {
    const response = await getSalesChannelProductAnalysis({
      channel_name: props.channel.channel_name,
      start_date: props.period.start_date, end_date: props.period.end_date,
      data_version: props.period.data_version || undefined,
      keyword: keyword.value, product_type: kind.value,
      page: page.value, page_size: size.value,
      sort: sort.value.prop, direction: sort.value.order,
    })
    if (id === request) result.value = response.data
  } catch {
    if (id === request) error.value = '货品数据加载失败，请重试或刷新渠道页面'
  } finally {
    if (id === request) loading.value = false
  }
}
function search() { page.value = 1; load() }
function changeSort(value) { sort.value = value.order ? value : { prop: 'quantity', order: 'descending' }; search() }
watch(() => [visible.value, props.channel, props.period], () => {
  if (visible.value && props.channel) {
    keyword.value = ''; kind.value = ''; page.value = 1
    sort.value = { prop: 'quantity', order: 'descending' }
    load()
  } else { request++; loading.value = false }
})
</script>

<template>
  <el-drawer v-model="visible" size="85%" class="channel-products-drawer" destroy-on-close>
    <template #header><div><h2>{{ channel?.channel_name }} · 销售货品</h2><span>{{ period.start_date }} — {{ period.end_date }}</span></div></template>
    <div class="product-filters">
      <el-input v-model="keyword" placeholder="货品名称 / 品牌" clearable @keyup.enter="search" />
      <el-select v-model="kind" placeholder="全部分类" clearable><el-option label="正装" value="正装" /><el-option label="小样" value="小样" /></el-select>
      <el-button type="primary" @click="search">查询</el-button>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <div v-loading="loading" class="product-results">
      <div class="product-totals"><span>货品 <strong>{{ number(result.summary.products) }}</strong></span><span>销售数量 <strong>{{ number(result.summary.quantity) }}</strong></span><span>分摊销售额（元） <strong>{{ number(result.summary.paid_amount, 2) }}</strong></span></div>
      <el-table :data="result.rows" height="100%" class="product-table" :default-sort="{prop:'quantity', order:'descending'}" @sort-change="changeSort">
        <el-table-column prop="product" label="货品名称" min-width="280" sortable="custom" show-overflow-tooltip />
        <el-table-column prop="brand" label="品牌" min-width="110" sortable="custom" />
        <el-table-column prop="product_type" label="分类" width="100" sortable="custom" />
        <el-table-column prop="quantity" label="销售数量" width="140" sortable="custom" align="right"><template #default="{row}">{{ number(row.quantity) }}</template></el-table-column>
        <el-table-column prop="paid_amount" label="分摊销售额（元）" width="180" sortable="custom" align="right"><template #default="{row}">{{ number(row.paid_amount,2) }}</template></el-table-column>
        <el-table-column label="销售占比" width="110" align="right"><template #default="{row}">{{ number(row.share,1) }}%</template></el-table-column>
      </el-table>
      <el-pagination v-model:current-page="page" v-model:page-size="size" :total="result.pagination.total" :page-sizes="[20,50,100]" layout="total, sizes, prev, pager, next" @current-change="load" @size-change="search" />
    </div>
  </el-drawer>
</template>

<style scoped>
h2 { margin: 0 0 8px; font-size: 20px; color: var(--el-text-color-primary); }
:global(.channel-products-drawer .el-drawer__body) { display: flex; flex-direction: column; overflow: hidden; min-height: 0; }
.product-results { display: flex; flex: 1; flex-direction: column; min-height: 0; }
.product-table { flex: 1; min-height: 0; }
.product-filters { flex-shrink: 0; display: flex; gap: 12px; margin-bottom: 20px; flex-wrap: wrap; }
.product-filters .el-input { width: 260px; }
.product-filters .el-select { width: 140px; }
.product-totals { flex-shrink: 0; display: flex; gap: 32px; padding: 20px 0; flex-wrap: wrap; }
.product-totals strong { margin-left: 8px; font-size: 20px; }
.el-pagination { flex-shrink: 0; margin-top: 20px; overflow-x: auto; }
</style>
