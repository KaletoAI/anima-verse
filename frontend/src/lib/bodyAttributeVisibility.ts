export type BodyConditions = Record<string, (string | number | boolean | null)[]>

/** Resolve attribute conditions against edited slot values and profile fields. */
export function bodyAttributeVisible(
  conditions: BodyConditions | undefined,
  values: Record<string, unknown>,
  profile: Record<string, unknown>,
): boolean {
  return Object.entries(conditions ?? {}).every(([key, allowed]) => {
    const value = key.startsWith('attributes.') ? values[key.slice(11)] : profile[key]
    const normalize = (item: unknown) => item == null || String(item).trim() === ''
      ? null : String(item).trim().toLowerCase()
    return allowed.some(option => normalize(option) === normalize(value))
  })
}
