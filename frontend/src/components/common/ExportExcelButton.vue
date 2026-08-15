<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { exportCurrentData, exportExcel } from '../../api/exports'
import { useAuthStore } from '../../stores/auth'

const props = defineProps({
  dataset: { type: String, default: '' },
  filters: { type: Object, default: () => ({}) },
  title: { type: String, default: '' },
  rows: { type: Array, default: null },
  columns: { type: Array, default: null },
  notes: { type: Array, default: () => [] },
  total: { type: Number, default: 0 },
  disabled: { type: Boolean, default: false },
})
const auth = useAuthStore()

const exporting = ref(false)
const exceedsLimit = computed(() => props.total > 50000)
const disabledReason = computed(() => exceedsLimit.value ? '结果超过 50,000 条，请缩小筛选范围' : '')

function filenameFromHeader(value) {
  if (!value) return `BI导出_${Date.now()}.xlsx`
  const encoded = value.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  if (encoded) return decodeURIComponent(encoded)
  return value.match(/filename="?([^";]+)"?/i)?.[1] || `BI导出_${Date.now()}.xlsx`
}

async function errorMessage(error) {
  const body = error?.response?.data
  if (body instanceof Blob) {
    try {
      const payload = JSON.parse(await body.text())
      return payload.detail || payload.message
    } catch {
      return ''
    }
  }
  return body?.detail || body?.message || error?.message
}

async function download() {
  if (exceedsLimit.value) {
    ElMessage.warning(disabledReason.value)
    return
  }
  exporting.value = true
  try {
    const response = props.dataset
      ? await exportExcel(props.dataset, props.filters)
      : await exportCurrentData({ title: props.title, rows: props.rows || [], columns: props.columns || [], filters: props.filters, notes: props.notes })
    const url = URL.createObjectURL(response.data)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filenameFromHeader(response.headers?.['content-disposition'])
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    ElMessage.success(`已导出 ${Number(props.total || 0).toLocaleString('zh-CN')} 条数据`)
  } catch (error) {
    ElMessage.error(await errorMessage(error) || 'Excel 导出失败，请稍后重试')
  } finally {
    exporting.value = false
  }
}
</script>

<template>
  <el-tooltip v-if="auth.hasPermission('data.export')" :content="disabledReason" :disabled="!exceedsLimit" placement="top">
    <span>
      <el-button :icon="'Download'" :loading="exporting" :disabled="disabled || exceedsLimit" @click="download">
        导出 Excel
      </el-button>
    </span>
  </el-tooltip>
</template>
