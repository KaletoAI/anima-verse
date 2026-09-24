/** The root-motion import mode — its type, the loop rule and the one-line
 *  summary the library shows per clip (the form field is RootMotionField).
 *
 *  The server takes `root_motion` ∈ strip / keep / foot_lock in the import
 *  body (default strip) and refuses a loop together with any other mode; the
 *  listing reports what a clip was imported with as
 *  `root_motion: {mode, travel_m: [x, z]}` in the clip frame — +Z forward,
 *  +X the figure's LEFT, metres. */

export type RootMotionMode = 'strip' | 'keep' | 'foot_lock'

export interface ClipRootMotion {
  mode: RootMotionMode
  /** [left, forward] in metres, clip frame */
  travel_m?: [number, number] | null
}

export type T = (s: string) => string

/** A loop cannot carry travel — the same rule the import route answers with a 400. */
export function rootMotionBlocksLoop(loopOn: boolean, mode: RootMotionMode): boolean {
  return loopOn && mode !== 'strip'
}

/** "foot lock · 0.39 m forward, 0.01 m left" — empty when the listing has no
 *  root-motion block (pairs, clips without sidecar). A component below half a
 *  centimetre is left out. */
export function rootMotionSummary(rm: ClipRootMotion | null | undefined, t: T): string {
  if (!rm) return ''
  if (rm.mode === 'strip') return t('in place')
  const mode = rm.mode === 'foot_lock' ? t('foot lock') : t('recorded travel')
  const [left, fwd] = rm.travel_m || [0, 0]
  const parts: string[] = []
  if (Number.isFinite(fwd) && Math.abs(fwd) >= 0.005) {
    parts.push(`${Math.abs(fwd).toFixed(2)} ${fwd > 0 ? t('m forward') : t('m back')}`)
  }
  if (Number.isFinite(left) && Math.abs(left) >= 0.005) {
    parts.push(`${Math.abs(left).toFixed(2)} ${left > 0 ? t('m left') : t('m right')}`)
  }
  return parts.length ? `${mode} · ${parts.join(', ')}` : mode
}
