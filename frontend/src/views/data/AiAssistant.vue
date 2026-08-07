<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  listConversations,
  createConversation,
  getConversation,
  createRun,
  getRun,
  cancelRun,
  streamRunEvents,
} from '../../api/rag'

const route = useRoute()
const router = useRouter()

// 会话列表
const conversations = ref([])
const conversationsLoading = ref(false)
const currentConversationId = computed(() => route.query.conversation || null)

// 当前会话详情
const conversation = ref(null)
const conversationLoading = ref(false)

// 消息和运行状态
const messages = ref([])
const currentRun = ref(null)
const runEvents = ref([])
const streamingAnswer = ref('')
const isStreaming = ref(false)

// 输入
const question = ref('')
const questionLoading = ref(false)

// SSE 控制
let stopSSE = null
const lastEventId = ref(null)

// 引用来源
const citations = ref([])

// SQL 结果
const sqlResult = ref(null)

// 计算属性
const sortedMessages = computed(() => {
  return [...messages.value].sort((a, b) => new Date(a.created_at) - new Date(b.created_at))
})

const runSteps = computed(() => {
  return runEvents.value.filter(e =>
    ['node.started', 'node.completed', 'node.failed', 'tool.started', 'tool.completed'].includes(e.event)
  )
})

const isRunActive = computed(() => {
  return currentRun.value && ['pending', 'running'].includes(currentRun.value.status)
})

// 加载会话列表
async function loadConversations() {
  conversationsLoading.value = true
  try {
    const res = await listConversations()
    conversations.value = res.data || []
  } catch (e) {
    console.error('加载会话列表失败', e)
  } finally {
    conversationsLoading.value = false
  }
}

// 加载会话详情
async function loadConversation(id) {
  if (!id) {
    conversation.value = null
    messages.value = []
    return
  }

  conversationLoading.value = true
  try {
    const res = await getConversation(id)
    conversation.value = res.data
    messages.value = res.data.messages || []
  } catch (e) {
    console.error('加载会话失败', e)
    ElMessage.error('加载会话失败')
  } finally {
    conversationLoading.value = false
  }
}

// 创建新会话
async function handleCreateConversation() {
  try {
    const res = await createConversation({ title: '新对话' })
    const newId = res.data.id
    router.replace({ query: { conversation: newId } })
    await loadConversations()
    await loadConversation(newId)
  } catch (e) {
    ElMessage.error('创建会话失败')
  }
}

// 切换会话
function switchConversation(id) {
  router.replace({ query: { conversation: id } })
}

// 发送问题
async function handleSubmit() {
  const text = question.value.trim()
  if (!text || !currentConversationId.value) return

  questionLoading.value = true
  streamingAnswer.value = ''
  citations.value = []
  sqlResult.value = null
  runEvents.value = []
  lastEventId.value = null

  try {
    // 创建 Run
    const res = await createRun(currentConversationId.value, { question: text })
    const runId = res.data.run_id

    // 添加用户消息到本地
    messages.value.push({
      id: 'user-' + Date.now(),
      role: 'user',
      content: text,
      created_at: new Date().toISOString(),
    })

    // 清空输入
    question.value = ''

    // 开始流式读取
    isStreaming.value = true
    stopSSE = streamRunEvents(runId, {
      onEvent({ id, data }) {
        lastEventId.value = id
        runEvents.value.push({ event: data.event, ...data })

        switch (data.event) {
          case 'run.started':
            currentRun.value = { id: runId, status: 'running' }
            break
          case 'answer.delta':
            streamingAnswer.value += data.delta || ''
            break
          case 'citation':
            citations.value.push(data)
            break
          case 'tool.completed':
            if (data.tool === 'text_to_sql' && data.result) {
              sqlResult.value = data.result
            }
            break
          case 'run.completed':
            currentRun.value = { id: runId, status: 'completed' }
            isStreaming.value = false
            // 添加助手消息
            messages.value.push({
              id: 'assistant-' + Date.now(),
              role: 'assistant',
              content: streamingAnswer.value,
              citations: citations.value,
              sql: sqlResult.value,
              created_at: new Date().toISOString(),
            })
            streamingAnswer.value = ''
            loadConversation(currentConversationId.value)
            break
          case 'run.failed':
            currentRun.value = { id: runId, status: 'failed', error: data.error }
            isStreaming.value = false
            ElMessage.error(data.error || '运行失败')
            break
          case 'run.cancelled':
            currentRun.value = { id: runId, status: 'cancelled' }
            isStreaming.value = false
            if (streamingAnswer.value) {
              messages.value.push({
                id: 'assistant-' + Date.now(),
                role: 'assistant',
                content: streamingAnswer.value + '\n\n*(已取消)*',
                citations: citations.value,
                created_at: new Date().toISOString(),
              })
              streamingAnswer.value = ''
            }
            break
        }
      },
      onError(err) {
        console.error('SSE 错误', err)
        isStreaming.value = false
        ElMessage.error('连接中断')
      },
      onDone() {
        isStreaming.value = false
      },
    })
  } catch (e) {
    ElMessage.error(e.response?.data?.detail?.message || '发送失败')
    isStreaming.value = false
  } finally {
    questionLoading.value = false
  }
}

