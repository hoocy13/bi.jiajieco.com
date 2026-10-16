export function channelWarning(row) {
  const current = Number(row.paid_amount)
  const change = row.paid_amount_change
  if (change == null || !Number.isFinite(Number(change))) return '缺少基期'
  const previous = current - Number(change)
  if (previous < 0) return '上月负净额'
  if (previous === 0) return current === 0 ? '两月无销售' : '上月为零'
  if (current < 0) return '本月负净额'
  if (current === 0) return '本月无销售'
  if (previous < 10000) return '上月不足1万元'
  return ''
}

export function salesContributors(rows) {
  const comparable = rows.filter(row => row.paid_amount_change != null && Number.isFinite(Number(row.paid_amount_change)))
  const totalChange = comparable.reduce((sum, row) => sum + Number(row.paid_amount_change), 0)
  const map = row => ({ ...row, contribution: comparable.length === rows.length && totalChange !== 0 ? Number(row.paid_amount_change) / Math.abs(totalChange) : null })
  return {
    growth: comparable.filter(row => row.paid_amount_change > 0).sort((a, b) => b.paid_amount_change - a.paid_amount_change).slice(0, 3).map(map),
    decline: comparable.filter(row => row.paid_amount_change < 0).sort((a, b) => a.paid_amount_change - b.paid_amount_change).slice(0, 3).map(map),
  }
}
