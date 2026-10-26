<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import ReceiptHoldDialog from '../../components/groupBuy/ReceiptHoldDialog.vue'
import OrderCollectionDialog from '../../components/groupBuy/OrderCollectionDialog.vue'
import InboundReceiptDrawer from '../../components/groupBuy/InboundReceiptDrawer.vue'
import InboundColumnFilter from '../../components/common/InboundColumnFilter.vue'
import { getInboundOptions, getInboundReceipts, syncInbound, saveInboundMapping, actInbound, importInboundSuppliers } from '../../api/groupBuy'

const route=useRoute(),router=useRouter(),today=new Date()
const defaultMonth=`${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}`
const selectedMonth=ref(String(route.query.month||defaultMonth))
const currentEnd=new Date(today.getFullYear(),today.getMonth()+1,0).getDate()
const dates=ref([String(route.query.start_date||`${defaultMonth}-01`),String(route.query.end_date||`${defaultMonth}-${currentEnd}`)])
const brand=ref(String(route.query.brand||'兰蔻')),batchId=ref(Number(route.query.batch)||null)
const state=ref(['pending','partial','waiting','done','excluded','mapping','suppliers'].includes(route.query.state)?route.query.state:route.query.state==='confirmed'?'done':'pending')
const keyword=ref(String(route.query.keyword||'')),supplier=ref(String(route.query.supplier||''))
const queryValues=v=>(Array.isArray(v)?v:v?[v]:[]).filter(x=>typeof x==='string').slice(0,100)
const supplierNames=ref(queryValues(route.query.supplier_names)),productKeys=ref(queryValues(route.query.product_keys))
const sort=reactive({sort_by:['receipt_time','receipt_number','item_count','pending_count'].includes(route.query.sort_by)?route.query.sort_by:'receipt_time',sort_order:route.query.sort_order==='asc'?'asc':'desc'})
const page=ref(Number(route.query.page)||1),pageSize=ref(30),loading=ref(false),busy=ref(false),selection=ref([]),table=ref(null)
const options=ref({brands:[],batches:[],aliases:[],suppliers:[]}),data=ref({rows:[],total:0,summary:{},suppliers:[]})
const failure=ref(''),catalogSearch=ref(''),showMapping=ref(false),mapping=reactive({supplier:'',supplier_code:'',source_id:''})
const importInput=ref(null)
const batches=computed(()=>options.value.batches.filter(b=>b.brand===brand.value&&b.month===selectedMonth.value))
const target=computed(()=>batches.value.find(b=>b.id===batchId.value))
const aliases=computed(()=>options.value.aliases.filter(a=>a.brand===brand.value))
const suppliers=computed(()=>options.value.suppliers.filter(s=>!catalogSearch.value||`${s.code} ${s.name} ${s.alias} ${s.category}`.toLowerCase().includes(catalogSearch.value.toLowerCase())))
const catalogPage=ref(1)
const supplierChoices=computed(()=>{
  const names=new Map(options.value.suppliers.map(s=>[s.name.replace(/\s+/g,' ').trim(),{name:s.name,code:s.code,label:`${s.code} · ${s.name}`}]))
  for(const name of data.value.suppliers)if(!names.has(name))names.set(name,{name,code:'',label:name})
  return [...names.values()]
})
const n=x=>Number(x||0).toLocaleString('zh-CN')
const stamp=x=>x?x.replace('T',' ').slice(0,19):'尚未同步'
const scope=()=>({start_date:dates.value[0],end_date:dates.value[1],brand:brand.value})
let internalRoute=false
async function saveUrl(){internalRoute=true;try{await router.replace({query:{...scope(),month:selectedMonth.value,batch:batchId.value||undefined,state:state.value,keyword:keyword.value||undefined,supplier:supplier.value||undefined,supplier_names:supplierNames.value.length?supplierNames.value:undefined,product_keys:productKeys.value.length?productKeys.value:undefined,page:page.value,...sort}})}finally{internalRoute=false}}
watch(()=>route.query,async q=>{if(internalRoute||route.path!=='/group-buy/inbound')return;brand.value=String(q.brand||'兰蔻');selectedMonth.value=String(q.month||defaultMonth);batchId.value=Number(q.batch)||null;dates.value=[String(q.start_date||`${defaultMonth}-01`),String(q.end_date||`${defaultMonth}-${currentEnd}`)];state.value=['pending','partial','waiting','done','excluded','mapping','suppliers'].includes(q.state)?q.state:q.state==='confirmed'?'done':'pending';keyword.value=String(q.keyword||'');supplier.value=String(q.supplier||'');supplierNames.value=queryValues(q.supplier_names);productKeys.value=queryValues(q.product_keys);page.value=Number(q.page)||1;Object.assign(sort,{sort_by:['receipt_time','receipt_number','item_count','pending_count'].includes(q.sort_by)?q.sort_by:'receipt_time',sort_order:q.sort_order==='asc'?'asc':'desc'});await loadOptions();await loadRows()})
async function loadOptions(){options.value=(await getInboundOptions()).data;if(!batches.value.some(b=>b.id===batchId.value))batchId.value=null}
let loadSequence=0
async function loadRows(){
  if(!dates.value?.[0]||!dates.value?.[1])return
  const token=++loadSequence
  loading.value=true;failure.value='';selection.value=[];table.value?.clearSelection()
  try{const result=await getInboundReceipts({...scope(),state:['mapping','suppliers'].includes(state.value)?'all':state.value,keyword:keyword.value,supplier:supplier.value,supplier_names:supplierNames.value,product_keys:productKeys.value,page:page.value,page_size:pageSize.value,...sort});if(token!==loadSequence)return;data.value=result.data;table.value?.clearSelection();await saveUrl()}
  catch{if(token===loadSequence)failure.value='读取失败，请重试。当前显示的结果未更新。'}finally{if(token===loadSequence)loading.value=false}
}
async function changeState(next){state.value=next;page.value=1;await loadRows()}
async function query(reset=true){if(busy.value||loading.value)return;if(reset)page.value=1;await loadRows()}
async function refresh(){
  if(!dates.value?.[0]||!dates.value?.[1])return ElMessage.warning('请选择入库日期')
  busy.value=true;failure.value=''
  try{const r=await syncInbound(scope());await loadOptions();page.value=1;await loadRows();ElMessage.success(`已同步${n(r.data.total)}条采集明细`)}
  catch{failure.value='同步未完成，上次成功结果仍保留。请检查采集连接后重试。'}finally{busy.value=false}
}
async function changeBrand(){supplier.value='';supplierNames.value=[];productKeys.value=[];batchId.value=null;await query()}
async function changeTarget(){if(!batches.value.some(b=>b.id===batchId.value))batchId.value=null;await query()}
async function sortChange({prop,order}){sort.sort_by=prop||'receipt_time';sort.sort_order=order==='ascending'?'asc':'desc';await query()}
function clearSelection(){table.value?.clearSelection();selection.value=[]}
function openMapping(row=null){if(!target.value)return ElMessage.warning('请先选择团购月份和批次');Object.assign(mapping,{supplier:row?.supplier||'',supplier_code:row?.supplier_code||'',source_id:''});const choice=supplierChoices.value.find(s=>s.name.replace(/\s+/g,' ').trim()===mapping.supplier);if(choice)mapping.supplier_code=choice.code;showMapping.value=true}
function chooseSupplier(name){const c=supplierChoices.value.find(s=>s.name===name);mapping.supplier_code=c?.code||''}
async function saveMapping(){
  if(!target.value||!mapping.supplier||!mapping.source_id)return ElMessage.warning('请选择供应商和下单柜台')
  const existing=aliases.value.find(a=>a.supplier===mapping.supplier.replace(/\s+/g,' ').trim())
  const counter=target.value.sources.find(s=>s.id===mapping.source_id)?.name
  if(existing&&existing.counter!==counter){try{await ElMessageBox.confirm(`将“${mapping.supplier}”由“${existing.counter}”改为“${counter}”？已有确认关联保留。`,'修改柜台对应',{type:'warning'})}catch{return}}
  busy.value=true
  try{await saveInboundMapping({...mapping,supplier_code:mapping.supplier_code||null,batch_id:target.value.id,revision:target.value.revision});showMapping.value=false;await loadOptions();await loadRows();ElMessage.success('柜台对应已保存')}catch{}finally{busy.value=false}
}
async function importCatalog(event){const file=event.target.files?.[0];if(!file)return;busy.value=true;try{const form=new FormData();form.append('file',file);const r=await importInboundSuppliers(form);await loadOptions();ElMessage.success(`已导入${n(r.data.imported)}条供应商档案`)}catch{}finally{busy.value=false;event.target.value=''}}
function back(){router.push({path:'/group-buy',query:{month:selectedMonth.value,brand:brand.value,batch:batchId.value||undefined,tab:'order'}})}
onMounted(async()=>{try{await loadOptions();await loadRows()}catch{failure.value='页面加载失败，请刷新重试'}})

