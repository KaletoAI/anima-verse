import type { PropFull, PropVariant } from './propTypes'

export type PreparePropVariantOperation = (uid: string, label: string) => Promise<PropVariant | null>

/** An async authoring decision must never preserve a recyclable store index. */
export async function resolveVariantAfterBarrier<T extends { uid: string; index: number }>(
  uid: string, confirm: () => Promise<boolean>, read: () => Promise<T[]>,
): Promise<T | null> {
  if (!await confirm()) return null
  const target = (await read()).find((entry) => entry.uid === uid)
  if (!target) throw new Error('Die Zielvariante wurde entfernt. Die Operation wurde nicht ausgeführt.')
  return target
}

export type PropGenerationTarget =
  | { kind: 'append' }
  | { kind: 'existing'; uid: string; index: number; replaces: boolean }

/** Mirrors props.target_variant without creating a slot during a read. */
export function propGenerationTarget(variants: PropVariant[], max: number): PropGenerationTarget {
  const active = variants.filter((variant) => variant.active)
  const empty = active.find((variant) => !variant.tiers.length)
  if (empty) return { kind: 'existing', uid: empty.uid, index: empty.index, replaces: false }
  if (active.length < max) return { kind: 'append' }
  const last = active[active.length - 1]
  if (!last) throw new Error('Keine aktive Zielvariante vorhanden.')
  return { kind: 'existing', uid: last.uid, index: last.index, replaces: true }
}

export function propGenerationSubject(prop: Pick<PropFull, 'name'>,
  variant: Pick<PropVariant, 'description'>): string {
  return variant.description || prop.name
}
