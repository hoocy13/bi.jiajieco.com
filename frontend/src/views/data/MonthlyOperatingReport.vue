<script setup>
import { nextTick, onMounted, ref } from 'vue'
import { Download, Printer } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { getMonthlyReport, getMonthlyReports } from '../../api/reports'
import MonthlyReportSummary from '../../components/reports/MonthlyReportSummary.vue'
import MonthlyReportChannelDetails from '../../components/reports/MonthlyReportChannelDetails.vue'
import MonthlyReportConclusion from '../../components/reports/MonthlyReportConclusion.vue'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const exporting = ref(false)
const months = ref([])
const selectedMonth = ref('')
const report = ref(null)
const summary = ref(null)
const details = ref(null)
const conclusion = ref(null)
function printReport() { window.print() }
async function loadReport(month) {
  if (!month) return
  loading.value = true
  try {
    report.value = (await getMonthlyReport(month)).data
    selectedMonth.value = month
    const query = { ...route.query, month }
    delete query.channel_group
    await router.replace({ query })
  } finally { loading.value = false }
}
async function downloadPdf() {
  exporting.value = true
  const roots = [summary.value?.$el, details.value?.$el, conclusion.value?.$el].filter(Boolean)
  roots.forEach(root => root.classList.add('is-exporting'))
  try {
    await nextTick()
    const { exportMonthlyReportPdf } = await import('../../utils/monthlyReportPdf')
    await exportMonthlyReportPdf(roots, `${selectedMonth.value.replace('-', '年')}月经营月报.pdf`)
    ElMessage.success('PDF 已下载')
  } catch (error) { ElMessage.error(error?.message || 'PDF 生成失败') }
  finally { roots.forEach(root => root.classList.remove('is-exporting')); exporting.value = false }
}
onMounted(async () => {
  months.value = (await getMonthlyReports()).data || []
  const month = String(route.query.month || '')
  await loadReport(months.value.some(item => item.month === month) ? month : months.value[0]?.month)
})
</script>

<template>
  <div class="monthly-report-page" v-loading="loading">
    <section class="report-toolbar no-print">
      <div><span>月份</span><el-select v-model="selectedMonth" :disabled="exporting" placeholder="选择月份" @change="loadReport"><el-option v-for="item in months" :key="item.month" :label="item.month" :value="item.month" /></el-select></div>
      <div class="toolbar-actions"><el-button type="primary" :icon="Download" :loading="exporting" :disabled="loading || !report?.artifact" @click="downloadPdf">下载 PDF</el-button><el-button :icon="Printer" @click="printReport">打印</el-button></div>
    </section>
    <MonthlyReportSummary v-if="report?.artifact" ref="summary" :artifact="report.artifact" :month="selectedMonth" />
    <MonthlyReportChannelDetails v-if="report?.artifact" ref="details" :artifact="report.artifact" :month="selectedMonth" />
    <MonthlyReportConclusion v-if="report?.artifact" ref="conclusion" :artifact="report.artifact" :month="selectedMonth" />
    <el-empty v-else-if="!loading" description="暂无已发布月报" />
  </div>
</template>

<style scoped>
.monthly-report-page { display: grid; gap: 16px; min-width: 0; }
.report-toolbar { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; padding: 12px 16px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); }
.report-toolbar > div { display: flex; align-items: center; gap: 10px; } .report-toolbar span { font-size: 16px; color: var(--muted); } .report-toolbar .el-select { width: 150px; }
@media (max-width: 640px) {
 :global(body:has(.monthly-report-page)) { min-width: 0; }
 :global(.app-shell:has(.monthly-report-page) .topbar) { height: auto; flex-wrap: wrap; gap: 10px; padding: 12px 18px; }
 :global(.app-shell:has(.monthly-report-page) .topbar > div:first-child) { flex-basis: 100%; min-width: 0; }
 :global(.app-shell:has(.monthly-report-page) .topbar h1) { font-size: 20px; white-space: nowrap; }
 :global(.app-shell:has(.monthly-report-page) .top-actions) { flex-wrap: wrap; gap: 6px; max-width: 100%; }
 :global(.app-shell:has(.monthly-report-page) .top-actions > *) { flex-shrink: 0; }
 :global(.app-shell:has(.monthly-report-page) .theme-button), :global(.app-shell:has(.monthly-report-page) .user-button) { white-space: nowrap; }
 .report-toolbar { align-items: stretch; flex-direction: column; } .toolbar-actions { flex-wrap: wrap; }
}
@media print {
 :global(.sidebar), :global(.topbar), .no-print { display: none !important; }
 :global(.main-content) { padding: 0 !important; } :global(body), :global(#app), :global(.app-shell) { background: #fff !important; }
 @page { size: A4 portrait; margin: 10mm; }
}
</style>
