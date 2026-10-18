import type { SecondaryMotionPayload } from '@anima/scene-render'

type Category = 'live' | 'motion' | 'tilt' | 'rebuild'
type MotionField = Exclude<keyof SecondaryMotionPayload['groups'][string], 'bones' | 'scale_axis'>
export const motionFieldPreview = {
  bounce: 'motion', weight: 'tilt', spill_max_deg: 'tilt', head_sag: 'tilt',
  straighten_deg: 'live', freetext_clothing_gain: 'motion',
  rest_deg: 'live', rest_max_deg: 'live', length: 'live', girth: 'live',
  freq_hz: 'motion', freq: 'motion', zeta: 'motion', gain: 'motion', axis_gain: 'motion', max_deg: 'motion',
  gravity: 'tilt', gravity_scale: 'tilt', motion_gravity_scale: 'tilt',
  sag_max_deg: 'tilt', translate: 'tilt', flatten: 'tilt', stretch: 'tilt', spread: 'tilt', flatten_floor: 'tilt', spill: 'tilt', squash: 'tilt',
  enabled: 'rebuild', flip: 'rebuild', params: 'rebuild',
} satisfies Record<MotionField, Category> & Record<string, Category>

/** Mesh-operation fields use the params category regardless of declaration names. */
export function previewHint(field: string, t: (text: string) => string) {
  const category = motionFieldPreview[field as keyof typeof motionFieldPreview] ?? 'rebuild'
  const hints = {
    live: t('Visible in the preview immediately.'),
    motion: t('Visible in the preview while the figure moves (play a clip).'),
    tilt: t('Visible in the preview with Tilt; upright the rest shape already carries gravity.'),
    rebuild: t('Takes effect after Rebuild extension bones.'),
  }
  return { category, hint: ['flatten', 'spill', 'stretch', 'spread', 'flatten_floor'].includes(field)
    ? t('Use Tilt: direct posture targets, independent of gravity and frequency.')
    : field === 'translate' ? t('Use Tilt or gravity scale for sag; play a clip for bounce. Moves the whole weighted group.')
    : field === 'gravity_scale' || field === 'motion_gravity_scale'
    ? t('Visible upright when not 1; otherwise use Tilt.') : hints[category] }
}

/** Positive forward/back tilt puts the figure on its back at 90 degrees. */
export function applyPreviewTilt(root: { rotation: { set: (x: number, y: number, z: number) => unknown } }, forward: number, sideways: number) {
  root.rotation.set(-forward * Math.PI / 180, 0, sideways * Math.PI / 180)
}

/** Follow Tilt at at most 120 degrees per real second, including combined axes. */
export function rateLimitPreviewTilt(current: { forward: number; sideways: number }, target: { forward: number; sideways: number }, realDelta: number) {
  const step = 120 * (Number.isFinite(realDelta) ? Math.max(0, realDelta) : 0)
  const forward = target.forward - current.forward, sideways = target.sideways - current.sideways
  const distance = Math.hypot(forward, sideways)
  const fraction = distance > 0 ? Math.min(1, step / distance) : 0
  return { forward: current.forward + forward * fraction, sideways: current.sideways + sideways * fraction }
}

/** Apply unsaved toolbar multipliers without changing the polled status payload.
 * Undo the saved multipliers at the raw layer before its clamps, then retain
 * the resolved clothing/state factors from the server for the preview.
 */
export function previewMotionSliders(payload: SecondaryMotionPayload | undefined,
  defaults: SecondaryMotionPayload['groups'] | undefined,
  overrides: Record<string, Record<string, number | number[]>> | undefined,
  drafts: Record<string, Record<string, number | number[]>>) {
  if (!payload || !Object.keys(drafts).length) return payload
  const groups = { ...payload.groups }
  for (const [id, draft] of Object.entries(drafts)) {
    const current = payload.groups[id], base = defaults?.[id]
    if (!current || !base) continue
    const saved = overrides?.[id] ?? {}
    const next = { ...current }
    const rules = {
      gain: ['bounce', 1, 1], max_deg: ['bounce', 1, 180],
      freq_hz: ['bounce', -0.5, 20], zeta: ['bounce', -0.5, 10],
      gravity: ['weight', 1, 10], sag_max_deg: ['weight', 1, 180],
      spill_max_deg: ['weight', 1, 180], flatten: ['weight', 1, 1],
      stretch: ['weight', 1, 1], translate: ['weight', 1, 1],
    } as const
    for (const field of Object.keys(rules) as Array<keyof typeof rules>) {
      const [slider, power, limit] = rules[field]
      const raw = Number(saved[field] ?? base[field])
      const before = Math.min(limit, raw * Number(saved[slider] ?? 1) ** power)
      const after = Math.min(limit, raw * Number(draft[slider] ?? 1) ** power)
      next[field] = before > 0 ? Math.min(limit, current[field] * after / before) : current[field]
    }
    groups[id] = next
  }
  return { ...payload, groups, rev: `${payload.rev}:toolbar:${JSON.stringify(drafts)}` }
}