const holdRecord=ref(null),showCollections=ref(false)
const documentId=ref(''),documentStatus={pending:'待处理',partial:'部分处理',waiting:'待补下单表',done:'已处理',excluded:'已排除'}
const emptyText=computed(()=>`暂无${documentStatus[state.value]||''}入库单`)
function openDocument(row){documentId.value=row.doc_id}
function selectDocuments(){clearSelection();for(const row of data.value.rows)if(state.value==='excluded'||row.pending_count>0)table.value?.toggleRowSelection(row,true)}
async function documentChanged(){await loadOptions();await loadRows()}
async function bulkDocumentAction(){
  const restoring=state.value==='excluded'
  const rows=selection.value.flatMap(d=>d.lines.filter(r=>restoring?r.status==='excluded':['pending','ready'].includes(r.status)))
  if(!rows.length)return
  if(rows.length>1000)return ElMessage.warning('一次最多处理1000项，请减少所选入库单')
  let note
  try{note=(await ElMessageBox.prompt(`处理所选 ${selection.value.length} 张单中的 ${rows.length} 条${restoring?'已排除':'未处理'}明细，已关联明细保留。`,restoring?'恢复所选':'批量排除',{inputPlaceholder:'处理原因',inputValidator:v=>!!v?.trim()&&v.trim().length<=500||'请填写500字以内原因'})).value}catch{return}
  busy.value=true
  try{await actInbound({action:restoring?'release':'exclude',lines:rows.map(r=>({id:r.id,revision:r.revision})),note});await loadRows();ElMessage.success('处理完成')}catch{}finally{busy.value=false}
}
</script>

