import { salesContributors } from './monthlyReportInsights.js'

const valid = value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value))
export function buildSupplyActions(data = {}) {
  const inventory = data.operating_analysis?.inventory || {}
  const stockRows = key => inventory.available ? (inventory[key] || []).filter(row =>
    valid(row.stock) && Number(row.stock) >= 0 && valid(row.quantity) && Number(row.quantity) > 0 && valid(row.days) && Number(row.days) >= 0
  ).slice(0, 5) : []
  const { growth, decline } = salesContributors(data.channel_sales || [])
  return {
    inventory,
    low: stockRows('low'), high: stockRows('high'),
    channels: [...growth.slice(0, 2).map(row => ({ ...row, action: '核对后续订单' })),
      ...decline.slice(0, 2).map(row => ({ ...row, action: '核对订单与退货' }))],
  }
}
