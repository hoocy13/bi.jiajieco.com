import http from './http'

export function login(payload) {
  return http.post('/auth/login', payload)
}

export function getProfile() {
  return http.get('/auth/me')
}
