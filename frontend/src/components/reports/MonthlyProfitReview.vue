<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import http from '../../api/http'
import { Search, RefreshLeft } from '@element-plus/icons-vue'

const route = useRoute(), router = useRouter()
const data = ref(null), error = ref(''), loading = ref(false)
const expanded = ref([]), repair = ref('')
function openDetails(bucket = '规则可计算订单') { expanded.value = ['details']; repair.value = ''; change({ bucket, detail: bucket === '待核订单' ? 'orders' : 'product', keyword: '' }) }
let sequence = 0
const now = new Date()
const currentMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
const searchForm = reactive({ month: currentMonth, kind: '', channel: '' })
const title = computed(() => `${filters.value.month.slice(0,4)}年${Number(filters.value.month.slice(5))}月经营毛利`)
function search() { if (searchForm.month) change({ month: searchForm.month, kind: searchForm.kind, channel: searchForm.channel, keyword: '' }) }
function reset() { router.push({ path: route.path, query: { view: 'review', month: currentMonth } }) }
const filters = computed(() => ({ month: /^\d{4}-(0[1-9]|1[0-2])$/.test(String(route.query.month || '')) ? route.query.month : currentMonth, keyword: String(route.query.keyword || ''), kind: ['正装', '小样'].includes(route.query.kind) ? route.query.kind : '', channel: String(route.query.channel || ''), view: ['product', 'orders'].includes(route.query.detail) ? route.query.detail : 'channel', bucket: ['缺成本订单', '待核订单'].includes(route.query.bucket) ? route.query.bucket : '规则可计算订单', page: Math.max(1, Number(route.query.page) || 1), page_size: 50, sort_by: ['name', 'net_sales', 'quantity', 'cost', 'profit', 'margin'].includes(route.query.sort_by) ? route.query.sort_by : 'profit', sort_order: route.query.sort_order === 'asc' ? 'asc' : 'desc' }))
const money = (v) => v == null ? '-' : Number(v).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const wan = (v) => money(Number(v) / 10000)
const percent = (v) => v == null ? '-' : `${Number(v).toFixed(1)}%`
function change(values) { if (values.detail || values.keyword) expanded.value = ['details']; router.push({ path: route.path, query: { ...route.query, page: '1', ...values, view: 'review' } }) }
function sort({ prop, order }) { change({ sort_by: prop || 'profit', sort_order: order === 'ascending' ? 'asc' : 'desc' }) }
function drill(row) { if (filters.value.view === 'channel') change({ channel: row.code, detail: 'product' }) }
async function load() {
  const id = ++sequence; loading.value = true; error.value = ''; data.value = null; Object.assign(searchForm, { month: filters.value.month, kind: filters.value.kind, channel: filters.value.channel })
  try { const response = await http.get('/sales/profit-analysis/monthly-review', { params: filters.value, timeout: 180000 }); if (id === sequence) data.value = response.data }
  catch (e) { if (id === sequence) error.value = typeof e.response?.data?.detail === 'string' ? e.response.data.detail : '试算加载失败，请重试' }
  finally { if (id === sequence) loading.value = false }
}
watch(() => route.fullPath, load, { immediate: true })
</script>

