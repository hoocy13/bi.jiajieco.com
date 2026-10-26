<script setup>
import { computed, onMounted, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { aggregateGroupBuy, formatCents, formatPrice, groupBuyArrivalTotals } from '../../utils/groupBuyTotals'
import { getInboundProgress } from '../../api/groupBuy'
import { listGroupBatches, createGroupBatch, renameGroupBatch, deleteGroupBatch, restoreGroupBatch, getGroupTable, saveGroupCells, addGroupColumn, addGroupQuota, addGroupProduct, updateGroupProduct, deleteGroupItem, renameGroupItem, lookupGroupProduct, setGroupStatus, getGroupHistory, importGroupFiles, exportGroupBatch } from '../../api/groupBuy'

const route = useRoute(), router = useRouter()
const today = new Date()
const month = ref(String(route.query.month || `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}`))
const brand = ref(String(route.query.brand || '兰蔻'))
const brands = ['兰蔻', '资生堂', 'YSL', '植村秀', '赫莲娜']
const batches = ref([]), batchId = ref(Number(route.query.batch) || null), data = ref(null), loading = ref(false), busy = ref(false)
const tab = ref(route.query.tab === 'log' ? 'log' : 'order')
const showArrival=ref(route.query.arrivals==='true'),arrival=ref(null),arrivalLoading=ref(false),arrivalError=ref(false)
const receiptDrawer=ref(false),receiptDetails=ref([]),receiptTitle=ref('入库明细')
let arrivalSequence=0
async function loadArrival(){
  const token=++arrivalSequence,id=batchId.value
  if(!id||tab.value!=='order'){arrival.value=null;return}
  arrivalLoading.value=true;arrivalError.value=false;arrival.value=null
  try{const r=await getInboundProgress(id);if(token===arrivalSequence&&id===batchId.value)arrival.value=r.data}
  catch{if(token===arrivalSequence)arrivalError.value=true}finally{if(token===arrivalSequence)arrivalLoading.value=false}
}
watch([batchId,tab],loadArrival)
let receiptSequence=0
async function openReceipt(row,c){
  const token=++receiptSequence
  receiptTitle.value=`${row.code} · ${sourceName(c.source_id)} · 入库明细`;receiptDetails.value=[];receiptDrawer.value=true
  try{const r=await getInboundProgress(batchId.value,{product_id:row.id,source_id:c.source_id});if(token===receiptSequence)receiptDetails.value=r.data.details}catch{}
}
function arrivalValue(row,c){
  if(!arrival.value)return null
  const received=arrival.value.received[`${row.id}:${c.source_id}`]||0
  if(c.kind==='received')return (arrival.value.normal_received||arrival.value.received)[`${row.id}:${c.source_id}`]||0
  if(c.kind==='substitute')return arrival.value.substituted?.[`${row.id}:${c.source_id}`]||0
  return Math.max(value(row,'order',c.source_id)-received,0)
}
function overReceipt(row,c){return arrival.value?Math.max((arrival.value.received[`${row.id}:${c.source_id}`]||0)-value(row,'order',c.source_id),0):0}
async function openInbound(){if(!await discardGuard())return;router.push({path:'/group-buy/inbound',query:{month:month.value,brand:brand.value,batch:batchId.value||undefined}})}
const filters = reactive({ keyword: String(route.query.keyword || ''), source: String(route.query.source || ''), customer: '', only_gap: route.query.only_gap === 'true', sort_by: String(route.query.sort_by || 'position'), sort_order: route.query.sort_order === 'desc' ? 'desc' : 'asc' })
const quotaWarningClosedFor = ref(null)
const pending = ref({}), conflict = ref(false), selected = ref(null), logs = ref([]), logPage = ref(1), logTotal = ref(0)
const selectedName=ref('')
const nameChanged=computed(()=>!!selected.value && selectedName.value!==selected.value.name)
watch(()=>selected.value?.id,()=>{selectedName.value=selected.value?.name||''})
async function discardNameGuard(){
  if(!nameChanged.value)return true
  try{await ElMessageBox.confirm('商品名称尚未保存，是否放弃修改？','未保存修改',{confirmButtonText:'放弃修改',cancelButtonText:'继续编辑',type:'warning'});selectedName.value=selected.value.name;return true}catch{return false}
}
async function openDetails(row){if(busy.value||loading.value||!await discardNameGuard())return;selected.value=row}
async function rowDetails(event,row){if(event.target.closest('input,button,a,[role="button"]'))return;await openDetails(row)}
async function closeDetails(done){if(busy.value||!await discardNameGuard())return;selected.value=null;if(typeof done==='function')done()}
async function saveSelectedName(){
  if(!nameChanged.value||busy.value||locked.value||conflict.value)return
  const name=selectedName.value.trim()
  if(!name)return ElMessage.warning('产品名称不能为空')
  const row=selected.value
  const values=Object.fromEntries(['code','name','barcode','price','abc','pcb'].map(k=>[k,row[k]]))
  const ok=await mutate(()=>updateGroupProduct(batchId.value,row.id,{...values,name,revision:data.value.batch.revision}))
  if(ok){selected.value=data.value.rows.find(p=>p.id===row.id)||{...row,name};selectedName.value=name}
}
const defaultFields=['code','name','price','abc','pcb','quota','received_total','waiting_total','allocated','remaining']
function readPreference(key,fallback){try{return JSON.parse(localStorage.getItem(key))??fallback}catch{return fallback}}
const legacyFields=readPreference('group-buy.fields',defaultFields)
const storedFields=readPreference('group-buy.fields.v2',Array.isArray(legacyFields)?[...legacyFields,'received_total','waiting_total']:defaultFields)
const shownFields=ref(Array.isArray(storedFields)?[...new Set([...storedFields.filter(k=>[...defaultFields,'barcode'].includes(k)),'name'])]:defaultFields)
const hiddenColumns=ref([]),hiddenSources=ref([]),columnSettingsTab=ref('fields')
watch(shownFields,value=>{try{localStorage.setItem('group-buy.fields.v2',JSON.stringify(value))}catch{}},{deep:true})
watch(batchId,id=>{
  const pref=readPreference(`group-buy.columns.${id}`,{})
  hiddenColumns.value=Array.isArray(pref?.columns)?pref.columns:[]
  hiddenSources.value=Array.isArray(pref?.sources)?pref.sources:[]
},{immediate:true})
function toggleColumn(kind,id,visible){const target=kind==='sources'?hiddenSources:hiddenColumns;target.value=visible?target.value.filter(k=>k!==id):[...new Set([...target.value,id])];saveColumnPreference()}
function saveColumnPreference(){try{localStorage.setItem(`group-buy.columns.${batchId.value}`,JSON.stringify({columns:hiddenColumns.value,sources:hiddenSources.value}))}catch{}}
function resetColumns(){shownFields.value=[...defaultFields];hiddenColumns.value=[];hiddenSources.value=[];saveColumnPreference()}
const headerRow=ref(null),headerHeight=ref(34)
let headerObserver=null
watch(headerRow,element=>{
  headerObserver?.disconnect()
  if(element){headerObserver=new ResizeObserver(()=>{headerHeight.value=element.getBoundingClientRect().height});headerObserver.observe(element)}
})
onBeforeUnmount(()=>headerObserver?.disconnect())
const showCreate = ref(false), showImport = ref(false), showColumn = ref(false), showQuota = ref(false), showProduct = ref(false)
const showBatchManager = ref(false), showDeletedBatches = ref(false), managedBatches = ref([]), managerLoading = ref(false)
const editingProduct = ref(null), allBatches = ref([]), createForm = reactive({ month: month.value, brand: brand.value, name: '第一批', copy_from: null })
const importFiles = reactive({ order: null, allocation: null }), preview = ref(null)
const columnForm = reactive({ source: '', customer: '', counter: false })
const quotaForm = reactive({ product_id: '', source: '', mode: 'set', quantity: 0, note: '' })
const productForm = reactive({ code: '', name: '', barcode: '', price: 0, abc: '', pcb: null })
const productLookup=ref(null),lookupBusy=ref(false),manualIdentity=ref(false)
watch(manualIdentity,manual=>{if(!manual&&productLookup.value?.status==='matched'){productForm.name=productLookup.value.product.name;productForm.barcode=productLookup.value.product.barcode}})
let lookupSequence=0,lookupCode=''
watch(()=>productForm.code,()=>{
  lookupSequence++;lookupBusy.value=false;productLookup.value=null;manualIdentity.value=false
  if(showProduct.value){productForm.name='';productForm.barcode=''}
},{flush:'sync'})
watch(showProduct,visible=>{if(!visible){lookupSequence++;lookupBusy.value=false}})
async function lookupProduct(force=false){
  const code=productForm.code.trim()
  if(!code||!showProduct.value)return false
  if(lookupBusy.value&&lookupCode===code)return false
  if(!force&&originalProduct.value&&code===originalProduct.value.code&&!productLookup.value)return true
  if(!force&&productLookup.value?.status==='matched'&&productLookup.value.product.code===code)return true
  const sequence=++lookupSequence;lookupCode=code;lookupBusy.value=true
  try{
    const result=(await lookupGroupProduct(code)).data
    if(sequence!==lookupSequence||!showProduct.value||productForm.code.trim()!==code)return false
    if(result.status==='matched'){
      productForm.code=result.product.code
      productForm.name=result.product.name;productForm.barcode=result.product.barcode;manualIdentity.value=false
    }
    productLookup.value=result
    return result.status==='matched'
  }catch{if(sequence===lookupSequence)productLookup.value={status:'error',message:'商品库暂不可用，请稍后重试'};return false}
  finally{if(sequence===lookupSequence||productLookup.value?.status==='matched')lookupBusy.value=false}
}
const productOptions = ref([])
const showStructure = ref(false), structureKind = ref('products'), structureSearch = ref(''), structureData = ref(null)
const structureLoading = ref(false)
const structureRows = computed(() => {
  const d = structureData.value
  if (!d) return []
  let rows = structureKind.value === 'products' ? d.rows : structureKind.value === 'sources' ? d.sources : d.all_columns.map(c => ({...c, source: d.sources.find(s=>s.id===c.source_id)?.name}))
  const q = structureSearch.value.trim().toLowerCase()
  return rows.filter(r => !q || [r.code,r.name,r.barcode,r.source,r.customer,r.origin].filter(Boolean).join(' ').toLowerCase().includes(q))
})
async function loadStructure() {
  structureLoading.value = true
  try { structureData.value = (await getGroupTable(batchId.value, {all_rows:true})).data }
  finally { structureLoading.value = false }
}
async function openStructure(kind) {
  if (busy.value || !await discardGuard()) return
  structureKind.value = kind; structureSearch.value = ''; structureData.value=null; showStructure.value = true
  await loadStructure()
}
async function renameItem(kind, row) {
  if (busy.value || locked.value || !await discardGuard()) return
  let answer
  try { answer = await ElMessageBox.prompt(kind==='columns'?'修改此来源下的客户名称，数量保留。':'来源改名会同步显示在下单表和分配表，数量保留。', '修改名称', {
    inputValue:kind==='columns'?row.customer:row.name, inputValidator:v=>(!!v?.trim()&&v.trim().length<=128)||'名称须为1至128个字符', confirmButtonText:'保存名称',cancelButtonText:'取消',
  }) } catch { return }
  await mutate(async()=>{
    await renameGroupItem(batchId.value,kind,row.id,{revision:data.value.batch.revision,name:answer.value.trim()})
    if(kind==='columns' && filters.customer===row.customer) filters.customer=''
  })
}
async function removeItem(kind, row) {
  if (busy.value || locked.value || !await discardGuard()) return
  const products = structureData.value?.batch.id===batchId.value ? structureData.value.rows : data.value.rows
  let name, impact
  if (kind==='products') {
    name = `${row.code} ${row.name}`
    impact = `同时从下单表和分配表移除此商品，包含下单${n(sum(Object.values(row.orders)))}件、客户分配${n(sum(Object.values(row.allocations)))}件及全部额度。`
  } else if (kind==='columns') {
    name = `${sourceName(row.source_id)} / ${row.customer}${row.origin?'（'+row.origin+'）':''}`
    impact = `移除此客户列及其全部商品分配，共${n(sum(products.map(p=>p.allocations[row.id])))}件；来源额度和柜台下单量保留。`
  } else {
    name = row.name
    const cols = (structureData.value?.all_columns || []).filter(c=>c.source_id===row.id)
    impact = `同时移除此来源在下单表的柜台列、${cols.length}个客户列和全部额度，包含下单${n(sum(products.map(p=>p.orders[row.id])))}件、分配${n(sum(products.flatMap(p=>cols.map(c=>p.allocations[c.id]))))}件。`
  }
  try { await ElMessageBox.confirm(`确定删除“${name}”吗？${impact}删除仅影响当前批次，记录保留；暂不支持一键恢复。`, '删除'+(kind==='products'?'商品':kind==='columns'?'客户列':'来源 / 柜台'), {type:'warning',confirmButtonText:'确认删除',cancelButtonText:'取消'}) } catch { return }
  const ok = await mutate(async()=>{
    await deleteGroupItem(batchId.value,kind,row.id,data.value.batch.revision)
    if (kind==='sources' && filters.source===row.id) filters.source=''
    if (kind==='columns' && filters.customer===row.customer) filters.customer=''
    selected.value=null
  })
  if (ok && kind==='products') showProduct.value=false
}
let applied = null, seq = 0, internalRoute = false, lastTab = tab.value
const count = computed(() => Object.keys(pending.value).length)
const expandedTotals=ref([])
const showQuantityTotal=computed(()=>expandedTotals.value.includes('quantity'))
const showAmountTotal=computed(()=>expandedTotals.value.includes('amount'))
watch(batchId,()=>{expandedTotals.value=[]})
const locked = computed(() => data.value?.batch.status === 'confirmed')
const n = x => x == null ? '待维护' : Number(x).toLocaleString('zh-CN')
const money = formatPrice
const sum = arr => arr.reduce((a,b)=>a+Number(b||0),0)
const sourceName = id => data.value?.sources.find(s=>s.id===id)?.name || id
function key(p, kind, column) { return `${p}:${kind}:${column}` }
function value(row, kind, column) { return pending.value[key(row.id,kind,column)]?.quantity ?? (kind === 'order' ? row.orders[column] : row.allocations[column]) ?? 0 }
const sourceGroups = computed(() => {
  if (!data.value) return []
  const sources=data.value.sources.filter(s=>!hiddenSources.value.includes(s.id))
  const columns=data.value.columns.filter(c=>!hiddenColumns.value.includes(c.id)&&!hiddenSources.value.includes(c.source_id))
  if (tab.value === 'order') return sources.filter(s=>s.counter && (!filters.source || s.id===filters.source)).map(s=>({ id:s.id, name:s.name, cols:[{ id:s.id, source_id:s.id,kind:'order',label:showArrival.value?'下单':'下单数量',heading:s.name },...(showArrival.value?[{id:`${s.id}:received`,source_id:s.id,kind:'received',label:'正常到货',heading:s.name},{id:`${s.id}:substitute`,source_id:s.id,kind:'substitute',label:'替代到货',heading:s.name},{id:`${s.id}:waiting`,source_id:s.id,kind:'waiting',label:'待入库',heading:s.name}]:[])] }))
  return sources.map(s=>({ id:s.id, name:s.name, cols:columns.filter(c=>c.source_id===s.id).map(c=>({ ...c, label:c.customer, duplicate:data.value.all_columns.filter(x=>x.source_id===c.source_id && x.customer===c.customer).length>1 })) })).filter(s=>s.cols.length)
})
const visibleColumns = computed(()=>sourceGroups.value.flatMap(s=>s.cols))
const dimensionChoices = computed(()=>[
  { key:'code', label:'产品代码', width:108 }, { key:'name', label:'产品名称', width:220 },
  {key:'barcode',label:'国际条形码',width:132},
  {key:'price',label:'价格',width:82},{key:'abc',label:'ABC',width:48},{key:'pcb',label:'PCB',width:50},
  {key:'quota',label:tab.value==='order'?'下单合计':'分配额度',width:76},...(tab.value==='order'?[{key:'received_total',label:'已入库合计',width:88},{key:'waiting_total',label:'待入库合计',width:88}]:[]),...(tab.value==='allocation'?[{key:'allocated',label:'已分配',width:72},{key:'remaining',label:'剩余',width:74}]:[]),
].map(d=>showAmountTotal.value&&sheetTotals.value.summary[d.key]?{...d,width:Math.max(d.width,Math.min(190,formatCents(sheetTotals.value.summary[d.key].amount).length*7+20))}:d))
const dimensions=computed(()=>dimensionChoices.value.filter(d=>shownFields.value.includes(d.key)).map((d,i,arr)=>({...d,left:sum(arr.slice(0,i).map(x=>x.width))})))
const columnWidths=computed(()=>new Map(visibleColumns.value.map(c=>{
  const labelWidth=Array.from(c.heading||c.label).reduce((n,char)=>n+(/[\u0000-\u007f]/.test(char)?7:13),0)+24
  const amountWidth=showAmountTotal.value?formatCents(sheetTotals.value.columns.get(c.id)?.amount).length*7+20:0
  const width=Math.min(260,Math.max(110,labelWidth,amountWidth))
  return [c.id,{width:`${width}px`,minWidth:`${width}px`,maxWidth:`${width}px`}]
})))
function columnStyle(c){return columnWidths.value.get(c.id)}
function style(d) { return {left:`${d.left}px`,width:`${d.width}px`,minWidth:`${d.width}px`,maxWidth:`${d.width}px`} }
function calculateTotal(row) {
  const quantities = {}, quotas = {...row.quotas}, orders = {}
  for(const s of data.value.sources) {
    orders[s.id] = value(row,'order',s.id)
    if(s.counter) quotas[s.id] = orders[s.id] + (row.quotas[s.id] ?? 0) - (row.orders[s.id] || 0)
    quantities[s.id] = sum(data.value.all_columns.filter(c=>c.source_id===s.id).map(c=>value(row,'allocation',c.id)))
  }
  const missing = data.value.sources.some(s=>quotas[s.id]==null && quantities[s.id]>0)
  const over = data.value.sources.some(s=>quotas[s.id]!=null && quantities[s.id]>quotas[s.id])
  const allocated = sum(Object.values(quantities)), quota = missing ? null : sum(Object.values(quotas))
  const counterAllocated = sum(data.value.sources.filter(s=>s.counter).map(s=>quantities[s.id]))
  return { allocated: tab.value==='order'?counterAllocated:allocated, quota:tab.value==='order'?sum(Object.values(orders)):quota, remaining:tab.value==='order'?sum(Object.values(orders))-counterAllocated:quota==null?null:quota-allocated, over, quantities, quotas }
}
// Reuse per-product aggregates while rendering the full editable matrix.
const productTotals = computed(() => new Map((data.value?.rows || []).map(row => [row.id, calculateTotal(row)])))
function total(row) { return productTotals.value.get(row.id) || calculateTotal(row) }
function columnQuantity(row,c){return tab.value==='order'&&c.kind!=='order'?arrivalValue(row,c):value(row,tab.value==='order'?'order':'allocation',c.id)}
const rowArrivals=computed(()=>new Map((data.value?.rows||[]).map(row=>[row.id,arrival.value?groupBuyArrivalTotals(row,data.value.sources,arrival.value.received,(p,id)=>value(p,'order',id)):{received_total:null,waiting_total:null,over_received:null}])))
const batchArrivalSummary=computed(()=>{
  if(!arrival.value?.summary||!data.value)return null
  const result={...arrival.value.summary}
  for(const cell of Object.values(pending.value)){
    if(cell.kind!=='order'||!data.value.sources.some(s=>s.id===cell.column_id&&s.counter))continue
    const row=data.value.rows.find(p=>p.id===cell.product_id)
    if(!row)continue
    const old=row.orders[cell.column_id]||0,received=arrival.value.received[`${row.id}:${cell.column_id}`]||0
    result.ordered+=cell.quantity-old
    result.waiting_total+=Math.max(cell.quantity-received,0)-Math.max(old-received,0)
    result.over_received+=Math.max(received-cell.quantity,0)-Math.max(received-old,0)
  }
  return result
})
const sheetTotals=computed(()=>aggregateGroupBuy(data.value?.rows||[],visibleColumns.value,columnQuantity,row=>({...total(row),...rowArrivals.value.get(row.id)}),tab.value==='order'?['quota','received_total','waiting_total']:['quota','allocated','remaining']))
const quantityText=x=>x==null?'—':Number(x)===0?'·':n(x)
function display(row, d) { if(['received_total','waiting_total'].includes(d.key))return quantityText(rowArrivals.value.get(row.id)?.[d.key]); if(d.key==='price') return money(row.price); if(['quota','allocated','remaining'].includes(d.key))return tab.value==='order'?quantityText(total(row)[d.key]):n(total(row)[d.key]); if(d.key==='pcb')return row.pcb == null ? '—' : n(row.pcb); return row[d.key] || '—' }
function edit(row,kind,column,raw,element) {
  if(locked.value || busy.value || loading.value || conflict.value)return
  const quantity = raw === '' || raw == null ? 0 : Number(raw)
  if(!Number.isSafeInteger(quantity)||quantity<0||quantity>100000000){if(element)element.value=value(row,kind,column)||'';ElMessage.warning('数量必须为非负整数');return}
  const k=key(row.id,kind,column), old=(kind==='order'?row.orders[column]:row.allocations[column])||0
  if(old===quantity)delete pending.value[k]
  else pending.value[k]={product_id:row.id,kind,column_id:column,quantity}
}
function pasteCells(event, row, column) {
  if (locked.value || busy.value || conflict.value) return
  event.preventDefault()
  const text = event.clipboardData?.getData('text/plain')?.replace(/\r/g,'').replace(/\n+$/,'') || ''
  if (!text) return
  const matrix = text.split('\n').map(r => r.split('\t'))
  if(tab.value==='order'&&showArrival.value&&matrix.some(r=>r.length>1)){ElMessage.warning('到货进度列只读，请先收起到货进度再粘贴多列');return}
  const startRow = data.value.rows.findIndex(p => p.id === row.id)
  const startCol = visibleColumns.value.findIndex(c => c.id === column.id)
  if (startRow + matrix.length > data.value.rows.length || matrix.some(r => startCol + r.length > visibleColumns.value.length)) {
    ElMessage.warning('粘贴范围超出当前商品或显示列，请缩小范围后重试'); return
  }
  if (matrix.some(r => r.some(v => v.trim() !== '' && (!/^\d+$/.test(v.trim()) || Number(v)>100000000)))) {
    ElMessage.warning('粘贴内容只能包含非负整数，空白按0处理'); return
  }
  matrix.forEach((r, i) => r.forEach((v, j) => edit(data.value.rows[startRow+i], tab.value==='order'?'order':'allocation', visibleColumns.value[startCol+j].id, v.trim())))
  ElMessage.success('已填入待保存修改，请核对后保存')
}
async function discardGuard() {
  if(!count.value&&!nameChanged.value)return true
  try { await ElMessageBox.confirm('当前有未保存修改。是否放弃这些修改？','未保存修改',{confirmButtonText:'放弃修改',cancelButtonText:'继续编辑',type:'warning'});pending.value={};if(selected.value)selectedName.value=selected.value.name;conflict.value=false;return true } catch { return false }
}
function beforeUnload(e){if(count.value||nameChanged.value){e.preventDefault();e.returnValue=''}}
onBeforeRouteLeave(async()=>await discardGuard())
onBeforeUnmount(()=>window.removeEventListener('beforeunload',beforeUnload))
async function syncUrl(){
  internalRoute = true
  try { await router.replace({query:{month:month.value,brand:brand.value,batch:batchId.value||undefined,tab:tab.value,arrivals:showArrival.value?'true':undefined,...Object.fromEntries(Object.entries(filters).filter(([,v])=>v!==''&&v!==false))}}) }
  finally { internalRoute = false }
}
watch(() => route.query, async q => {
  if (internalRoute || route.path !== '/group-buy') return
  if (!await discardGuard()) { await syncUrl(); return }
  month.value = String(q.month || month.value); brand.value = String(q.brand || brand.value)
  batchId.value = Number(q.batch) || null; tab.value = q.tab === 'log' ? 'log' : 'order'
  showArrival.value=q.arrivals==='true'
  Object.assign(filters, {keyword:String(q.keyword||''), source:String(q.source||''),customer:'',only_gap:q.only_gap==='true',sort_by:String(q.sort_by||'position'),sort_order:q.sort_order==='desc'?'desc':'asc'})
  await loadList(); await loadTable()
})
async function loadList(){const r=await listGroupBatches({month:month.value,brand:brand.value});batches.value=r.data.rows;if(!batches.value.some(b=>b.id===batchId.value))batchId.value=batches.value[0]?.id||null}
async function loadTable(){
  const current=++seq
  if(!batchId.value){data.value=null;syncUrl();return}
  loading.value=true
  try{const r=await getGroupTable(batchId.value,{...filters,all_rows:true});if(current!==seq)return;data.value=r.data;conflict.value=false;applied={month:month.value,brand:brand.value,batch:batchId.value,filters:{...filters}};syncUrl();if(tab.value==='log')await loadHistory();if(tab.value==='order')await loadArrival()}
  finally{if(current===seq)loading.value=false}
}
async function queryChange(list=false){if(!await discardGuard()){if(applied){month.value=applied.month;brand.value=applied.brand;batchId.value=applied.batch;Object.assign(filters,applied.filters)}return}selected.value=null;if(list)await loadList();await loadTable()}
async function changeTab(){if(!await discardGuard()){tab.value=lastTab;return}lastTab=tab.value;selected.value=null;syncUrl();if(tab.value==='log')await loadHistory()}
async function sort(d){if(!await discardGuard())return;filters.sort_order=filters.sort_by===d.key&&filters.sort_order==='asc'?'desc':'asc';filters.sort_by=d.key==='quota'&&tab.value==='order'?'ordered':d.key;await loadTable()}
async function save(){
  if(!count.value||busy.value)return
  busy.value=true
  try{await saveGroupCells(batchId.value,{revision:data.value.batch.revision,cells:Object.values(pending.value)});pending.value={};conflict.value=false;await loadTable();if(selected.value)selected.value=data.value.rows.find(r=>r.id===selected.value.id)||null;ElMessage.success('修改已保存')}
  catch(e){if(e.response?.status===409)conflict.value=true}
  finally{busy.value=false}
}
async function mutate(fn){if(busy.value)return;busy.value=true;try{await fn();await loadTable();if(showStructure.value)await loadStructure();ElMessage.success('操作已保存');return true}catch(e){if(e.response?.status===409)conflict.value=true;return false}finally{busy.value=false}}
async function openCreate(){if(!await discardGuard())return;allBatches.value=(await listGroupBatches({})).data.rows;Object.assign(createForm,{month:month.value,brand:brand.value,name:'第一批',copy_from:null});showCreate.value=true}
async function create(){if(!createForm.month||!createForm.name.trim())return ElMessage.warning('请填写月份和批次名称');await mutate(async()=>{const r=await createGroupBatch({...createForm});month.value=createForm.month;brand.value=createForm.brand;batchId.value=r.data.id;await loadList();showCreate.value=false})}
async function loadManagedBatches() {
  managerLoading.value = true
  try { managedBatches.value = (await listGroupBatches({ month: month.value, brand: brand.value, deleted: showDeletedBatches.value })).data.rows }
  finally { managerLoading.value = false }
}
async function openBatchManager() {
  showDeletedBatches.value = false
  showBatchManager.value = true
  await loadManagedBatches()
}
async function runBatchAction(row, task, message) {
  if (busy.value) return
  const previousBatchId = batchId.value
  const changesCurrent = row.id === previousBatchId
  busy.value = true
  try {
    await task()
    await loadList()
    await loadManagedBatches()
    if (changesCurrent || batchId.value !== previousBatchId) {
      selected.value = null; conflict.value = false; logPage.value = 1; logs.value = []
      await loadTable()
    }
    ElMessage.success(message)
  } catch (e) {
    if (e.response?.status === 409) await loadManagedBatches()
  } finally { busy.value = false }
}
async function renameBatch(row) {
  if (busy.value || (row.id === batchId.value && !await discardGuard())) return
  let answer
  try {
    answer = await ElMessageBox.prompt('请输入新的批次名称', '修改批次名称', {
      inputValue: row.name, inputPattern: /\S/, inputErrorMessage: '批次名称不能为空',
      inputValidator: v => (v.trim().length > 0 && v.trim().length <= 64) || '批次名称须为1至64个字符',
      confirmButtonText: '保存名称', cancelButtonText: '取消',
    })
  } catch { return }
  await runBatchAction(row, () => renameGroupBatch(row.id, { revision: row.revision, name: answer.value.trim() }), '批次名称已修改')
}
async function deleteBatch(row) {
  if (busy.value || (row.id === batchId.value && !await discardGuard())) return
  try {
    await ElMessageBox.confirm(
      `确定删除“${row.month} ${row.brand} ${row.name}”吗？该批次包含${row.summary.product_count}件商品。删除后移入回收站，商品、下单、额度、分配及修改记录均保留，可在回收站恢复。`,
      '删除批次', { type: 'warning', confirmButtonText: '移入回收站', cancelButtonText: '取消' },
    )
  } catch { return }
  await runBatchAction(row, () => deleteGroupBatch(row.id, row.revision), '批次已移入回收站')
}
async function restoreBatch(row) {
  await runBatchAction(row, () => restoreGroupBatch(row.id, row.revision), '批次已恢复')
}
async function openManagedBatch(row) {
  if (busy.value || !await discardGuard()) return
  batchId.value = row.id; selected.value = null; showBatchManager.value = false
  logPage.value = 1; await loadTable()
}
async function openImport(){if(!await discardGuard())return;importFiles.order=null;importFiles.allocation=null;preview.value=null;showImport.value=true}
function fileChanged(kind,file){importFiles[kind]=file?.raw||null;preview.value=null}
function importData(){const f=new FormData();f.append('revision',data.value.batch.revision);if(importFiles.order)f.append('order_file',importFiles.order);if(importFiles.allocation)f.append('allocation_file',importFiles.allocation);return f}
async function importPreview(){busy.value=true;try{preview.value=(await importGroupFiles(batchId.value,'preview',importData())).data}finally{busy.value=false}}
async function importApply(){if(!preview.value)return;await mutate(async()=>{await importGroupFiles(batchId.value,'apply',importData());showImport.value=false})}
async function openColumn(){if(!await discardGuard())return;Object.assign(columnForm,{source:'',customer:'',counter:false});showColumn.value=true}
async function submitColumn(){if(!columnForm.source.trim()||(!columnForm.customer.trim()&&!columnForm.counter))return ElMessage.warning('请填写来源及客户，或勾选下单柜台');await mutate(async()=>{await addGroupColumn(batchId.value,{revision:data.value.batch.revision,...columnForm});showColumn.value=false})}
async function openQuota(row=null){if(!await discardGuard())return;productOptions.value=(await getGroupTable(batchId.value,{page:1,page_size:100,keyword:row?.code||''})).data.rows;Object.assign(quotaForm,{product_id:row?.id||productOptions.value[0]?.id||'',source:'',mode:'set',quantity:0,note:''});showQuota.value=true}
async function searchProducts(keyword){productOptions.value=(await getGroupTable(batchId.value,{keyword,page_size:100})).data.rows}
async function submitQuota(){if(!quotaForm.product_id||!quotaForm.source.trim()||!quotaForm.note.trim())return ElMessage.warning('请选择商品并填写来源和调整原因');await mutate(async()=>{await addGroupQuota(batchId.value,{revision:data.value.batch.revision,...quotaForm});showQuota.value=false;selected.value=null})}
const productFieldLabels={code:'产品代码',name:'产品名称',barcode:'条形码',price:'价格',abc:'ABC',pcb:'PCB'}
const activeProductField=ref('')
const originalProduct=ref(null)
const productInputs=ref({})
function focusProductField(){const field=Object.keys(productFieldLabels).find(k=>productFieldLabels[k]===activeProductField.value)||'code';productInputs.value[field]?.focus()}
async function removeEditingProduct(){if(originalProduct.value)await removeItem('products',originalProduct.value)}
async function openProduct(row=null,field=''){if(locked.value||busy.value||!await discardGuard())return;editingProduct.value=row?.id||null;originalProduct.value=row;productLookup.value=null;manualIdentity.value=false;activeProductField.value=productFieldLabels[field]||'';Object.assign(productForm,row?{code:row.code,name:row.name,barcode:row.barcode,price:Number(row.price),abc:row.abc,pcb:row.pcb}:{code:'',name:'',barcode:'',price:0,abc:'',pcb:null});showProduct.value=true}
async function submitProduct(){
  if(busy.value||lookupBusy.value)return
  if(!productForm.code.trim())return ElMessage.warning('请填写产品代码')
  if(!manualIdentity.value&&(!originalProduct.value||productForm.code.trim()!==originalProduct.value.code)){
    if(!await lookupProduct())return ElMessage.warning('请核对产品代码；确需手填时开启手动填写')
  }
  if(!productForm.name.trim())return ElMessage.warning('请填写产品名称')
  await mutate(async()=>{if(editingProduct.value)await updateGroupProduct(batchId.value,editingProduct.value,{revision:data.value.batch.revision,...productForm});else await addGroupProduct(batchId.value,{revision:data.value.batch.revision,...productForm});showProduct.value=false;selected.value=null})
}
async function toggleStatus(){if(!await discardGuard())return;try{await ElMessageBox.confirm(locked.value?'重新开放后可继续修改，操作会留痕。':'确认后锁定数量；额度待维护或来源超配时无法确认。','批次状态',{type:'warning'})}catch{return}await mutate(()=>setGroupStatus(batchId.value,locked.value?'reopen':'confirm',data.value.batch.revision))}
async function loadHistory(){const r=await getGroupHistory(batchId.value,logPage.value);logs.value=r.data.rows;logTotal.value=r.data.total}
const actionNames={create:'建立批次',cells:'修改数量',column:'新增客户列',quota:'调整额度',product:'新增商品',product_update:'修改商品',import:'Excel导入',confirm:'确认批次',reopen:'重新开放',rename:'批次改名',delete:'删除批次',restore:'恢复批次'}
Object.assign(actionNames,{column_update:'客户列改名',source_update:'来源改名',products_delete:'删除商品',columns_delete:'删除客户列',sources_delete:'删除来源 / 柜台'})
function historyDetail(r) {
  const c = r.changes
  if (c.removed) return `删除 ${c.removed.code||''} ${c.removed.name||c.removed.customer||''}；相关原始数据已留存`
  if (['column_update','source_update'].includes(r.action)) return `${c.before.name||c.before.customer} → ${c.after.name||c.after.customer}`
  if (c.cells) return c.cells.map(x => `${x.code} / ${x.column}：${x.before} → ${x.after}`).join('\n')
  if (r.action === 'quota') return `${c.code} / ${c.source}：${c.before ?? '待维护'} → ${c.after}；${c.note}`
  if (r.action === 'import') return c.files.map(f => f.name).join('、') + `；商品${c.summary.product_count}件`
  if (r.action === 'product_update') return `${c.code}：${JSON.stringify(c.before)} → ${JSON.stringify(c.after)}`
  if (c.source) return `${c.source} / ${c.customer}`
  if (c.code) return `${c.code} ${c.name}`
  return c.message || `${c.before || ''} → ${c.after || ''}`
}
async function download(kind){if(!await discardGuard())return;busy.value=true;try{const r=await exportGroupBatch(batchId.value,kind);const url=URL.createObjectURL(r.data),a=document.createElement('a');a.href=url;a.download=`${data.value.batch.month} ${data.value.batch.brand} ${data.value.batch.name} - ${kind==='order'?'下单':'分配'}.xlsx`;a.click();URL.revokeObjectURL(url)}finally{busy.value=false}}
const drawerRows=computed(()=>selected.value?data.value.all_columns.map(c=>({...c,source:sourceName(c.source_id)})):[])
onMounted(async()=>{window.addEventListener('beforeunload',beforeUnload);loading.value=true;try{await loadList();await loadTable()}finally{loading.value=false}})
</script>

<template>
  <section class="group-buy">
    <div class="heading"><div><h2>团购订单与分配</h2></div><div><el-button @click="openBatchManager" :disabled="busy||loading">批次管理</el-button><el-button type="primary" @click="openCreate" :disabled="busy||loading">新建批次</el-button></div></div>
    <div class="batch-toolbar">
      <el-date-picker v-model="month" type="month" value-format="YYYY-MM" :clearable="false" @change="queryChange(true)" :disabled="busy||loading" />
      <el-select v-model="brand" @change="queryChange(true)" :disabled="busy||loading"><el-option v-for="b in brands" :key="b" :value="b" :label="b" /></el-select>
      <el-select v-model="batchId" placeholder="选择批次" @change="queryChange()" :disabled="busy||loading"><el-option v-for="b in batches" :key="b.id" :value="b.id" :label="b.name" /></el-select>
      <template v-if="data"><el-tag :type="locked?'success':'warning'">{{locked?'已确认':'编辑中'}}</el-tag><span class="soft">数据更新：{{data.batch.updated_at.slice(0,10)}}</span></template>
    </div>
    <el-empty v-if="!batchId && !loading" description="本月该品牌暂无批次，先新建批次，再导入下单与分配表。" />
    <template v-else-if="data">
      <el-alert v-if="conflict" type="error" :closable="false" title="保存冲突：其他人已更新此批次。当前输入仍保留，请复制所需数值后刷新核对。" show-icon class="notice" />
      <el-alert v-if="tab==='allocation' && data.batch.summary.missing_count && quotaWarningClosedFor !== data.batch.id" :key="data.batch.id" type="warning" :closable="true" @close="quotaWarningClosedFor=data.batch.id" :title="`${data.batch.summary.missing_count}件商品的分配来源尚未维护额度。请补录可分配总量；吉客云已有分配不代表实际库存。`" class="notice" />
      <div class="sheet" v-loading="loading||busy">
        <div class="sheet-top"><el-radio-group v-model="tab" @change="changeTab"><el-radio-button value="order">柜台下单表</el-radio-button><el-radio-button value="log">修改记录</el-radio-button></el-radio-group><div class="metrics"><span>全批下单 <b>{{n(batchArrivalSummary?.ordered??data.batch.summary.ordered)}}</b></span><template v-if="tab==='order'"><el-tooltip content="全批已确认关联的到货，含替代抵扣；未归属入库不计入本批次。"><span>已入库 <b>{{arrivalLoading?'…':batchArrivalSummary?n(batchArrivalSummary.received_total):'—'}}</b></span></el-tooltip><el-tooltip content="逐商品、逐柜台累加待入库，超收不会抵消其他柜台的缺货。"><span>待入库 <b>{{arrivalLoading?'…':batchArrivalSummary?n(batchArrivalSummary.waiting_total):'—'}}</b></span></el-tooltip><span v-if="batchArrivalSummary?.over_received" class="negative">超收 <b>{{n(batchArrivalSummary.over_received)}}</b></span></template></div></div>
        <template v-if="tab!=='log'">
          <div class="filters"><el-input v-model="filters.keyword" clearable placeholder="商品名称 / 编码 / 条码" @keyup.enter="queryChange()" @clear="queryChange()" /><el-select v-model="filters.source" clearable placeholder="全部来源" @change="queryChange()"><el-option v-for="s in data.sources" :key="s.id" :value="s.id" :label="s.name" /></el-select><el-select v-if="tab==='allocation'" v-model="filters.customer" clearable filterable placeholder="全部客户" @change="queryChange()"><el-option v-for="c in data.customers" :key="c" :value="c" :label="c" /></el-select><el-button @click="queryChange()">查询</el-button><el-checkbox v-model="filters.only_gap" @change="queryChange()">只看差异</el-checkbox><template v-if="tab==='order'"><el-checkbox v-model="showArrival" @change="syncUrl">到货进度</el-checkbox><el-button @click="openInbound">采购入库关联</el-button></template><el-popover placement="bottom-end" :width="420" trigger="click" popper-class="group-buy-column-picker">
              <template #reference><el-button>显示列</el-button></template>
              <el-tabs v-model="columnSettingsTab">
                <el-tab-pane label="商品属性" name="fields"><el-checkbox-group v-model="shownFields" class="column-options"><el-checkbox v-for="d in dimensionChoices" :key="d.key" :value="d.key" :disabled="d.key==='name'">{{d.label}}</el-checkbox></el-checkbox-group></el-tab-pane>
                <el-tab-pane label="来源 / 柜台" name="sources"><div class="column-options"><el-checkbox v-for="s in data.sources" :key="s.id" :model-value="!hiddenSources.includes(s.id)" @change="toggleColumn('sources',s.id,$event)">{{s.name}}</el-checkbox></div></el-tab-pane>
                <el-tab-pane v-if="tab==='allocation'" label="客户列" name="customers"><div class="column-options"><el-checkbox v-for="c in data.all_columns" :key="c.id" :model-value="!hiddenColumns.includes(c.id)" @change="toggleColumn('columns',c.id,$event)">{{sourceName(c.source_id)}} / {{c.customer}}<span v-if="data.all_columns.filter(x=>x.source_id===c.source_id&&x.customer===c.customer).length>1">（{{c.origin}}）</span></el-checkbox></div></el-tab-pane>
              </el-tabs><el-button link type="primary" @click="resetColumns">恢复默认</el-button>
            </el-popover></div>
          <div v-if="tab==='order'" class="arrival-note"><span v-if="arrivalLoading">正在读取到货进度…</span><span v-else-if="arrivalError" class="negative">到货进度读取失败，暂不显示数量。<el-button link @click="loadArrival">重试</el-button></span><span v-else-if="arrival">采集更新：{{arrival.source_updated_at?.replace('T',' ')||'尚未同步'}}<span v-if="arrival.review_count"> · {{arrival.review_count}}条关联待复核</span></span></div><div class="actions"><el-button @click="openProduct()" :disabled="locked">新增商品</el-button><el-button @click="openStructure('products')">商品管理</el-button><el-button @click="openStructure('sources')">柜台管理</el-button><el-button @click="openQuota()" :disabled="locked">维护分配额度</el-button><el-button @click="openImport" :disabled="locked||data.batch.summary.product_count>0">导入Excel</el-button><el-dropdown @command="download"><el-button>导出全批次 ▾</el-button><template #dropdown><el-dropdown-menu><el-dropdown-item command="order">下单表（含额度台账）</el-dropdown-item><el-dropdown-item v-if="tab==='allocation'" command="allocation">分配表（含额度台账）</el-dropdown-item></el-dropdown-menu></template></el-dropdown><el-button class="push" @click="queryChange()">刷新</el-button><el-button @click="toggleStatus">{{locked?'重新开放':'确认批次'}}</el-button><el-button type="primary" :disabled="!count||locked||conflict" @click="save">保存修改{{count?` (${count})`:''}}</el-button></div>
          <div class="matrix" role="region" aria-label="团购商品表格" tabindex="0" :style="{'--group-header-height':`${headerHeight}px`}"><table><thead><tr ref="headerRow"><th v-for="(d,i) in dimensions" :key="d.key" rowspan="2" class="frozen" :class="{edge:i===dimensions.length-1}" :style="style(d)"><button @click="sort(d)">{{d.label}} {{filters.sort_by===d.key?(filters.sort_order==='asc'?'↑':'↓'):''}}</button></th><th v-for="g in sourceGroups" :key="g.id" :colspan="g.cols.length" class="group-head"><button :aria-label="`管理来源 ${g.name}`" @click="openStructure('sources')">{{g.name}}</button></th></tr><tr><th v-for="c in visibleColumns" :key="c.id" class="client-head" :style="columnStyle(c)"><button v-if="tab==='allocation'" :aria-label="`管理客户 ${c.label}`" @click="openStructure('columns')">{{c.label}}</button><template v-else>{{c.label}}</template><small v-if="c.duplicate">{{c.origin}}</small></th></tr></thead><tbody><tr v-for="row in data.rows" :key="row.id" :class="{'selected-row':selected?.id===row.id}" @click="rowDetails($event,row)"><td v-for="(d,i) in dimensions" :key="d.key" class="frozen" :class="{identity:['code','name'].includes(d.key),edge:i===dimensions.length-1,summary:['quota','allocated','remaining','received_total','waiting_total'].includes(d.key),negative:d.key==='remaining'&&(total(row).remaining<0||total(row).over)}" :style="style(d)"><button v-if="d.key==='name'" class="product-name" :aria-label="`查看 ${row.code} 商品明细`" @click.stop="openDetails(row)">{{row.name}}</button><template v-else>{{display(row,d)}}</template><small v-if="d.key==='remaining'&&total(row).over">来源超配</small><small v-if="d.key==='received_total'&&rowArrivals.get(row.id)?.over_received>0" class="negative">超收 {{n(rowArrivals.get(row.id).over_received)}}</small></td><td v-for="c in visibleColumns" :key="c.id" class="client-cell" :style="columnStyle(c)"><template v-if="tab==='order'&&c.kind!=='order'"><button v-if="['received','substitute'].includes(c.kind)" class="receipt-cell" :class="{'empty-quantity':arrivalValue(row,c)===0}" :aria-label="`${row.code} / ${sourceName(c.source_id)} ${c.label}`" :disabled="!arrival||arrivalLoading" @click.stop="openReceipt(row,c)">{{quantityText(arrivalValue(row,c))}}</button><span v-else :class="{'empty-quantity':arrivalValue(row,c)===0}">{{quantityText(arrivalValue(row,c))}}</span><small v-if="c.kind==='received'&&overReceipt(row,c)>0" class="negative">超收 {{n(overReceipt(row,c))}}</small></template><input v-else :aria-label="`${row.code} / ${tab==='order'?sourceName(c.id):sourceName(c.source_id)+' / '+c.customer}`" :value="value(row,tab==='order'?'order':'allocation',c.id)||''" placeholder="·" type="number" min="0" step="1" class="quantity" :class="{changed:pending[key(row.id,tab==='order'?'order':'allocation',c.id)]}" :disabled="locked||busy||conflict" @paste="pasteCells($event,row,c)" @input="edit(row,tab==='order'?'order':'allocation',c.id,$event.target.value,$event.target)" /></td></tr></tbody><tfoot v-if="expandedTotals.length"><tr>
            <td v-for="(d,i) in dimensions" :key="d.key" class="frozen" :class="{edge:i===dimensions.length-1,'total-label':d.key==='name'}" :style="style(d)">
              <template v-if="d.key==='name'"><div v-if="showQuantityTotal" class="total-line">数量合计</div><div v-if="showAmountTotal" class="total-line">金额合计</div></template>
              <template v-else-if="sheetTotals.summary[d.key]"><div v-if="showQuantityTotal" class="total-line">{{['received_total','waiting_total'].includes(d.key)&&sheetTotals.summary[d.key].quantity==null?'—':n(sheetTotals.summary[d.key].quantity)}}</div><div v-if="showAmountTotal" class="total-line">{{d.key==='received_total'?'—':formatCents(sheetTotals.summary[d.key].amount)}}</div></template>
              <template v-else><div v-if="showQuantityTotal" class="total-line">—</div><div v-if="showAmountTotal" class="total-line">—</div></template>
            </td>
            <td v-for="c in visibleColumns" :key="c.id" class="client-cell" :style="columnStyle(c)"><div v-if="showQuantityTotal" class="total-line" :aria-label="`${c.heading||c.label} 数量合计`">{{n(sheetTotals.columns.get(c.id).quantity)}}</div><div v-if="showAmountTotal" class="total-line" :aria-label="`${c.heading||c.label} 金额合计`">{{c.kind==='substitute'?'—':formatCents(sheetTotals.columns.get(c.id).amount)}}</div></td>
          </tr></tfoot></table><el-empty v-if="!data.rows.length" description="暂无商品，可导入Excel或新增商品。" /></div>
          <div class="sheet-footer"><span>共 {{data.batch.summary.product_count}} 行 · 展示 {{data.rows.length}} 行</span><el-checkbox-group v-model="expandedTotals" class="total-toggles" aria-label="展开合计"><el-checkbox value="quantity">数量合计</el-checkbox><el-checkbox value="amount">金额合计</el-checkbox></el-checkbox-group></div>
        </template>
        <template v-else><div class="history-table"><el-table height="100%" :data="logs"><el-table-column prop="revision" label="版本" width="70"/><el-table-column label="时间" width="180"><template #default="{row}">{{row.created_at.replace('T',' ').slice(0,19)}}</template></el-table-column><el-table-column prop="operator" label="修改人" width="110"/><el-table-column label="操作" width="110"><template #default="{row}">{{actionNames[row.action]||row.action}}</template></el-table-column><el-table-column label="明细"><template #default="{row}"><span class="log-detail">{{historyDetail(row)}}</span></template></el-table-column></el-table></div><el-pagination v-model:current-page="logPage" :total="logTotal" :page-size="20" layout="prev,pager,next" @current-change="loadHistory" /></template>
      </div>
    </template>
    <el-drawer v-model="receiptDrawer" :title="receiptTitle" size="min(1000px,96vw)">
      <el-table :data="receiptDetails" empty-text="暂无已确认入库明细">
        <el-table-column prop="receipt_number" label="入库单号" width="185"/>
        <el-table-column label="时间" width="165"><template #default="{row}">{{row.receipt_time?.replace('T',' ')}}</template></el-table-column>
        <el-table-column prop="name" label="实际入库商品" min-width="210"/><el-table-column label="方式 / 抵扣"><template #default="{row}">{{row.mode==='substitute'?`替代到货 · 抵扣 ${row.credit_quantity}`:'正常到货'}}<small>{{row.note}}</small></template></el-table-column>
        <el-table-column prop="quantity" label="数量" align="right"/>
      </el-table><el-button @click="openInbound" style="margin-top:16px">管理入库关联</el-button>
    </el-drawer>
    <el-dialog v-model="showStructure" :title="structureKind==='products'?'商品管理':'客户 / 柜台管理'" width="960px" :close-on-click-modal="false">
      <div class="structure-toolbar">
        <el-radio-group v-if="structureKind!=='products'" v-model="structureKind" @change="structureSearch=''">
          <el-radio-button v-if="tab==='allocation'" value="columns">客户列</el-radio-button><el-radio-button value="sources">来源 / 柜台</el-radio-button>
        </el-radio-group>
        <el-input v-model="structureSearch" clearable placeholder="搜索名称、编码或来源" aria-label="管理列表搜索" />
        <el-button type="primary" :disabled="locked||busy" @click="structureKind==='products'?openProduct():openColumn()">{{structureKind==='products'?'新增商品':'新增客户列 / 柜台'}}</el-button>
      </div>
      <p class="soft">管理当前批次全部{{structureKind==='products'?'商品':'列'}}，不受主表筛选影响。{{locked?'批次已确认，请先重新开放再修改。':'改名保留数量；删除前会显示影响范围。'}}</p>
      <el-table :data="structureRows" max-height="480" v-loading="structureLoading||busy" row-key="id">
        <template v-if="structureKind==='products'">
          <el-table-column prop="code" label="产品代码" width="125"/><el-table-column prop="name" label="产品名称" min-width="260"/>
          <el-table-column label="价格" width="110"><template #default="{row}">{{money(row.price)}}</template></el-table-column>
          <el-table-column prop="abc" label="ABC" width="65"/><el-table-column prop="pcb" label="PCB" width="65"/>
        </template>
        <template v-else-if="structureKind==='columns'">
          <el-table-column prop="source" label="来源 / 柜台" min-width="160"/><el-table-column prop="customer" label="客户名称" min-width="180"/>
          <el-table-column prop="origin" label="原始列" width="140"/>
        </template>
        <template v-else>
          <el-table-column prop="name" label="来源 / 柜台名称" min-width="240"/>
          <el-table-column label="类型" width="140"><template #default="{row}">{{row.counter?'下单柜台':'其他分配来源'}}</template></el-table-column>
          <el-table-column label="客户列数" width="100"><template #default="{row}">{{structureData.all_columns.filter(c=>c.source_id===row.id).length}}</template></el-table-column>
        </template>
        <el-table-column label="操作" width="150" fixed="right"><template #default="{row}">
          <el-button link type="primary" :disabled="locked||busy" @click="structureKind==='products'?openProduct(row):renameItem(structureKind,row)">{{structureKind==='products'?'编辑':'改名'}}</el-button>
          <el-button link type="danger" :disabled="locked||busy" @click="removeItem(structureKind,row)">删除</el-button>
        </template></el-table-column>
      </el-table>
      <template #footer><span class="soft">共{{structureRows.length}}项</span><el-button @click="showStructure=false">关闭</el-button></template>
    </el-dialog>
    <el-dialog v-model="showBatchManager" title="批次管理" width="920px" :close-on-click-modal="false">
      <div class="batch-manager-toolbar">
        <span>{{month}} · {{brand}}</span>
        <el-switch v-model="showDeletedBatches" active-text="回收站" inactive-text="正常批次" :disabled="busy||managerLoading" @change="loadManagedBatches" />
      </div>
      <p class="soft">删除后移入回收站，数据和修改记录保留；恢复时保留删除前的确认状态。同名批次（包括回收站）不能重复建立。</p>
      <el-table v-loading="managerLoading||busy" :data="managedBatches" max-height="420" empty-text="暂无批次">
        <el-table-column prop="name" label="批次名称" min-width="150" />
        <el-table-column label="状态" width="95"><template #default="{row}"><el-tag :type="row.status==='deleted'?'info':row.status==='confirmed'?'success':'warning'">{{row.status==='deleted'?'已删除':row.status==='confirmed'?'已确认':'编辑中'}}</el-tag></template></el-table-column>
        <el-table-column label="商品数" width="85"><template #default="{row}">{{n(row.summary.product_count)}}</template></el-table-column>
        <el-table-column label="已分配" width="105"><template #default="{row}">{{n(row.summary.allocated)}}</template></el-table-column>
        <el-table-column label="更新时间" width="175"><template #default="{row}">{{row.updated_at.replace('T',' ').slice(0,19)}}</template></el-table-column>
        <el-table-column label="操作" width="190"><template #default="{row}">
          <el-button v-if="row.status==='deleted'" link type="primary" :disabled="busy" @click="restoreBatch(row)">恢复</el-button>
          <template v-else><el-button link type="primary" :disabled="busy" @click="openManagedBatch(row)">打开</el-button><el-button link type="primary" :disabled="busy" @click="renameBatch(row)">改名</el-button><el-button link type="danger" :disabled="busy" @click="deleteBatch(row)">删除</el-button></template>
        </template></el-table-column>
      </el-table>
      <template #footer><el-button @click="showBatchManager=false">关闭</el-button></template>
    </el-dialog>
    <el-dialog v-model="showCreate" title="新建团购批次" width="460px" :close-on-click-modal="false"><el-form label-position="top"><el-form-item label="月份"><el-date-picker v-model="createForm.month" type="month" value-format="YYYY-MM"/></el-form-item><el-form-item label="品牌"><el-select v-model="createForm.brand"><el-option v-for="b in brands" :key="b" :value="b"/></el-select></el-form-item><el-form-item label="批次名称"><el-input v-model="createForm.name" maxlength="64"/></el-form-item><el-form-item label="复制同品牌已有批次（可选，数量清空）"><el-select v-model="createForm.copy_from" clearable><el-option v-for="b in allBatches.filter(b=>b.brand===createForm.brand)" :key="b.id" :value="b.id" :label="`${b.month} ${b.name}`"/></el-select></el-form-item><p class="soft">复制保留商品、价格、柜台和客户列；下单、额度及分配数量全部清零，请核对当期价格。</p></el-form><template #footer><el-button @click="showCreate=false">取消</el-button><el-button type="primary" :loading="busy" @click="create">建立批次</el-button></template></el-dialog>
    <el-dialog v-model="showImport" title="导入Excel到空批次" width="580px" :close-on-click-modal="false"><el-alert title="支持原始下单模板；已有商品的批次不允许覆盖导入。" type="info" :closable="false"/><p>下单表</p><el-upload :auto-upload="false" :limit="1" accept=".xlsx" :on-change="f=>fileChanged('order',f)" :on-remove="()=>fileChanged('order',null)" :key="`order-${showImport}`"><el-button>选择下单.xlsx</el-button></el-upload><p v-if="tab==='allocation'">分配表</p><el-upload v-if="tab==='allocation'" :auto-upload="false" :limit="1" accept=".xlsx" :on-change="f=>fileChanged('allocation',f)" :on-remove="()=>fileChanged('allocation',null)" :key="`allocation-${showImport}`"><el-button>选择分配.xlsx</el-button></el-upload><div v-if="preview" class="import-summary"><p>商品 {{preview.product_count}} 件，客户分配列 {{preview.column_count}} 列。</p><p>下单 {{n(preview.summary.ordered)}} 件，已分配 {{n(preview.summary.allocated)}} 件。</p><p v-if="preview.summary.missing_count">{{preview.summary.missing_count}}件商品需要补录来源额度。</p><p v-if="preview.duplicate_columns">{{preview.duplicate_columns}}个同名客户列按原列分别保留。</p></div><template #footer><el-button @click="showImport=false">取消</el-button><el-button :disabled="!importFiles.order&&!importFiles.allocation" :loading="busy" @click="importPreview">检查预览</el-button><el-button type="primary" :disabled="!preview" :loading="busy" @click="importApply">确认导入</el-button></template></el-dialog>
    <el-dialog v-model="showColumn" title="新增客户列 / 柜台" width="450px"><el-form label-position="top"><el-form-item label="来源 / 柜台名称"><el-select v-model="columnForm.source" filterable allow-create default-first-option><el-option v-for="s in data?.sources||[]" :key="s.id" :value="s.name"/></el-select></el-form-item><el-form-item label="客户名称（仅新增柜台时可留空）"><el-input v-model="columnForm.customer" maxlength="128"/></el-form-item><el-checkbox v-model="columnForm.counter">此来源属于下单柜台（显示在柜台下单表）</el-checkbox></el-form><template #footer><el-button :loading="busy" type="primary" @click="submitColumn">保存</el-button></template></el-dialog>
    <el-dialog v-model="showQuota" title="维护分配额度" width="530px"><el-form label-position="top"><el-form-item label="商品"><el-select v-model="quotaForm.product_id" filterable remote :remote-method="searchProducts"><el-option v-for="p in productOptions" :key="p.id" :value="p.id" :label="`${p.code} ${p.name}`"/></el-select></el-form-item><el-form-item label="来源名称"><el-select v-model="quotaForm.source" filterable allow-create default-first-option><el-option v-for="s in data?.sources||[]" :key="s.id" :value="s.name"/></el-select></el-form-item><el-form-item label="调整方式"><el-radio-group v-model="quotaForm.mode"><el-radio-button value="set">设置总额度</el-radio-button><el-radio-button value="add">追加额度</el-radio-button></el-radio-group></el-form-item><el-form-item label="数量"><el-input-number v-model="quotaForm.quantity" :min="0" :max="100000000" :precision="0"/></el-form-item><el-form-item label="调整原因"><el-input v-model="quotaForm.note" maxlength="500"/></el-form-item></el-form><template #footer><el-button :loading="busy" type="primary" @click="submitQuota">保存额度</el-button></template></el-dialog>
    <el-dialog v-model="showProduct" :title="editingProduct?'编辑商品资料':'新增商品'" width="520px" :close-on-click-modal="false" @opened="focusProductField">
      <el-alert v-if="productLookup&&productLookup.status!=='matched'" :title="productLookup.message" type="warning" :closable="false"/>
      <el-tag v-if="productLookup?.status==='matched'" type="success">已匹配商品库</el-tag>
      <el-checkbox v-model="manualIdentity" :disabled="busy||lookupBusy">手动填写名称 / 条码</el-checkbox>
      <el-form label-position="top" :disabled="busy||locked">
        <el-form-item v-for="(label,field) in productFieldLabels" :key="field" :label="label" :class="{'active-field':activeProductField===label}">
          <el-input v-if="field==='code'" :ref="el=>productInputs[field]=el" v-model="productForm.code" aria-label="产品代码" maxlength="128" @blur="lookupProduct()" @keyup.enter.stop="lookupProduct(true)"><template #append><el-button :loading="lookupBusy" @click="lookupProduct(true)">查询商品</el-button></template></el-input>
          <el-input-number v-else-if="field==='price'||field==='pcb'" :ref="el=>productInputs[field]=el" v-model="productForm[field]" :aria-label="label" :min="0" :precision="field==='price'?2:0"/>
          <el-input v-else :ref="el=>productInputs[field]=el" v-model="productForm[field]" :readonly="['name','barcode'].includes(field)&&!manualIdentity" :aria-label="label" :maxlength="field==='name'?300:field==='abc'?32:128" @keyup.enter="submitProduct" />
        </el-form-item>
      </el-form>
      <template #footer><el-button v-if="editingProduct" class="delete-product" type="danger" plain :disabled="busy||locked" @click="removeEditingProduct">删除商品</el-button><el-button @click="showProduct=false" :disabled="busy">取消</el-button><el-button :loading="busy" :disabled="locked||lookupBusy" type="primary" @click="submitProduct">保存商品</el-button></template>
    </el-dialog>
    <el-drawer :model-value="!!selected" title="商品明细" size="620px" :before-close="closeDetails">
      <template v-if="selected">
        <el-form label-position="top" @submit.prevent="saveSelectedName">
          <el-form-item label="产品名称"><div class="drawer-name"><el-input v-model="selectedName" aria-label="产品名称" maxlength="300" :disabled="locked||busy||conflict" @keyup.enter="saveSelectedName"/><el-button :disabled="!nameChanged||locked||busy||conflict" :loading="busy" @click="saveSelectedName">保存名称</el-button></div></el-form-item>
        </el-form>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="产品代码">{{selected.code}}</el-descriptions-item><el-descriptions-item label="价格">{{money(selected.price)}}</el-descriptions-item>
          <el-descriptions-item label="ABC">{{selected.abc||'—'}}</el-descriptions-item><el-descriptions-item label="PCB">{{selected.pcb??'—'}}</el-descriptions-item>
          <el-descriptions-item v-if="selected.barcode" label="条形码" :span="2">{{selected.barcode}}</el-descriptions-item>
        </el-descriptions>
        <div class="drawer-actions"><el-button v-if="tab==='allocation'" :disabled="locked||busy" @click="openQuota(selected)">维护分配额度</el-button><el-button :disabled="locked||busy" @click="openProduct(selected)">编辑商品资料</el-button></div>
        <template v-if="tab==='allocation'">
        <h3>来源额度</h3>
        <el-table :data="data.sources.map(s=>({...s,quota:total(selected).quotas[s.id],allocated:total(selected).quantities[s.id]}))"><el-table-column prop="name" label="来源"/><el-table-column label="额度"><template #default="{row}">{{n(row.quota)}}</template></el-table-column><el-table-column prop="allocated" label="已分配"/></el-table>
        <h3>客户分配</h3>
        <el-table :data="drawerRows"><el-table-column prop="source" label="来源"/><el-table-column prop="customer" label="客户"><template #default="{row}">{{row.customer}}<small v-if="data.all_columns.filter(c=>c.source_id===row.source_id&&c.customer===row.customer).length>1" class="soft"> {{row.origin}}</small></template></el-table-column><el-table-column label="数量" width="100"><template #default="{row}"><input :aria-label="`${selected.code} / ${row.source} / ${row.customer} 明细`" class="quantity" type="number" min="0" :disabled="locked||conflict||busy" :value="value(selected,'allocation',row.id)" @input="edit(selected,'allocation',row.id,$event.target.value,$event.target)"/></template></el-table-column></el-table>
        </template>
      </template>
      <template #footer><el-button @click="closeDetails()" :disabled="busy">关闭</el-button><el-button type="primary" :disabled="!count||locked||conflict" :loading="busy" @click="save">保存修改</el-button></template>
    </el-drawer>
  </section>
</template>

<style scoped>
.heading,.batch-toolbar,.notice,.sheet-top,.filters,.actions,.arrival-note,.sheet-footer{flex-shrink:0;min-width:0;max-width:100%}
.history-table{flex:1;min-width:0;min-height:0;overflow:hidden}.sheet>.el-pagination{flex:none;padding:10px 16px}
.matrix::-webkit-scrollbar{width:12px;height:12px}.matrix::-webkit-scrollbar-track{background:var(--surface-soft,#f5f7fa)}.matrix::-webkit-scrollbar-thumb{background:#a8abb2;border:3px solid var(--surface-soft,#f5f7fa);border-radius:6px}.matrix::-webkit-scrollbar-thumb:hover{background:#73767a}.matrix::-webkit-scrollbar-corner{background:var(--surface-soft,#f5f7fa)}
.empty-quantity,.receipt-cell.empty-quantity{color:var(--text-soft,#909399)}
.receipt-cell{border:0;background:transparent;color:var(--accent,#a62467);font:inherit;cursor:pointer;padding:6px 3px;width:100%;text-align:right}.receipt-cell:disabled{color:var(--text-soft,#909399);cursor:default}.arrival-note{padding:0 16px 10px;color:var(--text-soft,#909399);font-size:12px}
.total-toggles{display:flex;gap:18px}.total-toggles :deep(.el-checkbox){margin:0;height:26px}

.matrix tfoot td{position:sticky;bottom:0;z-index:4;background:var(--surface-soft,#f7f8fa);border-top:2px solid var(--border,#e4e7ed);font-weight:600;padding-top:5px;padding-bottom:5px;cursor:default}.matrix tfoot td.frozen{z-index:5}.matrix tfoot .total-label{text-align:left}.total-line{height:25px;line-height:25px;font-variant-numeric:tabular-nums}.total-line+.total-line{border-top:1px solid var(--border,#ebeef5)}

.column-options{display:flex;flex-direction:column;max-height:310px;overflow:auto;gap:2px;padding-bottom:12px}.column-options :deep(.el-checkbox){height:auto;min-height:30px;margin:0}.column-options :deep(.el-checkbox__label){white-space:normal;overflow-wrap:anywhere}.drawer-name{display:flex;gap:10px;width:100%}.drawer-name>.el-input{flex:1;min-width:0}.drawer-actions{display:flex;gap:10px;margin:16px 0}.matrix tbody tr{cursor:pointer}.matrix .selected-row td{background:var(--surface-hover,#fff8fb)}

.structure-toolbar{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.structure-toolbar>.el-input{width:250px}.structure-toolbar>.el-button{margin-left:auto}.delete-product{margin-right:auto}.active-field :deep(.el-form-item__label){color:var(--accent);font-weight:600}

.batch-manager-toolbar{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:12px}

.group-buy{display:flex;flex-direction:column;flex:1;min-width:0;min-height:0;width:100%;max-width:100%;--accent:#b52663;--el-color-primary:#b52663}.heading{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px}.heading h2{font-size:22px;margin:0}.heading p{color:var(--text-soft,#909399);margin:8px 0 0;font-size:13px}.soft{font-size:12px;color:var(--text-soft,#909399)}.batch-toolbar,.filters,.actions,.sheet-top,.metrics,.sheet-footer{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.batch-toolbar{margin-bottom:16px}.batch-toolbar :deep(.el-date-editor){width:155px}.batch-toolbar>.el-select{width:145px}.notice{margin-bottom:12px}.sheet{display:flex;flex-direction:column;flex:1;min-width:0;min-height:0;max-width:100%;border:1px solid var(--border,#e4e7ed);border-radius:7px;background:var(--surface,#fff);overflow:hidden}.sheet-top{padding:14px 16px;border-bottom:1px solid var(--border,#ebeef5)}.metrics{margin-left:auto;font-size:12px;color:var(--text-soft,#909399)}.metrics b{font-size:16px;margin-left:6px;color:var(--text,#303133)}.filters{padding:12px 16px 4px}.filters>.el-input{width:205px}.filters>.el-select{width:135px}.filters :deep(.el-checkbox){margin-right:0}.actions{padding:8px 16px}.actions .el-button+.el-button{margin-left:0}.push{margin-left:auto!important}.hint{padding:4px 16px 12px;font-size:12px;color:var(--text-soft,#909399)}.dirty{color:#b7791f;margin-left:12px}.matrix{flex:1;min-width:0;min-height:0;width:100%;max-width:100%;overflow:auto;overscroll-behavior:contain;scrollbar-gutter:stable;border-top:1px solid var(--border,#e4e7ed);position:relative}.matrix table{border-collapse:separate;border-spacing:0;table-layout:fixed;width:max-content;min-width:100%;font-size:12px}.matrix th,.matrix td{height:43px;padding:5px 8px;border-right:1px solid var(--border,#ebeef5);border-bottom:1px solid var(--border,#ebeef5);text-align:right;background:var(--surface,#fff);white-space:nowrap}.matrix th{position:sticky;top:0;z-index:4;background:var(--surface-soft,#f7f8fa);text-align:center;height:34px;font-weight:500}.matrix thead tr:nth-child(2) th{top:var(--group-header-height,34px)}.matrix .frozen{position:sticky;z-index:2}.matrix th.frozen{z-index:6;background:var(--surface-soft,#f7f8fa)}.matrix th button{border:0;background:transparent;color:inherit;font:inherit;cursor:pointer;padding:0}.matrix .edge{border-right:2px solid #d6dce5}.matrix td.identity{text-align:left}.matrix td.summary{background:var(--surface-soft,#fafbfd);font-weight:600}.matrix th.group-head{background:var(--surface-soft,#f2f4f7)}.matrix small{display:block;font-size:10px;color:var(--text-soft,#909399)}.matrix .client-head,.matrix .client-cell{width:110px;min-width:110px;max-width:260px}.matrix .client-head,.matrix .group-head{white-space:normal;overflow-wrap:anywhere}.matrix .client-head button,.matrix .group-head button{white-space:normal;overflow-wrap:anywhere;line-height:1.5;width:100%;display:block}.product-name{border:0;background:transparent;cursor:pointer;font:inherit;white-space:normal;line-height:1.5;text-align:left;height:auto;display:block;width:100%;padding:0;color:inherit}.quantity{width:100%;border:1px solid transparent;background:transparent;text-align:right;font:inherit;color:inherit;padding:6px 3px;min-width:0;border-radius:2px}.quantity:hover{border-color:#dcdfe6}.quantity:focus{outline:none;border-color:var(--accent);background:#fff7fb;color:#303133}.quantity::-webkit-inner-spin-button{display:none}.quantity.changed{background:#fff4de;color:#805712}.quantity:disabled{opacity:.7}.matrix tr:hover td{background:var(--surface-hover,#fff8fb)}.negative{color:#d54848!important;background:#fff2f0!important}.sheet-footer{justify-content:space-between;padding:10px 16px;font-size:12px;color:var(--text-soft,#909399)}.log-detail{white-space:pre-wrap;line-height:1.8}.import-summary{background:var(--surface-soft,#f5f7fa);padding:10px 16px;margin-top:15px}:deep(.el-form .el-select){width:100%}@media(max-width:900px){.metrics{margin-left:0}.heading{align-items:start}.filters>.el-input,.filters>.el-select{width:150px}.sheet-top{gap:15px}.push{margin-left:0!important}}
@media(max-height:650px){.group-buy{min-height:560px;flex-shrink:0}}
@media(max-width:900px){.matrix .frozen{left:auto!important}.matrix tbody .frozen{position:static}}
</style>
