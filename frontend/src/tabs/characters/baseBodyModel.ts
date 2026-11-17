/**
 * baseBodyModel — pure helpers of the Base body tab (Task UI1 of
 * docs/superpowers/plans/2026-11-12-unified-worn-pieces.md: the base body's own tab, and the rule for every
 * flow of the character area — R1 one "Run all" that skips what is current, R2 single steps that redo even
 * what is current, R3 settings saved on their own). No React, no fetch: checked by
 * `scripts/check_base_body_ui.mjs`. Returned strings are English; the components put them through `t()`.
 */
import type { ExtensionTipOverride, ExtensionTipPanelInfo } from './useBaseBody'

import type { CpuProgress } from '../../lib/cpuProgress'

/** What "Run all" runs now (`figure_build.base_run_all`): the plain body's refresh, the face cleanup of the
 *  stored base mesh, its missing or outdated face retexture, the base mesh repair after a saved repair setting or a
 *  new repair version (Ruling A34), the extension rebuild of a base whose tip smoothing is not recorded yet (Ruling
 *  A43), the extension rebuild after saved tip settings (Task UI2), the collision capsules after saved channel settings
 *  (cross-person collision Task 15) — "" when every step is current. */
export type RunAllKind = '' | 'plain_body' | 'face_cleanup' | 'face_retexture' | 'mesh_repair' | 'tip_smoothing'
  | 'extension_rig' | 'collision'

/** `plain_body.run_all` of GET …/figure?plain=1. */
export interface BaseRunAll {
  kind: RunAllKind
  /** In run order; `jobs` are first-attempt hub jobs (`cleanup` is local: 0). */
  steps: Array<{ name: string; jobs: number | null }>
  /** 0 with kind "" = everything current; null = the plan could not be read (`note` says why). */
  hub_jobs: number | null
  note: string
  /** Why a face retexture is planned: "missing" (none, or a failed one) or "changed" (the saved face values differ
   *  from the ones it ran with — Task UI2); "" otherwise. */
  face_due?: '' | 'missing' | 'changed'
  /** A Run all of the character goes now. */
  running: boolean
  /** A194: the live CPU line of the base run in flight, null when none reports. */
  live?: CpuProgress | null
  /** Its last outcome ("" = it ended without an error). */
  last: { error: string; finished_at: string } | null
}

type Tr = (s: string) => string
const EN: Tr = (s) => s

export function jobsTr(hubJobs: number | null, t: Tr): string {
  if (hubJobs === null) return t('cost unknown')
  return hubJobs === 1 ? t('1 hub job') : t('{n} hub jobs').replace('{n}', String(hubJobs))
}

/** Written on and under the Run all button (rule R1). `reason` is written under a disabled button. */
export function runAllButton(r: BaseRunAll | null | undefined, t: Tr = EN): {
  label: string; disabled: boolean; reason: string | null
} {
  if (!r) return { label: t('Run all'), disabled: true, reason: null }
  if (r.running) return { label: t('Running…'), disabled: true, reason: t('Run all is running') }
  if (!r.kind) {
    if (r.hub_jobs === null) return { label: t('Run all'), disabled: true, reason: r.note || t('cost unknown') }
    return { label: t('Everything is current'), disabled: true, reason: null }
  }
  return { label: t('Run all ({cost})').replace('{cost}', jobsTr(r.hub_jobs, t)), disabled: false, reason: null }
}

