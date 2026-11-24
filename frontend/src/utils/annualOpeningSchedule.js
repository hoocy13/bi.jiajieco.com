// The published order uses the existing match IDs so scores and advancement stay linked.
const openingDays = [
  { date: '2026-12-02', ids: ['A5', 'A6', 'A9'] },
  { date: '2026-12-03', ids: ['A1', 'A2', 'A3', 'A4', 'A7', 'A8'] },
]

export function annualOpeningSchedule(match) {
  if (match.stage === 'opening') {
    for (const { date, ids } of openingDays) {
      const index = ids.indexOf(match.id)
      if (index >= 0) return { date, label: date.slice(5).replace('-', '/'), order: index + 1 }
    }
  }
  if (match.stage === 'playin' && match.id === 'P1') {
    return { date: '2026-12-08', label: '12/08', order: 1 }
  }
  return null
}

export function compareAnnualOpeningSchedule(a, b) {
  const first = annualOpeningSchedule(a)
  const second = annualOpeningSchedule(b)
  if (!first || !second) return Number(!first) - Number(!second)
  return first.date.localeCompare(second.date) || first.order - second.order
}
