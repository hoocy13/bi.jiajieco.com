<script setup>
import { computed } from 'vue'

const props = defineProps({
  label: String,
  value: String,
  unit: String,
  trend: String,
})

const isNegative = computed(() => String(props.trend || '').startsWith('-'))
</script>

<template>
  <section class="metric-card">
    <div class="metric-label">{{ label }}</div>
    <div class="metric-value">
      <strong>{{ value }}</strong>
      <span>{{ unit }}</span>
    </div>
    <div class="metric-trend" :class="{ 'is-negative': isNegative }">{{ trend }}</div>
  </section>
</template>
