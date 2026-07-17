<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { createUser, getUsers, updateUserStatus } from '../../api/users'

const loading = ref(false)
const saving = ref(false)
const createDialogVisible = ref(false)
const users = ref([])
const form = ref({
  username: '',
  password: '',
})

async function fetchUsers() {
  loading.value = true
  try {
    const result = await getUsers()
    users.value = result.data || []
  } finally {
    loading.value = false
  }
}

async function toggleStatus(row) {
  const nextStatus = !row.is_active
  await updateUserStatus(row.id, nextStatus)
  row.is_active = nextStatus
  ElMessage.success(nextStatus ? '已启用' : '已停用')
}

function openCreateDialog() {
  form.value = { username: '', password: '' }
  createDialogVisible.value = true
}

async function submitCreateUser() {
  const username = form.value.username.trim()
  if (!username || !form.value.password) {
    ElMessage.warning('请填写用户名和密码')
    return
  }
  saving.value = true
  try {
    await createUser({ username, password: form.value.password })
    ElMessage.success('用户已创建')
    createDialogVisible.value = false
    await fetchUsers()
  } finally {
    saving.value = false
  }
}

onMounted(fetchUsers)
</script>

<template>
  <section class="panel">
    <header>
      <h2>用户管理</h2>
      <div class="panel-actions">
        <el-button type="primary" :icon="'Plus'" @click="openCreateDialog">新增用户</el-button>
        <el-button :icon="'Refresh'" circle @click="fetchUsers" />
      </div>
    </header>
    <el-table v-loading="loading" :data="users" height="560">
      <el-table-column prop="id" label="ID" width="90" />
      <el-table-column prop="username" label="用户名" />
      <el-table-column prop="is_active" label="状态" width="140">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'">
            {{ row.is_active ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="150">
        <template #default="{ row }">
          <el-button
            :type="row.is_active ? 'danger' : 'primary'"
            size="small"
            link
            @click="toggleStatus(row)"
          >
            {{ row.is_active ? '停用' : '启用' }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="createDialogVisible" title="新增用户" width="420px">
      <el-form class="compact-form" label-position="top" @submit.prevent="submitCreateUser">
        <el-form-item label="用户名">
          <el-input v-model="form.username" autocomplete="off" placeholder="请输入用户名" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="form.password"
            autocomplete="new-password"
            placeholder="至少 8 位"
            show-password
            type="password"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitCreateUser">保存</el-button>
      </template>
    </el-dialog>
  </section>
</template>
