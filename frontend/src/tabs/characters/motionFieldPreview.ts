import type { SecondaryMotionPayload } from '@anima/scene-render'

type Category = 'live' | 'motion' | 'tilt' | 'rebuild'
type MotionField = Exclude<keyof SecondaryMotionPayload['groups'][string], 'bones'>
export const motionFieldPreview = {
  rest_deg: 'live', rest_max_deg: 'live',
  freq_hz: 'motion', freq: 'motion', zeta: 'motion', gain: 'motion', axis_gain: 'motion', max_deg: 'motion',
  gravity: 'tilt', gravity_scale: 'tilt', motion_gravity_scale: 'tilt',
  sag_max_deg: 'tilt', translate: 'tilt', flatten: 'tilt', spill: 'tilt', squash: 'tilt',
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
  return { category, hint: field === 'flatten' || field === 'spill'
    ? t('Use Tilt: direct posture targets, independent of gravity and frequency.')
    : field === 'translate' ? t('Use Tilt or gravity scale for sag; play a clip for bounce. Moves the whole weighted group.')
    : field === 'gravity_scale' || field === 'motion_gravity_scale'
    ? t('Visible upright when not 1; otherwise use Tilt.') : hints[category] }
}

/** Positive forward/back tilt puts the figure on its back at 90 degrees. */
export function applyPreviewTilt(root: { rotation: { set: (x: number, y: number, z: number) => unknown } }, forward: number, sideways: number) {
  root.rotation.set(-forward * Math.PI / 180, 0, sideways * Math.PI / 180)
}