// 停止生成
async function handleStop() {
  if (!currentRun.value?.id) return
  try {
    await cancelRun(currentRun.value.id)
    ElMessage.info('已请求停止')
  } catch (e) {
    ElMessage.error('停止失败')
  }
}

// 格式化消息内容（简单 Markdown）
function formatContent(content) {
  if (!content) return ''
  return content
    .replace(/\*\*(.*?)\*\*/g, '<strong></strong>')
    .replace(/\n/g, '<br>')
}

// 滚动到底部
const messagesRef = ref(null)
function scrollToBottom() {
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  })
}

// 监听消息变化自动滚动
watch([sortedMessages, streamingAnswer], scrollToBottom)

// 监听路由变化
watch(() => route.query.conversation, (id) => {
  if (id) loadConversation(id)
})

// 生命周期
onMounted(async () => {
  await loadConversations()
  if (currentConversationId.value) {
    await loadConversation(currentConversationId.value)
  }
})

onUnmounted(() => {
  stopSSE?.()
})
</script>

<template>
  <div class="ai-assistant-page">
    <!-- 左侧会话列表 -->
    <aside class="conversation-sidebar">
      <div class="sidebar-header">
        <h3>对话历史</h3>
        <el-button type="primary" size="small" @click="handleCreateConversation">
          <el-icon><Plus /></el-icon>
          新对话
        </el-button>
      </div>
      <div class="conversation-list" v-loading="conversationsLoading">
        <div
          v-for="conv in conversations"
          :key="conv.id"
          class="conversation-item"
          :class="{ active: conv.id === currentConversationId }"
          @click="switchConversation(conv.id)"
        >
          <el-icon><ChatDotRound /></el-icon>
          <span class="conversation-title">{{ conv.title || '新对话' }}</span>
          <span class="conversation-time">{{ new Date(conv.created_at).toLocaleDateString() }}</span>
        </div>
        <el-empty v-if="!conversations.length && !conversationsLoading" description="暂无对话" />
      </div>
    </aside>

    <!-- 右侧聊天区域 -->
    <main class="chat-main">
      <template v-if="currentConversationId">
        <!-- 消息区域 -->
        <div class="messages-container" ref="messagesRef">
          <div v-if="conversationLoading" class="loading-state">
            <el-icon class="is-loading"><Loading /></el-icon>
            <span>加载中...</span>
          </div>
          <template v-else>
            <!-- 消息列表 -->
            <div
              v-for="msg in sortedMessages"
              :key="msg.id"
              class="message-item"
              :class="['message-' + msg.role]"
            >
              <div class="message-avatar">
                <el-icon v-if="msg.role === 'user'"><User /></el-icon>
                <el-icon v-else><Monitor /></el-icon>
              </div>
              <div class="message-content">
                <div class="message-bubble" v-html="formatContent(msg.content)"></div>
                <!-- 引用来源 -->
                <div v-if="msg.citations?.length" class="message-citations">
                  <el-collapse>
                    <el-collapse-item title="引用来源">
                      <div v-for="(cite, idx) in msg.citations" :key="idx" class="citation-item">
                        <el-tag size="small" effect="plain">{{ idx + 1 }}</el-tag>
                        <span>{{ cite.source || cite.text }}</span>
                      </div>
                    </el-collapse-item>
                  </el-collapse>
                </div>
                <!-- SQL 结果 -->
                <div v-if="msg.sql" class="message-sql">
                  <el-collapse>
                    <el-collapse-item title="SQL 查询结果">
                      <pre class="sql-code">{{ msg.sql.sql }}</pre>
                      <el-table v-if="msg.sql.rows?.length" :data="msg.sql.rows" size="small" max-height="300">
                        <el-table-column
                          v-for="col in (msg.sql.columns || [])"
                          :key="col"
                          :prop="col"
                          :label="col"
                          min-width="120"
                          show-overflow-tooltip
                        />
                      </el-table>
                    </el-collapse-item>
                  </el-collapse>
                </div>
              </div>
            </div>

            <!-- 流式输出中的消息 -->
            <div v-if="isStreaming" class="message-item message-assistant">
              <div class="message-avatar">
                <el-icon><Monitor /></el-icon>
              </div>
              <div class="message-content">
                <div class="message-bubble streaming" v-html="formatContent(streamingAnswer)"></div>
                <div v-if="citations.length" class="message-citations">
                  <el-collapse>
                    <el-collapse-item title="引用来源">
                      <div v-for="(cite, idx) in citations" :key="idx" class="citation-item">
                        <el-tag size="small" effect="plain">{{ idx + 1 }}</el-tag>
                        <span>{{ cite.source || cite.text }}</span>
                      </div>
                    </el-collapse-item>
                  </el-collapse>
                </div>
              </div>
            </div>
          </template>
        </div>

        <!-- 运行步骤 -->
        <div v-if="runSteps.length" class="run-steps">
          <el-collapse>
            <el-collapse-item :title="'运行步骤 (' + runSteps.length + ')'">
              <el-timeline>
                <el-timeline-item
                  v-for="(step, idx) in runSteps"
                  :key="idx"
                  :type="step.event === 'node.failed' ? 'danger' : step.event === 'node.completed' ? 'success' : 'primary'"
                  :timestamp="step.node"
                >
                  <span v-if="step.event === 'node.started'">开始执行</span>
                  <span v-else-if="step.event === 'node.completed'">
                    完成 <el-tag v-if="step.duration_ms" size="small">{{ step.duration_ms }}ms</el-tag>
                  </span>
                  <span v-else-if="step.event === 'node.failed'" class="error-text">{{ step.error }}</span>
                  <span v-else-if="step.event === 'tool.started'">调用工具: {{ step.tool }}</span>
                  <span v-else-if="step.event === 'tool.completed'">工具完成: {{ step.tool }}</span>
                </el-timeline-item>
              </el-timeline>
            </el-collapse-item>
          </el-collapse>
        </div>

        <!-- 输入区域 -->
        <div class="input-area">
          <div class="input-wrapper">
            <el-input
              v-model="question"
              type="textarea"
              :autosize="{ minRows: 1, maxRows: 4 }"
              placeholder="输入你的问题... (Enter 发送，Shift+Enter 换行)"
              :disabled="isStreaming"
              @keydown.enter.exact.prevent="handleSubmit"
            />
            <div class="input-actions">
              <el-button
                v-if="isStreaming"
                type="danger"
                :icon="'VideoPause'"
                @click="handleStop"
              >
                停止生成
              </el-button>
              <el-button
                v-else
                type="primary"
                :icon="'Promotion'"
                :loading="questionLoading"
                :disabled="!question.trim()"
                @click="handleSubmit"
              >
                发送
              </el-button>
            </div>
          </div>
        </div>
      </template>

      <!-- 无会话时的空状态 -->
      <div v-else class="empty-state">
        <el-icon :size="64" color="var(--muted)"><ChatDotRound /></el-icon>
        <h2>AI 数据助手</h2>
        <p>基于 RAG 的智能问答，支持知识查询、指标分析和 SQL 查询</p>
        <el-button type="primary" @click="handleCreateConversation">开始新对话</el-button>
      </div>
    </main>
  </div>
