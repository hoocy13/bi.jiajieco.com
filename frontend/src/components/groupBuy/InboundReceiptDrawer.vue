<script setup>
import ReceiptHoldDialog from './ReceiptHoldDialog.vue'
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getInboundReceipt, getInboundComparison, confirmInboundReceipt, actInbound, getInboundHistory, saveInboundMapping, setInboundReceiptHold } from '../../api/groupBuy'
import { planInboundSuggestion } from '../../utils/groupBuyInboundSuggestion'

const props=defineProps({modelValue:String,brand:String,options:Object,initialBatch:Number})
const emit=defineEmits(['update:modelValue','changed'])
const receipt=ref(null),loading=ref(false),busy=ref(false),failure=ref(''),selection=ref([]),table=ref(null)
const drafts=reactive({}),orders=reactive({}),defaultBatch=ref(null),defaultSource=ref(''),search=ref('')
const editing=ref(null),edit=reactive({batch_id:null,source_id:'',mode:'normal',product_id:'',credit_quantity:1,note:''}),editLoading=ref(false)
const history=ref(null),historyRows=ref([])
const draftChanged=ref(false),holdOpen=ref(false),lineType=ref('all')
let sequence=0,editSequence=0
const batches=computed(()=>props.options.batches.filter(b=>b.brand===props.brand))
const batch=id=>batches.value.find(b=>b.id===id)
const sources=id=>batch(id)?.sources||[]
const key=d=>`${d.batch_id}:${d.source_id}`
const rowOrders=d=>orders[key(d)]||[]
const matches=(row,d)=>rowOrders(d).filter(p=>row.barcode&&p.barcode===row.barcode)
const editable=row=>['pending','ready'].includes(row.status)&&!row.reason.includes('解除')
const purchasable=row=>editable(row)&&row.purchase_eligible
const typeTag=row=>row.is_gift?'小样':row.product_type||'未分类'
const visibleRows=computed(()=>{const q=search.value.trim().toLowerCase();return (receipt.value?.rows||[]).filter(r=>(lineType.value==='all'||(lineType.value==='other'?!['正装','小样'].includes(r.product_type):r.product_type===lineType.value))&&(!q||`${r.name} ${r.code} ${r.barcode}`.toLowerCase().includes(q)))})
const label=d=>{const b=batch(d?.batch_id);return b?`${b.month} · ${b.name} · ${sources(b.id).find(s=>s.id===d.source_id)?.name||'未选柜台'}`:'未选批次'}
const n=x=>Number(x||0).toLocaleString('zh-CN')
const suggestionIssues=computed(()=>{
  const issues=(receipt.value?.rows||[]).map(r=>drafts[r.id]?.suggestionIssue).filter(Boolean)
  return {count:issues.length,reasons:[...new Set(issues)].join('；')}
})
function reason(row){
  if(receipt.value?.hold?.waiting&&editable(row))return '待补下单表'
  if(!editable(row)||!row.purchase_eligible)return row.reason
  if(row.source_issue)return row.source_issue
  const d=drafts[row.id]
  if(!d?.batch_id||!d.source_id)return '待选归属'
  if(!d.manual&&!d.automatic&&row.auto_match_reason)return row.auto_match_reason
  if(!orders[key(d)])return '正在读取下单…'
  if(d.suggestionIssue)return d.suggestionIssue
  if(d.mode==='substitute')return d.product_id&&d.credit_quantity>0&&d.note.trim()?'替代待确认':'请补齐替代商品、抵扣数量和原因'
  const count=matches(row,d).length
  return count===1?'待确认':count?'下单表条码重复':'该柜台未下单此条码'
}
const canConfirm=computed(()=>!receipt.value?.hold?.waiting&&selection.value.length>0&&selection.value.every(r=>purchasable(r)&&['待确认','替代待确认'].includes(reason(r))))
async function fetchOrders(lineId,d){
  if(!d.batch_id||!d.source_id)return
  const cacheKey=key(d)
  if(orders[cacheKey])return
  const r=await getInboundComparison(lineId,{batch_id:d.batch_id,source_id:d.source_id})
  orders[cacheKey]=r.data.orders
}
async function load(){
  const token=++sequence,id=props.modelValue
  if(!id)return
  loading.value=true;failure.value='';selection.value=[];receipt.value=null;draftChanged.value=false
  for(const k of Object.keys(drafts))delete drafts[k]
  for(const k of Object.keys(orders))delete orders[k]
  try{
    const r=await getInboundReceipt(id,{brand:props.brand,batch_id:props.initialBatch||undefined})
    if(token!==sequence)return
    receipt.value=r.data
    let chosen=batch(props.initialBatch)||batch(r.data.recommended_batch_id)
    if(!chosen){const counts=new Map();for(const row of r.data.rows)for(const c of row.candidates)counts.set(c.batch_id,(counts.get(c.batch_id)||0)+1);const ranked=[...counts].sort((a,b)=>b[1]-a[1]);if(ranked.length&&(!ranked[1]||ranked[0][1]>ranked[1][1]))chosen=batch(ranked[0][0]);if(!chosen&&batches.value.length===1)chosen=batches.value[0]}
    defaultBatch.value=chosen?.id||null;defaultSource.value=''
    if(chosen){const c=await getInboundComparison(r.data.rows[0].id,{batch_id:chosen.id});if(token!==sequence)return;defaultSource.value=c.data.source_id||'';if(defaultSource.value)orders[`${chosen.id}:${defaultSource.value}`]=c.data.orders}
    const requests=new Map()
    for(const row of r.data.rows){const c=row.recommendation;const d={batch_id:c?.batch_id||chosen?.id||null,source_id:c?.source_id||defaultSource.value,mode:'normal',product_id:'',credit_quantity:Number(row.quantity)>0?Number(row.quantity):1,note:'',automatic:!!c?.automatic,manual:false};drafts[row.id]=d;if(d.batch_id&&d.source_id)requests.set(key(d),{id:row.id,d})}
    await Promise.all([...requests.values()].map(({id,d})=>fetchOrders(id,d)))
    if(token!==sequence)return
    loading.value=false
    await nextTick()
    if(token!==sequence)return
    for(const row of r.data.rows)if(purchasable(row)&&drafts[row.id].automatic&&reason(row)==='待确认')table.value?.toggleRowSelection(row,true)
  }catch{if(token===sequence)failure.value='入库单读取失败，请重试'}finally{if(token===sequence)loading.value=false}
}
watch(()=>props.modelValue,()=>{editing.value=null;history.value=null;search.value='';lineType.value='all';++editSequence;if(props.modelValue)load();else ++sequence},{immediate:true})
async function defaultBatchChanged(){defaultSource.value='';if(!defaultBatch.value||!receipt.value)return;try{const id=defaultBatch.value,r=await getInboundComparison(receipt.value.rows[0].id,{batch_id:id});if(defaultBatch.value!==id)return;defaultSource.value=r.data.source_id||'';if(defaultSource.value)orders[`${id}:${defaultSource.value}`]=r.data.orders}catch{}}
async function applyDefault(){
  if(!selection.value.length||!defaultBatch.value||!defaultSource.value)return ElMessage.warning('请选择商品、批次和柜台')
  busy.value=true
  try{await fetchOrders(selection.value[0].id,{batch_id:defaultBatch.value,source_id:defaultSource.value});for(const row of selection.value)if(purchasable(row))Object.assign(drafts[row.id],{batch_id:defaultBatch.value,source_id:defaultSource.value,mode:'normal',product_id:'',note:'',manual:true,automatic:false,suggestionIssue:''});draftChanged.value=true}catch{}finally{busy.value=false}
}
async function rememberCounter(){
  const b=batch(defaultBatch.value),s=sources(defaultBatch.value).find(s=>s.id===defaultSource.value)
  if(!b||!s||!receipt.value)return
  try{await ElMessageBox.confirm(`记住“${receipt.value.supplier}”对应“${s.name}”，并重新自动匹配本单？未确认的归属设置将重新生成。`,'记住柜台对应')}catch{return}
  busy.value=true
  const existing=props.options.aliases.find(a=>a.brand===props.brand&&a.supplier===receipt.value.supplier)
  try{await saveInboundMapping({batch_id:b.id,revision:b.revision,source_id:s.id,supplier:receipt.value.supplier,supplier_code:existing?.supplier_code||undefined});emit('changed');await load();ElMessage.success('已记住柜台对应并重新匹配')}catch{}finally{busy.value=false}
}
function selectReady(){table.value?.clearSelection();for(const row of visibleRows.value)if(purchasable(row)&&reason(row)==='待确认')table.value?.toggleRowSelection(row,true)}
async function adoptSuggestion(){
  const suggestion=receipt.value?.suggestion,b=batch(props.initialBatch)
  if(!suggestion?.source_id||!b||receipt.value.hold?.waiting)return
  busy.value=true
  try{
    const d={batch_id:b.id,source_id:suggestion.source_id}
    await fetchOrders(receipt.value.rows[0].id,d)
    const plan=planInboundSuggestion(receipt.value.rows,rowOrders(d))
    search.value='';lineType.value='all';await nextTick()
    table.value?.clearSelection();defaultBatch.value=b.id;defaultSource.value=d.source_id
    let count=0
    for(const item of plan){
      Object.assign(drafts[item.id],d,{mode:'normal',product_id:'',note:'',manual:true,automatic:false,suggestionIssue:item.issue})
      if(item.selectable){table.value?.toggleRowSelection(receipt.value.rows.find(r=>r.id===item.id),true);count++}
    }
    if(plan.length)draftChanged.value=true
    if(count)ElMessage.success(`已带入归属，勾选 ${count} 项`)
    else ElMessage.warning(suggestionIssues.value.reasons||'无可勾选项')
  }catch{}finally{busy.value=false}
}
async function openEdit(row){editing.value=row;Object.assign(edit,drafts[row.id]);await loadEditOrders()}
async function loadEditOrders(){const token=++editSequence;editLoading.value=true;try{await fetchOrders(editing.value.id,{...edit})}catch{}finally{if(token===editSequence)editLoading.value=false}}
async function editBatchChanged(){edit.source_id='';edit.product_id='';if(!edit.batch_id)return;const token=++editSequence;editLoading.value=true;try{const r=await getInboundComparison(editing.value.id,{batch_id:edit.batch_id});if(token!==editSequence)return;edit.source_id=r.data.source_id||'';if(edit.source_id)orders[key(edit)]=r.data.orders}catch{}finally{if(token===editSequence)editLoading.value=false}}
function saveEdit(){if(!edit.batch_id||!edit.source_id)return ElMessage.warning('待选归属');if(edit.mode==='substitute'&&(!edit.product_id||!edit.credit_quantity||!edit.note.trim()))return ElMessage.warning('请填写替代商品、抵扣数量和原因');drafts[editing.value.id]={...edit,manual:true,automatic:false,suggestionIssue:''};draftChanged.value=true;editing.value=null}
async function confirm(){
  if(!canConfirm.value)return
  const rows=[...selection.value]
  const targetLabels=[...new Set(rows.map(r=>label(drafts[r.id])))].join('；')
  try{await ElMessageBox.confirm(`确认将所选 ${rows.length} 项关联到：${targetLabels}？其中替代到货 ${rows.filter(r=>drafts[r.id].mode==='substitute').length} 项。`,'确认入库归属',{confirmButtonText:'确认所选',cancelButtonText:'取消'})}catch{return}
  busy.value=true
  try{await confirmInboundReceipt({lines:rows.map(r=>{const d=drafts[r.id];return {id:r.id,revision:r.revision,batch_id:d.batch_id,batch_revision:batch(d.batch_id).revision,source_id:d.source_id,mode:d.mode,product_id:d.mode==='substitute'?d.product_id:undefined,credit_quantity:d.mode==='substitute'?d.credit_quantity:undefined,note:d.note}})});ElMessage.success(`已关联 ${rows.length} 项`);emit('changed');await load()}catch{failure.value='未保存所选明细，请核对提示并刷新单据后重试。';emit('changed')}finally{busy.value=false}
}
async function action(action,rows=selection.value){
  if(!rows.length)return
  let note;try{note=(await ElMessageBox.prompt(`处理所选 ${rows.length} 项，请填写原因。`,action==='exclude'?'不属于团购':'解除 / 恢复',{inputValidator:v=>!!v?.trim()&&v.trim().length<=500||'请填写500字以内原因'})).value}catch{return}
  busy.value=true
  try{await actInbound({action,lines:rows.map(r=>({id:r.id,revision:r.revision})),note});emit('changed');await load();ElMessage.success('处理完成')}catch{}finally{busy.value=false}
}
async function openHistory(row){history.value=row;historyRows.value=[];try{historyRows.value=(await getInboundHistory(row.id)).data}catch{}}
async function resume(){
  const h=receipt.value.hold
  try{await ElMessageBox.confirm('确认下单表已补齐并导入？接下来只重新生成匹配建议，不会自动确认入库。','资料齐了，重新匹配')}catch{return}
  busy.value=true
  try{await setInboundReceiptHold(receipt.value.doc_id,props.brand,{revision:h.revision,waiting:false,month:h.month,counter:h.counter,note:h.note});emit('changed');await load();ElMessage.success('已回到待处理，匹配建议已更新')}catch{}finally{busy.value=false}
}
async function close(done){if(busy.value)return;if(draftChanged.value){try{await ElMessageBox.confirm('关闭后未确认的归属设置不保留，是否关闭？','关闭入库单')}catch{return}}emit('update:modelValue','');done?.()}
</script>

