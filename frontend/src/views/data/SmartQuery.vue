<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth'
import TextToSqlAgent from './TextToSqlAgent.vue'
import AiAssistant from './AiAssistant.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const tabs = computed(() => [
  auth.hasPermission('ai.text_to_sql.use') ? { label: '快捷问数', value: 'query' } : null,
  auth.hasPermission('ai.assistant.use') ? { label: '深度分析助手', value: 'assistant' } : null,
].filter(Boolean))

const activeMode = computed({
  get: () => tabs.value.some(item => item.value === route.query.mode)
    ? route.query.mode
    : tabs.value[0]?.value,
  set: mode => router.replace({ query: { ...route.query, mode } }),
})
</script>

<template>
  <div class="smart-query-page">
    <div class="smart-query-tabs">
      <div>
        <h2>智能问数</h2>
        <p>用自然语言查询业务指标，或进入深度对话继续分析。</p>
      </div>
      <el-segmented v-if="tabs.length > 1" v-model="activeMode" :options="tabs" />
    </div>
    <TextToSqlAgent v-if="activeMode === 'query'" />
    <AiAssistant v-else-if="activeMode === 'assistant'" />
  </div>
</template>

<style scoped>
.smart-query-page { display: grid; gap: 14px; }
.smart-query-tabs { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 16px 18px; background: var(--surface); border: 1px solid var(--border); border-radius: 9px; }
.smart-query-tabs h2 { margin: 0; font-size: 17px; }
.smart-query-tabs p { margin: 5px 0 0; color: var(--text-soft); font-size: 12px; }
.smart-query-page :deep(.ai-assistant-page) { height: calc(100vh - 214px); min-height: 560px; }
@media (max-width: 760px) { .smart-query-tabs { align-items: flex-start; flex-direction: column; } }
</style>
