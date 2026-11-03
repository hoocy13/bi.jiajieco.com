import test from 'node:test'
import assert from 'node:assert/strict'
import { buildSupplyActions } from './monthlyReportActions.js'

test('unavailable inventory never becomes a procurement recommendation', () => {
  const result = buildSupplyActions({ operating_analysis: { inventory: { available: false, low: [{ stock: 1, quantity: 2, days: 15 }] } } })
  assert.deepEqual(result.low, [])
  assert.deepEqual(result.high, [])
})
test('exclude unknown or return-only coverage and keep verified zero stock', () => {
  const result = buildSupplyActions({ operating_analysis: { inventory: { available: true, low: [
    { stock: 0, quantity: 10, days: 0, product_code: 'A' },
    { stock: null, quantity: 10, days: 0 },
    { stock: 10, quantity: -2, days: null },
  ] } }, channel_sales: [
    { channel: '增长渠道', paid_amount: 120, paid_amount_change: 20 },
    { channel: '下降渠道', paid_amount: 30, paid_amount_change: -10 },
    { channel: '缺基期', paid_amount: 40 },
  ] })
  assert.equal(result.low.length, 1)
  assert.equal(result.low[0].product_code, 'A')
  assert.deepEqual(result.channels.map(row => row.action), ['核对后续订单', '核对订单与退货'])
})
