import http from './http'

export function getSalesOverview(params = {}) {
  return http.get('/sales/overview', { params })
}

export function getSalesDetail(params = {}) {
  return http.get('/sales/detail', { params })
}

export function getSalesProductRank(params = {}) {
  return http.get('/sales/product-rank', { params })
}

export function getSalesBrandAnalysis(params = {}) {
  return http.get('/sales/brand-analysis', {
    params,
    paramsSerializer: { indexes: null },
  })
}

export function getSalesChannelAnalysis(params = {}) {
  return http.get('/sales/channel-analysis', { params })
}

export function getSalesChannelCustomerAnalysis(params = {}) {
  return http.get('/sales/channel-customer-analysis', { params })
}

export function getSalesBrandChannelAnalysis(params = {}) {
  return http.get('/sales/brand-channel-analysis', {
    params,
    paramsSerializer: { indexes: null },
  })
}
