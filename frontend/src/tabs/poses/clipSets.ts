/**
 * The clip listing as the admin UI reads it, plus the two rules every surface
 * that shows sets has to agree on: the ORDER of the sets (neutral first, then
 * the base sets, then whatever was discovered) and their short label.
 *
 * Lives beside the components rather than inside one so both the Library view
 * and the entry editor's coverage badge speak the same vocabulary.
 */
/** One installed clip file as the listing reports it. Everything past the
 *  first four fields is sidecar detail — a clip written before the sidecar
 *  carried it simply has none. */
export interface ApiClipRow {
  kind: string
  /** 'a' / 'b' = the two halves of a pair clip, empty = a solo clip */
  role?: string
  /** the subdirectory the file lives in — empty is the neutral set */
  set?: string
  /** free = tracked in git, licensed = local only */
  library?: string
  /** the older name of the same field */
  source?: string
  name?: string
  filename?: string
  /** path inside the library: `[<set>/]<file>` */
  rel?: string
  url: string
  size?: number
  duration_s?: number | null
  fps?: number | null
  frames?: number | null
  loop?: boolean
  origin?: string
  has_sidecar?: boolean
}

export interface ClipListing {
  clips: ApiClipRow[]
  kinds: string[]
  pair_kinds?: string[]
  clip_sets?: string[]
  sets?: string[]
}

/** The sets a kind exists in, neutral first — the vocabulary of the coverage
 *  badge in the entry editor as well as of this matrix. */
export function clipCoverage(clips: ApiClipRow[], kind: string): string[] {
  if (!kind) return []
  const out = new Set<string>()
  for (const c of clips) if (c.kind === kind) out.add(c.set || '')
  return orderSets(Array.from(out))
}

/** Neutral first, then the three base sets, then whatever was discovered. */
export function orderSets(sets: string[]): string[] {
  const base = ['', 'female', 'male', 'animal']
  const rest = sets.filter((s) => !base.includes(s)).sort()
  return [...base.filter((s) => sets.includes(s)), ...rest]
}

/** Short label of a set — the two gendered ones read as their sign, so a
 *  coverage badge stays one line. */
export function setLabel(set: string, t: (en: string) => string): string {
  if (!set) return t('neutral')
  if (set === 'female') return '♀'
  if (set === 'male') return '♂'
  return set
}