/** One line on what the planned Run all does (`faceDue`: `face_due` of the plan). */
export function runAllWhat(kind: RunAllKind, t: Tr = EN, faceDue: BaseRunAll['face_due'] = ''): string {
  switch (kind) {
    case 'plain_body': return t('Refreshes the base body: the views that are not current, then the model')
    case 'face_cleanup': return t('Brings the face cleanup onto the stored base mesh, then redoes what follows it')
    case 'face_retexture': return faceDue === 'changed'
      ? t('Face values changed — not applied yet: redoes the face retexture with the saved values')
      : t('Adds the missing face retexture to the base model')
    case 'mesh_repair': return t('The base mesh is not repaired with the saved settings: repairs it, then rebuilds the extension bones (local)')
    case 'tip_smoothing': return t('Tip smoothing not applied to this model yet: rebuilds the extension bones (local, no hub job)')
    case 'extension_rig': return t('Tip settings saved, not built yet: rebuilds the extension bones of the base model')
    case 'collision': return t('Channel settings saved, not applied yet: recomputes the collision capsules of every stored model (local, no hub job)')
    default: return ''
  }
}

/** Under the saved face values (rule R3 → R1, Task UI2): the face retexture of the stored base model ran with other
 *  values — "Face values changed — not applied yet (2 hub jobs)"; null when they are applied (or the face step is
 *  not what Run all plans now: a plan that rebuilds the model or the cleanup applies the values too). */
export function faceDueLine(r: BaseRunAll | null | undefined, t: Tr = EN): string | null {
  if (!r || r.kind !== 'face_retexture' || r.face_due !== 'changed') return null
  return t('Face values changed — not applied yet ({cost})').replace('{cost}', jobsTr(r.hub_jobs, t))
}

/** A step name of the plan (`base_body.base_rebuild_steps` / `model3d.mesh_hub_stages`) as a label. */
export function runAllStep(name: string, t: Tr = EN): string {
  const view = /^view (front|back|left|right)$/.exec(name)
  if (view) {
    return { front: t('Front view'), back: t('Back view'), left: t('Left view'), right: t('Right view') }[
      view[1] as 'front' | 'back' | 'left' | 'right']
  }
  switch (name) {
    case 'skin front': return t('Skin detail step')
    case 'mesh': return t('Mesh')
    case 'face view': return t('Face view (from the profile picture)')
    case 'upscale': return t('Upscale (face reference)')
    case 'face': return t('Face retexture')
    case 'rig': return t('Rig')
    case 'cleanup': return t('Face cleanup (local)')
    case 'repair': return t('Mesh repair (local)')
    case 'tip_smoothing': return t('Tip smoothing (local)')
    case 'extension': return t('Extension bones (local)')
    case 'collision': return t('Collision capsules (local)')
    default: return name
  }
}

/** The answers of POST …/base-body/run-all. */
export const RUN_ALL_STATUS: Record<string, string> = {
  started: 'Run all started',
  current: 'Everything is current',
}

// --- Face settings (rule R3: saved on their own, nothing runs) -------------------------------------------

/** The face retexture's light and colour values (`face_photo_adjust.DEFAULTS`). */
export interface FacePhoto { balance: number; tone_match: number; skin_recolor: number; brightness: number }
/** Its four controls (`face_retexture.validated_params` defaults). */
export interface FaceControls { strength: number; feather: number; render_resolution: number; yaw: number }

export const FACE_PHOTO_DEFAULTS: FacePhoto = { balance: 1, tone_match: 1, skin_recolor: 1, brightness: 1 }
export const FACE_CONTROL_DEFAULTS: FaceControls = { strength: 1, feather: 0.18, render_resolution: 768, yaw: 0 }

/** The stored values (only deviations are stored) over the defaults. */
export function facePhotoOf(stored: Partial<FacePhoto> | null | undefined): FacePhoto {
  return { ...FACE_PHOTO_DEFAULTS, ...(stored || {}) }
}
export function faceControlsOf(stored: Partial<FaceControls> | null | undefined): FaceControls {
  return { ...FACE_CONTROL_DEFAULTS, ...(stored || {}) }
}

