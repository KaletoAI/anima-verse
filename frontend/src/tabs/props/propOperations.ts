import type { PropFull, PropVariant } from './propTypes'

export type PreparePropVariantOperation = (uid: string, label: string) => Promise<PropVariant | null>

/** An async authoring decision must never preserve a recyclable store index. */
export async function resolveVariantAfterBarrier<T extends { uid: string; index: number }>(
  uid: string, beforeOperation: () => Promise<boolean>, read: () => Promise<T[]>,
): Promise<T | null> {
  if (!await beforeOperation()) return null
  const target = (await read()).find((entry) => entry.uid === uid)
  if (!target) throw new Error('The target variant was removed. The operation was not performed.')
  return target
}

export type PropGenerationTarget =
  | { kind: 'append'; index: number; sourceUid: string; sourceIndex: number }
  | { kind: 'existing'; uid: string; index: number }

/** Only the explicit new-variant operation allocates a slot. */
export function propGenerationTarget(
  variants: PropVariant[], max: number, generating: number[] = [],
): PropGenerationTarget {
  if (generating.length) throw new Error('Generation is running for this prop. Wait for it to finish.')
  const active = variants.filter((variant) => variant.active)
  if (active.length >= max) throw new Error('Variant limit reached. Disable or remove a variant first.')
  const source = variants.find((variant) => variant.primary) || active[0]
  if (!source) throw new Error('No active source variant is available.')
  return { kind: 'append', index: variants.length, sourceUid: source.uid, sourceIndex: source.index }
}

/** Settings belong to the confirmed target, or to the author copied on append. */
export function propGenerationAuthor(variants: PropVariant[], target: PropGenerationTarget): PropVariant {
  const uid = target.kind === 'append' ? target.sourceUid : target.uid
  const author = variants.find((variant) => variant.uid === uid)
  if (!author) throw new Error('The target variant was removed. The operation was not performed.')
  return author
}

export function propGenerationSubject(prop: Pick<PropFull, 'name'>,
  variant: Pick<PropVariant, 'description'>): string {
  return variant.description || prop.name
}

export interface PropGenerationRepair {
  op_id: string
  original_variant: number | null
  original_name: string
  backend: string
  tier: string
  reason: string
  created_at: string
  status: 'ready' | 'collected' | 'waiting_provider' | 'unrecorded'
  mesh_ready: boolean
  collected: boolean
  can_resume: boolean
}

export interface PropRepairSnapshot {
  variants: PropVariant[]
  revision: string
  generating_variants: number[]
  repairs: PropGenerationRepair[]
}

export interface PropRepairConfirmation {
  repair: PropGenerationRepair
  target: PropVariant
  body: { resume_op_id: string; variant_uid: string; base_revision: string }
}

/** Resolve the selected UID and publish-only payload AFTER the save/cancel decision. */
export async function resolvePropRepairAfterBarrier(
  opId: string, uid: string, beforeOperation: () => Promise<boolean>, read: () => Promise<PropRepairSnapshot>,
): Promise<PropRepairConfirmation | null> {
  if (!await beforeOperation()) return null
  const current = await read()
  const repair = current.repairs.find((entry) => entry.op_id === opId)
  if (!repair) throw new Error('The retained generation is no longer awaiting assignment.')
  if (!repair.can_resume) throw new Error('No publishable result or existing provider job was recorded.')
  const target = current.variants.find((entry) => entry.uid === uid)
  if (!target) throw new Error('The target variant was removed. The operation was not performed.')
  if (current.generating_variants.includes(target.index)) {
    throw new Error('This target variant is generating. The retained job is kept.')
  }
  if (!current.revision) throw new Error('Could not read the current document revision.')
  return { repair, target, body: {
    resume_op_id: opId, variant_uid: target.uid, base_revision: current.revision,
  } }
}