</template>

<style scoped>
.ai-assistant-page {
  display: flex;
  height: calc(100vh - 120px);
  gap: 0;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  background: var(--bg);
}

/* 左侧会话列表 */
.conversation-sidebar {
  width: 280px;
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  background: var(--bg-soft);
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px;
  border-bottom: 1px solid var(--border);
}

.sidebar-header h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
}

.conversation-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.conversation-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px;
  border-radius: var(--radius);
  cursor: pointer;
  transition: background 0.2s;
}

.conversation-item:hover {
  background: var(--bg-hover);
}

.conversation-item.active {
  background: var(--accent-soft);
  color: var(--accent);
}

.conversation-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 14px;
}

.conversation-time {
  font-size: 12px;
  color: var(--muted);
}

/* 右侧聊天区域 */
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

/* 消息区域 */
.messages-container {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

.loading-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 40px;
  color: var(--muted);
}

/* 消息样式 */
.message-item {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
}

.message-user {
  flex-direction: row-reverse;
}

.message-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.message-user .message-avatar {
  background: var(--accent);
  color: white;
}

.message-assistant .message-avatar {
  background: var(--bg-soft);
  border: 1px solid var(--border);
  color: var(--text);
}

.message-content {
  max-width: 70%;
}

.message-bubble {
  padding: 12px 16px;
  border-radius: 12px;
  line-height: 1.6;
  font-size: 14px;
}

