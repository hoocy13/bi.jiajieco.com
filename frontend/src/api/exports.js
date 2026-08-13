import http from './http'

export function exportExcel(dataset, filters) {
  return http.post(
    `/exports/${dataset}`,
    { filters },
    {
      responseType: 'blob',
      timeout: 120000,
      metadata: { rawResponse: true },
    },
  )
}

export function exportCurrentData(payload) {
  return http.post('/exports/custom', payload, { responseType: 'blob', timeout: 120000, metadata: { rawResponse: true } })
}