<template>
  <section class="inbound-page">
    <header class="heading"><div><el-button link @click="back">← 柜台下单表</el-button><h2>采购入库关联</h2></div><div class="heading-buttons"><el-button @click="showCollections=true">下单表收集</el-button><el-button type="primary" :loading="busy" :disabled="loading" @click="refresh">同步采集数据</el-button></div></header>
    <div class="filters">
      <el-select v-model="brand" aria-label="入库品牌" @change="changeBrand" :disabled="busy||loading"><el-option v-for="b in options.brands" :key="b" :value="b" :label="b" /></el-select>
      <el-date-picker v-model="dates" type="daterange" value-format="YYYY-MM-DD" start-placeholder="入库开始日期" end-placeholder="入库结束日期" range-separator="至" :clearable="false" @change="query()" :disabled="busy||loading" />
      <el-select v-model="supplier" filterable clearable placeholder="全部往来单位" aria-label="往来单位筛选" @change="query()" :disabled="busy||loading"><el-option v-for="s in data.suppliers" :key="s" :value="s" :label="s" /></el-select>
      <el-input v-model="keyword" clearable placeholder="入库单号 / 条码 / 商品" aria-label="入库搜索" @keyup.enter="query()" @clear="query()" :disabled="busy||loading" /><el-button @click="query()" :disabled="busy||loading">查询</el-button><InboundColumnFilter v-model="productKeys" label="入库商品" :options="data.product_filters" :disabled="busy||loading" @change="query()"/>
    </div>
    <div class="target-bar"><strong>默认归属</strong><el-date-picker v-model="selectedMonth" type="month" value-format="YYYY-MM" :clearable="false" aria-label="归属月份" @change="changeTarget" :disabled="busy||loading"/><el-select v-model="batchId" clearable placeholder="选择批次" aria-label="归属批次" @change="query()" :disabled="busy||loading"><el-option v-for="b in batches" :key="b.id" :value="b.id" :label="b.name"/></el-select><span class="updated">采集更新 {{stamp(data.source_updated_at)}} · 本地同步 {{stamp(data.synced_at)}}</span></div>
    <el-alert v-if="failure" :title="failure" type="error" show-icon :closable="false"/>
    <div class="panel" v-loading="loading">
      <div class="panel-top"><el-radio-group v-model="state" @change="changeState" :disabled="busy||loading"><el-radio-button value="pending">待处理 {{n((data.summary.pending||0)+(data.summary.partial||0))}}</el-radio-button><el-radio-button value="waiting">待补下单表 {{n(data.summary.waiting)}}</el-radio-button><el-radio-button value="partial">部分处理 {{n(data.summary.partial)}}</el-radio-button><el-radio-button value="done">已处理 {{n(data.summary.done)}}</el-radio-button><el-radio-button value="excluded">已排除 {{n(data.summary.excluded)}}</el-radio-button><el-radio-button value="mapping">柜台对应</el-radio-button><el-radio-button value="suppliers">供应商档案</el-radio-button></el-radio-group></div>
      <template v-if="!['mapping','suppliers'].includes(state)">
        <div class="actions"><el-button @click="selectDocuments" :disabled="busy||loading||!data.rows.length">全选本页</el-button><template v-if="selection.length"><strong>已选 {{selection.length}} 张单</strong><el-button @click="bulkDocumentAction" :disabled="busy||loading">{{state==='excluded'?'恢复所选':'排除所选未处理商品'}}</el-button><el-button link @click="clearSelection">取消选择</el-button></template><span class="quiet">上海仓库新 · 当前品牌</span></div>
        <div class="table-area"><el-table ref="table" :data="data.rows" row-key="doc_id" height="100%" @sort-change="sortChange" @selection-change="selection=$event" :empty-text="emptyText">
          <el-table-column type="selection" width="44" :selectable="row=>!busy&&!loading&&(state==='excluded'||row.pending_count>0)"/>
          <el-table-column label="入库单号" prop="receipt_number" min-width="200" sortable="custom"><template #default="{row}"><el-button link type="primary" @click="openDocument(row)">{{row.receipt_number}}</el-button></template></el-table-column>
          <el-table-column label="入库日期" prop="receipt_time" width="175" sortable="custom"><template #default="{row}">{{stamp(row.receipt_time)}}</template></el-table-column>
          <el-table-column prop="supplier" label="往来单位" min-width="200"><template #header><InboundColumnFilter v-model="supplierNames" label="往来单位" :options="data.supplier_filters" :disabled="busy||loading" @change="query()"/></template></el-table-column>
          <el-table-column label="商品项数" prop="item_count" width="110" align="right" sortable="custom"/>
          <el-table-column label="已处理 / 未处理" width="155" align="center"><template #default="{row}">{{row.processed_count}} / {{row.pending_count}}</template></el-table-column>
          <el-table-column label="状态 / 归属" min-width="210"><template #default="{row}"><el-tag :type="row.pending_count?'warning':'success'">{{documentStatus[row.status]}}</el-tag><div v-if="row.status==='waiting'" class="quiet">{{row.hold.month}} · {{row.hold.counter}}</div><div v-for="label in row.destinations" :key="label" class="quiet">{{label}}</div></template></el-table-column>
          <el-table-column label="操作" width="230" fixed="right"><template #default="{row}"><el-button link type="primary" @click="openDocument(row)">{{row.status==='waiting'?'补齐后匹配':row.pending_count?'处理':'查看'}}</el-button><el-button v-if="row.pending_count>0" link @click="holdRecord=row" :disabled="busy||loading">{{row.status==='waiting'?'修改待补信息':'待补下单表'}}</el-button></template></el-table-column>
        </el-table></div>
        <footer><span>共 {{n(data.total)}} 张入库单</span><el-pagination v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[30,50,100]" :total="data.total" layout="sizes,prev,pager,next" @current-change="query(false)" @size-change="query()"/></footer>
      </template>
      <template v-else-if="state==='mapping'"><div class="actions"><el-button type="primary" @click="openMapping()" :disabled="busy||!target">新增柜台对应</el-button></div><div class="table-area"><el-table height="100%" :data="aliases" empty-text="先选择归属批次，再建立供应商与柜台对应"><el-table-column prop="supplier_code" label="供应商编号" width="140"/><el-table-column prop="supplier" label="吉客云往来单位" min-width="250"/><el-table-column prop="counter" label="团购柜台" min-width="180"/><el-table-column label="操作" width="100"><template #default="{row}"><el-button link type="primary" @click="openMapping(row)" :disabled="busy||!target">修改</el-button></template></el-table-column></el-table></div></template>
      <template v-else><div class="actions"><el-input v-model="catalogSearch" placeholder="搜索供应商编号、名称或分类" clearable aria-label="供应商档案搜索" @input="catalogPage=1"/><el-button @click="importInput.click()" :disabled="busy">导入供应商档案</el-button><input ref="importInput" type="file" accept=".xlsx" hidden @change="importCatalog"/></div><div class="table-area"><el-table height="100%" :data="suppliers.slice((catalogPage-1)*30,catalogPage*30)" empty-text="暂无供应商档案"><el-table-column prop="code" label="供应商编号" width="150"/><el-table-column prop="name" label="供应商名称" min-width="280"/><el-table-column prop="category" label="原分类" min-width="130"/><el-table-column prop="alias" label="别名" min-width="180"/></el-table></div><footer><span>共 {{n(suppliers.length)}} 条</span><el-pagination v-model:current-page="catalogPage" :total="suppliers.length" :page-size="30" layout="prev,pager,next"/></footer></template>
    </div>
    <ReceiptHoldDialog :record="holdRecord" :brand="brand" :month="selectedMonth" :options="options" @close="holdRecord=null" @changed="documentChanged"/><OrderCollectionDialog v-model="showCollections" :brand="brand" :month="selectedMonth" :options="options"/>
    <InboundReceiptDrawer v-model="documentId" :brand="brand" :options="options" :initial-batch="batchId" @changed="documentChanged"/>
    <el-dialog v-model="showMapping" title="往来单位对应柜台" width="550px" :close-on-click-modal="false"><el-form label-position="top"><el-form-item label="供应商 / 往来单位"><el-select v-model="mapping.supplier" filterable allow-create placeholder="搜索供应商名称或编号" @change="chooseSupplier"><el-option v-for="s in supplierChoices" :key="s.code||s.name" :value="s.name" :label="s.label"/></el-select></el-form-item><el-form-item label="团购下单柜台"><el-select v-model="mapping.source_id" placeholder="选择当前批次柜台"><el-option v-for="s in target?.sources||[]" :key="s.id" :value="s.id" :label="s.name"/></el-select></el-form-item></el-form><template #footer><el-button @click="showMapping=false" :disabled="busy">取消</el-button><el-button type="primary" @click="saveMapping" :loading="busy">保存对应</el-button></template></el-dialog>

  </section>
