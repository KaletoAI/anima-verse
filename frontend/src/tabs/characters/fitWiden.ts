/**
 * fitWiden — Ruling A48c: the fit allowance's widening (Ruling A47), as the 3D mesh view previews it.
 *
 * THE RULE is `garment_fit.widen` (Python, the fit): the placed piece is widened by `scale` about the body's
 * vertical torso axis `(centre_x, centre_z)` —
 *   - z is scaled about `centre_z`: `z' = centre_z + (z − centre_z) · scale`;
 *   - x is scaled about `centre_x` within `half_width` of it and SHIFTED beyond by the widening at `half_width`:
 *     `x' = x + (scale − 1) · clip(x − centre_x, −half_width, half_width)` — a sleeve keeps its length;
 *   - y (the length) never changes; scale 1 leaves everything as it is.
 * Ruling A68 — THE DEPTH RULE is `garment_fit.depth_shift` (the fit adds it AFTER its push-out): z moves away from
 * the torso's depth centre `centre_z` by `ease · wz · wx · wy` with
 *   - `wz = clip((z − centre_z) / ramp, −1, 1)` (full in front and behind, a ramp through the sides),
 *   - `wx = clip((x_limit − |x − centre_x|) / ramp, 0, 1)` (none toward the sleeves),
 *   - `wy = clip((y_limit − y) / ramp, 0, 1)` (none at the collar and the neck opening);
 * `ease` = the depth choice in percent of the torso's half depth (`depthEase`). x and y never change.
 * This file is the ONE port of those rules for the client (`scripts/smoke_fit_widen_parity.py` checks it against the
 * Python on a synthetic mesh, with hand-derived numbers). The server sends the axis in the shown mesh's own frame
 * (`garment_mesh_view.widen_axis`: the placement is a uniform scale plus an offset, so widening the placed piece
 * equals widening the mesh about the mapped-back axis), and per factor what the fit allowance can apply the share
 * inside the body and the trunk gap (`allowance_table`) — the viewer only looks those up.
 *
 * The rest are the pure helpers of the allowance control beside the viewer.
 */
import type { AllowanceChoice, FitSettingsInfo } from './fitSettingsModel'

/** The axis the fit widens about, in the shown mesh's frame (`garment_mesh_view.widen_axis`), with the depth
 *  allowance's frame (Ruling A68; absent on a view computed without it). */
export interface WidenAxis {
  centre_x: number; centre_z: number; half_width: number
  ramp?: number; x_limit?: number; y_limit?: number; half_depth?: number
}

/** One factor of the body view's allowance table (`garment_mesh_view.allowance_table`). */
export interface AllowanceStep {
  factor: number
  share: number
  face_share: number
  inside_faces: number
  gap_p50_mm: number | null
  gap_min_mm: number | null
  /** Ruling A68: per depth choice (`AllowanceView.depth.choices`) [front, back] median gap, mm, before the push. */
  depth_gaps?: Array<[number | null, number | null]>
}

/** The body view's `allowance` block. */
export interface AllowanceView {
  axis: WidenAxis
  factors: number[]
  steps: AllowanceStep[]
  band_vertices: number
  /** Ruling A68: the depth choices (percent) and their shift in mm on this body. */
  depth?: { choices: number[]; ease_mm: number[] }
  mask_faces: number
  /** base64, one byte per face of the red overlay: bit i = inside the body at `factors[i]`. */
  mask: string
}

/** `garment_fit.widen` on one point. */
export function widenPoint(x: number, y: number, z: number, scale: number, axis: WidenAxis): [number, number, number] {
  if (scale === 1) return [x, y, z]
  const dx = x - axis.centre_x
  const hw = axis.half_width
  return [x + (scale - 1) * Math.max(-hw, Math.min(hw, dx)), y, axis.centre_z + (z - axis.centre_z) * scale]
}

/** `garment_fit.widen` on flat xyz positions, in place (the viewer's model and red overlay). */
export function widenInPlace(xyz: Float32Array | Float64Array | number[], scale: number, axis: WidenAxis): void {
  if (scale === 1) return
  const hw = axis.half_width
  for (let i = 0; i + 2 < xyz.length; i += 3) {
    const dx = xyz[i] - axis.centre_x
    xyz[i] = xyz[i] + (scale - 1) * Math.max(-hw, Math.min(hw, dx))
    xyz[i + 2] = axis.centre_z + (xyz[i + 2] - axis.centre_z) * scale
  }
}

