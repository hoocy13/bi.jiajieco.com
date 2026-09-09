<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, DocumentAdd, Download, Refresh, Upload, View } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import { deleteMonthlyReportVersion, downloadMonthlyReportVersion, generateMonthlyReport, getMonthlyReportManagement, publishMonthlyReport } from '../../api/reports'

const router = useRouter()

const loading = ref(false)
const generating = ref(false)
const now = new Date()
const lastCompletedMonth = new Date(now.getFullYear(), now.getMonth() - 1, 1)
const selectedMonth = ref(`${lastCompletedMonth.getFullYear()}-${String(lastCompletedMonth.getMonth() + 1).padStart(2, '0')}`)
const rows = ref([])

function disableIncompleteMonth(date) {
  return date >= new Date(now.getFullYear(), now.getMonth(), 1)
}

function errorMessage(error) {
  const detail = error?.response?.data?.detail
  return detail?.message || detail || error?.response?.data?.message || error?.message || '月报生成失败'
}

function formatTime(value) {
  return value ? String(value).replace('T', ' ').slice(0, 16) : '-'
}

async function fetchRows() {
  loading.value = true
  try {
    const result = await getMonthlyReportManagement()
    rows.value = result.data || []
  } finally {
    loading.value = false
  }
}

async function generateDraft() {
  if (!selectedMonth.value) return ElMessage.warning('请选择已经结束的报告月份')
  await ElMessageBox.confirm(
    `将读取已发布ADS数据并计算一次 ${selectedMonth.value} 月报，生成后先保存为草稿。`,
    '生成月报草稿',
    { confirmButtonText: '开始生成', cancelButtonText: '取消', type: 'warning' },
  )
  generating.value = true
  try {
    const result = await generateMonthlyReport(selectedMonth.value)
    ElMessage.success(`${result.data.month} V${result.data.revision} 草稿已生成`)
    await fetchRows()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    generating.value = false
  }
}

async function publish(row) {
  await ElMessageBox.confirm(
    `确认发布 ${row.month} V${row.revision}？发布后查看、下载和打印均读取这份快照。`,
    '发布经营月报',
    { confirmButtonText: '确认发布', cancelButtonText: '取消', type: 'warning' },
  )
  await publishMonthlyReport(row.month, row.revision)
  ElMessage.success('月报已发布')
  await fetchRows()
}

function viewReport(row) {
  router.push({ path: '/reports/monthly', query: { month: row.month } })
}

async function downloadVersion(row) {
  const response = await downloadMonthlyReportVersion(row.month, row.revision)
  const url = URL.createObjectURL(response.data)
  const link = document.createElement('a')
  link.href = url
  link.download = `${row.month.replace('-', '年')}月经营月报-V${row.revision}.pdf`
  link.click()
  URL.revokeObjectURL(url)
}

async function remove(row) {
  const publishedWarning = row.status === 'published' ? '删除后，该版本将不能继续查看或下载。' : '删除后无法恢复。'
  await ElMessageBox.confirm(
    `确认删除 ${row.month} V${row.revision}？${publishedWarning}本操作不会删除经营源数据。`,
    '删除月报版本',
    { confirmButtonText: '确认删除', cancelButtonText: '取消', type: 'warning' },
  )
  await deleteMonthlyReportVersion(row.month, row.revision)
  ElMessage.success(`${row.month} V${row.revision} 已删除`)
  await fetchRows()
}

onMounted(fetchRows)
</script>

<template>
  <div class="management-page">
    <section class="management-toolbar">
      <div>
        <h2>月报生成与发布</h2>
        <p>生成时计算一次并保存草稿；发布、查看、PDF下载和打印不再计算指标。</p>
      </div>
      <div class="toolbar-actions">
        <el-date-picker
          v-model="selectedMonth"
          type="month"
          value-format="YYYY-MM"
          placeholder="选择已结束月份"
          :disabled-date="disableIncompleteMonth"
        />
        <el-button :icon="Refresh" @click="fetchRows">刷新</el-button>
        <el-button type="primary" :icon="DocumentAdd" :loading="generating" @click="generateDraft">生成草稿</el-button>
      </div>
    </section>

    <section class="management-panel">
      <el-table v-loading="loading" :data="rows" stripe>
        <el-table-column prop="month" label="报告月份" width="130" sortable />
        <el-table-column prop="revision" label="版本" width="90" sortable><template #default="{ row }">V{{ row.revision }}</template></el-table-column>
        <el-table-column label="状态" width="110"><template #default="{ row }"><el-tag :type="row.status === 'published' ? 'success' : 'warning'">{{ row.status === 'published' ? '已发布' : '草稿' }}</el-tag></template></el-table-column>
        <el-table-column label="PDF" width="100"><template #default="{ row }">{{ row.pdf_available ? '已生成' : '不可用' }}</template></el-table-column>
        <el-table-column label="生成时间" width="170"><template #default="{ row }">{{ formatTime(row.generated_at) }}</template></el-table-column>
        <el-table-column prop="sales_data_version" label="销售数据版本" min-width="260" show-overflow-tooltip />
        <el-table-column prop="inventory_data_version" label="库存数据版本" min-width="260" show-overflow-tooltip />
        <el-table-column label="操作" width="300" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status === 'published'" link type="primary" :icon="View" @click="viewReport(row)">查看</el-button>
            <el-button v-if="row.pdf_available" link type="primary" :icon="Download" @click="downloadVersion(row)">下载</el-button>
            <el-button v-if="row.status === 'draft'" link type="primary" :icon="Upload" @click="publish(row)">发布</el-button>
            <el-button link type="danger" :icon="Delete" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<style scoped>
.management-page { display: grid; gap: 16px; }.management-toolbar, .management-panel { border: 1px solid var(--border); border-radius: 8px; background: var(--surface); box-shadow: var(--shadow); }.management-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 18px 20px; }.management-toolbar h2 { margin: 0; font-size: 18px; }.management-toolbar p { margin: 7px 0 0; color: var(--muted); font-size: 12px; }.toolbar-actions { display: flex; gap: 8px; align-items: center; }.management-panel { overflow: hidden; }
@media (max-width: 900px) { .management-toolbar { align-items: stretch; flex-direction: column; }.toolbar-actions { flex-wrap: wrap; } }
</style>
