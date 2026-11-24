// Scheduled starts are in China Standard Time (UTC+08:00).
const openingDates = ['2026-11-30', '2026-12-01', '2026-12-02']

export function annualOpeningSchedule(match) {
  const slot = /^A([1-9])$/.exec(match.id)
  if (match.stage === 'opening' && slot) {
    const index = Number(slot[1]) - 1
    const date = openingDates[Math.floor(index / 3)]
    return { date, label: date.slice(5).replace('-', '/'), order: index % 3 + 1 }
  }
  if (match.stage === 'playin' && match.id === 'P1') {
    return { date: '2026-12-03', label: '12/03', order: 1 }
  }
  return null
}