/** Why the values cannot be saved (the server's bounds), null = they can. */
export function faceSettingsInvalid(photo: FacePhoto, controls: FaceControls): string | null {
  const within = (v: number, lo: number, hi: number) => Number.isFinite(v) && v >= lo && v <= hi
  if (!within(photo.balance, 0, 1) || !within(photo.tone_match, 0, 1) || !within(photo.skin_recolor, 0, 1)) {
    return 'Light balance, tone match and skin colour correction go from 0 to 100 %'
  }
  if (!within(photo.brightness, 0.5, 1.5)) return 'Face brightness goes from 50 to 150 %'
  if (!within(controls.strength, 0, 1)) return 'Strength goes from 0 to 1'
  if (!within(controls.feather, 0, 0.5)) return 'Feather goes from 0 to 0.5'
  if (!Number.isInteger(controls.render_resolution) || !within(controls.render_resolution, 256, 2048)) {
    return 'Render resolution is a whole number from 256 to 2048'
  }
  if (!within(controls.yaw, -180, 180)) return 'Yaw goes from −180 to 180 degrees'
  return null
}

/** Whether the draft differs from what is saved. */
export function faceSettingsChanged(saved: { photo: FacePhoto; controls: FaceControls },
  draft: { photo: FacePhoto; controls: FaceControls }): boolean {
  const keys = <T extends object>(o: T) => Object.keys(o) as Array<keyof T>
  return keys(saved.photo).some((k) => saved.photo[k] !== draft.photo[k])
    || keys(saved.controls).some((k) => saved.controls[k] !== draft.controls[k])
}

/** Under the face values after a save: what applies them (nothing runs on Save). */
export const FACE_SETTINGS_NOTE = 'Saving runs nothing. The next face retexture uses these values: the face step '
  + 'of a new base model (with "Improve face before rigging"), Run all — which redoes the face when the saved values '
  + 'differ from the applied ones — or "Face retexture…" now.'

// --- A garment chain's "Run all" (the Wardrobe's piece dialog; rule R1 applied there) --------------------

/** The dialog's Run all from `garments.run_estimate` (GET …/garments/{item} `run`): "Run all (6 hub jobs)";
 *  "Run all (refit on the CPU)" when the chain refits first; nothing to run → "Everything is current",
 *  disabled; no estimate (null / undefined) → plain "Run all" (the server decides). */
export function chainRunAll(run: { steps: string[]; hub_jobs: number | null; refit: boolean } | null | undefined,
  t: Tr = EN): { label: string; disabled: boolean } {
  if (!run) return { label: t('Run all'), disabled: false }
  if (!run.steps.length) return { label: t('Everything is current'), disabled: true }
  if (run.refit) return { label: t('Run all (refit on the CPU)'), disabled: false }
  return { label: t('Run all ({cost})').replace('{cost}', jobsTr(run.hub_jobs, t)), disabled: false }
}

// --- A pair tip panel (rule R3: Save stores the settings, Rebuild builds them — Task UI2) ------------------------

/** The panel's state line after a save: the saved settings are not built yet (`extension_tips[].due`). */
export const TIP_DUE_NOTE = 'Saved — not built yet. Rebuild (local, no hub job) or Run all builds it.'
/** The Extension bones box's state line when the groups themselves changed since the build (Ruling A49:
 *  `plain_body.extension.due_reason` = `groups`, e.g. a base that counts as unclothed now). */
export const EXT_DUE_GROUPS_NOTE = 'The groups changed since the last build. Rebuild (local, no hub job) or Run all builds them.'
/** The Rebuild button's label: the CPU extension rebuild of the base model, no hub job. */
export const TIP_REBUILD_LABEL = 'Rebuild (local, no hub job)'

/** The dots a tip panel hands the viewer: one per side, where the tip sits. */
export type TipDots = Array<{ at: [number, number, number]; color: string }>
/** A tip that sits where it was built / one the draft moved. */
export const TIP_BUILT_COLOR = '#3fb950'
export const TIP_DRAFT_COLOR = '#f0b35c'
/** Whether a tip panel's "Show markers" starts on (Ruling A62: off on every load). A view switch of the open tab
 *  only — never saved; moving a position slider turns it on. */
export const TIP_MARKERS_START_SHOWN = false

