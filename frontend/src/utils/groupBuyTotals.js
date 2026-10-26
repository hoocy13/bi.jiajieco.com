// Prices are decimal strings from the API. Sum integer cents to avoid rounding
// errors or loss of precision when multiplying large prices and quantities.
export function priceCents(price) {
  const match = /^([+-]?)(\d+)(?:\.(\d*))?(?:e([+-]?\d+))?$/i.exec(String(price).trim())
  if (!match) throw new TypeError('Invalid product price')
  const [, sign, whole, fraction = '', exponent = '0'] = match
  const digits = BigInt(whole + fraction)
  if (digits === 0n) return 0n
  const scale = Number(exponent) + 2 - fraction.length
  const factor = 10n ** BigInt(Math.abs(scale))
  if (scale < 0 && digits % factor !== 0n) throw new RangeError('Product price must have at most two decimal places')
  const cents = scale < 0 ? digits / factor : digits * factor
  return sign === '-' ? -cents : cents
}

export function formatCents(cents) {
  if (cents == null) return '待维护'
  const sign = cents < 0n ? '-' : ''
  const value = cents < 0n ? -cents : cents
  return `${sign}${(value / 100n).toLocaleString('zh-CN')}.${String(value % 100n).padStart(2, '0')}`
}

export function formatPrice(price) {
  return formatCents(priceCents(price)).replace(/\.00$/, '').replace(/(\.\d)0$/, '$1')
}

export function aggregateGroupBuy(rows, columns, columnQuantity, rowTotals, summaryKeys = ['quota', 'allocated', 'remaining']) {
  const empty = () => ({ quantity: 0, amount: 0n })
  const result = {
    columns: new Map(columns.map(c => [c.id, empty()])),
    summary: Object.fromEntries(summaryKeys.map(key => [key, empty()])),
  }
  function add(target, quantity, price) {
    if (quantity == null) {
      target.quantity = null
      target.amount = null
    } else if (target.quantity != null) {
      target.quantity += quantity
      target.amount += BigInt(quantity) * price
    }
  }
  for (const row of rows) {
    const price = priceCents(row.price)
    const totals = rowTotals(row)
    for (const key of Object.keys(result.summary)) add(result.summary[key], totals[key], price)
    for (const column of columns) add(result.columns.get(column.id), columnQuantity(row, column), price)
  }
  return result
}

export function groupBuyArrivalTotals(row, sources, received, orderQuantity = (row, id) => row.orders[id] || 0) {
  const result = { received_total: 0, waiting_total: 0, over_received: 0 }
  for (const source of sources) {
    if (!source.counter) continue
    const actual = received[`${row.id}:${source.id}`] || 0
    const ordered = orderQuantity(row, source.id)
    result.received_total += actual
    result.waiting_total += Math.max(ordered - actual, 0)
    result.over_received += Math.max(actual - ordered, 0)
  }
  return result
}
