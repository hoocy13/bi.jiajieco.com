// Monthly reports use whole ten-thousands; preserve small nonzero amounts.
export function reportAmount(value, divisor = 10000) {
  if (value == null || !Number.isFinite(Number(value))) return '-'
  const amount = Number(value) / divisor
  if (amount !== 0 && Math.abs(amount) < 0.01) return amount < 0 ? '>-0.01' : '<0.01'
  const digits = amount !== 0 && Math.abs(amount) < 1 ? 2 : 0
  return amount.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}
