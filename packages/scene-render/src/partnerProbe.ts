/**
 * The admin viewer's PARTNER PROBE (cross-person collision, plan Task 8): a
 * stand-in partner body made of capsules that the admin moves against the
 * shown figure, to see how its hair and extension chains react without a
 * second character in the world. Preview only — nothing is stored.
 *
 * - The probe's capsules come in a bind pose, in the shown model's frame
 *   (metres, +y up, the figure facing +z): the shown body's own bind capsules
 *   (`BoundCapsule.bind`, "This body, mirrored") or another character's set
 *   in its bind pose (`GET /characters/{c}/model3d/collision/bind-pose`).
 * - `probeCapsules` places them: mirror (x → −x, a right-handed stand-in for
 *   the same body), then the yaw about +y (three's rotation: +x turns towards
 *   −z), then the translation to (x, 0, z).
 * - The sweep moves the probe back and forth along its own facing (+z turned
 *   by the yaw): a triangle wave of `span` metres at `speed` m/s.
 * - The snapshot is a `PartnerSnapshot` named `PROBE_NAME`: no channels, no
 *   interaction — the consumers read it exactly as a partner figure.
 *
 * Pure: no Three.
 */
import type { Vec3 } from './collision'
import type { PartnerCapsule, PartnerSnapshot } from './partnerContact'

/** The probe's partner name: contact rows name its capsules `probe:<capsule id>`. */
export const PROBE_NAME = 'probe'
/** The probe's wireframe colour — apart from every region colour of `CAPSULE_REGION_COLORS`. */
export const PROBE_COLOR = 0xff4fd8

/** One capsule of the probe's source set in its bind pose (model frame, metres). */
export interface ProbeSourceCapsule { id: string; region: string; a: Vec3; b: Vec3; r: number }

/** Where the probe stands: metres in the shown model's frame, `yaw` in degrees about +y. */
export interface ProbePose { x: number; z: number; yaw: number }

/**
 * The probe's capsules at `pose`: each endpoint mirrored (`mirror`: x → −x),
 * then turned by `pose.yaw` degrees about +y (x' = x·cos θ + z·sin θ,
 * z' = −x·sin θ + z·cos θ), then moved by (x, 0, z). The radius stays.
 */
export function probeCapsules(capsules: readonly ProbeSourceCapsule[], pose: ProbePose,
  mirror: boolean): PartnerCapsule[] {
  const theta = (pose.yaw * Math.PI) / 180
  const c = Math.cos(theta), s = Math.sin(theta)
  const place = (p: Vec3): Vec3 => {
    const x = mirror ? -p[0] : p[0]
    return [x * c + p[2] * s + pose.x, p[1], -x * s + p[2] * c + pose.z]
  }
  return capsules.map(cap => ({ id: cap.id, region: cap.region, now: { a: place(cap.a), b: place(cap.b), r: cap.r } }))
}

/**
 * The sweep's offset along the probe's facing at time `t` (seconds): a
 * triangle wave in [−span, span] that starts at 0 moving forwards at `speed`
 * m/s — up to span, back through 0 to −span, and up again (period
 * 4·span/speed). 0 for a span or speed that is not positive.
 */
export function probeSweepOffset(t: number, speed: number, span: number): number {
  if (!(span > 0) || !(speed > 0)) return 0
  const period = 4 * span
  const phase = ((speed * t) % period + period) % period
  if (phase <= span) return phase
  if (phase <= 3 * span) return 2 * span - phase
  return phase - period
}

/** `pose` moved `offset` metres along its facing (+z turned by the yaw: (sin θ, 0, cos θ)). */
export function probeSweptPose(pose: ProbePose, offset: number): ProbePose {
  const theta = (pose.yaw * Math.PI) / 180
  return { x: pose.x + offset * Math.sin(theta), z: pose.z + offset * Math.cos(theta), yaw: pose.yaw }
}

/** The probe as a partner of this frame: `{name: PROBE_NAME, capsules, channels: [], interaction: null}`. */
export function probeSnapshot(capsules: readonly PartnerCapsule[]): PartnerSnapshot {
  return { name: PROBE_NAME, capsules, channels: [], interaction: null }
}