/** The dots of one tip panel for the viewer, or null when there are none to draw (markers hidden, the group off, no
 *  side found): the built tip (else the suggestion) moved by the draft's difference to the built offset along the
 *  surface tangents there — a preview only; the build walks the real surface. */
export function tipPreviewDots(panel: Pick<ExtensionTipPanelInfo, 'sides'>, draft: Pick<ExtensionTipOverride, 'offsets' | 'mirror'>,
  shown: boolean, off: boolean): TipDots | null {
  if (!shown || off) return null
  const dots: TipDots = []
  panel.sides.forEach((side, i) => {
    if (!side) return
    const base = side.tip ?? side.suggested
    const built = side.tip ? side.offset_mm : [0, 0]
    const offset = draft.offsets[draft.mirror ? 0 : i]
    const du = (offset.up - built[0]) / 1000
    const dout = (offset.out - built[1]) / 1000
    const moved = Math.abs(du) > 1e-9 || Math.abs(dout) > 1e-9
    dots.push({
      at: [0, 1, 2].map((k) => base[k] + du * side.tangent_up[k] + dout * side.tangent_out[k]) as [number, number, number],
      color: moved ? TIP_DRAFT_COLOR : TIP_BUILT_COLOR,
    })
  })
  return dots.length ? dots : null
}

// --- Base mesh repair (Ruling A34: holes filled on the CPU; saved on its own, "Repair again" runs it) ---------

/** The repair's settings (`base_mesh_repair.validated_settings`). */
export interface MeshRepairSettings { enabled: boolean; max_hole_cm: number }
export const MESH_REPAIR_DEFAULTS: MeshRepairSettings = { enabled: true, max_hole_cm: 4 }
export const MAX_HOLE_RANGE: [number, number] = [0.5, 20]

/** `plain_body.mesh_repair` of GET …/figure?plain=1 (`model3d.mesh_repair_state`). */
export interface MeshRepairState {
  settings: MeshRepairSettings
  record: {
    status?: string; holes?: number; filled?: number; largest_cm?: number
    unfilled?: Array<{ size_cm: number | null; reason: string }>; at?: string; error?: string
  } | null
  /** The settings or the repair version changed since the stored repair ran. */
  due: boolean
  /** The server's status line: "3 holes filled, largest 0.2 cm" … */
  summary: string
  light: 'ok' | 'warn' | 'error' | 'off'
  /** A "Repair again" of the character runs. */
  running: boolean
  last: { signature: string; error: string; at: string } | null
}

/** The status light's colour class (ModelSteps' dots). */
export function meshRepairDot(light: MeshRepairState['light']): string {
  return light === 'ok' ? 'green' : light === 'warn' ? 'yellow' : light === 'error' ? 'red' : 'grey'
}

/** Why the draft cannot be saved, null = it can. */
export function meshRepairInvalid(draft: MeshRepairSettings): string | null {
  const [lo, hi] = MAX_HOLE_RANGE
  if (!Number.isFinite(draft.max_hole_cm) || draft.max_hole_cm < lo || draft.max_hole_cm > hi) {
    return 'The largest hole to fill goes from 0.5 to 20 cm'
  }
  return null
}

/** The body of POST …/model3d/options: only deviations from the defaults (the server prunes them as well). */
export function meshRepairBody(draft: MeshRepairSettings): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  if (draft.enabled !== MESH_REPAIR_DEFAULTS.enabled) out.enabled = draft.enabled
  if (draft.max_hole_cm !== MESH_REPAIR_DEFAULTS.max_hole_cm) out.max_hole_cm = draft.max_hole_cm
  return out
}

