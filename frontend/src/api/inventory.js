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
