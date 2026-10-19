import { salesContributors } from './monthlyReportInsights.js'
import { buildMonthlyComparison, periodMonth } from './monthlyReportComparison.js'
import { reportAmount } from './monthlyReportFormat.js'

const valid = n => n != null && Number.isFinite(Number(n))
const pct = n => valid(n) ? `${n > 0 ? '+' : ''}${(Number(n)*100).toFixed(1)}%` : '暂缺'
const money = n => `${n > 0 ? '+' : ''}${reportAmount(n)}万元`
const delta = (current, base) => valid(current) && valid(base) && Number(base)>0 ? Number(current)/Number(base)-1 : null

export function buildManagementReview(data = {}, month) {
  const current=buildMonthlyComparison(data.periods||[],[],month).current
  const yearAgoMonth=/^\d{4}-\d{2}$/.test(month||'') ? `${Number(month.slice(0,4))-1}-${month.slice(5)}` : null
  const yearAgo=(data.periods||[]).find(row=>periodMonth(row.period)===yearAgoMonth)
  const yoy=delta(current?.paid_amount,yearAgo?.paid_amount)
  const {growth,decline}=salesContributors(data.channel_sales||[])
  const gain=growth[0], loss=decline[0]
  const falling=(data.operating_analysis?.brands||[]).filter(b=>valid(b.change)&&b.change<0).sort((a,b)=>a.change-b.change)[0]
  const flows=data.operating_analysis?.brand_flows?.brands||[]
  const stock=flows.filter(f=>valid(f.summary?.ending_quantity)).slice().sort((a,b)=>b.summary.ending_quantity-a.summary.ending_quantity)[0]
  const result=[
    {topic:'经营结果',fact:current ? `净销售额${reportAmount(current.paid_amount)}万元；环比${pct(current.paid_amount_mom)}；同比${pct(yoy)}。` : '缺少可核实的本月销售汇总。',
      advice:'按渠道复盘增量与持续成交情况，不凭单月环比安排扩张。',metric:'净销售额、环比、同比'},
    {topic:'增长来源',fact:gain ? `可比渠道中，${gain.channel}增量最大（${money(gain.paid_amount_change)}）${growth[1] ? `，其次为${growth[1].channel}（${money(growth[1].paid_amount_change)}）` : ''}。` : '暂无可核实的正向增量渠道。',
      advice:gain ? `向${gain.channel}确认后续订单计划；先验证续单，再决定新增投入。` : '先核实渠道基期与实际订单，再提出增长安排。',metric:'渠道净销售额、后续订单'},
    {topic:'下降关注',fact:loss ? `${loss.channel}在可比渠道中下降额最大（${money(loss.paid_amount_change)}）${falling ? `；本月销售前五品牌中，${falling.name}下降额最大（${money(falling.change)}）` : ''}。` : '暂无可核实的下降渠道。',
      advice:loss ? '核实订单、退货与同款成交价变化，确认原因后再调整渠道或商品安排。' : '持续核对渠道表现，不预设下降原因。',metric:'订单、退货、同款成交价'},
    {topic:'订单结构',fact:current && valid(current.orders_mom) && valid(current.avg_order_amount_mom) ? `订单数环比${pct(current.orders_mom)}，平均订单金额环比${pct(current.avg_order_amount_mom)}。` : '缺少可比的订单数或平均订单金额。',
      advice:'分开核实批发、零售及商品组合变化；平均订单金额下降不直接视为降价。',metric:'分业务订单数、平均订单金额'},
    {topic:'库存安排',fact:stock ? `本月销售前五品牌中，${stock.brand}正装＋小样月末总库存最高，为${reportAmount(stock.summary.ending_quantity)}万件。` : '缺少可核实的月末品牌库存。',
      advice:stock ? '结合可用库存、待执行订单和采购交期确认采购节奏，不凭总库存判断积压或缺货。' : '补齐月末库存后再讨论采购安排。',metric:'可用库存、待执行订单、交期'},
  ]
  return result
}
