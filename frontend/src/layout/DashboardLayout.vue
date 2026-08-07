<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useRequestStatusStore } from '../stores/requestStatus'
import { useThemeStore } from '../stores/theme'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const requestStatus = useRequestStatusStore()
const theme = useThemeStore()
theme.initialize()

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
      { path: '/ai/assistant', label: 'AI 数据助手' },
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
      { path: '/inventory/brand-arrivals', label: '品牌月度到货' },
      { path: '/inventory/brand-inventory-flow', label: '品牌进销存' },
      { path: '/inventory/turnover', label: '品牌周转' },
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

function selectTheme(name) {
  theme.apply(name)
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
          <el-dropdown trigger="click" @command="selectTheme">
            <button class="theme-button" aria-label="选择网页色调">
              <span class="theme-swatch" :style="{ background: theme.current.primary }"></span>
              <span>{{ theme.current.label }}</span>
              <el-icon><ArrowDown /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item v-for="option in theme.options" :key="option.name" :command="option.name" :class="{ 'is-selected-theme': option.name === theme.name }">
                  <span class="theme-option-swatch" :style="{ background: option.primary }"></span>
                  {{ option.label }}
                  <el-icon v-if="option.name === theme.name"><Check /></el-icon>
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
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
        <router-view :key="`${$route.fullPath}-${theme.name}`" />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.theme-button { display: inline-flex; align-items: center; gap: 8px; min-height: 32px; padding: 0 10px; color: var(--text-soft); background: var(--surface); border: 1px solid var(--border); border-radius: 7px; font: inherit; font-size: 12px; font-weight: 700; cursor: pointer; }
.theme-button:hover { color: var(--accent-strong); border-color: var(--theme-soft-strong); background: var(--accent-soft); }
.theme-swatch, .theme-option-swatch { display: inline-block; width: 10px; height: 10px; flex: 0 0 auto; border-radius: 50%; box-shadow: 0 0 0 1px rgb(23 24 28 / 12%); }
.theme-option-swatch { margin-right: 8px; }
:global(.el-dropdown-menu__item.is-selected-theme) { color: var(--accent-strong); font-weight: 700; background: var(--accent-soft); }
</style>


