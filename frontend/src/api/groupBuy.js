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

const inbound = '/group-buy/inbound'
export const setInboundReceiptHold = (id, brand, data) => request('post', `${inbound}/receipts/${encodeURIComponent(id)}/hold`, { params: { brand }, data })
export const getOrderCollections = params => request('get', `${inbound}/order-collections`, { params })
export const saveOrderCollection = data => request('post', `${inbound}/order-collections`, { data })
export const getInboundReceipts = params => request('get', `${inbound}/receipts`, { params, paramsSerializer: { indexes: null } })
export const getInboundReceipt = (id, params) => request('get', `${inbound}/receipts/${encodeURIComponent(id)}`, { params })
export const confirmInboundReceipt = data => request('post', `${inbound}/receipt-confirmations`, { data })
export const getInboundOptions = () => request('get', `${inbound}/options`)
export const getInboundLines = params => request('get', `${inbound}/lines`, { params, paramsSerializer: { indexes: null } })
export const syncInbound = data => request('post', `${inbound}/sync`, { data })
export const saveInboundMapping = data => request('post', `${inbound}/mapping`, { data })
export const actInbound = data => request('post', `${inbound}/actions`, { data })
export const getInboundProgress = (id, params = {}) => request('get', `${inbound}/progress/${id}`, { params })
export const getInboundHistory = id => request('get', `${inbound}/history/${id}`)
export const getInboundComparison = (id, params = {}) => request('get', `${inbound}/comparison/${id}`, { params })
export const importInboundSuppliers = data => request('post', `${inbound}/suppliers/import`, { data })
