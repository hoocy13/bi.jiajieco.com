import http from './http'

function queryParams(params = {}) {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    if (Array.isArray(value)) value.forEach((item) => query.append(key, item))
    else query.append(key, value)
  })
  return query
}

export function getSalesProfitAnalysis(params = {}) {
  return http.get('/sales/profit-analysis', { params: queryParams(params) })
}

export function exportSalesProfitAnalysis(params = {}) {
  return http.get('/sales/profit-analysis/export', { params: queryParams(params), responseType: 'blob' })
}
