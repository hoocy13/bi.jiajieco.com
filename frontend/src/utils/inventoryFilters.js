export function queryArray(value, fallback = []) {
  if (Array.isArray(value)) return value.filter(Boolean)
  if (typeof value === 'string' && value) return [value]
  return [...fallback]
}

export function inventoryQuery(values) {
  const query = {}
  Object.entries(values).forEach(([key, value]) => {
    if (Array.isArray(value)) {
      if (value.length) query[key] = value
      return
    }
    if (value !== '' && value !== null && value !== undefined) query[key] = String(value)
  })
  return query
}

export function productTypeParam(values) {
  return values.length ? values : ['__all__']
}
