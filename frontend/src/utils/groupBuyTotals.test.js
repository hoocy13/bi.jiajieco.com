import test from 'node:test'
import assert from 'node:assert/strict'
import { aggregateGroupBuy, formatCents, formatPrice, priceCents, groupBuyArrivalTotals } from './groupBuyTotals.js'

test('sums decimal prices exactly, including amounts beyond safe float precision', () => {
  assert.equal(priceCents('0.10') * 3n + priceCents('0.20'), 50n)
  assert.equal(priceCents('1.200'), 120n)
  assert.equal(priceCents('0.1000'), 10n)
  assert.equal(priceCents('1E+2'), 10000n)
  assert.equal(formatCents(priceCents('99999999999999.99') * 100000000n), '9,999,999,999,999,999,000,000.00')
  assert.equal(formatCents(-125n), '-1.25')
})

test('unit prices omit unnecessary decimals without changing fractional values', () => {
  assert.equal(formatPrice('1120.00'), '1,120')
  assert.equal(formatPrice('12.50'), '12.5')
  assert.equal(formatPrice('12.35'), '12.35')
  assert.equal(formatPrice('0.00'), '0')
  assert.equal(formatPrice('99999999999999.99'), '99,999,999,999,999.99')
})

test('uses each displayed product price and live quantities, with distinct customer columns', () => {
  const rows = [
    { id: 'a', price: '12.35', quantities: { first: 2, duplicate: 3 }, totals: { quota: 8, allocated: 5, remaining: 3 } },
    { id: 'b', price: '0.10', quantities: { first: 4, duplicate: 0 }, totals: { quota: 5, allocated: 4, remaining: 1 } },
  ]
  const columns = [{ id: 'first' }, { id: 'duplicate' }]
  const pending = { 'a:first': 7 }
  const getQuantity = (row, c) => pending[`${row.id}:${c.id}`] ?? row.quantities[c.id]
  const totals = aggregateGroupBuy(rows, columns, getQuantity, row => row.totals)
  assert.deepEqual(totals.columns.get('first'), { quantity: 11, amount: 8685n })
  assert.deepEqual(totals.columns.get('duplicate'), { quantity: 3, amount: 3705n })
  assert.deepEqual(totals.summary.allocated, { quantity: 9, amount: 6215n })
  const filtered = aggregateGroupBuy(rows.slice(1), columns.slice(0, 1), getQuantity, row => row.totals)
  assert.deepEqual(filtered.columns.get('first'), { quantity: 4, amount: 40n })
  assert.equal(filtered.columns.size, 1)
})

test('preserves unknown quota, negative remaining amounts and customer summary groups', () => {
  const rows = [
    { price: '100.00', allocations: [3, 2], totals: { quota: null, allocated: 5, remaining: null } },
    { price: '2.50', allocations: [1, 2], totals: { quota: 2, allocated: 3, remaining: -1 } },
  ]
  const result = aggregateGroupBuy(rows, [{ id: 'customer' }], row => row.allocations.reduce((a, b) => a + b, 0), row => row.totals)
  assert.deepEqual(result.columns.get('customer'), { quantity: 8, amount: 50750n })
  assert.deepEqual(result.summary.quota, { quantity: null, amount: null })
  assert.equal(formatCents(result.summary.remaining.amount), '待维护')
  const negative = aggregateGroupBuy(rows.slice(1), [], () => 0, row => row.totals)
  assert.deepEqual(negative.summary.remaining, { quantity: -1, amount: -250n })
})

test('arrival totals keep counter shortages separate from excess and ignore non-counter stock', () => {
  const row={id:'p',orders:{a:10,b:10,stock:99}}
  const sources=[{id:'a',counter:true},{id:'b',counter:true},{id:'stock',counter:false}]
  assert.deepEqual(groupBuyArrivalTotals(row,sources,{'p:a':15,'p:b':5,'p:stock':99}),{received_total:20,waiting_total:5,over_received:5})
  assert.deepEqual(groupBuyArrivalTotals(row,sources,{'p:a':-2}),{received_total:-2,waiting_total:22,over_received:0})
  assert.deepEqual(groupBuyArrivalTotals(row,sources,{'p:a':15,'p:b':5},(p,id)=>id==='b'?12:p.orders[id]),{received_total:20,waiting_total:7,over_received:5})
})

test('arrival footer totals aggregate the displayed product set and preserve unavailable quantities', () => {
  const rows=[{price:'2.50',summary:{quota:10,received_total:4,waiting_total:6}},{price:'1.00',summary:{quota:5,received_total:2,waiting_total:3}}]
  const keys=['quota','received_total','waiting_total']
  assert.deepEqual(aggregateGroupBuy(rows,[],()=>0,r=>r.summary,keys).summary.waiting_total,{quantity:9,amount:1800n})
  assert.equal(aggregateGroupBuy(rows.slice(0,1),[],()=>0,r=>r.summary,keys).summary.received_total.quantity,4)
  assert.equal(aggregateGroupBuy([{price:'1',summary:{received_total:null}}],[],()=>0,r=>r.summary,['received_total']).summary.received_total.quantity,null)
})
