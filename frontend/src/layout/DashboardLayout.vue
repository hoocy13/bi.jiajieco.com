<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useRequestStatusStore } from '../stores/requestStatus'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const requestStatus = useRequestStatusStore()

const title = computed(() => route.meta.title || '经营总览')
const activeMenuPath = computed(() => (
  route.path.startsWith('/sales/brand-analysis/')
    ? '/sales/brand-analysis'
    : route.path
))

const menuGroups = [
  {
    key: 'guide',
    label: '引导看板',
    icon: 'DataBoard',
    children: [
      { path: '/dashboard', label: '经营总览' },
      { path: '/ai/decisions', label: 'AI 决策中心' },
      { path: '/ai/text-to-sql', label: '数据智能问答' },
    ],
  },
  {
    key: 'sales',
    label: '销售分析',
    icon: 'TrendCharts',
    children: [
      { path: '/sales/overview', label: '销售概览' },
      { path: '/sales/detail', label: '销售明细' },
      { path: '/sales/product-rank', label: '商品销售排行' },
      { path: '/sales/brand-analysis', label: '品牌销售分析' },
      { path: '/sales/channel-analysis', label: '渠道分析' },
    ],
  },
  {
    key: 'inventory',
    label: '库存分析',
    icon: 'Box',
    children: [
      { path: '/inventory/overview', label: '库存概览' },
      { path: '/inventory/turnover', label: '库存周转' },
      { path: '/inventory/slow-moving', label: '滞销商品' },
      { path: '/inventory/batch-expiry', label: '批次效期分析' },
      { path: '/inventory/health', label: '库存健康度' },
    ],
  },
  {
    key: 'system',
    label: '系统设置',
    icon: 'Setting',
    children: [
      { path: '/users', label: '用户管理' },
      { path: '/model-settings', label: '模型设置' },
    ],
  },
]

function logout() {
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <el-container
    class="app-shell"
    :class="{ 'is-brand-analysis': $route.path.startsWith('/sales/brand-analysis') }"
  >
    <el-aside width="252px" class="sidebar">
      <div class="brand">
        <div class="brand-mark">J</div>
        <div>
          <strong>Jiajieco BI</strong>
          <span>bi.jiajieco.com</span>
        </div>
      </div>
      <el-menu :default-active="activeMenuPath" router class="side-menu">
        <el-sub-menu v-for="group in menuGroups" :key="group.key" :index="group.key">
          <template #title>
            <el-icon><component :is="group.icon" /></el-icon>
            <span>{{ group.label }}</span>
          </template>
          <el-menu-item v-for="item in group.children" :key="item.path" :index="item.path">
            <span>{{ item.label }}</span>
          </el-menu-item>
        </el-sub-menu>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="topbar">
        <div>
          <h1>{{ title }}</h1>
        </div>
        <div class="top-actions">
          <div class="request-status" :class="{ 'is-loading': requestStatus.isLoading }">
            <el-icon v-if="requestStatus.isLoading" class="is-loading"><Loading /></el-icon>
            <el-icon v-else><Timer /></el-icon>
            <span>{{ requestStatus.statusText }}</span>
          </div>
          <el-button :icon="'Refresh'" circle />
          <el-dropdown>
            <button class="user-button">
              <el-icon><User /></el-icon>
              <span>{{ auth.user?.username || 'admin' }}</span>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item>账号信息</el-dropdown-item>
                <el-dropdown-item divided @click="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-main class="main-content">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.app-shell.is-brand-analysis {
  --accent: #e61d4f;
  --accent-strong: #c8103f;
  --accent-soft: #fff0f4;
  --nav-active: #fff0f4;
  --el-color-primary: #e61d4f;
  --el-color-primary-light-3: #ed5f82;
  --el-color-primary-light-5: #f38ea7;
  --el-color-primary-light-7: #f9bdcc;
  --el-color-primary-light-9: #fff0f4;
  --el-color-primary-dark-2: #c8103f;
  background:
    radial-gradient(circle at 46% -180px, rgb(230 29 79 / 0.08), transparent 360px),
    var(--bg);
}
</style>