/** The status line beside the light (the server's `summary`, built here so it is translated). */
export function meshRepairLine(state: MeshRepairState, t: Tr = EN): string {
  const r = state.record
  let line: string
  if (!r) line = t('Not repaired yet — the next rebuild repairs it')
  else if (r.status === 'failed') line = r.error || t('Repair failed')
  else if (r.status === 'skipped') line = t('Switched off')
  else {
    const parts: string[] = []
    const filled = r.filled ?? 0
    if (filled) {
      parts.push((filled === 1 ? t('1 hole filled, largest {cm} cm') : t('{n} holes filled, largest {cm} cm'))
        .replace('{n}', String(filled)).replace('{cm}', (r.largest_cm ?? 0).toFixed(1)))
    }
    const open = r.unfilled ?? []
    if (open.length) {
      const sizes = open.map((u) => (u.size_cm !== null ? `${u.size_cm.toFixed(1)} cm` : '?')).join(', ')
      parts.push((open.length === 1 ? t('1 hole left open ({sizes})') : t('{n} holes left open ({sizes})'))
        .replace('{n}', String(open.length)).replace('{sizes}', sizes))
    }
    line = parts.length ? parts.join(' · ') : t('Closed — no hole')
  }
  return state.due && r ? `${line} · ${t('settings changed — Repair again applies them')}` : line
}

// --- Tip smoothing (Ruling A43: its own row with a record; it runs inside the extension rebuild) --------------------

/** One group's entry of the record (`extension_tip.tip_smoothing_group`). */
export interface TipSmoothingGroup {
  applied: boolean
  reason: string
  max_shift_mm: number | null
  moved: number
  radius_mm: number | null
  passes: number | null
  /** Normals near the tips pointing into the body / more than 60° off their surface: [before, after]. */
  inverted: [number, number] | null
  off_60: [number, number] | null
  region_mm: number | null
  /** "neutralised": the part is switched off and leaves a neutral surface (Ruling A44); absent = smoothed. */
  mode?: 'smoothed' | 'neutralised'
  /** Neutralised: per side the height of the model's own tip above its surroundings, [before, after] in mm. */
  height_mm?: Array<[number | null, number | null]>
  /** Per side the source bump's height above the surface fitted around it, [before, after] in mm (Ruling A53). */
  bump_mm?: Array<[number | null, number | null]>
  /** Switched on: per side the placed tip's distance from the source apex in mm (an offset moves it away). */
  tip_from_source_mm?: Array<number | null>
}

/** `plain_body.tip_smoothing` of GET …/figure?plain=1 (`extension_tip.tip_smoothing_state`); null = no switched-on
 *  tip part on the base model (the row is hidden). */
export interface TipSmoothingState {
  groups: Array<{ id: string; label: string; mode?: 'smoothed' | 'neutralised' }>
  record: {
    version: number; at: string; status: 'built' | 'failed'; error: string
    groups: Record<string, TipSmoothingGroup>
  } | null
  /** No record of the current version (a model built before it): the next extension rebuild applies it. */
  due: boolean
  light: 'ok' | 'warn' | 'error' | 'off'
  /** The server's English line (the model step's tooltip). */
  summary: string
  /** The extension rebuild of the character runs ("Smooth again"). */
  running: boolean
  last: { signature: string; error: string; at: string } | null
  version: number
}

/** The button: the extension rebuild of the base model, which smooths the tips again — local, no hub job. */
export const TIP_SMOOTH_AGAIN_LABEL = 'Smooth again (local, no hub job)'
export const TIP_SMOOTHING_DUE_LINE = 'Not applied to this model yet — rebuilds the extension bones (local, no hub job)'
/** The reason of a switched-off tip part that leaves a neutral surface (Ruling A44; the server's `NEUTRALISED_REASON`). */
export const NEUTRALISED_LINE = 'Smoothed — part is off'

/** The status line beside the light: "Applied 01:12 — max shift 4.5 mm, inverted normals 22 → 0", or why nothing was
 *  smoothed, or that it is due. `time` formats the record's time (the tab's clock settings). */
