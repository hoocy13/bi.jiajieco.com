<script setup>
import { useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth'

const auth = useAuthStore()
const router = useRouter()
function logout() { auth.logout(); router.push('/login') }
</script>

<template>
  <section class="panel pending-panel">
    <el-icon class="pending-icon"><Lock /></el-icon>
    <h2>账号等待授权</h2>
    <p>你的账号已经注册成功，目前还没有 BI 页面访问权限。</p>
    <div class="pending-account">{{ auth.user?.display_name }} · {{ auth.user?.email || auth.user?.username }}</div>
    <p>请联系管理员在“账号权限”中为你分配角色，授权后刷新页面即可生效。</p>
    <el-button type="primary" @click="auth.loadProfile()">刷新权限</el-button>
    <el-button @click="logout">退出登录</el-button>
  </section>
</template>

<style scoped>
.pending-panel { max-width: 680px; margin: 10vh auto; padding: 56px; text-align: center; }
.pending-icon { width: 64px; height: 64px; margin-bottom: 18px; border-radius: 18px; color: var(--accent-strong); background: var(--accent-soft); font-size: 30px; }
.pending-panel p { color: var(--text-soft); line-height: 1.8; }
.pending-account { display: inline-block; margin: 14px 0; padding: 10px 16px; border-radius: 8px; background: var(--surface-soft); font-weight: 700; }
</style>
