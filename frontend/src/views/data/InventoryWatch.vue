<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getWatchOptions, getWatches, getWatchCandidates, addWatches, updateWatch, removeWatch, getWatchProduct } from '../../api/inventoryWatches'

const route = useRoute()
const router = useRouter()
const array = value => value ? (Array.isArray(value) ? value.map(String) : [String(value)]) : []
const positive = (value, fallback) => Number.isInteger(Number(value)) && Number(value) > 0 ? Number(value) : fallback
const filters = ref({ channel_code: [], warehouse: [], brand: '', product_type: [], keyword: '', status: 'all', view: 'product', sort: 'remaining', direction: 'descending', page: 1, page_size: 20 })
const options = ref({ channels: [], configured_channels: [], warehouses: [], brands: [], product_types: [] })
const result = ref({ rows: [], summary: {}, scope: {}, pagination: { total: 0 } })
const loading = ref(false)
const error = ref('')
let request = 0
function readQuery() {
  const q = route.query
  filters.value = { channel_code: array(q.channel_code).slice(0, 1), warehouse: array(q.warehouse), brand: String(q.brand || ''), product_type: array(q.product_type), keyword: String(q.keyword || ''),
    status: 'all',
    view: 'product',
    sort: ['quantity', 'stock', 'available', 'remaining', 'my_remaining', 'end_time', 'product', 'product_code', 'brand', 'product_type', 'channel_name', 'rules'].includes(q.sort) ? q.sort : 'remaining',
    direction: q.direction === 'ascending' ? 'ascending' : 'descending', page: positive(q.page, 1), page_size: [10, 20, 50, 100].includes(Number(q.page_size)) ? Number(q.page_size) : 20 }
}
const number = value => value == null ? '—' : Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 0 })
const amount = value => Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const date = value => value ? String(value).replace('T', ' ').slice(0, 19) : '未提供'
const optionsLoading = ref(false)
const channelName = computed(() => options.value.channels.find(c => c.code === filters.value.channel_code[0])?.name || options.value.configured_channels.find(c => c.code === filters.value.channel_code[0])?.name || '渠道库存')
const day = value => value ? String(value).slice(0, 10) : '未提供'
async function loadOptions() {
  optionsLoading.value = true
  error.value = ''
  try { options.value = (await getWatchOptions()).data }
  catch { error.value = '渠道配置加载失败，请重试。' }
  finally { optionsLoading.value = false }
}
function chooseChannel(code) {
  detailOpen.value = false
  return router.push({ query: code ? { channel_code: code } : {} })
}
async function refresh() { await loadOptions(); if (!error.value) await load() }
async function load() {
  const id = ++request
  if (!filters.value.channel_code.length) { loading.value = false; return }
  loading.value = true
  error.value = ''
  try {
    const response = await getWatches(filters.value)
    if (id === request) result.value = response.data
  } catch { if (id === request) error.value = '关注清单加载失败，请重试。' }
  finally { if (id === request) loading.value = false }
}
async function apply(reset = true) {
  if (reset) filters.value.page = 1
  const query = Object.fromEntries(Object.entries(filters.value).filter(([, v]) => v !== '' && (!Array.isArray(v) || v.length)))
  const before = route.fullPath
  await router.replace({ query })
  if (before === route.fullPath) await load()
}
watch(() => route.fullPath, () => { readQuery(); load() })
function sortMain({ prop, order }) { filters.value.sort = order ? prop : 'remaining'; filters.value.direction = order || 'descending'; apply() }
function resetFilters() {
  const code = filters.value.channel_code[0]
  filters.value.warehouse = []; filters.value.brand = ''; filters.value.product_type = []; filters.value.keyword = ''; filters.value.page = 1
  if (Object.keys(route.query).length > 1) router.replace({ query: { channel_code: code } })
  else apply()
}

