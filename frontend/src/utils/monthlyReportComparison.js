function numeric(value) {
  if (value === null || value === undefined || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

export function periodMonth(period) {
  const match = String(period || '').match(/^(\d{4})(?:年|-)(\d{1,2})(?:月|\b)/)
  if (!match || Number(match[2]) < 1 || Number(match[2]) > 12) return null
  return `${match[1]}-${match[2].padStart(2, '0')}`
}

export function previousMonth(month) {
  const normalized = periodMonth(month)
  if (!normalized) return null
  const [year, number] = normalized.split('-').map(Number)
  return number === 1 ? `${year - 1}-12` : `${year}-${String(number - 1).padStart(2, '0')}`
}

export function monthOverMonth(current, previous) {
  const value = numeric(current)
  const base = numeric(previous)
  if (value === null || base === null || base === 0) return null
  return value / base - 1
}

function difference(current, previous) {
  const value = numeric(current)
  const base = numeric(previous)
  return value === null || base === null ? null : value - base
}

// Match calendar months, never adjacent array rows: snapshots also contain last year's same month.
export function buildMonthlyComparison(periods = [], channels = [], month) {
  const periodsByMonth = new Map(periods.map(row => [periodMonth(row.period), row]).filter(([key]) => key))
  const rows = periods.map(row => {
    const previous = periodsByMonth.get(previousMonth(periodMonth(row.period)))
    return {
      ...row,
      paid_amount_mom: monthOverMonth(row.paid_amount, previous?.paid_amount),
      orders_mom: monthOverMonth(row.orders, previous?.orders),
      quantity_mom: monthOverMonth(row.quantity, previous?.quantity),
      avg_order_amount_mom: monthOverMonth(row.avg_order_amount, previous?.avg_order_amount),
      paid_amount_change: difference(row.paid_amount, previous?.paid_amount),
    }
  })
  const currentMonth = periodMonth(month)
  const current = currentMonth ? rows.find(row => periodMonth(row.period) === currentMonth) : undefined
  const previous = periodsByMonth.get(previousMonth(currentMonth))
  const currentChannels = currentMonth ? channels.filter(row => periodMonth(row.period) === currentMonth) : []
  const previousChannels = channels.filter(row => periodMonth(row.period) === previousMonth(currentMonth))
  return {
    periods: rows,
    current,
    previous,
    channels: currentChannels.length ? ['线上', '线下'].map(group => {
      const channel = currentChannels.find(row => row.channel_group === group)
      const previousChannel = previousChannels.find(row => row.channel_group === group)
      const amount = numeric(channel?.paid_amount)
      const total = numeric(current?.paid_amount)
      return {
        channel_group: group,
        paid_amount: amount,
        share: amount !== null && total !== null && total !== 0 ? amount / total : null,
        paid_amount_mom: monthOverMonth(amount, previousChannel?.paid_amount),
        paid_amount_change: difference(amount, previousChannel?.paid_amount),
      }
    }) : [],
  }
}