<template>
  <el-drawer append-to-body :model-value="!!modelValue" title="处理入库单" size="min(1380px, 98vw)" :before-close="close" class="receipt-workbench">
    <div class="receipt-workspace" v-loading="loading||busy">
      <el-alert v-if="failure" :title="failure" type="error" :closable="false"><el-button link @click="load">刷新单据</el-button></el-alert>
      <template v-if="receipt">
        <el-alert v-if="receipt.hold?.waiting" title="这张单在等下单表，到货已保留。" type="warning" :closable="false"><span>{{receipt.hold.month}} · {{receipt.hold.counter}} · {{receipt.hold.note}}</span><el-button type="primary" @click="resume" :disabled="busy">资料齐了，重新匹配</el-button></el-alert>
        <div class="receipt-heading"><strong>{{receipt.receipt_number}}</strong><span>{{receipt.supplier}}</span><span>{{receipt.receipt_time.slice(0,10)}}</span><el-tag type="info">上海仓库新</el-tag></div>
        <div v-if="receipt.suggestion" class="suggestion-bar"><div><strong>{{({high:'高匹配',possible:'疑似相关',review:'待核对'})[receipt.suggestion.level]}}</strong><small v-if="receipt.suggestion.label">{{receipt.suggestion.label}} · 条码 {{receipt.suggestion.matched_count}}/{{receipt.suggestion.pending_count}}</small><small>{{receipt.suggestion.reason}}</small></div><el-button v-if="receipt.suggestion.source_id&&receipt.suggestion.level!=='high'" @click="adoptSuggestion" :disabled="busy||loading">采用建议</el-button></div>
        <div v-if="suggestionIssues.count" class="suggestion-notice">未勾选 {{suggestionIssues.count}} 项：{{suggestionIssues.reasons}}</div>
        <div class="classification-summary"><el-tag v-for="(count,kind) in receipt.type_counts" :key="kind" :type="kind==='正装'?'success':kind==='小样'?'info':'warning'">{{kind==='小样'?'小样':kind}} {{count}} 项</el-tag></div>
        <details v-if="receipt.rows.some(purchasable)" class="advanced-target"><summary>更多操作</summary><div class="target-controls"><span>统一归属</span><el-select v-model="defaultBatch" filterable placeholder="月份 / 批次" aria-label="整单默认批次" @change="defaultBatchChanged" :disabled="busy"><el-option v-for="b in batches" :key="b.id" :value="b.id" :label="`${b.month} · ${b.name}`"/></el-select><el-select v-model="defaultSource" filterable placeholder="选择柜台" aria-label="整单默认柜台" :disabled="busy"><el-option v-for="s in sources(defaultBatch)" :key="s.id" :value="s.id" :label="s.name"/></el-select><el-button @click="applyDefault" :disabled="busy||!selection.length">应用到所选</el-button><el-button @click="rememberCounter" :disabled="busy||!defaultBatch||!defaultSource">记住柜台对应</el-button></div></details>
        <div class="selection-controls"><el-radio-group v-if="Object.keys(receipt.type_counts||{}).length>1" v-model="lineType" size="small" @change="table?.clearSelection()"><el-radio-button value="all">全部</el-radio-button><el-radio-button value="正装">正装</el-radio-button><el-radio-button value="小样">小样</el-radio-button><el-radio-button value="other">待核实</el-radio-button></el-radio-group><el-input v-model="search" clearable placeholder="搜索商品 / 条码" aria-label="单内商品搜索" @input="table?.clearSelection()"/><el-button v-if="receipt.rows.some(purchasable)" @click="selectReady" :disabled="busy">勾选匹配项</el-button><span v-if="receipt.rows.some(editable)">已选 {{selection.length}} 项</span></div>
        <div class="receipt-lines"><el-table ref="table" :data="visibleRows" row-key="id" height="100%" @selection-change="selection=$event" :empty-text="loading?'读取中':'没有符合条件的商品'">
          <el-table-column v-if="receipt.rows.some(editable)" type="selection" width="44" :selectable="row=>!busy&&!receipt.hold?.waiting&&editable(row)"/>
          <el-table-column label="实际入库商品" min-width="235"><template #default="{row}">{{row.name}}<small>{{row.code}} · {{row.barcode||'无条码'}}</small></template></el-table-column>
          <el-table-column label="分类" width="105"><template #default="{row}"><el-tag :type="row.product_type==='正装'?'success':row.is_gift?'info':'warning'">{{typeTag(row)}}</el-tag></template></el-table-column>
          <el-table-column label="入库数量" width="90" align="right"><template #default="{row}">{{n(row.quantity)}}</template></el-table-column>
          <el-table-column v-if="receipt.rows.some(r=>r.status!=='gift')" label="归属批次 / 柜台" min-width="220"><template #default="{row}">{{row.status==='gift'?'小样':purchasable(row)?label(drafts[row.id]):[row.batch_label,row.counter].filter(Boolean).join(' · ')||'—'}}</template></el-table-column>
          <el-table-column v-if="receipt.rows.some(r=>r.status!=='gift')" label="对应下单 / 处理状态" min-width="270"><template #default="{row}">
            <template v-if="purchasable(row)&&drafts[row.id]"><template v-if="drafts[row.id].mode==='substitute'"><el-tag type="warning" size="small">替代到货</el-tag> {{rowOrders(drafts[row.id]).find(p=>p.id===drafts[row.id].product_id)?.name}}<small>实收 {{n(row.quantity)}} · 抵扣 {{n(drafts[row.id].credit_quantity)}} · {{drafts[row.id].note}}</small></template><template v-else-if="matches(row,drafts[row.id]).length===1">{{matches(row,drafts[row.id])[0].name}}<small>下单 {{n(matches(row,drafts[row.id])[0].ordered)}} · 尚欠 {{n(matches(row,drafts[row.id])[0].waiting)}}</small></template><el-tag v-if="drafts[row.id].automatic" size="small" type="success">自动匹配</el-tag><el-tag v-if="drafts[row.id].automatic&&drafts[row.id].batch_id!==defaultBatch" size="small" type="warning">其他批次 · {{batch(drafts[row.id].batch_id)?.month}}</el-tag><small>{{reason(row)}}</small></template>
            <template v-else>{{row.status==='gift'?'不计采购':row.reason}}<small v-if="row.product">{{row.product}}<template v-if="row.mode==='substitute'"> · 抵扣 {{n(row.credit_quantity)}}</template></small><small>{{row.note}}</small></template>
          </template></el-table-column>
          <el-table-column label="操作" width="165" fixed="right"><template #default="{row}"><el-button v-if="purchasable(row)" link type="primary" @click="openEdit(row)" :disabled="busy||receipt.hold?.waiting">调整归属</el-button><el-button v-if="!editable(row)&&row.status!=='gift'" link @click="action('release',[row])" :disabled="busy">{{row.status==='excluded'?'恢复':'解除'}}</el-button><el-button link @click="openHistory(row)">记录</el-button></template></el-table-column>
        </el-table></div>
      </template>
    </div>
    <template #footer><el-button @click="close()" :disabled="busy">关闭</el-button><el-button v-if="receipt&&!receipt.hold?.waiting&&receipt.rows.some(editable)" @click="holdOpen=true" :disabled="busy">待补下单表</el-button><el-button v-if="receipt?.rows.some(editable)" @click="action('exclude')" :disabled="busy||!selection.length">不属于团购</el-button><el-button v-if="receipt?.rows.some(purchasable)" type="primary" @click="confirm" :disabled="busy||!canConfirm" :loading="busy">确认所选（{{selection.length}}）</el-button></template>
  </el-drawer>
  <ReceiptHoldDialog :record="holdOpen?receipt:null" :brand="brand" :month="batch(defaultBatch)?.month||new Date().toISOString().slice(0,7)" :options="options" @close="holdOpen=false" @changed="emit('changed');load()"/>
  <el-dialog append-to-body :model-value="!!editing" title="调整商品归属" width="min(650px, 96vw)" :close-on-click-modal="false" @close="editing=null">
    <template v-if="editing"><p>{{editing.name}} · 实收 {{n(editing.quantity)}}</p><el-form label-position="top" v-loading="editLoading">
      <el-form-item label="月份 / 批次"><el-select v-model="edit.batch_id" filterable aria-label="单项归属批次" @change="editBatchChanged"><el-option v-for="b in batches" :key="b.id" :value="b.id" :label="`${b.month} · ${b.name}`"/></el-select></el-form-item>
      <el-form-item label="柜台"><el-select v-model="edit.source_id" filterable aria-label="单项归属柜台" @change="edit.product_id='';loadEditOrders()"><el-option v-for="s in sources(edit.batch_id)" :key="s.id" :value="s.id" :label="s.name"/></el-select></el-form-item>
      <el-form-item label="处理方式"><el-radio-group v-model="edit.mode"><el-radio-button value="normal">正常到货</el-radio-button><el-radio-button value="substitute">替代到货</el-radio-button></el-radio-group></el-form-item>
      <template v-if="edit.mode==='substitute'"><el-form-item label="抵扣哪个下单商品"><el-select v-model="edit.product_id" filterable aria-label="被替代下单商品"><el-option v-for="p in rowOrders(edit)" :key="p.id" :value="p.id" :label="`${p.code} · ${p.name}（尚欠 ${n(p.waiting)}）`"/></el-select></el-form-item><el-form-item label="抵扣原订单数量"><el-input-number v-model="edit.credit_quantity" :min="1" :max="100000000" :precision="0"/></el-form-item><el-form-item label="替代原因"><el-input v-model="edit.note" maxlength="500" aria-label="替代原因"/></el-form-item></template>
      <template v-else><el-alert :title="matches(editing,edit).length===1?`条码一致：${matches(editing,edit)[0].name}`:matches(editing,edit).length>1?'下单表条码重复':'该柜台未下单此条码'" :type="matches(editing,edit).length===1?'success':'warning'" :closable="false"/></template>
    </el-form></template>
    <template #footer><el-button @click="editing=null">取消</el-button><el-button type="primary" @click="saveEdit" :disabled="editLoading">应用到本项</el-button></template>
  </el-dialog>
  <el-dialog append-to-body :model-value="!!history" title="处理记录" width="min(620px,96vw)" @close="history=null"><el-empty v-if="!historyRows.length" description="暂无记录"/><div v-for="h in historyRows" :key="h.id" class="audit-entry">{{({confirm:'确认关联',release:'解除 / 恢复',exclude:'排除',source_update:'源资料更新',source_missing:'源明细待复核'})[h.action]||h.action}} · {{h.operator}} · {{h.created_at.replace('T',' ').slice(0,19)}}<p>{{h.changes.note}}</p><small v-if="h.changes.mode==='substitute'">替代到货：实收 {{h.changes.source_quantity}}，抵扣 {{h.changes.credit_quantity}}</small></div></el-dialog>
