import http from './http'

export function getRoles() {
  return http.get('/roles')
}

export function getPermissions() {
  return http.get('/roles/permissions')
}

export function createRole(payload) {
  return http.post('/roles', payload)
}

export function updateRole(id, payload) {
  return http.put(`/roles/${id}`, payload)
}

export function deleteRole(id) {
  return http.delete(`/roles/${id}`)
}
