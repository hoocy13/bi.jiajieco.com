import http from './http'

export function askTextToSql(payload) {
  return http.post('/text-to-sql/ask', payload, { timeout: 120000 })
}

export function generateTextToSql(payload) {
  return http.post('/text-to-sql/generate-sql', payload, { timeout: 120000 })
}
