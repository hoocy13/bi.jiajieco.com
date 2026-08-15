import http from './http'

export function getAnnouncements(params) { return http.get('/announcements', { params }) }
export function getActiveAnnouncements() { return http.get('/dashboard/announcements') }
export function createAnnouncement(payload) { return http.post('/announcements', payload) }
export function updateAnnouncement(id, payload) { return http.put(`/announcements/${id}`, payload) }
export function deleteAnnouncement(id) { return http.delete(`/announcements/${id}`) }