</template>

<style scoped>
.suggestion-notice{font-size:13px;color:var(--el-color-warning-dark-2);line-height:1.6;flex-shrink:0}
.classification-summary{display:flex;align-items:center;flex-wrap:wrap;gap:8px;flex-shrink:0}
.advanced-target{flex-shrink:0}.advanced-target>summary{cursor:pointer;font-size:13px;color:var(--text-soft);padding:2px 0}.advanced-target[open]>.target-controls{margin-top:12px}
.suggestion-bar{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;padding:12px 16px;border:1px solid var(--el-color-success-light-7);background:var(--el-color-success-light-9);border-radius:6px;flex-shrink:0}.suggestion-bar strong{font-size:13px}
.receipt-workspace{display:flex;flex-direction:column;height:100%;min-height:0;gap:16px}.receipt-heading,.target-controls,.selection-controls{display:flex;align-items:center;flex-wrap:wrap;gap:12px;flex-shrink:0}.receipt-heading strong{font-size:18px}.receipt-heading span,.selection-controls span{color:var(--text-soft);font-size:13px}.target-controls>.el-select{width:220px}.selection-controls>.el-input{width:300px}.receipt-lines{flex:1;min-height:180px;overflow:hidden}small{display:block;line-height:1.6;color:var(--text-soft);font-size:12px}.el-form :deep(.el-select){width:100%}.audit-entry{padding:12px 0;border-bottom:1px solid var(--border-color,#ebeef5)}.audit-entry p{margin:6px 0}.receipt-workspace>.el-alert{flex-shrink:0}:deep(.el-table .cell){overflow-wrap:anywhere}
@media(max-height:650px){.receipt-workspace{height:auto;min-height:450px}.receipt-lines{height:260px;flex:none}}
</style>