export function tipSmoothingLine(state: TipSmoothingState, t: Tr = EN, time: (iso: string) => string = (iso) => iso): string {
  const r = state.record
  if (!r || (state.due && (r.version ?? 0) < state.version)) return t(TIP_SMOOTHING_DUE_LINE)
  if (r.status === 'failed') return t('Last rebuild failed: {error}').replace('{error}', r.error || '?')
  if (state.due) return t('A tip part is not covered yet — rebuilds the extension bones (local, no hub job)')
  const all = Object.values(r.groups || {})
  // A switched-off part (Ruling A44): its own reason first, then the switched-on parts' line, if any.
  const neutral = all.filter((g) => g.mode === 'neutralised')
  const groups = all.filter((g) => g.mode !== 'neutralised')
  if (neutral.length) {
    const texts = Array.from(new Set(neutral.map((g) => t(g.reason || NEUTRALISED_LINE))))
    if (groups.length) texts.push(tipSmoothingLine({ ...state, record: { ...r, groups: Object.fromEntries(groups.map((g, i) => [String(i), g])) } }, t, time))
    return texts.join('; ')
  }
  const applied = groups.filter((g) => g.applied)
  if (!applied.length) {
    const reasons = Array.from(new Set(groups.map((g) => g.reason || 'Not smoothed')))
    return reasons.map((reason) => t(reason)).join('; ') || t('Not smoothed')
  }
  const shift = Math.max(...applied.map((g) => g.max_shift_mm ?? 0))
  let line = t('Applied {time} — max shift {mm} mm').replace('{time}', time(r.at)).replace('{mm}', shift.toFixed(1))
  const inverted = applied.map((g) => g.inverted).filter((v): v is [number, number] => Array.isArray(v) && v.length === 2)
  if (inverted.length) {
    line += t(', inverted normals {before} → {after}')
      .replace('{before}', String(inverted.reduce((a, v) => a + v[0], 0)))
      .replace('{after}', String(inverted.reduce((a, v) => a + v[1], 0)))
  }
  return line
}

/** The light's colour class (ModelSteps' dots). */
export function tipSmoothingDot(light: TipSmoothingState['light']): string {
  return meshRepairDot(light)
}

/** One line per group for the tooltip (the numbers behind the status line). */
export function tipSmoothingDetail(state: TipSmoothingState, t: Tr = EN): string[] {
  const r = state.record
  if (!r) return []
  const label = (id: string) => state.groups.find((g) => g.id === id)?.label || id
  return Object.entries(r.groups || {}).map(([id, g]) => {
    const parts: string[] = []
    const pairs = (rows: Array<[number | null, number | null]> | undefined, digits: number) =>
      (rows || []).filter((v) => v && v[0] !== null && v[1] !== null)
        .map((v) => `${(v[0] as number).toFixed(digits)} → ${(v[1] as number).toFixed(digits)}`).join(' / ')
    if (g.mode === 'neutralised') {
      parts.push(t(g.reason || NEUTRALISED_LINE))
      const height = pairs(g.height_mm, 1)
      if (height) parts.push(t('tip height {values} mm').replace('{values}', height))
      const bump = pairs(g.bump_mm, 1)
      if (bump) parts.push(t('source bump {values} mm').replace('{values}', bump))
      return `${label(id)}: ${parts.join(', ')}`
    }
    if (!g.applied) parts.push(t(g.reason || 'Not smoothed'))
    else {
      parts.push(t('max shift {mm} mm').replace('{mm}', (g.max_shift_mm ?? 0).toFixed(1)))
      parts.push(t('{n} vertices moved').replace('{n}', String(g.moved)))
      if (g.radius_mm !== null) parts.push(t('radius {mm} mm').replace('{mm}', g.radius_mm.toFixed(1)))
      if (g.passes !== null) parts.push(t('{n} passes').replace('{n}', String(g.passes)))
      const bump = pairs(g.bump_mm, 1)
      if (bump) parts.push(t('source bump {values} mm').replace('{values}', bump))
    }
    if (g.inverted) parts.push(t('inverted normals {before} → {after}').replace('{before}', String(g.inverted[0])).replace('{after}', String(g.inverted[1])))
    if (g.off_60) parts.push(t('normals off by more than 60° {before} → {after}').replace('{before}', String(g.off_60[0])).replace('{after}', String(g.off_60[1])))
    return `${label(id)}: ${parts.join(', ')}`
  })
}