.message-user .message-bubble {
  background: var(--accent);
  color: white;
  border-bottom-right-radius: 4px;
}

.message-assistant .message-bubble {
  background: var(--bg-soft);
  border: 1px solid var(--border);
  border-bottom-left-radius: 4px;
}

.message-bubble.streaming {
  border-color: var(--accent);
}

.message-bubble.streaming::after {
  content: '|';
  animation: blink 0.8s infinite;
  color: var(--accent);
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

/* 引用和 SQL */
.message-citations,
.message-sql {
  margin-top: 8px;
}

.citation-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 6px 0;
  font-size: 13px;
}

.sql-code {
  margin: 8px 0;
  padding: 12px;
  background: #111318;
  color: #f1f3f5;
  border-radius: var(--radius);
  font-family: 'JetBrains Mono', 'Consolas', monospace;
  font-size: 12px;
  line-height: 1.5;
  overflow-x: auto;
}

/* 运行步骤 */
.run-steps {
  border-top: 1px solid var(--border);
  padding: 12px 20px;
}

.error-text {
  color: var(--el-color-danger);
}

/* 输入区域 */
.input-area {
  border-top: 1px solid var(--border);
  padding: 16px 20px;
  background: var(--bg);
}

.input-wrapper {
  display: flex;
  gap: 12px;
  align-items: flex-end;
}

.input-wrapper .el-input {
  flex: 1;
}

.input-actions {
  display: flex;
  gap: 8px;
}

/* 空状态 */
.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  color: var(--muted);
}

.empty-state h2 {
  margin: 0;
  font-size: 20px;
  color: var(--text);
}

.empty-state p {
  margin: 0;
  font-size: 14px;
}

/* 深色模式适配 */
:deep(.el-collapse-item__header) {
  background: transparent;
  border-bottom: 1px solid var(--border);
}

:deep(.el-collapse-item__wrap) {
  background: transparent;
}

:deep(.el-timeline-item__tail) {
  border-left-color: var(--border);
}

/* 响应式 */
@media (max-width: 768px) {
  .ai-assistant-page {
    flex-direction: column;
    height: auto;
  }

  .conversation-sidebar {
    width: 100%;
    max-height: 200px;
    border-right: none;
    border-bottom: 1px solid var(--border);
  }

  .message-content {
    max-width: 85%;
  }
}
</style>
