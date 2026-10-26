<script setup>
import { computed, ref, watch } from 'vue'
import { Filter } from '@element-plus/icons-vue'

const props=defineProps({label:String,modelValue:{type:Array,default:()=>[]},options:{type:Array,default:()=>[]},disabled:Boolean})
const emit=defineEmits(['update:modelValue','change'])
const visible=ref(false),search=ref(''),draft=ref([])
const choices=computed(()=>props.options.filter(o=>!search.value||(o.search||o.label).toLowerCase().includes(search.value.trim().toLowerCase())))
function open(){search.value='';draft.value=[...props.modelValue]}
watch(visible,value=>{if(value)open()},{flush:'sync'})
function apply(values=draft.value){emit('update:modelValue',[...values]);visible.value=false;emit('change')}
</script>

<template>
  <el-popover v-model:visible="visible" trigger="click" placement="bottom-start" :width="380" :disabled="disabled">
    <template #reference><button class="column-filter" :class="{active:modelValue.length}" :aria-label="`筛选${label}`" :aria-pressed="!!modelValue.length" :disabled="disabled">{{label}}<el-icon><Filter/></el-icon><span v-if="modelValue.length">{{modelValue.length}}</span></button></template>
    <div class="filter-title">筛选{{label}}</div>
    <el-input v-model="search" :aria-label="`搜索${label}选项`" :placeholder="label==='入库商品'?'搜索商品名称、编码或条码':'搜索往来单位'" clearable/>
    <div class="filter-options"><el-checkbox-group v-model="draft" :max="100"><el-checkbox v-for="o in choices" :key="o.value" :value="o.value"><span class="option-label">{{o.label}}<small v-if="o.detail">{{o.detail}}</small></span></el-checkbox></el-checkbox-group><el-empty v-if="!choices.length" description="没有匹配选项" :image-size="48"/></div>
    <div class="filter-footer"><span>已选 {{draft.length}} 项</span><el-button @click="apply([])" :disabled="disabled">清除</el-button><el-button type="primary" @click="apply()" :disabled="disabled">应用筛选</el-button></div>
  </el-popover>
</template>

<style scoped>
.column-filter{display:inline-flex;align-items:center;gap:5px;border:0;padding:0;color:inherit;background:transparent;font:inherit;font-weight:inherit;cursor:pointer}.column-filter.active{color:var(--el-color-primary)}.column-filter:disabled{cursor:default}.filter-title{font-weight:600;margin-bottom:10px}.filter-options{max-height:290px;overflow:auto;margin:10px 0}.filter-options :deep(.el-checkbox-group){display:flex;flex-direction:column;align-items:stretch}.filter-options :deep(.el-checkbox){height:auto;min-height:34px;margin:0;padding:5px 0;align-items:flex-start;white-space:normal}.filter-options :deep(.el-checkbox__input){margin-top:3px}.filter-options :deep(.el-checkbox__label){min-width:0;white-space:normal;line-height:1.5;word-break:break-word}.option-label small{display:block;color:var(--text-soft);font-size:11px}.filter-footer{display:flex;align-items:center;gap:8px;border-top:1px solid var(--border);padding-top:10px}.filter-footer>span{margin-right:auto;color:var(--text-soft);font-size:12px}.filter-footer .el-button+.el-button{margin-left:0}
</style>
