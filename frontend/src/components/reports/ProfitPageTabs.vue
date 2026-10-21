<script setup>
defineProps({ view: { type: String, required: true } })
defineEmits(['change'])
const pages = [{ value: 'review', label: '经营毛利' }, { value: 'profit', label: '毛利分析' }, { value: 'prices', label: '客户分析' }]
</script>
<template>
  <nav class="profit-page-tabs" aria-label="分析分页">
    <button v-for="p in pages" :key="p.value" type="button" :class="{ active: view === p.value }" :aria-current="view === p.value ? 'page' : undefined" @click="$emit('change', p.value)">{{ p.label }}</button>
  </nav>
</template>
<style scoped>
.profit-page-tabs{display:inline-flex;gap:3px;background:var(--surface-muted,var(--el-fill-color-light));padding:3px;border:1px solid var(--border);border-radius:5px;white-space:nowrap}.profit-page-tabs button{border:0;background:transparent;border-radius:3px;padding:7px 13px;color:var(--muted);font-size:12px;font-weight:600;cursor:pointer}.profit-page-tabs button.active{background:var(--surface);color:var(--theme-strong);box-shadow:0 1px 3px #0000000a}.profit-page-tabs button:focus-visible{outline:2px solid var(--theme-primary)}
</style>
