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
const Roles = () => import('../views/data/Roles.vue')
const Register = () => import('../views/data/Register.vue')
const PendingAccess = () => import('../views/data/PendingAccess.vue')
const Announcements = () => import('../views/data/Announcements.vue')

const routes = [
  { path: '/', redirect: '/dashboard' },
  { path: '/login', component: Login, meta: { public: true } },
  { path: '/register', component: Register, meta: { public: true } },
  { path: '/pending-access', component: PendingAccess },
  {
    path: '/',
    component: DashboardLayout,
    children: [
      { path: 'dashboard', component: Dashboard, meta: { title: '经营总览', permission: 'dashboard.view' } },
      { path: 'ai/decisions', component: AiDecisionCenter, meta: { title: 'AI 决策中心', permission: 'ai.decision.view' } },
      { path: 'ai/text-to-sql', component: TextToSqlAgent, meta: { title: '数据智能问答', permission: 'ai.text_to_sql.use' } },
      { path: 'ai/assistant', component: AiAssistant, meta: { title: 'AI 数据助手', permission: 'ai.assistant.use' } },
      { path: 'sales', redirect: '/sales/overview' },
      { path: 'sales/overview', component: SalesOverview, meta: { title: '销售概览', permission: 'sales.view' } },
      { path: 'sales/detail', component: Sales, meta: { title: '销售明细', permission: 'sales.view' } },
      { path: 'sales/product-rank', component: ProductRank, meta: { title: '商品销售排行', permission: 'sales.view' } },
      { path: 'sales/brand-analysis', component: BrandAnalysis, meta: { title: '品牌销售分析', permission: 'sales.view' } },
      { path: 'sales/brand-analysis/:brand', component: BrandChannelAnalysis, meta: { title: '品牌销售分析', permission: 'sales.view' } },
      { path: 'sales/channel-analysis', component: ChannelAnalysis, meta: { title: '渠道分析', permission: 'sales.view' } },
      { path: 'sales/customer-analysis', component: CustomerAnalysis, meta: { title: '客户分析', permission: 'sales.view' } },
                    { path: 'inventory', redirect: '/inventory/overview' },
      { path: 'inventory/overview', component: InventoryOverview, meta: { title: '库存概览', permission: 'inventory.view' } },
      { path: 'inventory/brand-arrivals', component: BrandMonthlyArrivals, meta: { title: '品牌月度到货', permission: 'inventory.view' } },
      { path: 'inventory/brand-inventory-flow', component: BrandInventoryFlow, meta: { title: '品牌进销存', permission: 'inventory.view' } },
      { path: 'inventory/turnover', component: InventoryTurnover, meta: { title: '品牌周转', permission: 'inventory.view' } },
      { path: 'inventory/slow-moving', component: SlowMoving, meta: { title: '滞销分析', permission: 'inventory.view' } },
      { path: 'inventory/batch-expiry', component: BatchExpiryAnalysis, meta: { title: '批次效期分析', permission: 'inventory.view' } },
      { path: 'inventory/health', component: InventoryHealth, meta: { title: '库存健康度', permission: 'inventory.view' } },
      { path: 'users', component: Users, meta: { title: '账号权限', permission: 'system.users.manage' } },
      { path: 'roles', component: Roles, meta: { title: '角色管理', permission: 'system.roles.manage' } },
      { path: 'model-settings', component: ModelSettings, meta: { title: '模型设置', permission: 'system.models.manage' } },
      { path: 'announcements', component: Announcements, meta: { title: '系统公告', permission: 'system.announcements.manage' } },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!to.meta.public && !auth.isAuthenticated) {
    return '/login'
  }
  if (to.path === '/login' && auth.isAuthenticated) {
    return '/dashboard'
  }
  if (auth.isAuthenticated && !auth.profileLoaded) await auth.loadProfile()
  if (to.meta.permission && !auth.hasPermission(to.meta.permission)) {
    return '/pending-access'
  }
  return true
})

export default router




