<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { colorizeBars } from '../../utils/chartColors'
import VChart from 'vue-echarts'
import { useThemeStore } from '../../stores/theme'

defineOptions({ inheritAttrs: false })

const theme = useThemeStore()
const route = useRoute()
const props = defineProps({ option: Object })
const option = computed(() => {
  let result = props.option
  if (theme.name === 'mono' && result) {
    const colors = theme.isDark ? ['#d2d2d8', '#a0a0a8', '#76767e', '#b9b9c0', '#909098'] : ['#45454b', '#85858d', '#b2b2b9', '#65656d', '#ceced3']
    const series = Array.isArray(result.series) ? result.series : result.series ? [result.series] : []
    result = { ...result, color: colors, series: series.map((item, index) => ({
      ...item,
      ...(item.type === 'bar' || item.type === 'line' ? { itemStyle: { ...item.itemStyle, color: colors[index % colors.length] }, lineStyle: { ...item.lineStyle, color: colors[index % colors.length] } } : {}),
    })) }
  }
  return theme.interfaceStyle === 'glass'
    ? { ...(theme.name === 'mono' ? result : colorizeBars(result, route.path, theme.isDark)), backgroundColor: 'transparent' }
    : result
})
</script>

<template>
  <VChart v-bind="$attrs" :option="option" :theme="theme.isDark ? 'dark' : undefined" />
</template>
