export type Physics = Record<string, number | number[]>
export type MotionDraft = { baseline: Record<string, string>; values: Record<string, string> }
export function validNumber(text: string, min: number, max?: number, positive = false) {
  const value = Number(text)
  return text.trim() !== '' && Number.isFinite(value) && value >= min
    && (max === undefined || value <= max) && (!positive || value > 0)
}
export function makeDraft(values: Physics): MotionDraft {
  const strings: Record<string, string> = {}
  for (const [key, value] of Object.entries(values)) {
    if (key === 'squash' && Array.isArray(value)) {
      strings.squash_min = String(value[0]); strings.squash_max = String(value[1])
    } else if (typeof value === 'number') strings[key] = String(value)
  }
  return { baseline: strings, values: { ...strings } }
}
export function editDraft(draft: MotionDraft, key: string, value: string): MotionDraft {
  return { ...draft, values: { ...draft.values, [key]: value } }
}
export function draftChanged(draft: MotionDraft) {
  return Object.keys(draft.values).some(key => draft.values[key] !== draft.baseline[key])
}
export function draftOverrides(draft: MotionDraft, defaults: Physics, overrides: Physics): Physics {
  const next = { ...overrides }
  for (const key of Object.keys(draft.values)) {
    if (key.startsWith('squash_') || draft.values[key] === draft.baseline[key]) continue
    const value = Number(draft.values[key])
    if (value === defaults[key]) delete next[key]
    else next[key] = value
  }
  if (['squash_min', 'squash_max'].some(key => draft.values[key] !== draft.baseline[key])) {
    const current = (overrides.squash ?? defaults.squash) as number[]
    const value = ['squash_min', 'squash_max'].map((key, index) =>
      draft.values[key] === draft.baseline[key] ? current[index] : Number(draft.values[key]))
    if (JSON.stringify(value) === JSON.stringify(defaults.squash)) delete next.squash
    else next.squash = value
  }
  return next
}
