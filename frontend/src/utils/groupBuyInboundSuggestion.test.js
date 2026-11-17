import test from 'node:test'
import assert from 'node:assert/strict'
import { planInboundSuggestion } from './groupBuyInboundSuggestion.js'

const row = (id, quantity, barcode = '001') => ({ id, quantity, barcode, status: 'pending', purchase_eligible: true })
const order = (waiting, barcode = '001', id = 'p') => ({ id, barcode, waiting })

test('已到齐的真实场景归因于数量，而不是条码重复', () => {
  const rows = [...Array.from({ length: 9 }, (_, i) => row(i, i ? 1 : 126)), ...Array.from({ length: 6 }, (_, i) => row(i + 9, i ? 1 : 129, '002'))]
  const result = planInboundSuggestion(rows, [order(0), order(0, '002', 'p2')])
  assert.equal(result.length, 15)
  assert.ok(result.every(r => r.issue === '该柜台已到齐' && !r.selectable))
})

test('同条码多批入库合计可容纳时可全部勾选，不视作下单条码重复', () => {
  const rows = [row(1, 6), row(2, 4)]
  assert.ok(planInboundSuggestion(rows, [order(10)]).every(r => r.selectable))
  assert.deepEqual(planInboundSuggestion(rows, [order(9)]).map(r => r.issue), ['同商品入库10，待到货9', '同商品入库10，待到货9'])
})

test('未下单和下单表条码重复分别提示', () => {
  assert.equal(planInboundSuggestion([row(1, 1)], [order(10, 'other')])[0].issue, '该柜台未下单此条码')
  assert.equal(planInboundSuggestion([row(1, 1)], [order(10), order(10, '001', 'duplicate')])[0].issue, '下单表条码重复')
})

test('小样、已处理和待解除记录不带入，负数及源异常不快捷勾选', () => {
  const result = planInboundSuggestion([
    { ...row(1, 1), purchase_eligible: false }, { ...row(2, 1), status: 'confirmed' },
    { ...row(3, 1), reason: '需解除原关联' }, row(4, -1), { ...row(5, 1), source_issue: '源资料待复核' },
  ], [order(10)])
  assert.deepEqual(result.map(r => r.id), [4, 5])
  assert.deepEqual(result.map(r => r.issue), ['入库数量待核对', '源资料待复核'])
})