<template>
  <main class="monthly-profit-review" v-loading="loading">
    <section class="review-panel month-filters">
      <el-date-picker v-model="searchForm.month" type="month" value-format="YYYY-MM" format="YYYY年MM月" :clearable="false" aria-label="统计月份" style="width:180px" :disabled-date="d => d.getFullYear() > now.getFullYear() || (d.getFullYear() === now.getFullYear() && d.getMonth() > now.getMonth())" />
      <el-select v-model="searchForm.kind" placeholder="全部分类" aria-label="筛选货品分类" style="width:150px"><el-option label="全部分类" value="" /><el-option label="正装" value="正装" /><el-option label="小样" value="小样" /></el-select>
      <el-select v-model="searchForm.channel" filterable clearable placeholder="全部渠道" aria-label="筛选渠道" style="width:230px"><el-option v-for="c in (data?.channels || [])" :key="c" :label="c" :value="c" /></el-select>
      <el-button type="primary" :icon="Search" :loading="loading" @click="search">查询</el-button><el-tooltip content="重置本月"><el-button :icon="RefreshLeft" circle aria-label="重置本月" @click="reset" /></el-tooltip>
      <span v-if="data?.updated_at">数据更新时间 {{ data.updated_at }}</span>
    </section>
    <header class="review-heading">
      <div><div class="eyebrow">月度经营</div><h1>{{ title }}</h1></div>
      <div class="review-heading-pages"><slot name="pages" /></div>
    </header>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <template v-if="data">
      <el-alert v-if="data.empty" title="所选月份暂无已同步销售数据" type="info" :closable="false" />
      <el-alert title="仅展示规则可计算部分，非公司完整利润；待核及缺成本订单已整单隔离。" type="warning" :closable="false" show-icon />
      <section class="review-cards">
        <article class="primary"><span>可计算部分估算毛利（万元）</span><strong>{{ wan(data.summary.profit) }}</strong><span>对应毛利率 {{ percent(data.summary.margin) }}</span></article>
        <article><span>可计算销售占本月销售比</span><strong>{{ percent(data.sales_coverage?.net_share) }}</strong><span>可计算 {{ wan(data.sales_coverage?.eligible_net_sales) }} / {{ filters.kind || filters.channel ? '当前范围' : '本月' }} {{ wan(data.sales_coverage?.total_net_sales) }} 万元</span></article>
        <article v-for="b in data.buckets.filter(b => b.name !== '规则可计算订单')" :key="b.name"><span>{{ b.name }}净销售额（万元）</span><strong>{{ wan(b.net_sales) }}</strong><span><template v-if="b.orders != null">{{ Number(b.orders).toLocaleString() }} 个订单 · </template>暂不计毛利</span></article>
      </section>
      <section class="review-panel">
        <h2>正装与小样 <span>仅纳入可计算订单</span></h2>
        <div class="type-grid"><article v-for="t in data.types" :key="t.name" @click="change({ kind: t.name, bucket: '规则可计算订单', detail: 'channel' })" tabindex="0" @keydown.enter="change({ kind: t.name, bucket: '规则可计算订单', detail: 'channel' })">
          <header><h3>{{ t.name }}</h3><el-tag :type="t.profit < 0 ? 'danger' : 'success'">{{ percent(t.margin) }}</el-tag></header>
          <strong :class="{ negative: t.profit < 0 }">{{ wan(t.profit) }} <small>万元</small></strong>
          <div class="profit-track"><i :class="{ negative: t.profit < 0 }" :style="{ width: `${Math.min(100, Math.abs(t.profit) / Math.max(...data.types.map(t => Math.abs(t.profit)), 1) * 100)}%` }" /></div>
          <p>纳入计算销售额 {{ wan(t.net_sales) }} 万元 · 查看渠道 →</p>
        </article></div>
      </section>
      <el-collapse v-model="expanded" class="review-detail-collapse"><el-collapse-item name="details" title="经营下钻">
      <section class="review-panel">
        <div class="review-toolbar"><h2>{{ filters.view === 'orders' ? '待核订单' : '经营下钻' }}</h2>
          <el-select :model-value="filters.bucket" aria-label="订单范围" style="width:170px" @change="v => change({ bucket: v, detail: v === '待核订单' ? 'orders' : 'channel', kind: '' })"><el-option v-for="b in data.buckets" :key="b.name" :label="b.name" :value="b.name" /></el-select>
          <el-radio-group v-if="filters.view !== 'orders'" :model-value="filters.view" @change="v => change({ detail: v })"><el-radio-button value="channel">渠道</el-radio-button><el-radio-button value="product">商品</el-radio-button></el-radio-group>
          <el-input :model-value="filters.keyword" clearable placeholder="订单号 / 货品" aria-label="搜索订单或货品" style="width:200px" @change="v => change({ keyword: v })" />
          <el-button @click="reset()">重置</el-button>
        </div>
        <p class="scope-note" v-if="data.filtered_summary">当前筛选净销售额 {{ wan(data.filtered_summary.net_sales) }} 万元<span v-if="data.filtered_summary.profit != null"> · 估算毛利 {{ wan(data.filtered_summary.profit) }} 万元</span>。渠道纳入范围不同，不代表完整利润排名。</p>
        <p class="scope-note" v-else>以下为整单待核原因，不代表均为退款缺失；金额为整单净销售额，不是退款金额。</p>
        <el-table :data="data.rows" @sort-change="sort" @row-click="drill" :default-sort="{ prop: filters.sort_by, order: filters.sort_order === 'asc' ? 'ascending' : 'descending' }" style="width:100%">
          <el-table-column prop="name" :label="filters.view === 'orders' ? '订单编号' : filters.view === 'product' ? '货品' : '渠道（点击下钻）'" min-width="240" sortable="custom" />
          <el-table-column v-if="filters.view === 'product'" prop="code" label="货品编号" min-width="160" />
          <el-table-column v-if="filters.view === 'orders'" prop="channel" label="渠道" min-width="170" />
          <el-table-column prop="net_sales" label="净销售额（元）" min-width="150" align="right" sortable="custom"><template #default="{ row }">{{ money(row.net_sales) }}</template></el-table-column>
          <el-table-column prop="quantity" label="净数量" min-width="110" align="right" sortable="custom"><template #default="{ row }">{{ money(row.quantity).replace(/\.00$/, '') }}</template></el-table-column>
          <el-table-column v-if="filters.bucket === '规则可计算订单'" prop="cost" label="估算成本（元）" min-width="150" align="right" sortable="custom"><template #default="{ row }">{{ money(row.cost) }}</template></el-table-column>
          <el-table-column v-if="filters.bucket === '规则可计算订单'" prop="profit" label="估算毛利（元）" min-width="150" align="right" sortable="custom"><template #default="{ row }"><b :class="{ negative: row.profit < 0 }">{{ money(row.profit) }}</b></template></el-table-column>
          <el-table-column v-if="filters.bucket === '规则可计算订单'" prop="margin" label="毛利率" min-width="100" align="right" sortable="custom"><template #default="{ row }">{{ percent(row.margin) }}</template></el-table-column>
          <el-table-column v-if="filters.bucket !== '规则可计算订单'" prop="reason" label="待核原因" min-width="300" />
        </el-table>
        <el-pagination layout="total, prev, pager, next" :total="data.total" :page-size="50" :current-page="filters.page" @current-change="v => change({ page: String(v) })" />
      </section>
      </el-collapse-item></el-collapse>
      <el-drawer :model-value="Boolean(repair)" :title="repair === '缺成本订单' ? '缺成本订单：处理建议' : '待核订单：处理建议'" size="min(620px, 95vw)" @close="repair = ''">
        <template v-if="repair === '缺成本订单'">
          <el-alert title="卡片金额是整张订单被隔离的销售额，不全是缺价货品金额。" type="info" :closable="false" />
          <p>当前范围缺成本货品 {{ data.repair_summary?.missing_skus }} 个，对应净销售额 {{ wan(data.repair_summary?.missing_goods_net_sales) }} 万元（包括待核订单中的缺价货品）。</p>
          <ol class="repair-steps"><li>先核对货品编号、条码与现有成本记录，排除编号不一致；不凭名称自动合并。</li><li>正装先检查五品牌规则是否适用，以及零售价是否缺失或冲突；只对确认适用的货品维护成本。</li><li>小样、组合和特殊规格核实单品或整套成本，不能自动套正装折扣。</li><li>按缺价货品涉及销售额从高到低处理，补齐整单所有货品后重新计算；待核问题未解决的仍保留隔离。</li></ol>
          <el-table :data="data.repair_summary?.top_missing || []"><el-table-column prop="code" label="货品编号" min-width="150" /><el-table-column prop="name" label="货品" min-width="180" /><el-table-column label="净销售额（万元）" width="145" align="right"><template #default="{ row }">{{ wan(row.net_sales) }}</template></el-table-column></el-table>
          <p>这里只给出核对顺序，不自动补价，也不恢复此前删除的成本记录。</p>
          <el-button type="primary" @click="openDetails('缺成本订单')">展开缺成本明细</el-button>
        </template>
        <template v-else>
          <el-alert title="按具体原因处理，不统一当作退款缺失，也不自动补金额。" type="warning" :closable="false" />
          <ul><li v-for="r in data.repair_summary?.pending_reasons || []" :key="r.reason">{{ r.reason }}：{{ r.orders.toLocaleString() }} 个订单</li></ul>
          <p>原因可能重叠，订单数不能直接相加。</p>
          <ol class="repair-steps"><li>零金额退货：核实真实退库和退款是否记在另一关联单；退库确认后冲减成本，退款仍缺失时保留待核。</li><li>零金额发货：区分赠品、组合、代发和收入另记；实际出货保留成本，组合合并核算，不虚构拆分售价。</li><li>金额数量方向异常：回到原订单及售后记录核实，不按符号批量修正。</li><li>按订单保留核实结论，金额问题回到采集或业务源修复；重算后再解除整单隔离。</li></ol>
          <el-button type="primary" @click="openDetails('待核订单')">展开待核订单</el-button>
        </template>
      </el-drawer>
    </template>
  </main>
