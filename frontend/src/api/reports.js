import http from './http'

export function getMonthlyReports() {
  return http.get('/reports/monthly')
}

export function getMonthlyReport(month) {
  return http.get(`/reports/monthly/${month}`)
}

export function downloadMonthlyReport(month) {
  return http.get(`/reports/monthly/${month}/download`, {
    responseType: 'blob',
    metadata: { rawResponse: true },
  })
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

export function downloadMonthlyReportVersion(month, revision) {
  return http.get(`/reports/monthly-management/${month}/${revision}/download`, {
    responseType: 'blob',
    metadata: { rawResponse: true },
  })
}

export function deleteMonthlyReportVersion(month, revision) {
  return http.delete(`/reports/monthly-management/${month}/${revision}`)
}
