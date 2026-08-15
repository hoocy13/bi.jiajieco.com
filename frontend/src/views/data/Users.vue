<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getRoles } from '../../api/roles'
import { getUsers, updateUserProfile, updateUserRole, updateUserStatus } from '../../api/users'
import { useAuthStore } from '../../stores/auth'

const auth = useAuthStore()
const loading = ref(false)
const users = ref([])
const roles = ref([])
const total = ref(0)
const query = reactive({ keyword: '', role_id: null, page: 1, page_size: 20 })
const roleDialog = ref(false)
const selectedUser = ref(null)
const selectedRoleId = ref(null)
const profileDialog = ref(false)
const profileSaving = ref(false)
const profileForm = reactive({ display_name: '', email: '', phone: '' })

function formatDate(value) { return value ? new Date(`${value}Z`).toLocaleString('zh-CN', { hour12: false }) : '从未登录' }
function maskPhone(value) { return value?.length >= 7 ? `${value.slice(0, 3)}****${value.slice(-4)}` : (value || '—') }

async function fetchUsers() {
  loading.value = true
  try {
    const result = await getUsers(query)
    users.value = result.data.items
    total.value = result.data.total
  } finally { loading.value = false }
}

async function loadRoles() { roles.value = (await getRoles()).data.filter(item => item.is_active) }
function search() { query.page = 1; fetchUsers() }
function openRole(row) { selectedUser.value = row; selectedRoleId.value = row.role?.id || null; roleDialog.value = true }
function openProfile(row) {
  selectedUser.value = row
  Object.assign(profileForm, { display_name: row.display_name || '', email: row.email || '', phone: row.phone || '' })
  profileDialog.value = true
}
async function saveProfile() {
  if (!profileForm.display_name.trim()) return ElMessage.warning('请填写姓名')
  if (profileForm.email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(profileForm.email)) return ElMessage.warning('请输入有效的邮箱地址')
  profileSaving.value = true
  try {
    await updateUserProfile(selectedUser.value.id, {
      display_name: profileForm.display_name.trim(),
      email: profileForm.email.trim() || null,
      phone: profileForm.phone.trim() || null,
    })
    if (selectedUser.value.id === auth.user?.id) await auth.loadProfile()
    ElMessage.success('用户信息已更新')
    profileDialog.value = false
    await fetchUsers()
  } finally { profileSaving.value = false }
}
async function saveRole() {
  if (!selectedRoleId.value) return ElMessage.warning('请选择角色')
  await updateUserRole(selectedUser.value.id, selectedRoleId.value)
  ElMessage.success('角色已更新')
  roleDialog.value = false
  fetchUsers()
}
async function toggleStatus(row) {
  await updateUserStatus(row.id, !row.is_active)
  ElMessage.success(row.is_active ? '账号已停用' : '账号已启用')
  fetchUsers()
}

onMounted(async () => { await loadRoles(); await fetchUsers() })
</script>

