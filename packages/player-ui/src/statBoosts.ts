/** Shared boost presentation for the avatar and nearby characters. */
export interface StatBoost {
  base: number
  boost: number
  value: number
  boosts: { condition: string; label: string; amount: number; remaining_hours: number }[]
}
export interface BoostCondition {
  name?: string
  label?: string
  icon?: string
  remaining_hours?: number | null
  boosts?: { stat: string; amount: number }[]
}
type Translate = (s: string) => string
const signed = (value: number) => value >= 0 ? `+${value}` : String(value)

function boostLine(t: Translate, name: string, amount: string, hours: number | null | undefined) {
  return t('{name} {amount} ({hours} h left)')
    .replace('{name}', name).replace('{amount}', amount)
    .replace('{hours}', hours == null ? '?' : hours.toFixed(1))
}

export function statTitle(t: Translate, label: string, base: number, boost?: StatBoost) {
  if (!boost) return `${label}: ${base}/100`
  return [t('{label} {base} + {boost} = {value}')
    .replace('{label}', label).replace('{base}', String(boost.base))
    .replace('{boost}', String(boost.boost)).replace('{value}', String(boost.value)),
  ...boost.boosts.map(b => boostLine(t, b.label, signed(b.amount), b.remaining_hours))].join('\n')
}

export function conditionTitle(t: Translate, c: BoostCondition) {
  const name = c.label || c.name || ''
  const lines = c.boosts?.map(b => boostLine(t, `${name} · ${b.stat}`, signed(b.amount), c.remaining_hours)) || []
  return lines.length ? lines.join('\n') : c.remaining_hours == null ? name
    : boostLine(t, name, '', c.remaining_hours)
}