</template>

<style scoped>
.heading-buttons{display:flex;gap:10px;flex-wrap:wrap}
.receipt-card-title{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:14px}.receipt-card-title>span{color:var(--text-soft);font-size:12px}.comparison-heading{font-size:15px;margin:22px 0 12px}.comparison-target,.comparison-source{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:12px;align-items:center}.comparison-target :deep(.el-date-editor){width:150px;flex:none}.comparison-target>.el-select{width:190px}.comparison-source>.el-select{flex:1}.comparison-table-title{display:flex;align-items:center;gap:12px;justify-content:space-between;margin:14px 0;font-size:13px}.comparison-table-title>.el-input{width:280px}.source-details{margin-top:20px}.source-details>summary{cursor:pointer;font-size:12px;color:var(--text-soft);margin-bottom:12px}:deep(.matching-order){--el-table-tr-bg-color:var(--el-color-success-light-9)}.bulk-toolbar.has-selection{background:var(--el-color-primary-light-9)}.selected-summary{font-size:13px;font-weight:600}.selection-hint{font-size:12px;color:var(--text-soft);line-height:1.5}.bulk-toolbar>.quiet{margin-left:0}.table-area{flex:1;min-width:0;min-height:0;overflow:hidden}.heading,.filters,.target-bar{flex-shrink:0}.processing-reason{margin-top:20px}.processing-help{color:var(--text-soft);font-size:13px;line-height:1.7}.processing-actions{display:flex;flex-wrap:wrap;gap:10px}.processing-actions .el-button{margin:0}.overage{font-size:12px;line-height:1.7;color:var(--el-color-warning,#b88230)}
.inbound-page{display:flex;flex-direction:column;flex:1;min-width:0;min-height:0;width:100%;max-width:100%;box-sizing:border-box;color:var(--text-main,#303133)}.heading,.filters,.target-bar,.actions,.panel-top,footer{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.heading{justify-content:space-between;margin-bottom:20px}.heading h2{font-size:21px;margin:8px 0 0}.heading .el-button.is-link{font-size:13px}.filters{margin-bottom:12px}.filters>.el-select{width:180px}.filters>.el-input{width:235px}.filters :deep(.el-date-editor){width:285px;flex:none}.target-bar{padding:14px 0 20px}.target-bar strong{font-size:14px}.target-bar :deep(.el-date-editor){width:150px;flex:none}.target-bar>.el-select{width:180px}.updated{margin-left:auto;font-size:12px;color:var(--text-soft,#909399)}.panel{display:flex;flex-direction:column;flex:1;min-width:0;min-height:0;max-width:100%;background:var(--surface,#fff);border:1px solid var(--border-color,#e4e7ed);border-radius:7px;overflow:hidden}.panel-top{flex:none;padding:16px;border-bottom:1px solid var(--border-color,#ebeef5)}.actions{flex:none;padding:12px 16px}.actions>.el-input{width:300px}.quiet{font-size:12px;line-height:1.7;color:var(--text-soft,#909399)}.actions>.quiet{margin-left:auto}.receipt-no{font-variant-numeric:tabular-nums}.panel :deep(.el-table .cell){word-break:break-word}.panel :deep(.el-tag){max-width:100%;height:auto;white-space:normal;line-height:1.5;padding:4px 7px}footer{flex:none;padding:12px 16px;justify-content:space-between;font-size:12px;color:var(--text-soft,#909399)}.el-alert{margin-bottom:14px}.el-form :deep(.el-select){width:100%}.history-entry{padding:16px 0;border-bottom:1px solid var(--border-color,#ebeef5)}.history-entry span{display:block;color:var(--text-soft,#909399);font-size:12px;margin-top:6px}.history-entry p{white-space:pre-wrap}@media(max-width:900px){.updated{margin-left:0}.filters :deep(.el-date-editor){width:100%}.actions>.quiet{margin-left:0}.panel-top{overflow-x:auto}}
@media(max-height:650px){.inbound-page{min-height:560px;flex-shrink:0}}
</style>
