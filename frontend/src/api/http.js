import axios from 'axios'
import { ElMessage } from 'element-plus'
import { useRequestStatusStore } from '../stores/requestStatus'

const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 30000,
})

http.interceptors.request.use((config) => {
  const requestStatus = useRequestStatusStore()
  const requestId = `${Date.now()}-${Math.random().toString(16).slice(2)}`
  config.metadata = { ...(config.metadata || {}), requestId }
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
    requestStatus.finish(response.config.metadata?.requestId, 'success')
    if (response.data && typeof response.data === 'object') {
      response.data._request = {
        duration_ms: Math.round(requestStatus.lastDurationMs),
        url: response.config.url,
        method: (response.config.method || 'GET').toUpperCase(),
      }
    }
    return response.data
  },
  (error) => {
    const requestStatus = useRequestStatusStore()
    requestStatus.finish(error.config?.metadata?.requestId, 'error')

    if (error.response?.status === 401) {
      localStorage.removeItem('jjc_token')
      localStorage.removeItem('jjc_user')
      if (window.location.pathname !== '/login') {
        ElMessage.error('登录已过期，请重新登录')
        window.location.href = '/login'
      }
      return Promise.reject(error)
    }

    const message = error.response?.data?.message || error.message || '请求失败'
    ElMessage.error(message)
    return Promise.reject(error)
  },
)

export default http
