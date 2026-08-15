import http from './http'

export function getUsers(params) {
  return http.get('/users', { params })
}

export function createUser(payload) {
  return http.post('/users', payload)
}

export function updateUserStatus(id, isActive) {
  return http.patch(`/users/${id}/status`, { is_active: isActive })
}

export function updateUserRole(id, roleId) {
  return http.put(`/users/${id}/role`, { role_id: roleId })
}

export function updateUserProfile(id, payload) {
  return http.put(`/users/${id}/profile`, payload)
}
