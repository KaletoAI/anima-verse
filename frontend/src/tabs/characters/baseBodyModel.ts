/**
 * baseBodyModel — pure helpers of the Base body tab (Task UI1 of
 * docs/superpowers/plans/2026-11-12-unified-worn-pieces.md: the base body's own tab, and the rule for every
 * flow of the character area — R1 one "Run all" that skips what is current, R2 single steps that redo even
 * what is current, R3 settings saved on their own). No React, no fetch: checked by
 * `scripts/check_base_body_ui.mjs`. Returned strings are English; the components put them through `t()`.
 */

/** What "Run all" runs now (`figure_build.base_run_all`): the plain body's refresh, the face cleanup of the
 *  stored base mesh, its missing or outdated face retexture, the extension rebuild after saved tip settings (Task
 *  UI2) — "" when every step is current. */
export type RunAllKind = '' | 'plain_body' | 'face_cleanup' | 'face_retexture' | 'extension_rig'

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
