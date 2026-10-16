import { displayPlatform, isOnlineChannel, isWuyanChannel } from './salesChannelClassification.js'

function aggregate(rows, name) {
  const paid_amount = rows.reduce((sum, row) => sum + Number(row.paid_amount || 0), 0)
  const comparable = rows.every(row => Number.isFinite(row.previous_amount))
  const previous_amount = comparable ? rows.reduce((sum, row) => sum + row.previous_amount, 0) : null
  return {
    name, paid_amount, previous_amount,
    mom: previous_amount === null || previous_amount < 0.005 ? null : paid_amount / previous_amount - 1,
  }
}

export function summarizeReportChannels(channels, total, limit = 6) {
  return ['线上平台', '线下渠道', '梧颜'].map((name, index) => {
    const rows = channels.filter(row => (isWuyanChannel(row) ? 2 : isOnlineChannel(row) ? 0 : 1) === index)
      .map(row => ({ ...row, previous_amount: row.paid_amount_change === null || row.paid_amount_change === undefined ? null : Number(row.paid_amount) - Number(row.paid_amount_change) }))
    const groups = new Map()
    for (const row of rows) {
      const key = index === 0 ? displayPlatform(row) : row.channel
      if (!groups.has(key)) groups.set(key, [])
      groups.get(key).push(row)
    }
    let entries = [...groups].map(([key, values]) => aggregate(values, key)).sort((a, b) => b.paid_amount - a.paid_amount || a.name.localeCompare(b.name, 'zh-CN'))
    if (entries.length > limit) entries = [...entries.slice(0, limit - 1), aggregate(entries.slice(limit - 1), `其他（${entries.length - limit + 1}）`)]
    return { ...aggregate(rows, name), share: total ? rows.reduce((sum, row) => sum + Number(row.paid_amount || 0), 0) / total : null, rows: entries, available: channels.length > 0 }
  })
}
