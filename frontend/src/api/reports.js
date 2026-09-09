import http from './http'

export function getMonthlyReports() {
  return http.get('/reports/monthly')
}

export function getMonthlyReport(month) {
  return http.get(`/reports/monthly/${month}`)
}

export function getMonthlyReportManagement() {
  return http.get('/reports/monthly-management')
}

export function generateMonthlyReport(month) {
  return http.post('/reports/monthly-management/generate', { month })
}

export function publishMonthlyReport(month, revision) {
  return http.post(`/reports/monthly-management/${month}/${revision}/publish`)
}

export function deleteMonthlyReportVersion(month, revision) {
  return http.delete(`/reports/monthly-management/${month}/${revision}`)
}
