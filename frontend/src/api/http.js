import axios from 'axios'
import { ElMessage } from 'element-plus'
import { useRequestStatusStore } from '../stores/requestStatus'

const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 30000,
})

function headerValue(headers, name) {
  if (!headers) return undefined
  if (typeof headers.get === 'function') return headers.get(name)
  return headers[name.toLowerCase()]
}

function numericHeader(headers, name) {
  const value = Number(headerValue(headers, name))
  return Number.isFinite(value) ? value : undefined
}

function responseDiagnostics(response) {
  return {
    serverRequestId: headerValue(response?.headers, 'x-request-id') || '',
    serverDurationMs: numericHeader(response?.headers, 'x-response-time-ms'),
    dbDurationMs: numericHeader(response?.headers, 'x-db-time-ms'),
    dbQueryCount: numericHeader(response?.headers, 'x-db-query-count'),
    slowQueryCount: numericHeader(response?.headers, 'x-db-slow-query-count'),
    odsDurationMs: numericHeader(response?.headers, 'x-ods-time-ms'),
    odsQueryCount: numericHeader(response?.headers, 'x-ods-query-count'),
    adsDurationMs: numericHeader(response?.headers, 'x-ads-time-ms'),
    adsQueryCount: numericHeader(response?.headers, 'x-ads-query-count'),
    queryMode: headerValue(response?.headers, 'x-bi-query-mode') || '',
    responseSource: headerValue(response?.headers, 'x-bi-response-source') || '',
    dualStatus: headerValue(response?.headers, 'x-bi-dual-status') || '',
  }
}

http.interceptors.request.use((config) => {
  const requestStatus = useRequestStatusStore()
  const requestId = globalThis.crypto?.randomUUID?.()
    || `${Date.now()}-${Math.random().toString(16).slice(2)}`
  config.metadata = { ...(config.metadata || {}), requestId }
  config.headers['X-Request-ID'] = requestId
  requestStatus.start(requestId, config)

  const token = localStorage.getItem('jjc_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

http.interceptors.response.use(
  (response) => {
    const requestStatus = useRequestStatusStore()
    const diagnostics = responseDiagnostics(response)
    const requestRecord = requestStatus.finish(
      response.config.metadata?.requestId,
      'success',
      diagnostics,
    )
    if (response.config.metadata?.rawResponse) return response
    if (response.data && typeof response.data === 'object') {
      response.data._request = {
        duration_ms: Math.round(requestRecord?.durationMs || 0),
        server_duration_ms: diagnostics.serverDurationMs,
        db_duration_ms: diagnostics.dbDurationMs,
        db_query_count: diagnostics.dbQueryCount,
        slow_query_count: diagnostics.slowQueryCount,
        ods_duration_ms: diagnostics.odsDurationMs,
        ods_query_count: diagnostics.odsQueryCount,
        ads_duration_ms: diagnostics.adsDurationMs,
        ads_query_count: diagnostics.adsQueryCount,
        query_mode: diagnostics.queryMode,
        response_source: diagnostics.responseSource,
        dual_status: diagnostics.dualStatus,
        request_id: diagnostics.serverRequestId || response.config.metadata?.requestId,
        url: response.config.url,
        method: (response.config.method || 'GET').toUpperCase(),
      }
    }
    return response.data
  },
  (error) => {
    const requestStatus = useRequestStatusStore()
    requestStatus.finish(
      error.config?.metadata?.requestId,
      'error',
      responseDiagnostics(error.response),
    )

    if (error.response?.status === 401) {
      localStorage.removeItem('jjc_token')
      localStorage.removeItem('jjc_user')
      if (window.location.pathname !== '/login') {
        ElMessage.error('登录已过期，请重新登录')
        window.location.href = '/login'
      }
      return Promise.reject(error)
    }

    if (error.config?.metadata?.rawResponse) return Promise.reject(error)

    const message = error.response?.data?.message || error.message || '请求失败'
    ElMessage.error(message)
    return Promise.reject(error)
  },
)

export default http
