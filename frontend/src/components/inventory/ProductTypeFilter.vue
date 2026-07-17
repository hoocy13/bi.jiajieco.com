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
    class="product-type-filter"
    multiple
    collapse-tags
    collapse-tags-tooltip
    clearable
    :loading="loading"
    placeholder="选择货品分类"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <el-option v-for="item in options" :key="item" :label="item" :value="item" />
  </el-select>
</template>

<style scoped>
.product-type-filter {
  width: 100%;
}
</style>
