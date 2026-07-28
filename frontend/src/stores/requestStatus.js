import { defineStore } from 'pinia'

function formatDuration(ms) {
  if (!ms && ms !== 0) return ''
  if (ms < 1000) return `${Math.round(ms)} ms`
  return `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} 秒`
}

export const useRequestStatusStore = defineStore('requestStatus', {
  state: () => ({
    activeCount: 0,
    activeRequests: {},
    lastDurationMs: 0,
    lastUrl: '',
    lastMethod: '',
    lastStatus: '',
    lastFinishedAt: '',
    lastServerDurationMs: 0,
    lastDbDurationMs: 0,
    lastDbQueryCount: 0,
    lastOdsDurationMs: 0,
    lastOdsQueryCount: 0,
    lastAdsDurationMs: 0,
    lastAdsQueryCount: 0,
    lastQueryMode: '',
    lastResponseSource: '',
    lastDualStatus: '',
    history: [],
  }),
  getters: {
    isLoading: (state) => state.activeCount > 0,
    lastDurationText: (state) => formatDuration(state.lastDurationMs),
    statusText: (state) => {
      if (state.activeCount > 0) return `正在加载 ${state.activeCount} 个请求`
      if (!state.lastDurationMs) return '等待查询'
      return `最近加载 ${formatDuration(state.lastDurationMs)}`
    },
  },
  actions: {
    start(requestId, config) {
      this.activeRequests[requestId] = {
        url: config.url || '',
        method: (config.method || 'GET').toUpperCase(),
        startAt: performance.now(),
      }
      this.activeCount = Object.keys(this.activeRequests).length
    },
    finish(requestId, status = 'success', diagnostics = {}) {
      const request = this.activeRequests[requestId]
      if (!request) return undefined
      const durationMs = Math.max(0, performance.now() - request.startAt)
      delete this.activeRequests[requestId]
      this.activeCount = Object.keys(this.activeRequests).length
      this.lastDurationMs = durationMs
      this.lastUrl = request.url
      this.lastMethod = request.method
      this.lastStatus = status
      this.lastFinishedAt = new Date().toISOString()
      this.lastServerDurationMs = diagnostics.serverDurationMs || 0
      this.lastDbDurationMs = diagnostics.dbDurationMs || 0
      this.lastDbQueryCount = diagnostics.dbQueryCount || 0
      this.lastOdsDurationMs = diagnostics.odsDurationMs || 0
      this.lastOdsQueryCount = diagnostics.odsQueryCount || 0
      this.lastAdsDurationMs = diagnostics.adsDurationMs || 0
      this.lastAdsQueryCount = diagnostics.adsQueryCount || 0
      this.lastQueryMode = diagnostics.queryMode || ''
      this.lastResponseSource = diagnostics.responseSource || ''
      this.lastDualStatus = diagnostics.dualStatus || ''
      const record = {
        url: request.url,
        method: request.method,
        status,
        durationMs,
        ...diagnostics,
        finishedAt: this.lastFinishedAt,
      }
      this.history.unshift(record)
      this.history = this.history.slice(0, 20)
      return record
    },
  },
})
