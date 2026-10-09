import http from './http'

function inventoryParams(params = {}) {
  const searchParams = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    if (Array.isArray(value)) {
      value.forEach((item) => searchParams.append(key, item))
      return
    }
    searchParams.append(key, value)
  })
  return searchParams
}

export function getInventoryWarehouses() {
  return http.get('/inventory/warehouses')
}

export function getInventoryOverview(params = {}) {
  return http.get('/inventory/overview', { params: inventoryParams(params) })
}

export function getInventoryDetail(params = {}) {
  return http.get('/inventory/health', { params: inventoryParams({ ...params, issue_type: 'any' }) })
}

export function getInventoryValuation(params = {}) {
  return http.get('/inventory/valuation', { params: inventoryParams(params) })
}

export function exportInventoryValuation(params = {}) {
  return http.get('/inventory/valuation/export', { params: inventoryParams(params), responseType: 'blob' })
}

export function getCoreCostPrices(params = {}) {
  return http.get('/inventory/valuation/prices', { params: inventoryParams(params) })
}

export function exportCoreCostPrices(params = {}) {
  return http.get('/inventory/valuation/prices/export', { params: inventoryParams(params), responseType: 'blob' })
}

export function getCoreCostHistory(code) {
  return http.get(`/inventory/valuation/prices/${encodeURIComponent(code)}/history`)
}

export function saveCoreCostPrice(payload) {
  return http.post('/inventory/valuation/prices', payload)
}
export function deleteCoreCostPrice(code) {
  return http.delete(`/inventory/valuation/prices/${encodeURIComponent(code)}`)
}

export function restoreCoreCostPrice(code, revisionId) {
  return http.post(`/inventory/valuation/prices/${encodeURIComponent(code)}/restore`, null, { params: { revision_id: revisionId } })
}

export function previewCoreCostImport(file) {
  const form = new FormData()
  form.append('file', file)
  return http.post('/inventory/valuation/prices/import-preview', form)
}

export function importCoreCostPrices(rows) {
  return http.post('/inventory/valuation/prices/import', { rows })
}

export function getInventoryProductDetail(productCode, params = {}) {
  return http.get(`/inventory/product-detail/${encodeURIComponent(productCode)}`, {
    params: inventoryParams(params),
  })
}

export function getBatchExpiryAnalysis(params = {}) {
  return http.get('/inventory/batch-expiry', { params: inventoryParams(params) })
}

export function getInventoryHealth(params = {}) {
  return http.get('/inventory/health', { params: inventoryParams(params) })
}

export function getInventoryTurnover(params = {}) {
  return http.get('/inventory/turnover', { params: inventoryParams(params) })
}

export function getBrandInventoryTurnover(params = {}) {
  return http.get('/inventory/brand-turnover', { params: inventoryParams(params) })
}

export function getSlowMovingInventory(params = {}) {
  return http.get('/inventory/slow-moving', { params: inventoryParams(params) })
}

export function getBrandMonthlyArrivals(params = {}) {
  return http.get('/inventory/brand-monthly-arrivals', { params: inventoryParams(params) })
}

export function getBrandInventoryFlow(params = {}) {
  return http.get('/inventory/brand-inventory-flow', { params: inventoryParams(params) })
}

export function getBrandInventoryTurnoverAnalysis(params = {}) {
  return http.get('/inventory/brand-inventory-turnover-analysis', { params: inventoryParams(params) })
}

export function getReservationAnalysis(params = {}) {
  return http.get('/reservations/analysis', { params: inventoryParams(params) })
}
