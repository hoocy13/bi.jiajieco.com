export function isOnlineChannel(item) {
  if (typeof item.is_online === 'boolean') return item.is_online
  if (item.channel_group) return item.channel_group === '线上'
  return Boolean(item.platform && item.platform !== '未设置')
}

export function isWuyanChannel(item) {
  const name = String(item.channel_name || item.channel || '').trim()
  return String(item.category || '').trim() === '梧颜' || ['梧颜', '枷美妆'].some(word => name.includes(word))
}

export function displayPlatform(item) {
  const platform = String(item.platform || '').trim()
  const value = `${platform} ${item.channel_name || item.channel || ''}`
  const names = [
    ['天猫', '天猫'], ['淘宝', '淘宝'], ['拼多多', '拼多多'], ['得物', '得物'],
    ['京东', '京东'], ['快手', '快手'], ['抖店', '抖音'], ['抖音', '抖音'],
    ['美团', '美团'], ['微信', '微信'], ['SHEIN', 'SHEIN'], ['95分', '95分'],
    ['度小店', '百度'], ['基木鱼', '百度'],
  ]
  return names.find(([word]) => value.includes(word))?.[1] || (platform && platform !== '未设置' ? platform : '其他电商')
}
