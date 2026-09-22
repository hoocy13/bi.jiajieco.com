<script setup>
import VChart from 'vue-echarts'
import { useThemeStore } from '../../stores/theme'

defineOptions({ inheritAttrs: false })

const theme = useThemeStore()
</script>

<template>
  <VChart v-bind="$attrs" :theme="theme.isDark ? 'dark' : undefined" />
</template>
