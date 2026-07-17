import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import DashboardLayout from '../layout/DashboardLayout.vue'
import Login from '../views/data/Login.vue'
import Dashboard from '../views/data/Dashboard.vue'
import SalesOverview from '../views/data/SalesOverview.vue'
import Sales from '../views/data/Sales.vue'
import ProductRank from '../views/data/ProductRank.vue'
import BrandAnalysis from '../views/data/BrandAnalysis.vue'
import BrandChannelAnalysis from '../views/data/BrandChannelAnalysis.vue'
import ChannelAnalysis from '../views/data/ChannelAnalysis.vue'
import InventoryOverview from '../views/data/InventoryOverview.vue'
import InventoryTurnover from '../views/data/InventoryTurnover.vue'
import SlowMoving from '../views/data/SlowMoving.vue'
import BatchExpiryAnalysis from '../views/data/BatchExpiryAnalysis.vue'
import InventoryHealth from '../views/data/InventoryHealth.vue'
import AiDecisionCenter from '../views/data/AiDecisionCenter.vue'
import TextToSqlAgent from '../views/data/TextToSqlAgent.vue'
import ModelSettings from '../views/data/ModelSettings.vue'
import Users from '../views/data/Users.vue'

const routes = [
  { path: '/', redirect: '/dashboard' },
  { path: '/login', component: Login, meta: { public: true } },
  {
    path: '/',
    component: DashboardLayout,
    children: [
      { path: 'dashboard', component: Dashboard, meta: { title: '经营总览' } },
      { path: 'ai/decisions', component: AiDecisionCenter, meta: { title: 'AI 决策中心' } },
      { path: 'ai/text-to-sql', component: TextToSqlAgent, meta: { title: '数据智能问答' } },
      { path: 'sales', redirect: '/sales/overview' },
      { path: 'sales/overview', component: SalesOverview, meta: { title: '销售概览' } },
      { path: 'sales/detail', component: Sales, meta: { title: '销售明细' } },
      { path: 'sales/product-rank', component: ProductRank, meta: { title: '商品销售排行' } },
      { path: 'sales/brand-analysis', component: BrandAnalysis, meta: { title: '品牌销售分析' } },
      { path: 'sales/brand-analysis/:brand', component: BrandChannelAnalysis, meta: { title: '品牌销售分析' } },
      { path: 'sales/channel-analysis', component: ChannelAnalysis, meta: { title: '渠道分析' } },
      { path: 'inventory', redirect: '/inventory/overview' },
      { path: 'inventory/overview', component: InventoryOverview, meta: { title: '库存概览' } },
      { path: 'inventory/turnover', component: InventoryTurnover, meta: { title: '库存周转' } },
      { path: 'inventory/slow-moving', component: SlowMoving, meta: { title: '滞销商品' } },
      { path: 'inventory/batch-expiry', component: BatchExpiryAnalysis, meta: { title: '批次效期分析' } },
      { path: 'inventory/health', component: InventoryHealth, meta: { title: '库存健康度' } },
      { path: 'users', component: Users, meta: { title: '用户管理' } },
      { path: 'model-settings', component: ModelSettings, meta: { title: '模型设置' } },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (!to.meta.public && !auth.isAuthenticated) {
    return '/login'
  }
  if (to.path === '/login' && auth.isAuthenticated) {
    return '/dashboard'
  }
  return true
})

export default router
