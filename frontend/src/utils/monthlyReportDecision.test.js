import test from 'node:test'
import assert from 'node:assert/strict'
import { buildManagementReview } from './monthlyReportDecision.js'
const periods=[{period:'2025年9月',paid_amount:200,orders:20,avg_order_amount:10},{period:'2026年8月',paid_amount:100,orders:10,avg_order_amount:10},{period:'2026年9月',paid_amount:150,orders:30,avg_order_amount:5}]
test('management facts use the same calendar periods and never infer discounting',()=>{
 const rows=buildManagementReview({periods},'2026-09')
 assert.match(rows[0].fact,/环比\+50.0%.*同比-25.0%/)
 assert.match(rows[3].fact,/\+200.0%.*-50.0%/)
 assert.match(rows[3].advice,/不直接视为降价/)
})
test('rank conclusions explicitly limit brand scope to the sales top five',()=>{
 const rows=buildManagementReview({channel_sales:[{channel:'A',paid_amount_change:100},{channel:'B',paid_amount_change:-20}],operating_analysis:{brands:[{name:'品牌甲',change:-30}],brand_flows:{brands:[{brand:'品牌甲',summary:{ending_quantity:10000}}]}}},'2026-09')
 assert.match(rows[1].fact,/A增量最大/)
 assert.match(rows[2].fact,/前五品牌中.*品牌甲/)
 assert.match(rows[4].fact,/前五品牌中.*正装＋小样.*1万件/)
 assert.match(rows[4].advice,/不凭总库存判断积压或缺货/)
})
test('absent facts are unavailable rather than zero or automatic claims',()=>{
 const rows=buildManagementReview({},'2026-09')
 assert.equal(rows.length,5)
 assert.match(rows[0].fact,/缺少/)
 assert.match(rows[1].fact,/暂无可核实/)
 assert.match(rows[4].fact,/缺少/)
})
test('missing year-ago period does not invent a zero yoy comparison',()=>{
 const rows=buildManagementReview({periods:periods.slice(1)},'2026-09')
 assert.match(rows[0].fact,/同比暂缺/)
})
