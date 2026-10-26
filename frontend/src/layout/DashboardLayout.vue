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

const menuGroups = computed(() => [
  {
    key: 'guide',
    label: '经营分析',
    icon: 'DataBoard',
    children: [
      { path: '/dashboard', label: '经营总览', permission: 'dashboard.view' },
      { path: '/reports/monthly', label: '经营月报', permission: 'report.monthly.view' },
    ],
  },
  {
    key: 'sales',
    label: '销售分析',
    icon: 'TrendCharts',
    children: [
      { path: '/sales/overview', label: '销售概览', permission: 'sales.view' },
      { path: '/sales/brand-analysis', label: '品牌销售分析', permission: 'sales.view' },
      { path: '/sales/product-rank', label: '商品销售排行', permission: 'sales.view' },
      { path: '/sales/channel-analysis', label: '渠道分析', permission: 'sales.view' },
      { path: '/sales/customer-analysis', label: '客户分析', permission: 'sales.view' },
      { path: '/sales/detail', label: '销售明细', permission: 'sales.view' },
    ],
  },
  {
    key: 'procurement',
    label: '采购分析',
    icon: 'ShoppingCart',
    children: [
      { path: '/inventory/brand-arrivals', label: '采购入库分析', permission: 'inventory.view' },
    ],
  },
  {
    key: 'group-buy',
    label: '团购管理',
    icon: 'ShoppingBag',
    children: [
      { path: '/group-buy', label: '团购订单与分配', permission: 'group_buy.manage' },
      { path: '/group-buy/inbound', label: '采购入库关联', permission: 'group_buy.manage' },
    ],
  },
  {
    key: 'inventory',
    label: '库存分析',
    icon: 'Box',
    children: [
      { path: '/inventory/overview', label: '库存概览', permission: 'inventory.view' },
      { path: '/inventory/brand-inventory-flow', label: '品牌进销存', permission: 'inventory.view' },
      { path: '/inventory/turnover', label: '品牌周转', permission: 'inventory.view' },
      { path: '/inventory/health', label: '库存健康度', permission: 'inventory.view' },
      { path: '/inventory/slow-moving', label: '滞销分析', permission: 'inventory.view' },
      { path: '/inventory/batch-expiry', label: '批次效期分析', permission: 'inventory.view' },
      { path: '/inventory/reservations', label: '预留单分析', permission: 'inventory.view' },
      { path: '/inventory/detail', label: '库存明细', permission: 'inventory.view' },
    ],
  },
  {
    key: 'finance',
    label: '财务分析',
    icon: 'Wallet',
    children: [
      { path: '/sales/profit-analysis', label: '销售毛利与价格分析', permission: 'sales.profit.view' },
      { path: '/inventory/valuation', label: '库存价格估算', permission: 'inventory.view' },
    ],
  },
  {
    key: 'intelligence',
    label: '数据智能',
    icon: 'Cpu',
    children: [
      { path: '/ai/decisions', label: '智能洞察', permission: 'ai.decision.view' },
      { path: '/ai/query', label: '智能问数', permissionsAny: ['ai.text_to_sql.use', 'ai.assistant.use'] },
      { path: '/ai/analysis', label: '分析工作台', permission: 'ai.decision.view' },
    ],
  },
  {
    key: 'system',
    label: '系统管理',
    icon: 'Setting',
    children: [
      { path: '/users', label: '账号权限', permission: 'system.users.manage' },
      { path: '/roles', label: '角色管理', permission: 'system.roles.manage' },
      { path: '/model-settings', label: '模型设置', permission: 'system.models.manage' },
      { path: '/announcements', label: '系统公告', permission: 'system.announcements.manage' },
      { path: '/reports/monthly-management', label: '月报管理', permission: 'report.monthly.manage' },
    ],
  },
].map(group => ({
  ...group,
  children: group.children.filter(item => (
    item.permissionsAny
      ? item.permissionsAny.some(permission => auth.hasPermission(permission))
      : auth.hasPermission(item.permission)
  )),
}))
  .filter(group => group.children.length))