</template>

<style scoped>
.review-heading-pages{border:0;padding:0;margin-left:auto}.review-detail-collapse{border:1px solid var(--border);border-radius:6px;background:var(--surface);padding:0 16px}.review-detail-collapse :deep(.el-collapse-item__header){font-size:15px;font-weight:600}.review-detail-collapse :deep(.el-collapse-item__content){padding-bottom:8px}.review-cards .el-button{align-self:flex-start;padding:0;height:auto}.repair-steps{padding-left:22px;line-height:1.9}.repair-steps li{margin:12px 0}@media(max-width:720px){.review-heading{flex-wrap:wrap}.review-heading-pages{width:100%;margin-left:0}}
.monthly-profit-review{--profit-accent:var(--theme-primary);display:grid;gap:12px;min-width:0;color:var(--text);--el-color-primary:var(--theme-primary)}
.month-filters{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:10px 12px!important}.month-filters>span{font-size:12px;color:var(--muted);margin-left:auto}
.review-heading{display:flex;align-items:center;justify-content:space-between;gap:16px;min-height:106px;padding:18px 22px;border:1px solid var(--border);border-top:3px solid var(--profit-accent);border-radius:6px;background:var(--surface)}
.review-heading>div:not(.review-heading-pages){border-left:4px solid var(--profit-accent);padding-left:12px}.eyebrow{color:var(--theme-strong);font-weight:600;font-size:11px}h1{font-size:22px;margin:5px 0 8px;line-height:1.3}h2{font-size:16px;margin:0}h2 span{font-size:12px;color:var(--muted);font-weight:400;margin-left:12px}.review-heading p,footer,.scope-note{color:var(--muted);font-size:12px;margin:5px 0}
.review-cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.review-cards article{display:flex;flex-direction:column;gap:10px;background:var(--surface);border:1px solid var(--border);border-top:2px solid var(--profit-accent);border-radius:6px;padding:16px;min-width:0}.review-cards strong{font-size:24px;line-height:1.3;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}.review-cards span{font-size:12px;color:var(--muted)}.review-cards .primary{background:var(--profit-accent);border-color:var(--profit-accent)}.review-cards .primary strong,.review-cards .primary span{color:#fff}
.review-panel{background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:16px;min-width:0}.type-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:16px}.type-grid article{cursor:pointer;padding:16px;background:var(--surface-muted,var(--surface));border:1px solid var(--border);border-radius:6px}.type-grid article:hover{border-color:var(--theme-primary)}.type-grid article:focus-visible{outline:2px solid var(--theme-primary);outline-offset:2px}.type-grid header{display:flex;align-items:center;justify-content:space-between}.type-grid h3{margin:0 0 12px;font-size:15px}.type-grid strong{font-size:24px}.type-grid small{font-size:12px;font-weight:400;color:var(--muted)}.type-grid p{font-size:12px;color:var(--muted)}.profit-track{background:var(--border);border-radius:4px;height:8px;margin-top:14px}.profit-track i{display:block;background:var(--theme-primary);height:100%;border-radius:4px}.profit-track i.negative{background:var(--el-color-danger)}.negative{color:var(--el-color-danger)}
.review-toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.review-toolbar h2{margin-right:auto}.el-pagination{margin-top:16px;justify-content:flex-end}footer{padding-bottom:12px}
@media(max-width:1100px){.review-cards{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:600px){.month-filters>*{width:100%!important}.month-filters>span{margin-left:0}.review-heading{padding:14px}.review-cards,.type-grid{grid-template-columns:1fr}.review-panel{padding:12px}.review-cards article{padding:14px}.review-toolbar h2{width:100%}h1{font-size:20px}}
</style>
