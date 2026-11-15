/**
 * footwearAllowance — Ruling A82: the footwear piece's Width / Length allowance, as the shod preview shows it live.
 *
 * THE RULE is `footwear_fit.ALLOWANCE_STEPS` (Python, the fit), read in the SHOWN fit's cut frame (metres, x from the
 * shoe's heel end toward the toe, y up from the shoe's ground, z across — `garment_footwear.preview_frame`):
 *   - Length +L % = the shoe one size longer, ALL of it heel room: the size factor `s(L) = (F·(1+L) + A) / (F + A)`
 *     (F the longer foot, A the toe room `footwear_fit.ALLOW_M`), the heel end `F·L` further behind the heel, the
 *     toe room unchanged;
 *   - Width +W % = the fitted width factor × (1 + W) — z grows by that share; Length never changes the width.
 * Relative to the shown fit (made with Ws / Ls): `x' = F·(Ls − L) + r·x`, `y' = r·y`, `z' = z·(1 + W) / (1 + Ws)` with
 * `r = s(L) / s(Ls)`. The fit re-solves the foot's pose on the longer insole, so the preview is the shoe's size and
 * place, not the fit's last millimetre — "the fit applies it on the body" (the same caveat as the clothing preview).
 *
 * The shoe nodes are skinned: their positions live in the body's bind space. Per side the map is
 * `J · F⁻¹ · T · F · J⁻¹` with J the Foot joint's bind matrix (the skeleton's bone inverse, inverted) and F the
 * cut frame (Foot-local → cut). Matrices here are row-major arrays of 16.
 */

/** What the preview needs of the shown fit (`garment_footwear.preview_frame`). */
export interface ShoeFrame {
  sides: Record<string, { frame: number[][]; joint: string }>
  foot_len_m: number
  allow_m: number
  width_pct: number
  length_pct: number
}

/** The allowance box of the footwear panel (`garment_footwear.allowance_view`). */
export interface FootwearAllowanceView {
  settings: { width: AllowanceSetting; length: AllowanceSetting }
  steps: number[]
  auto: 'auto'
  /** What the shown fit applied (Auto's pick included), null without a shown fit. */
  applied: { width_pct: number; length_pct: number; auto?: { width: AllowanceSetting; length: AllowanceSetting;
    tried_length: number[] } | null } | null
  foot_len_m: number | null
  ball_width_mm: number | null
  frame: ShoeFrame | null
  /** The shown shoe was made with other settings than the saved ones (the fit is due). */
  due: boolean
}

export type AllowanceSetting = 'auto' | number
export type AllowanceName = 'width' | 'length'

type M4 = number[]

function mul(a: M4, b: M4): M4 {
  const o = new Array(16).fill(0)
  for (let r = 0; r < 4; r++) for (let c = 0; c < 4; c++) {
    let v = 0
    for (let k = 0; k < 4; k++) v += a[4 * r + k] * b[4 * k + c]
    o[4 * r + c] = v
  }
  return o
}

/** Inverse of an affine 4x4 (row-major). */
export function invAffine(m: M4): M4 {
  const [a, b, c, d, e, f, g, h, i] = [m[0], m[1], m[2], m[4], m[5], m[6], m[8], m[9], m[10]]
  const det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
  const inv = [
    (e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det,
    (f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det,
    (d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det,
  ]
  const t = [m[3], m[7], m[11]]
  const o = [inv[0], inv[1], inv[2], 0, inv[3], inv[4], inv[5], 0, inv[6], inv[7], inv[8], 0, 0, 0, 0, 1]
  for (let r = 0; r < 3; r++) o[4 * r + 3] = -(o[4 * r] * t[0] + o[4 * r + 1] * t[1] + o[4 * r + 2] * t[2])
  return o
}

/** The size factor of a length share (the module docstring's `s(L)`). */
export function sizeFactor(frame: Pick<ShoeFrame, 'foot_len_m' | 'allow_m'>, lengthPct: number): number {
  const F = frame.foot_len_m
  const A = frame.allow_m
  return (F * (1 + lengthPct / 100) + A) / (F + A)
}

/** The cut-frame map T (row-major) from the shown fit to the allowance `width` / `length` (percent). */
export function cutMap(frame: ShoeFrame, width: number, length: number): M4 {
  const r = sizeFactor(frame, length) / sizeFactor(frame, frame.length_pct)
  const dx = frame.foot_len_m * (frame.length_pct - length) / 100
  const wz = (1 + width / 100) / (1 + frame.width_pct / 100)
  return [r, 0, 0, dx, 0, r, 0, 0, 0, 0, wz, 0, 0, 0, 0, 1]
}

/** Whether the previewed allowance is the shown fit's own (nothing to deform). */
export function isShown(frame: ShoeFrame | null | undefined, width: number, length: number): boolean {
  return !frame || (Math.abs(width - frame.width_pct) < 1e-9 && Math.abs(length - frame.length_pct) < 1e-9)
}

/** The bind-space map of one side: `J · F⁻¹ · T · F · J⁻¹` (`boneInverse` = J⁻¹, row-major). */
export function bindMap(frameRows: number[][], boneInverse: M4, T: M4): M4 {
  const F = frameRows.flat()
  return mul(invAffine(boneInverse), mul(invAffine(F), mul(T, mul(F, boneInverse))))
}

/** Apply a row-major affine map to flat xyz positions, in place. */
export function applyInPlace(xyz: Float32Array | number[], m: M4): void {
  for (let i = 0; i + 2 < xyz.length; i += 3) {
    const x = xyz[i], y = xyz[i + 1], z = xyz[i + 2]
    xyz[i] = m[0] * x + m[1] * y + m[2] * z + m[3]
    xyz[i + 1] = m[4] * x + m[5] * y + m[6] * z + m[7]
    xyz[i + 2] = m[8] * x + m[9] * y + m[10] * z + m[11]
  }
}

/** A bone name as the server and three.js both reduce it (three's loader drops ':' and '.'). */
export function boneKey(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]/g, '')
}

/** The side of a shoe node `garment_footwear_<item>_<side>[_shaft]` of `itemId`, or null for any other node. */
export function shoeSide(nodeName: string, itemId: string): string | null {
  const head = `garment_footwear_${itemId}_`
  if (!nodeName.startsWith(head)) return null
  const side = nodeName.slice(head.length).split('_')[0]
  return side === 'left' || side === 'right' ? side : null
}

/** The resolved percent of a setting: Auto = what the shown fit applied (Auto's pick), else 0. */
export function resolved(view: FootwearAllowanceView | null | undefined, name: AllowanceName,
  setting: AllowanceSetting): number {
  if (setting !== 'auto') return setting
  const applied = view?.applied
  if (!applied) return 0
  return name === 'width' ? applied.width_pct : applied.length_pct
}

/** The mm a step adds: Length = that share of the foot's length, Width = that share of the shoe's ball width. */
export function stepMm(view: FootwearAllowanceView | null | undefined, name: AllowanceName, pct: number): number | null {
  const ref = name === 'length' ? (view?.foot_len_m != null ? view.foot_len_m * 1000 : null) : view?.ball_width_mm ?? null
  return ref == null ? null : (ref * pct) / 100
}

/** "+4 % = +9.6 mm" */
export function stepText(view: FootwearAllowanceView | null | undefined, name: AllowanceName, pct: number): string {
  const mm = stepMm(view, name, pct)
  return `+${pct} %${mm != null ? ` = +${mm.toFixed(1)} mm` : ''}`
}
