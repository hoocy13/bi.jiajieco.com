import http from './http'

const root = '/inventory-watches'
function params(values) {
  const result = new URLSearchParams()
  for (const [key, value] of Object.entries(values || {})) {
    for (const item of Array.isArray(value) ? value : [value]) {
      if (item !== '' && item != null) result.append(key, String(item))
    }
  }
  return result
}
export const getWatchOptions = () => http.get(`${root}/options`)
export const getWatches = values => http.get(root, { params: params(values) })
export const getWatchCandidates = values => http.get(`${root}/candidates`, { params: params(values) })
export const addWatches = body => http.post(`${root}/batch`, body)
export const updateWatch = (id, body) => http.patch(`${root}/${id}`, body)
export const removeWatch = id => http.delete(`${root}/${id}`)
export const getWatchProduct = (code, values) => http.get(`${root}/products/${encodeURIComponent(code)}`, { params: params(values) })
