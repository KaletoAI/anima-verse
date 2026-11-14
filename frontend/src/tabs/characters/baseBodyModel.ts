/**
 * baseBodyModel — pure helpers of the Base body tab (Task UI1 of
 * docs/superpowers/plans/2026-11-12-unified-worn-pieces.md: the base body's own tab, and the rule for every
 * flow of the character area — R1 one "Run all" that skips what is current, R2 single steps that redo even
 * what is current, R3 settings saved on their own). No React, no fetch: checked by
 * `scripts/check_base_body_ui.mjs`. Returned strings are English; the components put them through `t()`.
 */

/** What "Run all" runs now (`figure_build.base_run_all`): the plain body's refresh, the face cleanup of the
 *  stored base mesh, its missing or outdated face retexture, the base mesh repair after a saved repair setting or a
 *  new repair version (Ruling A34), the extension rebuild of a base whose tip smoothing is not recorded yet (Ruling
 *  A43), the extension rebuild after saved tip settings (Task UI2) — "" when every step is current. */
export type RunAllKind = '' | 'plain_body' | 'face_cleanup' | 'face_retexture' | 'mesh_repair' | 'tip_smoothing'
  | 'extension_rig'

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
  /** Its last outcome ("" = it ended without an error). */
  last: { error: string; finished_at: string } | null
}

type Tr = (s: string) => string
const EN: Tr = (s) => s

function jobsTr(hubJobs: number | null, t: Tr): string {
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
    case 'upscale': return t('Upscale (face reference)')
    case 'face': return t('Face retexture')
    case 'rig': return t('Rig')
    case 'cleanup': return t('Face cleanup (local)')
    case 'repair': return t('Mesh repair (local)')
    case 'tip_smoothing': return t('Tip smoothing (local)')
    case 'extension': return t('Extension bones (local)')
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
/** The Rebuild button's label: the CPU extension rebuild of the base model, no hub job. */
export const TIP_REBUILD_LABEL = 'Rebuild (local, no hub job)'

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
  /** Neutralised: per side the colour difference (ΔE) of the part's area against the skin around it, [before, after]. */
  delta_e?: Array<[number | null, number | null]>
  painted?: number
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
export const NEUTRALISED_LINE = 'Smoothed and painted over — part is off'

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
      const colour = pairs(g.delta_e, 1)
      if (colour) parts.push(t('colour difference ΔE {values}').replace('{values}', colour))
      return `${label(id)}: ${parts.join(', ')}`
    }
    if (!g.applied) parts.push(t(g.reason || 'Not smoothed'))
    else {
      parts.push(t('max shift {mm} mm').replace('{mm}', (g.max_shift_mm ?? 0).toFixed(1)))
      parts.push(t('{n} vertices moved').replace('{n}', String(g.moved)))
      if (g.radius_mm !== null) parts.push(t('radius {mm} mm').replace('{mm}', g.radius_mm.toFixed(1)))
      if (g.passes !== null) parts.push(t('{n} passes').replace('{n}', String(g.passes)))
    }
    if (g.inverted) parts.push(t('inverted normals {before} → {after}').replace('{before}', String(g.inverted[0])).replace('{after}', String(g.inverted[1])))
    if (g.off_60) parts.push(t('normals off by more than 60° {before} → {after}').replace('{before}', String(g.off_60[0])).replace('{after}', String(g.off_60[1])))
    return `${label(id)}: ${parts.join(', ')}`
  })
}
