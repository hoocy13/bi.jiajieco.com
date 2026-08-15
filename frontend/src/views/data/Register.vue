<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { register } from '../../api/auth'

const router = useRouter()
const loading = ref(false)
const form = reactive({ email: '', display_name: '', phone: '', password: '', confirmPassword: '' })

async function submit() {
  if (!form.email || !form.display_name || !form.password) return ElMessage.warning('请填写邮箱、用户名和密码')
  if (form.password.length < 8) return ElMessage.warning('密码至少 8 位')
  if (form.password !== form.confirmPassword) return ElMessage.warning('两次输入的密码不一致')
  loading.value = true
  try {
    await register({ email: form.email, display_name: form.display_name, phone: form.phone || null, password: form.password })
    ElMessage.success('注册成功，请登录并等待管理员授权')
    router.push('/login')
  } finally { loading.value = false }
}
</script>

<template>
  <main class="login-hero register-page">
    <div class="login-hero__shell">
      <header class="login-nav login-nav--simple"><div class="login-nav__logo">Jiajieco BI</div></header>
      <section class="register-shell">
        <section class="login-card register-card">
          <div class="login-card__head"><h2>注册 BI 账号</h2><p>注册后由管理员分配访问角色</p></div>
          <el-form class="login-form" label-position="top" @submit.prevent="submit">
            <el-form-item label="邮箱"><el-input v-model="form.email" size="large" autocomplete="email" placeholder="name@company.com" /></el-form-item>
            <el-form-item label="用户名"><el-input v-model="form.display_name" size="large" placeholder="请输入用户名" /></el-form-item>
            <el-form-item label="手机号（选填）"><el-input v-model="form.phone" size="large" /></el-form-item>
            <div class="register-passwords">
              <el-form-item label="密码"><el-input v-model="form.password" size="large" type="password" show-password autocomplete="new-password" /></el-form-item>
              <el-form-item label="确认密码"><el-input v-model="form.confirmPassword" size="large" type="password" show-password autocomplete="new-password" /></el-form-item>
            </div>
            <el-button type="primary" size="large" :loading="loading" @click="submit">注册账号</el-button>
            <el-button link @click="router.push('/login')">已有账号，返回登录</el-button>
          </el-form>
        </section>
      </section>
    </div>
  </main>
</template>

<style scoped>
.register-page { min-height: 100vh; background: linear-gradient(135deg, #f8f3f5, #eef5f1); }
.register-shell { min-height: calc(100vh - 88px); display: grid; place-items: center; padding: 32px; }
.register-card { width: min(620px, 100%); padding: 34px; background: rgb(255 255 255 / 92%); }
.login-card__head p { margin: 8px 0 20px; color: var(--text-soft); }
.register-passwords { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
@media (max-width: 640px) { .register-passwords { grid-template-columns: 1fr; gap: 0; } }
</style>