const adding = ref(false)
const candidateLoading = ref(false)
const candidateError = ref('')
const candidateTable = ref()
const candidate = ref({ channel_code: [], keyword: '', brand: '', product_type: [], mode: 'sales', sort: 'quantity', direction: 'descending', page: 1, page_size: 20 })
const targetChannels = ref([])
const candidates = ref({ rows: [], pagination: { total: 0 }, scope: {} })
const selected = ref(new Map())
const saving = ref(false)
let candidateRequest = 0
const newCount = computed(() => [...selected.value.values()].reduce((n, r) => n + targetChannels.value.filter(c => !r.watched_channels.includes(c)).length, 0))
function openAdd() {
  candidate.value.channel_code = [...filters.value.channel_code]
  candidate.value.mode = 'sales'
  candidate.value.sort = 'quantity'
  candidate.value.direction = 'descending'
  targetChannels.value = [...filters.value.channel_code]
  candidate.value.page = 1
  selected.value = new Map()
  candidateTable.value?.clearSelection()
  adding.value = true
  loadCandidates()
}
async function loadCandidates(reset = false) {
  if (reset) { candidate.value.page = 1; selected.value = new Map(); candidateTable.value?.clearSelection() }
  const id = ++candidateRequest
  candidateLoading.value = true
  candidateError.value = ''
  try {
    const response = await getWatchCandidates(candidate.value)
    if (id === candidateRequest) candidates.value = response.data
  } catch { if (id === candidateRequest) candidateError.value = '候选货品加载失败，请重试。' }
  finally { if (id === candidateRequest) candidateLoading.value = false }
}
function selectionChange(values) { selected.value = new Map(values.map(r => [r.product_code, r])) }
function candidateSort({ prop, order }) { candidate.value.sort = order ? prop : 'quantity'; candidate.value.direction = order || 'descending'; loadCandidates(true) }
function changeCandidateMode(mode) {
  candidate.value.sort = mode === 'sales' ? 'quantity' : 'product_code'
  candidate.value.direction = mode === 'sales' ? 'descending' : 'ascending'
  loadCandidates(true)
}
function rankCandidates() { candidate.value.direction = 'descending'; loadCandidates(true) }
async function save() {
  saving.value = true
  try {
    const response = await addWatches({ channel_codes: targetChannels.value, product_codes: [...selected.value.keys()] })
    ElMessage.success(`已新增 ${response.data.added} 个关注关系，${response.data.existing} 个已存在`)
    adding.value = false
    await loadOptions()
    if (filters.value.channel_code.length) await load()
    else await chooseChannel(targetChannels.value[0])
  } finally { saving.value = false }
}

