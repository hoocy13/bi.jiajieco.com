// Replace decorative neutral bar fills only; preserve warning/status colors.
const neutrals = new Set(['#39393d', '#333336', '#1d1d1f', '#a0a0a6', '#99999f', '#d3d3d7', '#58585e', '#334155', '#344054', '#64748b', '#9aa8b5'])
const isNeutral = color => typeof color === 'string' && neutrals.has(color.toLowerCase())
const neutralFill = color => isNeutral(color) || (color?.colorStops?.length && color.colorStops.every(stop => isNeutral(stop.color)))

export function colorizeBars(option, path, dark) {
  if (!option?.series) return option
  const sales = path.startsWith('/sales') && path !== '/sales/overview'
  const colors = sales
    ? (dark ? ['#ce94a5', '#a8beaa', '#d4b389'] : ['#a26579', '#769582', '#b99a6b'])
    : (dark ? ['#86b69b', '#c7af87', '#c796a5'] : ['#52846b', '#b1966a', '#a47183'])
  const series = Array.isArray(option.series) ? option.series : [option.series]
  let barIndex = 0
  return { ...option, series: series.map((item, index) => {
    if (item.type !== 'bar') return item
    const color = colors[barIndex++ % colors.length]
    const palette = item.color || option.color
    const inherited = typeof palette === 'string' ? palette : palette?.[index % palette.length]
    const fill = item.itemStyle?.color
    const replace = fill == null ? (!inherited || isNeutral(inherited)) : neutralFill(fill)
    return {
      ...item,
      ...(replace ? { itemStyle: { ...item.itemStyle, color } } : {}),
      ...(Array.isArray(item.data) ? { data: item.data.map(row => row && typeof row === 'object' && neutralFill(row.itemStyle?.color)
        ? { ...row, itemStyle: { ...row.itemStyle, color } } : row) } : {}),
    }
  }) }
}
