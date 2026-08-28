<script setup>
import { reactive, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

const route = useRoute()
const router = useRouter()
const allowed = {
  metric: ['paid_amount', 'orders', 'quantity'],
  method: ['trend', 'contribution', 'anomaly'],
  dimension: ['brand', 'channel', 'customer'],
  period: ['last_30', 'last_90', 'year'],
}
const pick = (key, fallback) => allowed[key].includes(String(route.query[key])) ? String(route.query[key]) : fallback
const form = reactive({
  metric: pick('metric', 'paid_amount'),
  method: pick('method', 'trend'),
  dimension: pick('dimension', 'brand'),
  period: pick('period', 'last_90'),
})

watch(form, value => router.replace({ query: { ...value } }), { deep: true })

function startAnalysis() {
  ElMessage.info('分析模型将在下一阶段开放，当前已完成统一入口和参数框架')
}
</script>

<template>
  <div class="analysis-workspace page-stack">
    <section class="analysis-intro">
      <div>
        <h2>分析工作台</h2>
        <p>统一承载趋势、对比、归因和预测分析。第一期先开放分析参数框架。</p>
      </div>
      <span>规划中</span>
    </section>
    <section class="panel analysis-config">
      <header><h2>新建分析</h2></header>
      <el-form label-position="top">
        <div class="analysis-fields">
          <el-form-item label="分析指标"><el-select v-model="form.metric"><el-option label="销售额" value="paid_amount" /><el-option label="订单数" value="orders" /><el-option label="销售数量" value="quantity" /></el-select></el-form-item>
          <el-form-item label="分析方式"><el-select v-model="form.method"><el-option label="趋势与环比" value="trend" /><el-option label="贡献度分析" value="contribution" /><el-option label="异常检测" value="anomaly" /></el-select></el-form-item>
          <el-form-item label="分析维度"><el-select v-model="form.dimension"><el-option label="品牌" value="brand" /><el-option label="渠道" value="channel" /><el-option label="客户" value="customer" /></el-select></el-form-item>
          <el-form-item label="分析周期"><el-select v-model="form.period"><el-option label="近30天" value="last_30" /><el-option label="近90天" value="last_90" /><el-option label="本年度" value="year" /></el-select></el-form-item>
        </div>
        <el-button type="primary" @click="startAnalysis">开始分析</el-button>
      </el-form>
    </section>
    <section class="analysis-roadmap">
      <div><strong>趋势与对比</strong><span>观察周期变化和异常拐点</span></div>
      <div><strong>贡献度分析</strong><span>定位品牌、渠道和客户贡献</span></div>
      <div><strong>预测分析</strong><span>后续接入销售和库存预测</span></div>
    </section>
  </div>
</template>

<style scoped>
.analysis-intro { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 20px; color: var(--text); background: var(--surface); border: 1px solid var(--border); border-radius: 9px; }
.analysis-intro h2 { margin: 0; font-size: 20px; }
.analysis-intro p { margin: 7px 0 0; color: var(--text-soft); font-size: 13px; }
.analysis-intro > span { flex: 0 0 auto; padding: 5px 9px; color: var(--text-soft); background: var(--surface-soft); border-radius: 6px; font-size: 12px; }
.analysis-config { padding-bottom: 18px; }
.analysis-config .el-form { padding: 16px 18px 0; }
.analysis-fields { display: grid; grid-template-columns: repeat(4, minmax(150px, 1fr)); gap: 12px; }
.analysis-fields :deep(.el-select) { width: 100%; }
.analysis-roadmap { display: grid; grid-template-columns: 1.35fr 1fr 1fr; gap: 12px; }
.analysis-roadmap div { display: grid; gap: 6px; padding: 18px; background: var(--surface); border: 1px solid var(--border); border-radius: 9px; }
.analysis-roadmap strong { font-size: 14px; }
.analysis-roadmap span { color: var(--text-soft); font-size: 12px; }
@media (max-width: 900px) { .analysis-fields { grid-template-columns: repeat(2, minmax(0, 1fr)); } .analysis-roadmap { grid-template-columns: 1fr; } }
@media (max-width: 560px) { .analysis-fields { grid-template-columns: 1fr; } .analysis-intro { align-items: flex-start; flex-direction: column; } }
</style>
