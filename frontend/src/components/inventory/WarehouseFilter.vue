<script setup>
defineProps({
  modelValue: {
    type: Array,
    default: () => [],
  },
  options: {
    type: Array,
    default: () => [],
  },
  loading: Boolean,
})

defineEmits(['update:modelValue'])
</script>

<template>
  <el-select
    :model-value="modelValue"
    class="warehouse-filter"
    multiple
    collapse-tags
    collapse-tags-tooltip
    clearable
    filterable
    :loading="loading"
    placeholder="选择仓库名称"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <el-option v-for="warehouse in options" :key="warehouse" :label="warehouse" :value="warehouse" />
  </el-select>
</template>

<style scoped>
.warehouse-filter {
  width: 100%;
}
</style>
