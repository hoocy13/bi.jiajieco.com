import http from './http'

export function getDashboardSummary() {
  return http.get('/dashboard/overview')
}
