import http from './http'

export function getUsers() {
  return http.get('/users')
}

export function createUser(payload) {
  return http.post('/users', payload)
}

export function updateUserStatus(id, isActive) {
  return http.patch(`/users/${id}/status`, { is_active: isActive })
}
