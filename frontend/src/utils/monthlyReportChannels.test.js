import assert from 'node:assert/strict'
import test from 'node:test'
import { summarizeReportChannels } from './monthlyReportChannels.js'
import { displayPlatform, isWuyanChannel } from './salesChannelClassification.js'

test('dashboard classification gives Wuyan priority and normalizes platform names', () => {
  assert.equal(isWuyanChannel({ channel: '寄样', category: '梧颜' }), true)
  assert.equal(isWuyanChannel({ channel_name: '枷美妆专营店', category: '其他' }), true)
  assert.equal(displayPlatform({ platform: '天猫国际直营超市', channel: '天猫国际自营' }), '天猫')
  assert.equal(displayPlatform({ platform: '未设置', channel: '桢美妆抖店' }), '抖音')
})

test('three groups are exclusive; group MoM uses summed baselines, not averaged rates', () => {
  const groups = summarizeReportChannels([
    { channel: '天猫甲', platform: '天猫', channel_group: '线上', paid_amount: 100, paid_amount_change: 20 },
    { channel: '天猫乙', platform: '天猫', channel_group: '线上', paid_amount: 20, paid_amount_change: -20 },
    { channel: '寄样', category: '梧颜', channel_group: '线上', paid_amount: 50, paid_amount_change: -50 },
    { channel: '客户甲', channel_group: '线下', paid_amount: 30, paid_amount_change: 10 },
  ], 200)
  assert.equal(groups.reduce((sum, group) => sum + group.paid_amount, 0), 200)
  assert.equal(groups.reduce((sum, group) => sum + group.share, 0), 1)
  assert.equal(groups[0].rows.length, 1)
  assert.equal(groups[0].rows[0].mom, 0)
  assert.equal(groups[2].mom, -0.5)
})

test('top five plus other retains every amount and negative adjustment', () => {
  const channels = Array.from({ length: 8 }, (_, i) => ({ channel: `客户${i}`, channel_group: '线下', paid_amount: i - 1, paid_amount_change: 1 }))
  const group = summarizeReportChannels(channels, 20)[1]
  assert.equal(group.rows.length, 6)
  assert.equal(group.rows[5].name, '其他（3）')
  assert.equal(group.rows.reduce((sum, row) => sum + row.paid_amount, 0), channels.reduce((sum, row) => sum + row.paid_amount, 0))
  assert.equal(group.rows.reduce((sum, row) => sum + row.previous_amount, 0), channels.reduce((sum, row) => sum + row.paid_amount - row.paid_amount_change, 0))
})

test('unavailable datasets and zero baselines do not claim a comparable rate', () => {
  assert.equal(summarizeReportChannels([], 100)[0].available, false)
  const groups = summarizeReportChannels([{ channel: '客户', channel_group: '线下', paid_amount: 20, paid_amount_change: 20 }], 20)
  assert.equal(groups[1].mom, null)
  assert.equal(summarizeReportChannels([{ channel: '客户', channel_group: '线下', paid_amount: 20 }], 20)[1].mom, null)
  assert.equal(summarizeReportChannels([{ channel: '客户', channel_group: '线下', paid_amount: 20, paid_amount_change: 30 }], 20)[1].mom, null)
})