const detailOpen = ref(false)
const detailRow = ref(null)
const detail = ref({ stocks: [], reservations: [], pagination: { total: 0 } })
const detailPage = ref(1)
const mineDetail = ref({ reservations: [], pagination: { total: 0 } })
const minePage = ref(1)
const mineSort = ref({ sort: 'priority', direction: 'ascending' })
const mineLoading = ref(false)
const mineError = ref('')
const mineSection = ref()
let mineRequest = 0
const reservationSections = computed(() => [
  { key: 'all', title: '预留单明细', data: detail.value, loading: detailLoading.value, error: detailError.value, page: detailPage.value },
  { key: 'mine', title: '我的预留', data: mineDetail.value, loading: mineLoading.value, error: mineError.value, page: minePage.value },
])
const detailSort = ref({ sort: 'priority', direction: 'ascending' })
const detailLoading = ref(false)
const detailError = ref('')
let detailRequest = 0
async function openDetail(row, focusMine = false) {
  detailRow.value = row; detailPage.value = 1; minePage.value = 1
  detail.value = { stocks: [], reservations: [], scope: {}, pagination: { total: 0 } }
  mineDetail.value = { reservations: [], pagination: { total: 0 } }
  detailSort.value = { sort: 'priority', direction: 'ascending' }
  mineSort.value = { sort: 'priority', direction: 'ascending' }
  detailOpen.value = true
  await Promise.all([loadDetail(), loadMineDetail()])
  if (focusMine && detailOpen.value && detailRow.value.product_code === row.product_code) {
    await nextTick(); mineSection.value?.scrollIntoView({ block: 'start', behavior: 'smooth' })
  }
}
function changeReservationPage(section, page) {
  if (section === 'mine') { minePage.value = page; loadMineDetail() }
  else { detailPage.value = page; loadDetail() }
}
function sortReservations(section, sort) {
  if (section === 'all') { sortDetail(sort); return }
  mineSort.value = { sort: sort.order ? sort.prop : 'priority', direction: sort.order || 'ascending' }
  minePage.value = 1; loadMineDetail()
}
async function loadMineDetail() {
  const id = ++mineRequest
  mineError.value = ''
  if (detailRow.value.my_remaining == null) { mineLoading.value = false; mineError.value = '当前渠道缺少预留对象对应信息'; return }
  mineLoading.value = true
  try {
    const response = await getWatchProduct(detailRow.value.product_code, { warehouse: filters.value.warehouse, channel_code: filters.value.channel_code[0], mine_only: true, ...mineSort.value, page: minePage.value, page_size: 20 })
    if (id === mineRequest) mineDetail.value = response.data
  } catch { if (id === mineRequest) mineError.value = '我的预留加载失败，请重试。' }
  finally { if (id === mineRequest) mineLoading.value = false }
}
function sortDetail({ prop, order }) { detailSort.value = { sort: order ? prop : 'priority', direction: order || 'ascending' }; detailPage.value = 1; loadDetail() }
async function loadDetail() {
  const id = ++detailRequest
  detailLoading.value = true
  detailError.value = ''
  try {
    const response = await getWatchProduct(detailRow.value.product_code, { warehouse: filters.value.warehouse, channel_code: filters.value.channel_code[0], mine_only: false, ...detailSort.value, page: detailPage.value, page_size: 20 })
    if (id === detailRequest) detail.value = response.data
  } catch { if (id === detailRequest) detailError.value = '货品详情加载失败，请重试。' }
  finally { if (id === detailRequest) detailLoading.value = false }
}
const mutations = ref(new Set())
async function editNote(relation) {
  try {
    const { value } = await ElMessageBox.prompt(`公共备注 · ${relation.channel_name}`, '修改关注备注', { inputValue: relation.note, inputType: 'textarea', inputValidator: v => (v || '').length <= 1000 || '最多1000字' })
    const response = await updateWatch(relation.id, { note: value || '', revision: relation.revision })
    relation.note = value || ''; relation.revision = response.data.revision
    ElMessage.success('公共备注已更新')
    await load()
  } catch (e) { if (e !== 'cancel' && e !== 'close') await load() }
}
async function cancelWatch(relation) {
  try {
    await ElMessageBox.confirm(`取消“${relation.channel_name}”对“${detailRow.value.product}（${detailRow.value.product_code}）”的关注？所有账号都会同步。`, '取消公共关注', { type: 'warning' })
    mutations.value.add(relation.id)
    await removeWatch(relation.id)
    detailRow.value.relations = detailRow.value.relations.filter(r => r.id !== relation.id)
    ElMessage.success('已取消该渠道的关注')
    await loadOptions()
    await load()
  } catch { /* The HTTP interceptor reports failed mutations. */ }
  finally { mutations.value.delete(relation.id) }
}
onMounted(async () => {
  readQuery()
  load()
  await loadOptions()
})
</script>