// ---- Task UI5: the tab checklist (lights per step, the flow head, the plan in one line) ----

/** A step's traffic light (hairstylesModel's `Light`, repeated here so this file stays import-free). */
export type BaseLight = 'green' | 'yellow' | 'red' | 'grey' | 'blue'

/** One step row (StepRowView). */
export interface BaseRow { light: BaseLight; state: string; reason: string; detail: string }

/** What a base view row reads (`plain_body.status[view]`, `images[view]`, `image_meta[view].freshness`). */
export interface BaseViewInput {
  running: boolean
  failed: boolean
  error?: string | null
  warning?: string | null
  stored: boolean
  freshness?: { state: string; reason?: string; action?: string } | null
}

/**
 * One base view as a step: rendering now → blue "Rendering"; its last render failed → red "Failed", the error;
 * nothing stored → yellow "Not rendered yet"; outdated → yellow "Outdated", the server's reason (mouse-over: reason and
 * action); kept with a warning → yellow "Kept with a warning"; else green "Current".
 */
export function baseViewRow(v: BaseViewInput, t: Tr = EN): BaseRow {
  if (v.running) return { light: 'blue', state: t('Rendering'), reason: '', detail: '' }
  if (v.failed) return { light: 'red', state: t('Failed'), reason: v.error || '', detail: v.error || '' }
  if (!v.stored) return { light: 'yellow', state: t('Not rendered yet'), reason: '', detail: '' }
  if (v.freshness?.state === 'stale') {
    const reason = t(v.freshness.reason || 'Made from older data')
    return { light: 'yellow', state: t('Outdated'), reason,
      detail: [reason, v.freshness.action ? t(v.freshness.action) : ''].filter(Boolean).join('\n') }
  }
  if (v.warning) return { light: 'yellow', state: t('Kept with a warning'), reason: v.warning, detail: v.warning }
  return { light: 'green', state: t('Current'), reason: '', detail: '' }
}

/** What the base model row reads (`plain_body.model`). */
export interface BaseModelInput {
  status: 'running' | 'failed' | 'unrigged' | 'ready'
  error?: string
  freshness?: { state: string; reason?: string; action?: string } | null
}

/**
 * The base model as a step: none → yellow "Not built yet"; running → blue "Building now"; failed → red "Failed", the
 * error; a static mesh → yellow "Static mesh without a rig"; outdated → yellow "Outdated", the reason; else green
 * "Ready".
 */
export function baseModelRow(m: BaseModelInput | null | undefined, t: Tr = EN): BaseRow {
  if (!m) return { light: 'yellow', state: t('Not built yet'), reason: '', detail: '' }
  if (m.status === 'running') return { light: 'blue', state: t('Building now'), reason: '', detail: '' }
  if (m.status === 'failed') return { light: 'red', state: t('Failed'), reason: m.error || '', detail: m.error || '' }
  if (m.status === 'unrigged') return { light: 'yellow', state: t('Static mesh without a rig'), reason: '', detail: '' }
  if (m.freshness?.state === 'stale') {
    const reason = t(m.freshness.reason || 'Made from older data')
    return { light: 'yellow', state: t('Outdated'), reason,
      detail: [reason, m.freshness.action ? t(m.freshness.action) : ''].filter(Boolean).join('\n') }
  }
  return { light: 'green', state: t('Ready'), reason: '', detail: '' }
}

/**
 * The flow head: Run all running, base-body work in flight (`baseBusy` = `plain_body.activity.base` — a Build at a
 * base step, a view, the base model, …; never an outfit model's build, Ruling A55) or a row running → blue "Building
 * now"; a red row or Run all's last error → red "A step failed"; Run all plans steps → yellow "1 step due" / "{n}
 * steps due" (its steps; else the yellow rows); else green "Up to date".
 */