const defaultOpenGroups = computed(() => menuGroups.value
  .filter(group => group.key !== 'system')
  .map(group => group.key))

function logout() {
  auth.logout()
  router.push('/login')
}

function selectTheme(name) {
  theme.apply(name)
}

function selectAppearance(name) {
  theme.applyAppearance(name)
}
</script>

<template>
  <el-container
    class="app-shell"
    :class="{ 'is-group-buy': $route.path.startsWith('/group-buy'), 'is-brand-analysis': $route.path.startsWith('/sales/brand-analysis'), 'is-sales-profit': $route.path === '/sales/profit-analysis' }"
  >
    <el-aside width="252px" class="sidebar">
      <div class="brand">
        <div class="brand-mark">BI</div>
      </div>
      <el-menu :default-active="activeMenuPath" :default-openeds="defaultOpenGroups" router class="side-menu">
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
          <el-dropdown trigger="click" @command="selectAppearance">
            <button class="theme-button" aria-label="选择外观模式">
              <el-icon><component :is="theme.isDark ? 'Moon' : 'Sunny'" /></el-icon>
              <span>{{ theme.appearanceOptions.find(option => option.name === theme.appearance)?.label }}</span>
              <el-icon><ArrowDown /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item v-for="option in theme.appearanceOptions" :key="option.name" :command="option.name" :class="{ 'is-selected-theme': option.name === theme.appearance }">
                  <el-icon><component :is="option.icon" /></el-icon>
                  {{ option.label }}
                  <el-icon v-if="option.name === theme.appearance"><Check /></el-icon>
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-button :icon="'Refresh'" circle />
          <el-dropdown>
            <button class="user-button">
              <el-icon><User /></el-icon>
              <span>{{ auth.user?.display_name || auth.user?.email || auth.user?.username || '用户' }}</span>
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
        <router-view :key="$route.path.startsWith('/group-buy') ? $route.path : `${$route.fullPath}-${theme.name}-${theme.resolvedAppearance}`" />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.app-shell.is-group-buy{height:100dvh;min-height:0;overflow:hidden}
.is-group-buy>.el-container{height:100%;min-width:0;min-height:0}
.is-group-buy .sidebar{height:100%;min-height:0;overflow-y:auto}
.is-group-buy .topbar{flex-shrink:0;min-width:0}
.is-group-buy .main-content{display:flex;flex-direction:column;min-width:0;min-height:0;overflow:auto;overscroll-behavior:contain}
.theme-button { display: inline-flex; align-items: center; gap: 8px; min-height: 32px; padding: 0 10px; color: var(--text-soft); background: var(--surface); border: 1px solid var(--border); border-radius: 7px; font: inherit; font-size: 12px; font-weight: 700; cursor: pointer; }
.theme-button:hover { color: var(--accent-strong); border-color: var(--theme-soft-strong); background: var(--accent-soft); }
.theme-swatch, .theme-option-swatch { display: inline-block; width: 10px; height: 10px; flex: 0 0 auto; border-radius: 50%; box-shadow: 0 0 0 1px rgb(23 24 28 / 12%); }
.theme-option-swatch { margin-right: 8px; }
:global(.el-dropdown-menu__item.is-selected-theme) { color: var(--accent-strong); font-weight: 700; background: var(--accent-soft); }
@media (max-width: 960px) {
  .is-sales-profit .topbar { height: auto; min-height: 68px; flex-wrap: wrap; gap: 10px; padding: 12px 18px; }
  .is-sales-profit .topbar > div:first-child { flex-basis: 100%; min-width: 0; }
  .is-sales-profit .topbar h1 { font-size: 17px; line-height: 1.5; }
  .is-sales-profit .top-actions { flex-wrap: wrap; gap: 6px; max-width: 100%; }
  .is-sales-profit .top-actions > * { flex-shrink: 0; }
  .is-sales-profit .theme-button, .is-sales-profit .user-button { white-space: nowrap; }
}
</style>


