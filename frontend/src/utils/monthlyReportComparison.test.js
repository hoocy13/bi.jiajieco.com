import assert from 'node:assert/strict'
import test from 'node:test'
import { buildMonthlyComparison, monthOverMonth, previousMonth } from './monthlyReportComparison.js'

test('missing and zero baselines are unavailable; a real zero current amount is a 100% decline', () => {
  for (const base of [null, undefined, '', 0]) assert.equal(monthOverMonth(120, base), null)
  assert.equal(monthOverMonth(null, 100), null)
  assert.equal(monthOverMonth(0, 100), -1)
  assert.equal(monthOverMonth(100, 100), 0)
})

test('calendar matching handles January, reordered rows, and last-year comparison rows', () => {
  assert.equal(previousMonth('2026-01'), '2025-12')
  const result = buildMonthlyComparison([
    { period: '2026年1月（本月）', paid_amount: 120, orders: 12, quantity: 24 },
    { period: '2025年1月（去年同期）', paid_amount: 60 },
    { period: '2025年12月（上月）', paid_amount: 100, orders: 10, quantity: 20 },
  ], [], '2026-01')
  assert.ok(Math.abs(result.current.paid_amount_mom - 0.2) < 1e-12)
  assert.equal(result.current.paid_amount_change, 20)
  assert.equal(result.periods[1].paid_amount_mom, null)
  assert.equal(result.periods[2].paid_amount_mom, null)
})

test('channel baselines match both calendar month and channel; a missing channel is not zero', () => {
  const result = buildMonthlyComparison([
    { period: '2026-08', paid_amount: 100 }, { period: '2026-09', paid_amount: 200 },
  ], [
    { period: '2026年9月', channel_group: '线下', paid_amount: 150 },
    { period: '2026年8月', channel_group: '线上', paid_amount: 50 },
    { period: '2026年9月', channel_group: '线上', paid_amount: 50 },
  ], '2026-09')
  assert.equal(result.channels[0].paid_amount_mom, 0)
  assert.equal(result.channels[0].share, 0.25)
  assert.equal(result.channels[1].paid_amount_mom, null)
  assert.equal(result.channels[1].paid_amount_change, null)
  assert.equal(result.channels[1].share, 0.75)
})

test('headline ratios and channel amount changes reconcile within the same report snapshot', () => {
  const result = buildMonthlyComparison([
    { period: '2026-08', paid_amount: 100, orders: 10, quantity: 100, avg_order_amount: 10 },
    { period: '2026-09', paid_amount: 120, orders: 15, quantity: 90, avg_order_amount: 8 },
  ], [
    { period: '2026-08', channel_group: '线上', paid_amount: 20 },
    { period: '2026-08', channel_group: '线下', paid_amount: 80 },
    { period: '2026-09', channel_group: '线上', paid_amount: 40 },
    { period: '2026-09', channel_group: '线下', paid_amount: 80 },
  ], '2026-09')
  const expected = { paid_amount_mom: 0.2, orders_mom: 0.5, quantity_mom: -0.1, avg_order_amount_mom: -0.2 }
  for (const metric of ['paid_amount', 'orders', 'quantity', 'avg_order_amount']) {
    assert.ok(Math.abs(result.current[`${metric}_mom`] - expected[`${metric}_mom`]) < 1e-12)
  }
  assert.equal(result.current.paid_amount_change, 20)
  assert.ok(Math.abs(result.channels.reduce((sum, row) => sum + row.paid_amount_change, 0) - result.current.paid_amount_change) < 0.01)
  assert.ok(Math.abs(result.channels.reduce((sum, row) => sum + row.share, 0) - 1) < 1e-12)
})