/** Ruling A68: the depth shift (in the axis' units) of a depth choice in percent; 0 without the depth frame. */
export function depthEase(axis: WidenAxis | null | undefined, depth: number): number {
  return axis?.half_depth != null ? (depth / 100) * axis.half_depth : 0
}

/** `garment_fit.depth_shift` on one point: the z shift. */
export function depthShift(x: number, y: number, z: number, ease: number, axis: WidenAxis): number {
  if (ease === 0 || axis.ramp == null || axis.x_limit == null || axis.y_limit == null) return 0
  const r = axis.ramp
  const wz = Math.max(-1, Math.min(1, (z - axis.centre_z) / r))
  const wx = Math.max(0, Math.min(1, (axis.x_limit - Math.abs(x - axis.centre_x)) / r))
  const wy = Math.max(0, Math.min(1, (axis.y_limit - y) / r))
  return ease * wz * wx * wy
}

/** `garment_fit.depth_ease` on flat xyz positions, in place (after `widenInPlace`, as the preview shows it). */
export function easeInPlace(xyz: Float32Array | Float64Array | number[], ease: number, axis: WidenAxis): void {
  if (ease === 0) return
  for (let i = 0; i + 2 < xyz.length; i += 3) {
    xyz[i + 2] = xyz[i + 2] + depthShift(xyz[i], xyz[i + 1], xyz[i + 2], ease, axis)
  }
}

/** The depth row's gaps [front, back] at `factor` and the depth choice `depth`, or null. */
export function depthGapsAt(view: AllowanceView | null | undefined, factor: number,
  depth: number): [number | null, number | null] | null {
  const step = stepAt(view, factor)
  const i = (view?.depth?.choices || []).indexOf(depth)
  return step?.depth_gaps && i >= 0 ? step.depth_gaps[i] ?? null : null
}

/** "+6 %" */
export function depthText(depth: number): string {
  return `+${depth} %`
}

/** The width factor of a fixed allowance choice (percent): +3 → 1.03; Auto has none of its own. */
export function choiceFactor(choice: AllowanceChoice): number | null {
  return choice === 'auto' ? null : Math.round((1 + choice / 100) * 10000) / 10000
}

/** The fixed choice whose factor is `factor`, or null (an automatic step only Auto reaches). */
export function factorChoice(factor: number, choices: AllowanceChoice[]): AllowanceChoice | null {
  for (const c of choices) {
    const f = choiceFactor(c)
    if (f != null && Math.abs(f - factor) < 1e-6) return c
  }
  return null
}

/** The factor Auto took on the stored fit (`fit_settings.allowance` when the fit was made with Auto), else null —
 *  then Auto decides at the next fit. */
export function autoFactor(info: FitSettingsInfo | null | undefined): number | null {
  const a = info?.allowance
  if (!a || a.setting !== 'auto' || a.inherited) return null
  return typeof a.factor === 'number' ? a.factor : null
}

/** "×1.04" */
export function factorText(f: number): string {
  return `×${f.toFixed(2)}`
}

/** The table row of `factor` (nearest), or null. */
export function stepAt(view: AllowanceView | null | undefined, factor: number): AllowanceStep | null {
  if (!view?.steps?.length) return null
  let best: AllowanceStep | null = null
  for (const s of view.steps) if (!best || Math.abs(s.factor - factor) < Math.abs(best.factor - factor)) best = s
  return best && Math.abs(best.factor - factor) < 1e-6 ? best : null
}

/** The mask bit of `factor` in `factors`, or −1. */
export function maskBit(factors: number[] | undefined, factor: number): number {
  return (factors || []).findIndex((f) => Math.abs(f - factor) < 1e-6)
}

/** The overlay's per-face bytes. */
export function decodeMask(b64: string): Uint8Array {
  const bin = atob(b64 || '')
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out
}

/** "12.4 mm" / "−3.0 mm" (a negative gap lies inside the body). */
export function mmText(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '–'
  return `${v < 0 ? '−' : ''}${Math.abs(v).toFixed(1)} mm`
}