<template>
  <section class="panel">
    <header><div><h2>账号权限</h2><span class="panel-source">新注册账号默认无权限，请分配角色后使用</span></div></header>
    <div class="permission-toolbar">
      <el-input v-model="query.keyword" :prefix-icon="'Search'" clearable placeholder="搜索姓名、邮箱或手机号" @keyup.enter="search" />
      <el-select v-model="query.role_id" clearable placeholder="全部角色" @change="search">
        <el-option v-for="role in roles" :key="role.id" :label="role.name" :value="role.id" />
      </el-select>
      <el-button :icon="'Search'" @click="search">查询</el-button>
      <el-button :icon="'Refresh'" @click="fetchUsers">刷新</el-button>
    </div>
    <el-table v-loading="loading" :data="users" height="560">
      <el-table-column label="用户" min-width="190"><template #default="{ row }"><strong>{{ row.display_name || row.username }}</strong><div class="cell-sub">{{ row.email || row.username }}</div></template></el-table-column>
      <el-table-column label="手机号" width="140"><template #default="{ row }">{{ maskPhone(row.phone) }}</template></el-table-column>
      <el-table-column label="当前角色" width="150"><template #default="{ row }"><span>{{ row.role?.name || '未分配' }}</span></template></el-table-column>
      <el-table-column label="最近登录" min-width="180"><template #default="{ row }">{{ formatDate(row.last_login_at) }}</template></el-table-column>
      <el-table-column label="状态" width="90"><template #default="{ row }"><span>{{ row.is_active ? '启用' : '停用' }}</span></template></el-table-column>
      <el-table-column label="操作" width="240" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="openProfile(row)">编辑资料</el-button><template v-if="row.id !== auth.user?.id"><el-button link type="primary" @click="openRole(row)">分配角色</el-button><el-button link :type="row.is_active ? 'danger' : 'primary'" @click="toggleStatus(row)">{{ row.is_active ? '停用' : '启用' }}</el-button></template></template></el-table-column>
    </el-table>
    <div class="permission-pagination"><el-pagination v-model:current-page="query.page" v-model:page-size="query.page_size" layout="total, prev, pager, next" :total="total" @current-change="fetchUsers" /></div>

    <el-dialog v-model="roleDialog" title="分配角色" width="520px">
      <div class="role-user"><strong>{{ selectedUser?.display_name }}</strong><span>{{ selectedUser?.email || selectedUser?.username }}</span></div>
      <el-radio-group v-model="selectedRoleId" class="role-options">
        <el-radio v-for="role in roles" :key="role.id" :value="role.id" border><span>{{ role.name }}</span><small>{{ role.description }}</small></el-radio>
      </el-radio-group>
      <template #footer><el-button @click="roleDialog = false">取消</el-button><el-button type="primary" @click="saveRole">保存角色</el-button></template>
    </el-dialog>

    <el-dialog v-model="profileDialog" title="编辑用户信息" width="500px">
      <el-form class="profile-form" label-position="top" @submit.prevent="saveProfile">
        <el-form-item label="姓名" required><el-input v-model="profileForm.display_name" maxlength="64" /></el-form-item>
        <el-form-item label="邮箱"><el-input v-model="profileForm.email" maxlength="255" placeholder="用于邮箱登录" /></el-form-item>
        <el-form-item label="手机号"><el-input v-model="profileForm.phone" maxlength="32" placeholder="选填" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="profileDialog = false">取消</el-button><el-button type="primary" :loading="profileSaving" @click="saveProfile">保存资料</el-button></template>
    </el-dialog>
  </section>
</template>

<style scoped>
.permission-toolbar { display: flex; align-items: center; gap: 8px; margin: 4px 0 18px; padding: 10px 12px; border: 1px solid var(--border); border-radius: 9px; background: var(--surface-soft); }
.permission-toolbar :deep(.el-input) { width: min(320px, 35vw); }
.permission-toolbar :deep(.el-select) { width: 160px; }
.permission-toolbar :deep(.el-button) { min-width: 72px; margin-left: 0; color: var(--text-soft); background: var(--surface); border-color: var(--border); }
.permission-toolbar :deep(.el-button:hover) { color: var(--accent-strong); border-color: var(--theme-soft-strong); background: var(--accent-soft); }
.cell-sub, .role-user span { margin-top: 4px; color: var(--text-soft); font-size: 12px; }
.permission-pagination { display: flex; justify-content: flex-end; padding-top: 18px; }
.role-user { display: flex; flex-direction: column; margin-bottom: 18px; }
.role-options { display: grid; gap: 10px; width: 100%; }
.role-options :deep(.el-radio) { width: 100%; height: auto; min-height: 54px; margin: 0; padding: 10px 14px; }
.role-options span, .role-options small { display: block; }
.role-options small { margin-top: 4px; color: var(--text-soft); }
.profile-form { padding: 2px 4px 0; }
@media (max-width: 760px) { .permission-toolbar { align-items: stretch; flex-direction: column; } .permission-toolbar :deep(.el-input), .permission-toolbar :deep(.el-select) { width: 100%; } }
</style>
