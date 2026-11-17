/**
 * collisionChannelsModel — the pure half of the Channels panel and the test rod (cross-person collision, plan Task
 * 15). No React, no fetch of its own: checked by `scripts/check_base_body_ui.mjs`. Returned strings are English; the
 * components put them through `t()`.
 *
 * - The per-character override of a declared channel (`model3d_opts.collision_channels[<id>]`,
 *   `app/core/collision_channels.py` `validate_overrides`): an offset in mm along the body frame (side, up, front),
 *   a radius scale, a depth scale (0.5–2), the funnel half-angle and the axis tilt (±45°, + = toward the back,
 *   Ruling A193). The server needs the first four keys per entry (tilt absent = 0); an entry equal to the default
 *   (offset 0, scales 1, the declared cone, tilt 0) is left out of the saved map.
 * - SAVE STORES ONLY (ruling R4): `saveChannelOverrides` posts `…/model3d/collision/channels` — never
 *   `…/model3d/collision`, the step that applies it. The collision step then reads "due"
 *   (`model_overview.CHANNELS_CHANGED`) until the step, Run all or the Build applies it.
 * - The live preview: the shown payload with each changed channel replaced by `previewChannel` of
 *   `@anima/scene-render` (the server's resolution, redone on the client for the draft).
 */
import { previewChannel } from '@anima/scene-render'
import type { ChannelOverride, CollisionPayload } from '@anima/scene-render'
import type { ModelStep } from './ModelSteps'
import type { Light } from './hairstylesModel'

/** One entry of `channel_declarations` (figure.py `_plain_body_extras` / model3d info,
 *  `collision_channels.declarations_info`): the declaration, where it was placed on the shown model, or why not. */
export interface ChannelDeclaration {
  id: string
  bone: string
  offset: [number, number, number]
  axis: [number, number, number]
  depth: number
  radius: number
  cone_deg: number
  funnel: number
  /** The core ops whose chains may enter. */
  accepts: string[]
  min_length: number
  compress_min: number
  exposed_only: boolean
  from_rig: string | null
  /** `rig` (the opening the package op reported) / `declared` (joint + offset); null = not on this model. */
  placement: 'rig' | 'declared' | null
  /** Why the channel is not on this model ("" when it is). */
  reason: string
}

export type ChannelOverrides = Record<string, ChannelOverride>

/** Slider ranges (the server's `validate_overrides`). */
export const OFFSET_MM_MAX = 50
export const SCALE_MIN = 0.5
export const SCALE_MAX = 2
export const CONE_MIN = 1
export const CONE_MAX = 60
export const TILT_MAX = 45

/** The override a channel starts from: the stored one, else the default (offset 0, scales 1, the declared cone). */
export function overrideOf(stored: ChannelOverrides | null | undefined, id: string, coneDeg: number): ChannelOverride {
  const entry = stored?.[id]
  if (entry) return { offset_mm: [...entry.offset_mm] as [number, number, number], radius_scale: entry.radius_scale,
    depth_scale: entry.depth_scale, cone_deg: entry.cone_deg, tilt_deg: entry.tilt_deg ?? 0 }
  return { offset_mm: [0, 0, 0], radius_scale: 1, depth_scale: 1, cone_deg: coneDeg, tilt_deg: 0 }
}

export function sameOverride(a: ChannelOverride, b: ChannelOverride): boolean {
  const near = (x: number, y: number) => Math.abs(x - y) < 1e-6
  return a.offset_mm.every((v, i) => near(v, b.offset_mm[i])) && near(a.radius_scale, b.radius_scale)
    && near(a.depth_scale, b.depth_scale) && near(a.cone_deg, b.cone_deg) && near(a.tilt_deg ?? 0, b.tilt_deg ?? 0)
}

/** The map to save: every declared channel's draft unless it is the default; ids no declaration names any more keep
 *  their stored entry (the declaration may come back — the server keeps them too). */
export function overridesToSave(stored: ChannelOverrides | null | undefined, declarations: ChannelDeclaration[],
  drafts: Record<string, ChannelOverride>): ChannelOverrides {
  const declared = new Set(declarations.map(d => d.id))
  const out: ChannelOverrides = {}
  for (const [id, entry] of Object.entries(stored || {})) if (!declared.has(id)) out[id] = entry
  for (const d of declarations) {
    const draft = drafts[d.id] ?? overrideOf(stored, d.id, d.cone_deg)
    if (!sameOverride(draft, overrideOf(null, d.id, d.cone_deg))) out[d.id] = draft
  }
  return out
}

/** The request Save sends — stores only (ruling R4). `post` is the API client's POST (injected for the check). */
export function saveChannelOverrides<T>(post: (path: string, body: unknown) => Promise<T>, character: string,
  overrides: ChannelOverrides): Promise<T> {
  return post(`/characters/${encodeURIComponent(character)}/model3d/collision/channels`, { channels: overrides })
}

/** The single step that applies it (rule R2: also when current) — `POST …/model3d/collision` for one stored model. */
export function recomputePath(character: string, signature: string): string {
  return `/characters/${encodeURIComponent(character)}/model3d/collision?signature=${encodeURIComponent(signature)}`
}

