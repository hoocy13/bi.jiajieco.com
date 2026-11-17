export function planInboundSuggestion(rows, orders) {
  const groups = new Map()
  const assignments = []
  for (const row of rows) {
    if (!row.purchase_eligible || !['pending', 'ready'].includes(row.status) || row.reason?.includes('解除')) continue
    const products = orders.filter(p => row.barcode && p.barcode === row.barcode)
    const quantity = Number(row.quantity)
    const item = { id: row.id, issue: '', selectable: false }
    assignments.push(item)
    if (row.source_issue) item.issue = row.source_issue
    else if (!products.length) item.issue = '该柜台未下单此条码'
    else if (products.length > 1) item.issue = '下单表条码重复'
    else if (!Number.isSafeInteger(quantity) || quantity <= 0) item.issue = '入库数量待核对'
    else {
      const product = products[0]
      const group = groups.get(product.id) || { product, items: [], quantity: 0 }
      group.items.push(item)
      group.quantity += quantity
      groups.set(product.id, group)
    }
  }
  for (const { product, items, quantity } of groups.values()) {
    const waiting = Number(product.waiting)
    const issue = !Number.isFinite(waiting) ? '待到货量读取失败'
      : waiting <= 0 ? '该柜台已到齐'
        : quantity > waiting ? `同商品入库${quantity}，待到货${waiting}` : ''
    for (const item of items) {
      item.issue = issue
      item.selectable = !issue
    }
  }
  return assignments
}
