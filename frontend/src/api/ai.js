import http from './http'

function decisionParams(params = {}) {
  const searchParams = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (Array.isArray(value)) {
      value.forEach((item) => searchParams.append(key, item))
    } else if (value !== undefined && value !== null && value !== '') {
      searchParams.append(key, value)
    }
  })
  return searchParams
}

export function getInventoryDecisions(params = {}) {
  return http.get('/ai/inventory-decisions', { params: decisionParams(params), timeout: 90000 })
}
