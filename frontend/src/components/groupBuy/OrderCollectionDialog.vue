<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getOrderCollections, saveOrderCollection } from '../../api/groupBuy'
const props=defineProps({modelValue:Boolean,brand:String,month:String,options:Object}),emit=defineEmits(['update:modelValue'])
const selectedMonth=ref(''),rows=ref([]),busy=ref(false),failure=ref(''),editing=ref(false),page=ref(1)
const form=reactive({counter:'',batch_id:null,status:'missing',note:'',revision:0})
const names={missing:'未收到',partial:'待补充',received:'已收到'}
const batches=computed(()=>props.options.batches.filter(b=>b.brand===props.brand&&b.month===selectedMonth.value))
const counters=computed(()=>[...new Set(props.options.batches.filter(b=>b.brand===props.brand).flatMap(b=>b.sources.map(s=>s.name)).concat(props.options.aliases.filter(a=>a.brand===props.brand).map(a=>a.counter)))])
let seq=0
async function load(){const token=++seq;busy.value=true;failure.value='';editing.value=false;try{const r=await getOrderCollections({brand:props.brand,month:selectedMonth.value});if(token===seq){rows.value=r.data;page.value=1}}catch{if(token===seq)failure.value='读取失败，请重试'}finally{if(token===seq)busy.value=false}}
watch(()=>props.modelValue,on=>{if(on){selectedMonth.value=props.month;load()}})
function edit(row){Object.assign(form,row?{counter:row.counter,batch_id:row.batch_id,status:row.status,note:row.note,revision:row.revision}:{counter:'',batch_id:null,status:'missing',note:'',revision:0});editing.value=true}
async function save(){if(!form.counter.trim())return ElMessage.warning('请选择或输入柜台');busy.value=true;try{rows.value=(await saveOrderCollection({...form,brand:props.brand,month:selectedMonth.value})).data;editing.value=false;ElMessage.success('收集状态已保存')}catch{}finally{busy.value=false}}
</script>
<template><el-dialog :model-value="modelValue" title="下单表收集" width="min(900px,96vw)" :close-on-click-modal="false" :before-close="done=>{if(!busy){emit('update:modelValue',false);done()}}">
  <div class="toolbar"><strong>{{brand}}</strong><el-date-picker v-model="selectedMonth" type="month" value-format="YYYY-MM" :clearable="false" @change="load" :disabled="busy"/><el-button @click="edit()" :disabled="busy">登记一个柜台</el-button><el-button @click="load" :disabled="busy">刷新</el-button></div>
  <el-alert v-if="failure" :title="failure" type="error" :closable="false"/>
  <el-form v-if="editing" label-position="top" class="collection-form" :disabled="busy"><el-form-item label="柜台"><el-select v-model="form.counter" filterable allow-create default-first-option :disabled="form.revision>0" aria-label="收集清单柜台"><el-option v-for="name in counters" :key="name" :value="name"/></el-select></el-form-item><el-form-item label="批次（没确定可以不选）"><el-select v-model="form.batch_id" clearable :disabled="form.revision>0"><el-option v-for="b in batches" :key="b.id" :value="b.id" :label="b.name"/></el-select></el-form-item><el-form-item label="下单表收到了吗"><el-radio-group v-model="form.status"><el-radio-button v-for="(label,value) in names" :key="value" :value="value">{{label}}</el-radio-button></el-radio-group></el-form-item><el-form-item label="备注"><el-input v-model="form.note" maxlength="500"/></el-form-item><el-button type="primary" @click="save" :loading="busy">保存状态</el-button><el-button @click="editing=false">取消</el-button></el-form>
  <el-table v-else :data="rows.slice((page-1)*20,page*20)" max-height="420" v-loading="busy" empty-text="还没有登记。入库单标为待补后，也会自动出现在这里。"><el-table-column prop="counter" label="柜台" min-width="180"/><el-table-column prop="batch_name" label="批次" min-width="140"/><el-table-column label="收集状态" width="110"><template #default="{row}"><el-tag :type="row.status==='received'?'success':'warning'">{{names[row.status]}}</el-tag></template></el-table-column><el-table-column prop="note" label="备注" min-width="160"/><el-table-column label="操作" width="100"><template #default="{row}"><el-button link type="primary" @click="edit(row)" :disabled="busy">改状态</el-button></template></el-table-column></el-table>
  <p>“已收到”仅记录资料已收齐；导入柜台下单表后，到“待补下单表”中打开原单重新匹配。</p>
  <template #footer><el-pagination v-if="!editing&&rows.length>20" v-model:current-page="page" :total="rows.length" :page-size="20" layout="prev,pager,next"/><el-button @click="emit('update:modelValue',false)" :disabled="busy">关闭</el-button></template>
</el-dialog></template>
<style scoped>.toolbar{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:16px}.toolbar :deep(.el-date-editor){width:160px}.collection-form{padding:16px;background:var(--surface-soft,#f5f7fa);border-radius:6px}.el-select{width:100%}p{font-size:13px;line-height:1.7;color:var(--text-soft)}</style>
