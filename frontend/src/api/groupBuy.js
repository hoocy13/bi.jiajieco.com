import http from './http'
import { ElMessage } from 'element-plus'

const base = '/group-buy/batches'
async function request(method, url, options = {}) {
  try {
    const r = await http({ method, url, ...options, metadata: { rawResponse: true } })
    return options.responseType === 'blob' ? r : r.data
  } catch (error) {
    if (error.response?.status !== 401) {
      let detail = error.response?.data
      if (detail instanceof Blob) { try { detail = JSON.parse(await detail.text()) } catch { detail = null } }
      const d = detail?.detail
      const message = d?.message || (Array.isArray(d) ? d.map(x=>x.msg).join('；') : null) || detail?.message || '团购操作失败，请重试'
      ElMessage.error(message)
    }
    throw error
  }
}
export const listGroupBatches = params => request('get', base, { params })
export const createGroupBatch = data => request('post', base, { data })
export const renameGroupBatch = (id, data) => request('patch', `${base}/${id}`, { data })
export const deleteGroupBatch = (id, revision) => request('delete', `${base}/${id}`, { data: { revision } })
export const restoreGroupBatch = (id, revision) => request('post', `${base}/${id}/restore`, { data: { revision } })
export const getGroupTable = (id, params) => request('get', `${base}/${id}`, { params })
export const lookupGroupProduct = code => request('get', '/group-buy/catalog', { params: { code } })
export const saveGroupCells = (id, data) => request('patch', `${base}/${id}/cells`, { data })
export const addGroupColumn = (id, data) => request('post', `${base}/${id}/columns`, { data })
export const addGroupQuota = (id, data) => request('post', `${base}/${id}/quotas`, { data })
export const addGroupProduct = (id, data) => request('post', `${base}/${id}/products`, { data })
export const updateGroupProduct = (id, productId, data) => request('patch', `${base}/${id}/products/${productId}`, { data })
export const deleteGroupItem = (id, collection, itemId, revision) => request('delete', `${base}/${id}/${collection}/${itemId}`, { data: { revision } })
export const renameGroupItem = (id, collection, itemId, data) => request('patch', `${base}/${id}/${collection}/${itemId}`, { data })
export const setGroupStatus = (id, action, revision) => request('post', `${base}/${id}/${action}`, { data: { revision } })
export const getGroupHistory = (id, page) => request('get', `${base}/${id}/history`, { params: { page } })
export const importGroupFiles = (id, stage, data) => request('post', `${base}/${id}/import/${stage}`, { data })
export const exportGroupBatch = (id, kind) => request('get', `${base}/${id}/export`, { params: { kind }, responseType: 'blob' })