/** The shown payload with each channel whose draft differs from the override it was resolved with replaced by
 *  `previewChannel`; null when nothing differs (the viewer then shows the stored set). */
export function previewPayload(payload: CollisionPayload | null | undefined,
  drafts: Record<string, ChannelOverride>): CollisionPayload | null {
  if (!payload?.channels?.length) return null
  let changed = false
  const channels = payload.channels.map(record => {
    const draft = drafts[record.id]
    if (!draft) return record
    const applied = record.applied ?? overrideOf(null, record.id, record.cone_deg)
    if (sameOverride(draft, applied)) return record
    changed = true
    return previewChannel(record, record.applied, draft)
  })
  return changed ? { ...payload, channels } : null
}

/** One line per declaration: where it sits on this model, or why it is not there. */
export function declarationLine(d: ChannelDeclaration): { light: Light; text: string } {
  if (d.placement === 'rig') return { light: 'green', text: "Placed at the opening the part's build reported" }
  if (d.placement === 'declared') return { light: 'green', text: 'Placed at the declared offset' }
  return { light: d.reason === 'Covered by the worn outfit' ? 'grey' : 'yellow', text: d.reason || 'Not computed' }
}

/** The declaration's numbers for the mouse-over (metres and degrees as declared). */
export function declarationDetail(d: ChannelDeclaration): string {
  const ops = d.accepts ?? []
  return [`${d.id} · joint ${d.bone}`, `depth ${(d.depth * 100).toFixed(1)} cm · radius ${(d.radius * 100).toFixed(1)} cm`
    + ` · funnel ${(d.funnel * 100).toFixed(1)} cm at ${d.cone_deg}°`,
  d.from_rig ? `opening from part ${d.from_rig}` : `offset ${d.offset.map(v => (v * 100).toFixed(1)).join(' / ')} cm`,
  `accepts ${ops.join(', ') || '–'} · min length ×${d.min_length} · compress to ×${d.compress_min}`].join('\n')
}

/** A short tab label of a channel id (`<package>:<id>` → `<id>`). */
export function channelLabel(id: string): string {
  const at = id.indexOf(':')
  return at >= 0 ? id.slice(at + 1) : id
}

/** The collision step's light and words (the model's `collision` step, `model_overview._collision_step`): what
 *  the Channels panel writes beside Save. Null without the step. */
export function collisionStepLine(step: ModelStep | null | undefined): { light: Light; state: string; reason: string }
  | null {
  if (!step) return null
  const reason = step.detail || ''
  switch (step.status) {
    case 'due': return { light: 'yellow', state: 'Due', reason }
    case 'done': return { light: 'green', state: 'Current', reason }
    case 'warning': return { light: 'yellow', state: 'Warning', reason }
    case 'failed': return { light: 'red', state: 'Failed', reason }
    default: return { light: 'grey', state: 'Not recorded', reason }
  }
}

// --- the test rod ----------------------------------------------------------------------------------------------

/** The rod the viewer's "Test rod" draws (`guideRod` of @anima/scene-render): metres and degrees. */
export interface RodSettings {
  /** The channel it enters ("" = the first). */
  channel: string
  length: number
  radius: number
  links: number
  /** How far its tip lies past the opening along the axis (metres; negative = in front of it). */
  insertion: number
  tiltDeg: number
}

export const ROD_DEFAULTS: RodSettings = { channel: '', length: 0.15, radius: 0.012, links: 3, insertion: 0.05, tiltDeg: 0 }
/** The swing budget per link the rod is guided with — the default `max_deg` of an extension chain. */
export const ROD_BUDGET_DEG = 30

/** What the viewer reads off the rod each moment. */
export interface RodReadout {
  turnsDeg: number[]
  k: number
  pastBottomMm: number
  suppressed: string[]
  /** The engagement weight, ramped like a chain's (`stepEngagement`). */
  w: number
  /** Ruling A102: the largest outward move of the receiving body's surface (mm) and how many vertices moved. */
  openingMm: number
  openingMoved: number
}

/** The readout as one line per value (plain words, units written out; `t` translates the templates). */
export function rodReadoutLines(r: RodReadout | null, t: (s: string) => string = (s) => s): string[] {
  if (!r) return [t('The rod is shown once the model carries a channel')]
  return [
    t('Turn per link: {list}').replace('{list}', r.turnsDeg.map(v => `${v.toFixed(1)}°`).join(' · ') || '–'),
    t('Depth scale k {k} · past the bottom {cm} cm').replace('{k}', r.k.toFixed(3))
      .replace('{cm}', (r.pastBottomMm / 10).toFixed(2)),
    t('Weight w {w} · skipped capsules: {list}').replace('{w}', r.w.toFixed(2))
      .replace('{list}', r.suppressed.join(', ') || t('none')),
    t('Opening widened by {cm} cm · {n} vertices moved').replace('{cm}', (r.openingMm / 10).toFixed(2))
      .replace('{n}', String(r.openingMoved)),
  ]
}
