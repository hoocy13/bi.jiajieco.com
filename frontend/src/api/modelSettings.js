import http from './http'

export function getModelSettings() {
  return http.get('/model-settings')
}

export function updateModelSettings(data) {
  return http.put('/model-settings', data)
}

export function testModelSettings() {
  return http.post('/model-settings/test')
}