export function baseHead(r: BaseRunAll | null | undefined, lights: readonly BaseLight[], baseBusy: boolean,
  t: Tr = EN): { light: BaseLight; words: string } {
  if (r?.running || baseBusy || lights.includes('blue')) return { light: 'blue', words: t('Building now') }
  if (lights.includes('red') || (r?.last?.error && !r.kind)) return { light: 'red', words: t('A step failed') }
  const due = r?.kind ? r.steps.length || 1 : lights.filter((l) => l === 'yellow').length
  if (due === 1) return { light: 'yellow', words: t('1 step due') }
  if (due > 1) return { light: 'yellow', words: t('{n} steps due').replace('{n}', String(due)) }
  return { light: 'green', words: t('Up to date') }
}

/** Run all's plan in one line (replaces the collapsed list), the hub jobs per step in brackets, a local step (0
 *  jobs) by its label alone: "Back view (1) · Mesh (1) · Face cleanup (local)". */
export function runAllPlanLine(r: BaseRunAll | null | undefined, t: Tr = EN): string {
  if (!r?.kind || !r.steps.length) return ''
  return r.steps.map((step) => {
    const label = runAllStep(step.name, t)
    if (step.jobs === 0) return label
    return `${label} (${step.jobs === null ? t('cost unknown') : step.jobs})`
  }).join(' · ')
}

// --- The state preview beside the viewer (Ruling A66) -------------------------------------------------------------

/** One state the picker offers (`plain_body.extension.states`, `prompt_filters.bone_pose_states`): a state whose
 *  bone pose moves at least one of the base model's extension groups, by its readable name. */
export interface PreviewStateChoice { id: string; label: string }

/** What GET …/base-body/state-motion answered for one pick, keyed to the state and the base model it was asked for. */
export interface PickedStateMotion<M> { state: string; signature: string; motion: M }

/** The line beside the picker when it offers states: a preview, nothing is stored or started. */
export const STATE_PREVIEW_NOTE = 'Preview only — nothing is saved, nothing runs.'
/** The base model carries no extension group: no picker, this line instead. */
export const STATE_PREVIEW_NO_GROUPS = 'This base model has no extension bones — a state has nothing to move here.'
/** Groups, but no state's bone pose names one of them. */
export const STATE_PREVIEW_NO_STATES = 'No state moves the extension bones of this base model.'

/** The picker beside the viewer: "None (at rest)" first, then each offered state by its name (else its id); without
 *  groups or without a state that moves them, no options and the line that says why. */
export function statePicker(groupCount: number, states: readonly PreviewStateChoice[] | null | undefined,
  t: Tr = EN): { options: Array<{ value: string; label: string }>; note: string } {
  if (groupCount <= 0) return { options: [], note: t(STATE_PREVIEW_NO_GROUPS) }
  if (!states?.length) return { options: [], note: t(STATE_PREVIEW_NO_STATES) }
  return {
    options: [{ value: '', label: t('None (at rest)') }, ...states.map((s) => ({ value: s.id, label: s.label || s.id }))],
    note: t(STATE_PREVIEW_NOTE),
  }
}

/** The GET that computes one state's motion on the bare base model (a read — the preview never posts). */
export function stateMotionUrl(character: string, state: string): string {
  return `/characters/${encodeURIComponent(character)}/base-body/state-motion?state=${encodeURIComponent(state)}`
}

/** The motion the viewer plays: at rest (`plain_body.extension.motion`) with nothing picked, the picked state's motion
 *  once it arrived for exactly that state and base model — until then (and for a pick of another model) the rest. */
export function viewerStateMotion<M>(rest: M | undefined, selected: string, picked: PickedStateMotion<M> | null,
  signature: string): M | undefined {
  if (!selected) return rest
  return picked && picked.state === selected && picked.signature === signature ? picked.motion : rest
}