<template>
  <div class="inventory-watch">
    <header class="watch-header">
      <div><h2>{{ filters.channel_code.length ? channelName : '库存关注' }}</h2><p v-if="!filters.channel_code.length">选择已配置渠道，查看关注货品库存</p></div>
      <div class="header-right">
        <div v-if="filters.channel_code.length" class="data-times header-times"><span>库存更新：{{ day(result.scope.inventory_updated_at) }}</span><span>预留更新：{{ day(result.scope.header_updated_at) }}</span><span>预留明细更新：{{ day(result.scope.detail_updated_at) }}</span></div>
        <div class="header-actions"><el-button v-if="filters.channel_code.length" @click="chooseChannel(null)">切换渠道</el-button><el-button :icon="'Refresh'" circle :loading="loading || optionsLoading" aria-label="刷新库存关注" title="刷新" @click="refresh" /><el-button type="primary" @click="openAdd">{{ filters.channel_code.length ? '添加关注货品' : '配置关注货品' }}</el-button></div>
      </div>
    </header>
    <el-alert v-if="error" :title="error" type="error" :closable="false"><el-button link @click="refresh">重试</el-button></el-alert>
    <el-card v-if="!filters.channel_code.length" shadow="never" class="channel-entry" v-loading="optionsLoading">
      <el-form inline><el-form-item label="已配置渠道"><el-select :model-value="null" filterable placeholder="请选择渠道" class="channel-select" @change="chooseChannel"><el-option v-for="c in options.configured_channels" :key="c.code" :label="`${c.name}（${c.product_count}个货品）`" :value="c.code" /></el-select></el-form-item></el-form>
      <el-empty v-if="!optionsLoading && !options.configured_channels.length && !error" description="暂无已配置渠道"><el-button type="primary" @click="openAdd">配置关注货品</el-button></el-empty>
    </el-card>
    <template v-else>
      <el-card shadow="never" class="filter-card">
        <el-form inline @submit.prevent="apply()">
          <el-form-item label="渠道"><el-select :model-value="filters.channel_code[0]" filterable class="channel-select" @change="chooseChannel"><el-option v-for="c in options.configured_channels" :key="c.code" :label="c.name" :value="c.code" /></el-select></el-form-item>
          <el-form-item label="仓库"><el-select v-model="filters.warehouse" multiple filterable collapse-tags placeholder="全部仓库"><el-option v-for="v in options.warehouses" :key="v" :value="v" :label="v" /></el-select></el-form-item>
          <el-form-item label="品牌"><el-select v-model="filters.brand" clearable filterable placeholder="全部品牌"><el-option v-for="v in options.brands" :key="v" :value="v" :label="v" /></el-select></el-form-item>
          <el-form-item label="分类"><el-select v-model="filters.product_type" multiple clearable collapse-tags collapse-tags-tooltip placeholder="全部分类"><el-option v-for="v in options.product_types" :key="v" :value="v" :label="v" /></el-select></el-form-item>
          <el-form-item><el-input v-model="filters.keyword" clearable placeholder="货品编号 / 名称" /></el-form-item>
          <el-form-item><el-button type="primary" native-type="submit">查询</el-button><el-button @click="resetFilters">重置</el-button></el-form-item>
        </el-form>
      </el-card>
      <el-card shadow="never" class="watch-list-card">
        <el-table v-loading="loading" :data="result.rows" height="100%" class="watch-main-table" :default-sort="{ prop: filters.sort, order: filters.direction }" @sort-change="sortMain" stripe>
          <el-table-column prop="product_code" label="货品编号" width="145" sortable="custom" />
          <el-table-column prop="product" label="货品名称" min-width="280" sortable="custom" show-overflow-tooltip><template #default="{ row }"><el-button link @click="openDetail(row)">{{ row.product }}</el-button></template></el-table-column>
          <el-table-column prop="brand" label="品牌" width="120" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="product_type" label="分类" width="100" sortable="custom" />
          <el-table-column prop="quantity" label="近30天销量" width="125" align="right" sortable="custom"><template #header><el-tooltip :content="`当前渠道销量：${day(result.scope.sales_start)} 至 ${day(result.scope.sales_end)}，含负数退货，不等同于已发货量；不按库存仓库筛选。`"><span>近30天销量</span></el-tooltip></template><template #default="{ row }">{{ number(row.quantity) }}</template></el-table-column>
          <el-table-column prop="stock" label="总库存" width="130" align="right" sortable="custom"><template #default="{ row }">{{ number(row.stock) }}</template></el-table-column>
          <el-table-column prop="available" label="可用库存" width="130" align="right" sortable="custom"><template #default="{ row }">{{ number(row.available) }}</template></el-table-column>
          <el-table-column prop="remaining" label="当前预留数量" width="150" align="right" sortable="custom"><template #default="{ row }">{{ number(row.remaining) }}</template></el-table-column>
          <el-table-column prop="my_remaining" label="我的预留数量" width="150" align="right" sortable="custom">
            <template #header><el-tooltip content="当前渠道作为预留对象的剩余数量；包含多渠道共用预留，不代表独占库存。"><span>我的预留数量</span></el-tooltip></template>
            <template #default="{ row }"><el-button v-if="row.my_remaining != null" link @click="openDetail(row, true)">{{ number(row.my_remaining) }}</el-button><span v-else>—</span></template>
          </el-table-column>
          <el-table-column label="操作" width="90" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="openDetail(row)">详情</el-button></template></el-table-column>
          <template #empty><el-empty :description="error ? '数据加载失败' : '该渠道暂无符合条件的关注货品'"><el-button v-if="!error" type="primary" @click="openAdd">添加关注货品</el-button></el-empty></template>
        </el-table>
        <el-pagination v-model:current-page="filters.page" v-model:page-size="filters.page_size" :page-sizes="[10,20,50,100]" :total="result.pagination.total" layout="total, sizes, prev, pager, next" @current-change="apply(false)" @size-change="apply()" />
      </el-card>
    </template>

    <el-drawer v-model="adding" title="添加关注货品" size="min(1280px, 96vw)" :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving" append-to-body class="watch-add-drawer">
      <div class="watch-add-content">
      <el-tabs v-model="candidate.mode" @tab-change="changeCandidateMode"><el-tab-pane label="近30天销售排行" name="sales" /><el-tab-pane label="搜索货品添加" name="all" /></el-tabs>
      <p class="muted mode-description">{{ candidate.mode === 'sales' ? '按所选渠道近30天的销售数量或销售金额排行，勾选货品添加关注。' : '按编号、名称或品牌搜索已同步货品，近30天没有销售记录的货品也可添加。' }}</p>
      <el-form inline class="candidate-form" @submit.prevent="loadCandidates(true)">
        <el-form-item label="销量参考渠道"><el-select v-model="candidate.channel_code" multiple filterable collapse-tags collapse-tags-tooltip class="channel-select" placeholder="请选择参考渠道"><el-option v-for="c in options.channels" :key="c.code" :label="c.name" :value="c.code" /></el-select></el-form-item>
        <el-form-item v-if="candidate.mode === 'sales'" label="排行依据"><el-radio-group v-model="candidate.sort" @change="rankCandidates"><el-radio-button value="quantity">销售数量</el-radio-button><el-radio-button value="amount">销售金额</el-radio-button></el-radio-group></el-form-item>
        <el-form-item label="品牌"><el-select v-model="candidate.brand" clearable filterable placeholder="全部品牌"><el-option v-for="v in options.brands" :key="v" :value="v" :label="v" /></el-select></el-form-item>
        <el-form-item label="分类"><el-select v-model="candidate.product_type" multiple clearable collapse-tags collapse-tags-tooltip placeholder="全部分类"><el-option v-for="v in options.product_types" :key="v" :value="v" :label="v" /></el-select></el-form-item>
        <el-form-item><el-input v-model="candidate.keyword" placeholder="货品编号 / 名称 / 品牌" clearable /></el-form-item><el-form-item><el-button type="primary" native-type="submit">查询货品</el-button></el-form-item>
      </el-form>
      <p class="muted">销量日期：{{ day(candidates.scope.sales_start) }} 至 {{ day(candidates.scope.sales_end) }} · 保留负数退货，不等同于已发货量。库存“—”表示当前库存快照未找到该货品。每次最多选择200个货品、50个渠道及1000个组合。</p>
      <el-alert v-if="candidateError" :title="candidateError" type="error" :closable="false" />
      <el-table ref="candidateTable" v-loading="candidateLoading" :data="candidates.rows" row-key="product_code" height="100%" class="rounded-table candidate-data-table" @selection-change="selectionChange" @sort-change="candidateSort">
        <el-table-column type="selection" reserve-selection :selectable="() => !candidateLoading" width="45" />
        <el-table-column prop="product_code" label="货品编号" width="135" sortable="custom" />
        <el-table-column prop="product" label="货品名称" min-width="230" show-overflow-tooltip sortable="custom" />
        <el-table-column prop="brand" label="品牌" width="105" sortable="custom" show-overflow-tooltip />
        <el-table-column prop="product_type" label="分类" width="90" sortable="custom" />
        <el-table-column prop="quantity" label="近30天销量" width="125" align="right" sortable="custom"><template #default="{ row }"><el-tooltip :content="row.channel_sales.map(s => `${s.channel}：${number(s.quantity)}`).join('；') || '无所选渠道销售记录'"><span>{{ number(row.quantity) }}</span></el-tooltip></template></el-table-column>
        <el-table-column prop="amount" label="近30天销售额" width="135" align="right" sortable="custom"><template #default="{ row }">{{ amount(row.amount) }}</template></el-table-column>
        <el-table-column prop="available" label="可用库存" width="120" align="right" sortable="custom"><template #default="{ row }">{{ number(row.available) }}</template></el-table-column>
        <el-table-column label="已关注" width="95"><template #default="{ row }">{{ row.watched_channels.length }} 个渠道</template></el-table-column>
      </el-table>
      <el-pagination class="candidate-pagination" v-model:current-page="candidate.page" :page-size="candidate.page_size" :total="candidates.pagination.total" layout="total, prev, pager, next" @current-change="loadCandidates()" />
      </div>
      <template #footer><div class="add-footer"><div><span>添加到渠道</span><el-select v-model="targetChannels" multiple :multiple-limit="50" filterable collapse-tags collapse-tags-tooltip placeholder="请选择目标渠道"><el-option v-for="c in options.channels" :key="c.code" :label="c.name" :value="c.code" /></el-select></div><p>已选 {{ selected.size }} 个货品，{{ targetChannels.length }} 个渠道，预计新增 {{ newCount }} 个关注关系</p><el-button @click="adding = false" :disabled="saving">取消</el-button><el-button type="primary" :loading="saving" :disabled="candidateLoading || !selected.size || !targetChannels.length || selected.size > 200 || selected.size * targetChannels.length > 1000 || !newCount" @click="save">添加公共关注</el-button></div></template>
    </el-drawer>

    <el-drawer v-model="detailOpen" :title="detailRow ? `${detailRow.product} · ${detailRow.product_code}` : '货品详情'" size="min(1440px, 96vw)" class="watch-detail" append-to-body>
      <div class="data-times detail-times"><span>库存更新：{{ day(detail.scope?.inventory_updated_at) }}</span><span>预留更新：{{ day(detail.scope?.header_updated_at) }}</span><span>预留明细更新：{{ day(detail.scope?.detail_updated_at) }}</span></div>
      <el-alert v-if="detailError" :title="detailError" type="error" :closable="false"><el-button link @click="loadDetail">重试</el-button></el-alert>
      <section class="watch-panel"><h3>分仓库存</h3>
      <el-table v-loading="detailLoading" :data="detail.stocks" class="detail-table rounded-table" :default-sort="{ prop: 'available', order: 'descending' }">
        <el-table-column prop="warehouse" label="仓库" sortable />
        <el-table-column prop="stock" label="总库存" sortable align="right"><template #default="{ row }"><span class="quantity">{{ number(row.stock) }}</span></template></el-table-column>
        <el-table-column prop="available" label="可用库存" sortable align="right"><template #default="{ row }"><span class="quantity">{{ number(row.available) }}</span></template></el-table-column>
      </el-table>
      </section>
      <section v-for="section in reservationSections" :key="section.key" :ref="el => { if (section.key === 'mine') mineSection = el }" class="watch-panel" :class="`reservation-${section.key}`">
      <h3>{{ section.title }}</h3>
      <el-alert v-if="section.error" :title="section.error" type="error" :closable="false"><el-button link @click="section.key === 'mine' ? loadMineDetail() : loadDetail()">重试</el-button></el-alert>
      <el-table v-loading="section.loading" :data="section.data.reservations" max-height="440" class="detail-table reservation-table rounded-table" @sort-change="sortReservations(section.key, $event)">
        <el-table-column prop="number" label="预留单号" width="165" sortable="custom" />
        <el-table-column prop="status" label="状态" width="90" sortable="custom" />
        <el-table-column prop="warehouse" label="仓库" min-width="145" sortable="custom" />
        <el-table-column prop="object_name" label="预留对象" min-width="180" show-overflow-tooltip sortable="custom" />
        <el-table-column prop="remaining" label="当前货品预留数量" width="165" align="right" sortable="custom"><template #default="{ row }"><span class="quantity">{{ number(row.remaining) }}</span></template></el-table-column>
        <el-table-column prop="applied_at" label="申请时间" width="125" sortable="custom"><template #default="{ row }">{{ day(row.applied_at) }}</template></el-table-column>
        <el-table-column prop="start_time" label="使用开始时间" width="145" sortable="custom"><template #default="{ row }">{{ day(row.start_time) }}</template></el-table-column>
        <el-table-column prop="rule" label="释放方式" width="145" sortable="custom" />
        <el-table-column prop="end_time" label="使用结束时间" width="185" sortable="custom" class-name="end-time-column"><template #default="{ row }"><span class="quantity">{{ date(row.end_time) }}</span></template></el-table-column>
      </el-table>
      <el-pagination class="reservation-pagination" :current-page="section.page" :page-size="20" :total="section.data.pagination.total" layout="total, prev, pager, next" @current-change="changeReservationPage(section.key, $event)" />
      </section>
      <el-collapse class="watch-config"><el-collapse-item title="关注配置" name="config">
        <el-table :data="detailRow?.relations || []"><el-table-column prop="channel_name" label="渠道" min-width="180" /><el-table-column prop="note" label="公共备注" min-width="240" show-overflow-tooltip /><el-table-column label="操作" width="180"><template #default="{ row }"><el-button link type="primary" @click="editNote(row)">修改备注</el-button><el-button link type="danger" :disabled="mutations.has(row.id)" @click="cancelWatch(row)">取消关注</el-button></template></el-table-column></el-table>
      </el-collapse-item></el-collapse>
    </el-drawer>
  </div>
