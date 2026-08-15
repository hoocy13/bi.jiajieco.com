<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createRole, deleteRole, getPermissions, getRoles, updateRole } from '../../api/roles'

const roles = ref([])
const permissions = ref([])
const loading = ref(false)
const dialogVisible = ref(false)
const editing = ref(null)
const form = reactive({ name: '', description: '', permission_codes: [] })
const moduleLabels = { dashboard: '经营总览', sales: '销售分析', inventory: '库存分析', ai: 'AI 功能', operation: '操作权限', system: '系统管理' }
const permissionGroups = computed(() => Object.entries(permissions.value.reduce((groups, item) => { (groups[item.module] ||= []).push(item); return groups }, {})))

async function fetchData() {
  loading.value = true
  try { [roles.value, permissions.value] = await Promise.all([getRoles().then(r => r.data), getPermissions().then(r => r.data)]) }
  finally { loading.value = false }
}
function openCreate() { editing.value = null; Object.assign(form, { name: '', description: '', permission_codes: [] }); dialogVisible.value = true }
function openEdit(role) { editing.value = role; Object.assign(form, { name: role.name, description: role.description, permission_codes: role.permissions.map(item => item.code) }); dialogVisible.value = true }
async function save() {
  if (!form.name) return ElMessage.warning('请填写角色名称')
  const payload = { name: form.name, description: form.description, permission_codes: form.permission_codes }
  if (editing.value) await updateRole(editing.value.id, payload)
  else await createRole(payload)
  ElMessage.success(editing.value ? '角色权限已更新' : '角色已创建')
  dialogVisible.value = false
  fetchData()
}

async function removeRole(role) {
  await ElMessageBox.confirm(`确定删除角色“${role.name}”吗？`, '删除角色', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
  await deleteRole(role.id)
  ElMessage.success('角色已删除')
  fetchData()
}

onMounted(fetchData)
</script>

<template>
  <section class="panel">
    <header><div><h2>角色管理</h2><span class="panel-source">角色统一控制页面和操作权限</span></div><el-button type="primary" :icon="'Plus'" @click="openCreate">新建角色</el-button></header>
    <el-table v-loading="loading" :data="roles" height="590">
      <el-table-column label="编号" width="90"><template #default="{ row }"><span class="role-number">{{ row.role_no }}</span></template></el-table-column>
      <el-table-column label="角色" min-width="160"><template #default="{ row }"><strong>{{ row.name }}</strong></template></el-table-column>
      <el-table-column prop="description" label="说明" min-width="240" />
      <el-table-column prop="user_count" label="用户数" width="100" />
      <el-table-column label="权限" min-width="300"><template #default="{ row }"><span class="permission-summary">{{ row.permissions.length ? `${row.permissions.slice(0, 4).map(item => item.name).join('、')}${row.permissions.length > 4 ? ` 等 ${row.permissions.length} 项` : ''}` : '无权限' }}</span></template></el-table-column>
      <el-table-column label="类型" width="110"><template #default="{ row }">{{ row.is_system ? '系统预置' : '自定义' }}</template></el-table-column>
      <el-table-column label="操作" width="150"><template #default="{ row }"><el-button v-if="!['pending', 'admin'].includes(row.code)" link type="primary" @click="openEdit(row)">编辑权限</el-button><el-button v-if="!row.is_system && row.user_count === 0" link type="danger" @click="removeRole(row)">删除</el-button></template></el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="editing ? '编辑角色' : '新建角色'" width="680px">
      <el-form label-position="top">
        <el-form-item label="角色名称"><el-input v-model="form.name" placeholder="例如：运营专员" /></el-form-item>
        <el-form-item label="角色说明"><el-input v-model="form.description" /></el-form-item>
        <el-form-item label="权限配置">
          <div class="permission-list">
            <el-checkbox-group v-model="form.permission_codes">
              <section v-for="[module, items] in permissionGroups" :key="module" class="permission-section">
                <div class="permission-section__title">{{ moduleLabels[module] || module }}</div>
                <el-checkbox v-for="item in items" :key="item.code" :value="item.code">{{ item.name }}</el-checkbox>
              </section>
            </el-checkbox-group>
          </div>
        </el-form-item>
      </el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" @click="save">保存角色</el-button></template>
    </el-dialog>
  </section>
</template>

<style scoped>
.cell-sub { margin-top: 4px; color: var(--text-soft); font-size: 12px; }
.role-number { color: var(--accent-strong); font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-weight: 700; letter-spacing: .04em; }
.permission-summary { color: var(--text-soft); line-height: 1.5; }
.permission-list { width: 100%; overflow: hidden; border: 1px solid var(--border); border-radius: 9px; background: var(--surface); }
.permission-list :deep(.el-checkbox-group) { display: block; }
.permission-section { display: grid; grid-template-columns: 130px repeat(2, minmax(0, 1fr)); align-items: center; min-height: 48px; padding: 7px 14px; border-bottom: 1px solid var(--border); }
.permission-section:last-child { border-bottom: 0; }
.permission-section__title { color: var(--text-soft); font-size: 12px; font-weight: 700; }
.permission-section :deep(.el-checkbox) { margin-right: 14px; }
@media (max-width: 680px) { .permission-section { grid-template-columns: 1fr; gap: 6px; padding: 12px 14px; } }
</style>
