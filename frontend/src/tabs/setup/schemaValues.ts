/** Immutable dotted paths; numeric segments address array entries. */
export type Json = null | boolean | number | string | Json[] | { [key: string]: Json }

export function getAt(root: Json, path: string): Json | undefined {
  let current: Json | undefined = root
  for (const segment of path.split('.')) {
    if (current === null || typeof current !== 'object') return undefined
    current = Array.isArray(current) ? current[Number(segment)] : current[segment]
  }
  return current
}

export function setAt(root: Json, path: string, value: Json): Json {
  const copy = structuredClone(root ?? {})
  const segments = path.split('.')
  let current = copy as Record<string, Json>
  segments.forEach((segment, index) => {
    if (index === segments.length - 1) current[segment] = value
    else {
      const child = current[segment]
      if (child === null || typeof child !== 'object') {
        current[segment] = /^\d+$/.test(segments[index + 1]) ? [] : {}
      }
      current = current[segment] as Record<string, Json>
    }
  })
  return copy
}

export function deleteAt(root: Json, path: string): Json {
  const copy = structuredClone(root ?? {})
  const segments = path.split('.')
  let current: Json | undefined = copy
  for (const segment of segments.slice(0, -1)) {
    if (current === null || typeof current !== 'object') return copy
    current = Array.isArray(current) ? current[Number(segment)] : current[segment]
  }
  if (current !== null && typeof current === 'object') {
    const leaf = segments[segments.length - 1]
    if (Array.isArray(current)) current.splice(Number(leaf), 1)
    else delete current[leaf]
  }
  return copy
}

export function originOf(path: string, overrides: string[]): 'default' | 'world' {
  return overrides.some(other => other === path || other.startsWith(path + '.') || path.startsWith(other + '.'))
    ? 'world' : 'default'
}
