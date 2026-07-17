<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { askTextToSql } from '../../api/textToSql'

const examples = [
  '近30天各品牌销售额排名前10',
  '今年每个月销售额和销量趋势',
  '昨天各渠道销售额是多少',
  '当前各品牌库存和可用库存是多少',
  '哪些商品剩余有效天数小于30天',
  '近30天销量最高的商品有哪些',
  '各品类销售额占比是多少',
  '毛利最高的品牌有哪些',
]

const question = ref(examples[0])
const loading = ref(false)
const result = ref(null)
const showSql = ref(true)
const includeSchemaContext = ref(false)

const columns = computed(() => result.value?.columns || [])
const rows = computed(() => result.value?.rows || [])
const attempts = computed(() => result.value?.attempts || [])
const selectedTables = computed(() => result.value?.schema_context?.tables || [])
const selectedMetrics = computed(() => result.value?.schema_context?.metrics || [])

function formatCell(value) {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'number') {
    return Number.isInteger(value) ? value.toLocaleString() : value.toLocaleString(undefined, { maximumFractionDigits: 2 })
  }
  return String(value)
}

function useExample(item) {
  question.value = item
  submit()
}

async function submit() {
  const text = question.value.trim()
  if (!text) {
    ElMessage.warning('请输入要查询的问题')
    return
  }
  loading.value = true
  try {
    const response = await askTextToSql({
      question: text,
      top_k_tables: 5,
      top_k_examples: 3,
      max_rows: 200,
      max_retries: 2,
      include_schema_context: includeSchemaContext.value,
    })
    result.value = response.data
    if (result.value?.failed) {
      ElMessage.warning('这次没有成功执行，可以换个问法或查看执行过程')
    }
  } finally {
    loading.value = false
  }
}

async function copySql() {
  if (!result.value?.sql) return
  await navigator.clipboard.writeText(result.value.sql)
  ElMessage.success('SQL 已复制')
}
</script>

<template>
  <div class="page-stack text-sql-page">
    <section class="toolbar-panel text-sql-ask">
      <div class="ask-main">
        <label class="ask-field">
          <span>直接问数据</span>
          <el-input
            v-model="question"
            type="textarea"
            :autosize="{ minRows: 3, maxRows: 5 }"
            placeholder="例如：近30天各品牌销售额排名前10"
            @keydown.enter.ctrl.prevent="submit"
          />
        </label>
        <div class="ask-actions">
          <el-button type="primary" :icon="'Search'" :loading="loading" @click="submit">查询</el-button>
          <el-checkbox v-model="includeSchemaContext">显示召回上下文</el-checkbox>
        </div>
      </div>

      <div class="example-row">
        <el-button v-for="item in examples" :key="item" size="small" plain @click="useExample(item)">
          {{ item }}
        </el-button>
      </div>
    </section>

    <section v-if="result" class="panel answer-panel" v-loading="loading">
      <header>
        <h2>查询结果<span class="panel-source">（Text-to-SQL Agent）</span></h2>
        <div class="answer-status">
          <el-tag :type="result.failed ? 'danger' : 'success'" effect="plain">
            {{ result.failed ? '执行失败' : `返回 ${result.row_count} 行` }}
          </el-tag>
          <el-tag v-if="result.limited" type="info" effect="plain">已限制 {{ result.max_rows }} 行</el-tag>
        </div>
      </header>

      <el-alert
        v-if="result.failed"
        :title="result.error || '执行失败'"
        type="warning"
        show-icon
        :closable="false"
        class="agent-alert"
      />

      <el-table v-if="rows.length" :data="rows" height="460">
        <el-table-column
          v-for="column in columns"
          :key="column"
          :prop="column"
          :label="column"
          min-width="150"
          show-overflow-tooltip
        >
          <template #default="{ row }">
            {{ formatCell(row[column]) }}
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="暂无结果" />
    </section>

    <section v-if="result" class="text-sql-grid">
      <section class="panel sql-panel">
        <header>
          <h2>生成 SQL</h2>
          <div class="panel-actions">
            <el-switch v-model="showSql" active-text="显示" inactive-text="隐藏" />
            <el-button size="small" :icon="'CopyDocument'" @click="copySql">复制</el-button>
          </div>
        </header>
        <pre v-if="showSql" class="sql-code">{{ result.sql }}</pre>
        <div v-else class="muted-box">SQL 已隐藏</div>
      </section>

      <section class="panel attempts-panel">
        <header>
          <h2>执行过程</h2>
        </header>
        <el-timeline>
          <el-timeline-item
            v-for="attempt in attempts"
            :key="attempt.attempt"
            :type="attempt.success ? 'success' : 'warning'"
            :timestamp="`第 ${attempt.attempt} 次 · ${attempt.stage}`"
          >
            <div class="attempt-line">
              <strong>{{ attempt.success ? '成功' : '未成功' }}</strong>
              <span v-if="attempt.row_count !== undefined">返回 {{ attempt.row_count }} 行</span>
              <span v-if="attempt.error">{{ attempt.error }}</span>
            </div>
          </el-timeline-item>
        </el-timeline>
      </section>
    </section>

    <section v-if="result && includeSchemaContext" class="panel context-panel">
      <header>
        <h2>召回上下文</h2>
      </header>
      <div class="context-columns">
        <div>
          <h3>表</h3>
          <el-tag v-for="table in selectedTables" :key="table.name" effect="plain">{{ table.name }}</el-tag>
        </div>
        <div>
          <h3>指标</h3>
          <el-tag v-for="metric in selectedMetrics" :key="metric.name" type="success" effect="plain">
            {{ metric.name }}
          </el-tag>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.text-sql-ask {
  display: grid;
  gap: 14px;
}

.ask-main {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 14px;
  align-items: end;
}

.ask-field {
  display: grid;
  gap: 8px;
}

.ask-field > span {
  color: var(--text-soft);
  font-size: 13px;
  font-weight: 650;
}

.ask-actions {
  display: flex;
  gap: 12px;
  align-items: center;
  padding-bottom: 2px;
}

.example-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.answer-panel header,
.sql-panel header,
.attempts-panel header,
.context-panel header {
  align-items: center;
}

.answer-status,
.panel-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.agent-alert {
  margin-bottom: 12px;
}

.text-sql-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(320px, 0.65fr);
  gap: 16px;
}

.sql-code {
  max-height: 360px;
  margin: 0;
  padding: 14px;
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: #111318;
  color: #f1f3f5;
  font-family: "JetBrains Mono", "Consolas", monospace;
  font-size: 12px;
  line-height: 1.65;
  white-space: pre-wrap;
}

.muted-box {
  padding: 18px;
  border: 1px dashed var(--border);
  border-radius: var(--radius);
  color: var(--muted);
}

.attempt-line {
  display: grid;
  gap: 4px;
  color: var(--text-soft);
  font-size: 13px;
}

.attempt-line span {
  word-break: break-word;
}

.context-columns {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.context-columns h3 {
  margin: 0 0 10px;
  color: var(--muted);
  font-size: 13px;
}

.context-columns .el-tag {
  margin: 0 8px 8px 0;
}

@media (max-width: 980px) {
  .ask-main,
  .text-sql-grid,
  .context-columns {
    grid-template-columns: 1fr;
  }

  .ask-actions {
    justify-content: flex-start;
  }
}
</style>
