<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { setInboundReceiptHold } from '../../api/groupBuy'
const props=defineProps({record:Object,brand:String,month:String,options:Object})
const emit=defineEmits(['close','changed'])
const busy=ref(false),form=reactive({month:'',counter:'',note:''})
const counters=computed(()=>[...new Set([...(props.options?.aliases||[]).filter(a=>a.brand===props.brand).map(a=>a.counter),...(props.options?.batches||[]).filter(b=>b.brand===props.brand).flatMap(b=>b.sources.map(s=>s.name))])])
watch(()=>props.record,r=>{if(r)Object.assign(form,{month:r.hold?.month||props.month,counter:r.hold?.counter||props.options?.aliases?.find(a=>a.brand===props.brand&&a.supplier===r.supplier)?.counter||'',note:r.hold?.note||''})},{immediate:true})
async function save(){if(!form.month||!form.counter.trim())return ElMessage.warning('请选择月份，填写或选择柜台');busy.value=true;try{await setInboundReceiptHold(props.record.doc_id,props.brand,{...form,revision:props.record.hold?.revision||0,waiting:true});ElMessage.success('整单已放入“待补下单表”');emit('changed');emit('close')}catch{}finally{busy.value=false}}
</script>
<template><el-dialog :model-value="!!record" title="下单表没收到，先放这里" width="min(520px,96vw)" :close-on-click-modal="false" :before-close="done=>{if(!busy){emit('close');done()}}">
  <template v-if="record"><p>{{record.receipt_number}} · {{record.supplier}}</p><p>整单到货保留，未关联商品先不计入批次；资料齐后再匹配。</p><el-form label-position="top" :disabled="busy"><el-form-item label="预计归属月份"><el-date-picker v-model="form.month" type="month" value-format="YYYY-MM" :clearable="false"/></el-form-item><el-form-item label="哪个柜台的下单表没收到"><el-select v-model="form.counter" filterable allow-create default-first-option placeholder="选择柜台，也可以直接输入" aria-label="待补资料柜台"><el-option v-for="name in counters" :key="name" :value="name"/></el-select></el-form-item><el-form-item label="备注（可不填）"><el-input v-model="form.note" maxlength="500" placeholder="例如：柜台尚未发10月下单表"/></el-form-item></el-form></template>
  <template #footer><el-button @click="emit('close')" :disabled="busy">取消</el-button><el-button type="primary" @click="save" :loading="busy">保存为待补</el-button></template>
</el-dialog></template>
<style scoped>p{font-size:13px;line-height:1.7}.el-select{width:100%}</style>
