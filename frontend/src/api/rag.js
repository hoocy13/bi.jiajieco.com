import http from './http'

// 会话相关
export function listConversations() {
  return http.get('/rag/conversations')
}

export function createConversation(data = {}) {
  return http.post('/rag/conversations', data)
}

export function getConversation(conversationId) {
  return http.get('/rag/conversations/' + conversationId)
}

// Run 相关
export function createRun(conversationId, data) {
  return http.post('/rag/conversations/' + conversationId + '/runs', data)
}

export function getRun(runId) {
  return http.get('/rag/runs/' + runId)
}

export function cancelRun(runId) {
  return http.post('/rag/runs/' + runId + '/cancel')
}

// SSE 流式读取（需要手动处理认证 Header）
export function streamRunEvents(runId, { onEvent, onError, onDone, lastEventId }) {
  const token = localStorage.getItem('token') || ''
  const url = new URL('/api/v1/rag/runs/' + runId + '/events', window.location.origin)
  if (lastEventId) {
    url.searchParams.set('after', lastEventId)
  }

  const controller = new AbortController()

  fetch(url.toString(), {
    headers: {
      'Authorization': 'Bearer ' + token,
      'Accept': 'text/event-stream',
    },
    signal: controller.signal,
  })
    .then(response => {
      if (!response.ok) {
        throw new Error('HTTP ' + response.status)
      }
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let currentId = ''

      function processChunk({ done, value }) {
        if (done) {
          onDone?.()
          return
        }

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('id: ')) {
            currentId = line.slice(4).trim()
          } else if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6))
              onEvent?.({ id: currentId, data })
            } catch (e) {
              // 忽略解析错误
            }
          }
        }

        reader.read().then(processChunk).catch(err => {
          if (err.name !== 'AbortError') {
            onError?.(err)
          }
        })
      }

      reader.read().then(processChunk).catch(err => {
        if (err.name !== 'AbortError') {
          onError?.(err)
        }
      })
    })
    .catch(err => {
      if (err.name !== 'AbortError') {
        onError?.(err)
      }
    })

  return () => controller.abort()
}

// 搜索知识库
export function searchKnowledge(params) {
  return http.get('/rag/knowledge/search', { params })
}
