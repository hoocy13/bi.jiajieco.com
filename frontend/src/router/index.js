import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import DashboardLayout from '../layout/DashboardLayout.vue'

const Login = () => import('../views/data/Login.vue')
const Dashboard = () => import('../views/data/Dashboard.vue')
const SalesOverview = () => import('../views/data/SalesOverview.vue')
const Sales = () => import('../views/data/Sales.vue')
const ProductRank = () => import('../views/data/ProductRank.vue')
const BrandAnalysis = () => import('../views/data/BrandAnalysis.vue')
const BrandChannelAnalysis = () => import('../views/data/BrandChannelAnalysis.vue')
const ChannelAnalysis = () => import('../views/data/ChannelAnalysis.vue')
const CustomerAnalysis = () => import('../views/data/CustomerAnalysis.vue')
const InventoryOverview = () => import('../views/data/InventoryOverview.vue')
const InventoryTurnover = () => import('../views/data/InventoryTurnover.vue')
const SlowMoving = () => import('../views/data/SlowMoving.vue')
const BatchExpiryAnalysis = () => import('../views/data/BatchExpiryAnalysis.vue')
const InventoryHealth = () => import('../views/data/InventoryHealth.vue')
const BrandMonthlyArrivals = () => import('../views/data/BrandMonthlyArrivals.vue')
const BrandInventoryFlow = () => import('../views/data/BrandInventoryFlow.vue')
const AiDecisionCenter = () => import('../views/data/AiDecisionCenter.vue')
const TextToSqlAgent = () => import('../views/data/TextToSqlAgent.vue')
const ModelSettings = () => import('../views/data/ModelSettings.vue')
const AiAssistant = () => import('../views/data/AiAssistant.vue')
const Users = () => import('../views/data/Users.vue')

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
      { path: 'ai/assistant', component: AiAssistant, meta: { title: 'AI 数据助手' } },
      { path: 'sales', redirect: '/sales/overview' },
      { path: 'sales/overview', component: SalesOverview, meta: { title: '销售概览' } },
      { path: 'sales/detail', component: Sales, meta: { title: '销售明细' } },
      { path: 'sales/product-rank', component: ProductRank, meta: { title: '商品销售排行' } },
      { path: 'sales/brand-analysis', component: BrandAnalysis, meta: { title: '品牌销售分析' } },
      { path: 'sales/brand-analysis/:brand', component: BrandChannelAnalysis, meta: { title: '品牌销售分析' } },
      { path: 'sales/channel-analysis', component: ChannelAnalysis, meta: { title: '渠道分析' } },
      { path: 'sales/customer-analysis', component: CustomerAnalysis, meta: { title: '客户分析' } },
              { path: 'inventory', redirect: '/inventory/overview' },
      { path: 'inventory/overview', component: InventoryOverview, meta: { title: '库存概览' } },
      { path: 'inventory/brand-arrivals', component: BrandMonthlyArrivals, meta: { title: '品牌月度到货' } },
      { path: 'inventory/brand-inventory-flow', component: BrandInventoryFlow, meta: { title: '品牌进销存' } },
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



