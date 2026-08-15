<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createAnnouncement, deleteAnnouncement, getAnnouncements, updateAnnouncement } from '../../api/announcements'

const items = ref([])
const loading = ref(false)
const dialogVisible = ref(false)
const saving = ref(false)
const editing = ref(null)
const form = reactive({ title: '', content: '', is_active: true })
const filters = reactive({ status: 'active' })

function formatDate(value) { return value ? new Date(`${value}Z`).toLocaleString('zh-CN', { hour12: false }) : '' }
async function fetchItems() { loading.value = true; try { items.value = (await getAnnouncements(filters)).data } finally { loading.value = false } }
function rowClassName({ row }) { return row.is_active ? '' : 'is-inactive-announcement' }
function openCreate() { editing.value = null; Object.assign(form, { title: '', content: '', is_active: true }); dialogVisible.value = true }
function openEdit(row) { editing.value = row; Object.assign(form, { title: row.title, content: row.content, is_active: row.is_active }); dialogVisible.value = true }
async function save() {
  if (!form.title.trim() || !form.content.trim()) return ElMessage.warning('请填写公告标题和内容')
  saving.value = true
  try {
    const payload = { title: form.title.trim(), content: form.content.trim(), is_active: form.is_active }
    if (editing.value) await updateAnnouncement(editing.value.id, payload)
    else await createAnnouncement(payload)
    ElMessage.success(editing.value ? '公告已更新' : '公告已创建')
    dialogVisible.value = false
    fetchItems()
  } finally { saving.value = false }
}
async function toggle(row) { await updateAnnouncement(row.id, { title: row.title, content: row.content, is_active: !row.is_active }); ElMessage.success(row.is_active ? '公告已停用' : '公告已启用'); fetchItems() }
async function remove(row) { await ElMessageBox.confirm(`确定删除公告“${row.title}”吗？`, '删除公告', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }); await deleteAnnouncement(row.id); ElMessage.success('公告已删除'); fetchItems() }
onMounted(fetchItems)
</script>

<template>
  <section class="panel">
    <header><div><h2>系统公告</h2><span class="panel-source">启用的公告会显示在经营总览顶部</span></div><el-button type="primary" :icon="'Plus'" @click="openCreate">新增公告</el-button></header>
    <div class="announcement-toolbar">
      <span>状态</span>
      <el-select v-model="filters.status" @change="fetchItems">
        <el-option label="启用" value="active" />
        <el-option label="停用" value="inactive" />
        <el-option label="全部" value="all" />
      </el-select>
      <el-button :icon="'Refresh'" @click="fetchItems">刷新</el-button>
    </div>
    <el-table v-loading="loading" :data="items" :row-class-name="rowClassName" height="540">
      <el-table-column prop="title" label="标题" min-width="200" />
      <el-table-column prop="content" label="内容" min-width="360" show-overflow-tooltip />
      <el-table-column label="状态" width="90"><template #default="{ row }">{{ row.is_active ? '启用' : '停用' }}</template></el-table-column>
      <el-table-column label="更新时间" width="180"><template #default="{ row }">{{ formatDate(row.updated_at) }}</template></el-table-column>
      <el-table-column label="操作" width="190"><template #default="{ row }"><el-button link type="primary" @click="openEdit(row)">编辑</el-button><el-button link type="primary" @click="toggle(row)">{{ row.is_active ? '停用' : '启用' }}</el-button><el-button link type="danger" @click="remove(row)">删除</el-button></template></el-table-column>
    </el-table>
    <el-dialog v-model="dialogVisible" :title="editing ? '编辑公告' : '新增公告'" width="600px">
      <el-form label-position="top" @submit.prevent="save">
        <el-form-item label="公告标题" required><el-input v-model="form.title" maxlength="120" show-word-limit /></el-form-item>
        <el-form-item label="公告内容" required><el-input v-model="form.content" type="textarea" :rows="6" maxlength="2000" show-word-limit /></el-form-item>
        <el-form-item label="立即启用"><el-switch v-model="form.is_active" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存公告</el-button></template>
    </el-dialog>
  </section>
</template>

<style scoped>
.announcement-toolbar { display: flex; align-items: center; gap: 10px; margin: 4px 0 18px; padding: 10px 12px; border: 1px solid var(--border); border-radius: 9px; background: var(--surface-soft); color: var(--text-soft); font-size: 13px; }
.announcement-toolbar :deep(.el-select) { width: 140px; }
.announcement-toolbar :deep(.el-button) { margin-left: 0; }
:deep(.el-table__row.is-inactive-announcement) { color: var(--text-soft); background: var(--surface-soft); }
:deep(.el-table__row.is-inactive-announcement td.el-table__cell) { background: transparent; opacity: .68; }
</style>
