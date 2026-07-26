/**
 * Output-resolution helpers for the image-generation dialogs.
 *
 * The server coerces a caller-picked size to the same 64-pixel grid and the
 * same range (``world_ops._clamp_image_dim``), so the fields never promise a
 * size that will not be generated — keep the two in lockstep.
 */
export const RES_MIN = 256
export const RES_MAX = 2048
export const RES_GRID = 64

/** A pixel size snapped to the 64 grid and clamped to 256..2048; 0 when the
 *  input is empty/unusable (= keep the backend default). */
export function snapResolution(px: number): number {
  if (!Number.isFinite(px) || px <= 0) return 0
  const snapped = Math.round(px / RES_GRID) * RES_GRID
  return Math.max(RES_MIN, Math.min(RES_MAX, snapped))
}

/** The aspect of two pixel sizes as a READABLE ratio: the exact reduced one
 *  while both sides stay small (so 1280 × 720 reads "16:9"), otherwise the
 *  nearest ratio with both sides ≤ 9, marked "≈" (832 × 1216 → "≈ 2:3").
 *  Bounding both sides keeps it symmetric — the same shape rotated gets the
 *  mirrored label, not a different one. */
export function ratioLabel(w: number, h: number): string {
  if (!(w > 0) || !(h > 0)) return ''
  if (Number.isInteger(w) && Number.isInteger(h)) {
    const gcd = (a: number, b: number): number => (b ? gcd(b, a % b) : a)
    const g = gcd(w, h) || 1
    if (w / g <= 16 && h / g <= 16) return `${w / g}:${h / g}`
  }
  const target = w / h
  let best = { n: 1, d: 1, err: Infinity }
  for (let d = 1; d <= 9; d++) {
    const n = Math.round(target * d)
    if (n < 1 || n > 9) continue
    const err = Math.abs(target - n / d)
    if (err < best.err - 1e-9) best = { n, d, err }
  }
  return `${best.err < 1e-9 ? '' : '≈ '}${best.n}:${best.d}`
}