</template>

<style scoped>
.inventory-watch { display: flex; flex-direction: column; gap: 18px; height: 100%; min-height: 0; min-width: 0; }
.inventory-watch > :not(.watch-list-card) { flex-shrink: 0; }
.watch-list-card { flex: 1 1 0; min-height: 220px; }
.watch-list-card :deep(.el-card__body) { display: flex; flex-direction: column; height: 100%; min-height: 0; box-sizing: border-box; }
.watch-main-table { flex: 1 1 0; min-height: 0; width: 100%; }
.watch-list-card :deep(.el-pagination) { flex-shrink: 0; }
.watch-header { display: flex; justify-content: space-between; align-items: center; gap: 16px; }
h2 { margin: 0 0 8px; font-size: 22px; font-weight: 600; }
.watch-header p, .muted, .data-times { color: var(--el-text-color-secondary); font-size: 13px; }
.watch-header p { margin: 0; }
.header-actions { display: flex; flex-shrink: 0; }
.header-right { display: grid; justify-items: end; gap: 12px; }
.header-times, .detail-times { justify-content: flex-end; text-align: right; }
.filter-card :deep(.el-card__body) { padding-bottom: 0; }
.inventory-watch :deep(.el-form-item) { margin-right: 16px; margin-bottom: 16px; }
.inventory-watch :deep(.el-select) { width: 180px; }
.inventory-watch :deep(.channel-select) { width: 280px; }
.inventory-watch :deep(.el-input) { width: 210px; }
.channel-entry :deep(.el-form-item) { margin-bottom: 0; }
.channel-entry :deep(.channel-select) { width: 340px; }
.data-times { display: flex; flex-wrap: wrap; gap: 6px 20px; line-height: 1.7; }
.detail-table { --el-table-text-color: var(--el-text-color-secondary); --el-table-header-text-color: var(--el-text-color-secondary); }
.detail-table :deep(.el-table__body td.el-table__cell .cell) { color: #909399; }
.detail-table :deep(.quantity) { color: var(--el-text-color-primary); font-variant-numeric: tabular-nums; }
.detail-table :deep(th.end-time-column .cell) { color: var(--el-text-color-primary); }
.watch-panel { margin-top: 18px; padding: 18px; border: 1px solid var(--el-border-color-light); border-radius: 16px; background: var(--el-bg-color); min-width: 0; }
.watch-panel h3 { margin: 0 0 14px; }
.rounded-table { border: 1px solid var(--el-border-color-light); border-radius: 12px; overflow: hidden; }
.reservation-pagination { display: flex; justify-content: flex-end; margin-top: 16px; flex-wrap: wrap; }
.watch-config { margin-top: 24px; }
.inventory-watch :deep(.el-pagination) { margin-top: 18px; justify-content: flex-end; flex-wrap: wrap; }
.watch-detail :deep(.el-pagination) { margin-top: 18px; justify-content: flex-end; flex-wrap: wrap; }
.candidate-form { margin-top: 12px; }
.watch-add-content { height: 100%; min-height: 0; display: flex; flex-direction: column; gap: 12px; }
.watch-add-content > :not(.candidate-data-table) { flex-shrink: 0; }
.watch-add-content :deep(.el-tabs__header) { margin-bottom: 0; }
.watch-add-content .muted { margin: 0; }
.candidate-data-table { flex: 1 1 0; min-height: 180px; width: 100%; }
.watch-add-content .candidate-pagination { margin-top: 0; }
.watch-add-drawer :deep(.el-drawer__body) { min-height: 0; }

.watch-add-content :deep(.el-form-item) { margin-right: 16px; margin-bottom: 16px; }
.watch-add-content :deep(.el-select) { width: 180px; }
.watch-add-content :deep(.channel-select) { width: 280px; }
.watch-add-content :deep(.el-input) { width: 210px; }
.watch-add-content :deep(.el-pagination) { margin-top: 18px; justify-content: flex-end; flex-wrap: wrap; }
.add-footer > div { display: flex; align-items: center; gap: 12px; }
.add-footer :deep(.el-select) { width: min(450px, 70vw); }
.add-footer p { color: var(--el-text-color-secondary); font-size: 13px; }
h3 { margin: 24px 0 12px; font-size: 16px; }
@media (max-width: 760px) {
  .watch-add-content { height: auto; min-height: 100%; }
  .candidate-data-table { flex: none; height: 50dvh !important; }
  .watch-panel { padding: 12px; }
  .watch-header { align-items: flex-start; flex-direction: column; }
  .header-right { width: 100%; }
  .inventory-watch :deep(.el-form-item) { width: 100%; margin-right: 0; }
  .inventory-watch :deep(.el-form-item__content) { min-width: 0; }
  .inventory-watch :deep(.el-select), .inventory-watch :deep(.el-input) { width: 100%; }
  .watch-add-content :deep(.el-form-item) { width: 100%; margin-right: 0; }
  .watch-add-content :deep(.el-form-item__content) { min-width: 0; }
  .watch-add-content :deep(.el-select), .watch-add-content :deep(.el-input) { width: 100%; }
}
</style>
