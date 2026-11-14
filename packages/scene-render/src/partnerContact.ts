/**
 * Partner contact, the pure rules (cross-person collision, stage 1; spec
 * `docs/superpowers/specs/2026-11-13-cross-person-collision-design.md`
 * Parts 1 and 3): which OTHER figures a reader reads, which of their capsules
 * each consumer takes, the per-chain broad phase, the combined own + partner
 * contact search, the release rate, and the snapshot of a partner's capsules.
 *
 * - A figure's BODY SPHERE comes from its bound capsules in the current frame:
 *   centre = the mean of all endpoints, radius = the largest endpoint distance
 *   plus that capsule's r.
 * - The reader's REACH SPHERE is its body sphere grown by its longest driven
 *   lever (and by the hair mesh's bounding spheres, for the GPU hair push).
 * - Candidates are the partners whose body sphere touches the reach sphere
 *   (gap ≤ 0); members of the reader's running pair interaction first, then the
 *   smallest gap; at most `PARTNER_MAX`.
 * - The contact search takes the smallest turn that is outside BOTH the own and
 *   the partner capsules; when none within the budget is, the turn with the
 *   smallest OWN depth (the own body always wins), the partner depth breaking
 *   ties.
 *
 * Nothing here suppresses own-body capsules: the own-body lists stay with the
 * consumers (`extensionCapsules`, `hairChainCapsules`, `garmentCapsules`). A
 * suppress list added for the partner wiring must name `outer_waist` along with
 * the other Hips-rooted capsules (collision v6 splits the Hips segment).
 *
 * Pure: no Three, no allocation beyond the returned values.
 */
import { HAIR_ONLY_REGIONS } from './collision'
import type { CapsuleNow, CollisionBinding, Vec3 } from './collision'

// --- constants (starting values; the builder sets the final ones from the plan's Task 9 check script) -----------

/** At most this many partners per reader: every other role of a group clip (roles a–e). */
export const PARTNER_MAX = 4
/** At most this many partner capsules in the GPU hair push's own uniform block. */
export const PARTNER_COLLIDE_MAX = 8
/** A GPU partner push above this (metres) fades to no push by 1.5 × this value (no vertex jumps across). */
export const PARTNER_PUSH_MAX_M = 0.04
/** Exit radius: a partner capsule that pushed a tip last frame tests with r + this (metres). */
export const PARTNER_HYST_M = 0.003
/** Release rate: the applied partner contact angle falls by at most this many degrees per second. */
export const PARTNER_RELEASE_DEG_S = 240
/** Root-distance prefilter slack (metres) before any partner is bound (plan ruling R8); the sphere test decides. */
export const PARTNER_PREFILTER_SLACK_M = 1.0

/** A capsule tip moved less than this (metres, or the caller's depth unit) counts as outside. */
const CONTACT_SLACK = 1e-6
/** Scan steps over the swing budget, then refinement iterations (the same numbers as `secondaryMotion.ts`). */
const CONTACT_SCAN = 12
const CONTACT_REFINE = 14

// --- types ------------------------------------------------------------------------------------------------------

/** A sphere in world space. */
export interface Sphere { c: Vec3; r: number }

/**
 * A declared channel in the current frame. Stage 2 (channels) defines it; in
 * stage 1 no channel exists, so the type is empty and `channels` is always `[]`.
 */
export type ChannelNow = never

/** One partner capsule as the snapshot holds it: payload id, region and world-space capsule. */
export interface PartnerCapsule { id: string; region: string; now: CapsuleNow }

/** A partner's capsules at the start of phase B (spec Part 1, "two-phase frame"). */
export interface PartnerSnapshot {
  name: string
  capsules: readonly PartnerCapsule[]
  channels: readonly ChannelNow[]
  interaction: { id: string; kind: string } | null
}

// --- helpers ----------------------------------------------------------------------------------------------------

function distance(p: Vec3, q: Vec3): number {
  return Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2])
}

/** Distance from `p` to the segment a→b (a == b: to the point). */
function segmentDistance(p: Vec3, a: Vec3, b: Vec3): number {
  const abx = b[0] - a[0], aby = b[1] - a[1], abz = b[2] - a[2]
  const apx = p[0] - a[0], apy = p[1] - a[1], apz = p[2] - a[2]
  const len2 = abx * abx + aby * aby + abz * abz
  const t = len2 > 1e-12 ? Math.min(1, Math.max(0, (apx * abx + apy * aby + apz * abz) / len2)) : 0
  return Math.hypot(apx - abx * t, apy - aby * t, apz - abz * t)
}

// --- spheres and selection --------------------------------------------------------------------------------------

/** A figure's body sphere: the mean of all capsule endpoints, radius the largest endpoint distance plus its capsule's r. Null without capsules. */
export function bodySphere(capsules: readonly CapsuleNow[]): Sphere | null {
  if (!capsules.length) return null
  let x = 0, y = 0, z = 0
  for (const { a, b } of capsules) { x += a[0] + b[0]; y += a[1] + b[1]; z += a[2] + b[2] }
  const n = 2 * capsules.length
  const c: Vec3 = [x / n, y / n, z / n]
  let r = 0
  for (const cap of capsules) r = Math.max(r, Math.max(distance(cap.a, c), distance(cap.b, c)) + cap.r)
  return { c, r }
}

/**
 * The reader's reach sphere: the body sphere's centre, its radius grown to
 * max(r + lever, max over `hair` of |c_h − c| + r_h). `lever` = the longest
 * driven lever (joint to tip at the current `length`); `hair` = the bounding
 * spheres of the hair meshes the GPU push reads partners for.
 */
export function reachSphere(body: Sphere, lever: number, hair?: readonly Sphere[]): Sphere {
  let r = body.r + Math.max(0, lever)
  for (const h of hair ?? []) r = Math.max(r, distance(h.c, body.c) + h.r)
  return { c: [body.c[0], body.c[1], body.c[2]], r }
}

/**
 * The partners a reader reads this frame: every candidate whose body sphere
 * touches `reach` (gap = centre distance − both radii ≤ 0); members of the
 * reader's running pair interaction first, then the smallest gap (ties keep
 * the candidates' order); at most `max`.
 */
export function selectPartners(reach: Sphere, members: ReadonlySet<string>,
  candidates: readonly { name: string; body: Sphere }[], max = PARTNER_MAX): string[] {
  const near: { name: string; member: boolean; gap: number; order: number }[] = []
  candidates.forEach((cand, order) => {
    const gap = distance(cand.body.c, reach.c) - reach.r - cand.body.r
    if (gap <= 0) near.push({ name: cand.name, member: members.has(cand.name), gap, order })
  })
  near.sort((p, q) => (p.member === q.member ? 0 : p.member ? -1 : 1) || p.gap - q.gap || p.order - q.order)
  return near.slice(0, Math.max(0, max)).map(entry => entry.name)
}

/**
 * Which partner capsules a consumer takes (spec Part 1 table):
 *  - `hair` (hair chains and hair meshes): every region, the hair-only ones
 *    included — for a partner the goal is the OUTER surface;
 *  - `extension` (every other driven chain): every region except
 *    `HAIR_ONLY_REGIONS`;
 *  - both drop `torso` when the set has `outer_trunk` (plan ruling R7: the
 *    outer circle encloses the inside-skin trunk capsules, and the budget is
 *    better spent elsewhere).
 * Payload order is kept.
 */
export function partnerCapsules<T extends { capsule: { region: string } }>(consumer: 'hair' | 'extension',
  bound: readonly T[]): T[] {
  const outer = bound.some(entry => entry.capsule.region === 'outer_trunk')
  return bound.filter(entry => {
    const region = entry.capsule.region
    if (outer && region === 'torso') return false
    return consumer === 'hair' || !HAIR_ONLY_REGIONS.includes(region)
  })
}

/** Broad phase per chain: the indices of the capsules whose segment comes within `lever + r` of the chain's joint. */
export function broadPhase(joint: Vec3, lever: number, capsules: readonly CapsuleNow[]): number[] {
  const kept: number[] = []
  capsules.forEach((cap, i) => { if (segmentDistance(joint, cap.a, cap.b) <= lever + cap.r) kept.push(i) })
  return kept
}

/**
 * The `max` capsules nearest to `sphere` (the GPU hair push's partner block):
 * indices ascending by segment distance to the sphere's centre minus the
 * capsule's r; ties keep the input order.
 */
export function nearestCapsules(sphere: Sphere, capsules: readonly CapsuleNow[], max: number): number[] {
  return capsules.map((cap, i) => ({ i, d: segmentDistance(sphere.c, cap.a, cap.b) - cap.r }))
    .sort((p, q) => p.d - q.d || p.i - q.i)
    .slice(0, Math.max(0, max))
    .map(entry => entry.i)
}

// --- the combined contact search --------------------------------------------------------------------------------

/** [own, partner] depths: is `p` strictly better than `q` — less own depth, then less partner depth. */
function better(p: readonly [number, number], q: readonly [number, number]): boolean {
  const po = p[0] < CONTACT_SLACK ? 0 : p[0], qo = q[0] < CONTACT_SLACK ? 0 : q[0]
  if (po !== qo) return po < qo
  const pp = p[1] < CONTACT_SLACK ? 0 : p[1], qp = q[1] < CONTACT_SLACK ? 0 : q[1]
  return pp < qp
}

const outsideBoth = (d: readonly [number, number]) => d[0] < CONTACT_SLACK && d[1] < CONTACT_SLACK

/**
 * The turn angle in (0, limit] for a tip against its own AND its partners'
 * capsules in ONE search (spec Part 3, "capped by the swing budget"):
 * `depthAt(angle)` = [own depth, partner depth] after that turn, `depth0` at 0.
 *  - the smallest angle that is outside both (a `CONTACT_SCAN` scan, refined
 *    by bisection);
 *  - otherwise the angle with the smallest own depth, ties broken by the
 *    smallest partner depth (the own body always wins; a ternary search
 *    around the best scan sample);
 *  - null when that is no better than 0 (and when the tip is already outside
 *    both at 0).
 * The same scan and refine counts as `secondaryMotion.ts`'s own-only search.
 */
export function contactAnglePair(depthAt: (angle: number) => [number, number], depth0: [number, number],
  limit: number): number | null {
  if (!(limit > 0) || outsideBoth(depth0)) return null
  const step = limit / CONTACT_SCAN
  let inside = 0, outside = -1, best = 0
  let bestDepth: [number, number] = depth0
  for (let k = 1; k <= CONTACT_SCAN; k++) {
    const depth = depthAt(k * step)
    if (outsideBoth(depth)) { outside = k * step; break }
    inside = k * step
    if (better(depth, bestDepth)) { best = k * step; bestDepth = depth }
  }
  if (outside > 0) {
    for (let i = 0; i < CONTACT_REFINE; i++) {
      const mid = (inside + outside) / 2
      if (outsideBoth(depthAt(mid))) outside = mid; else inside = mid
    }
    return outside
  }
  // The best turn: ternary search around the best scan sample, the order being own depth, then partner depth.
  let lo = Math.max(0, best - step), hi = Math.min(limit, best + step)
  for (let i = 0; i < CONTACT_REFINE; i++) {
    const m1 = lo + (hi - lo) / 3, m2 = hi - (hi - lo) / 3
    if (!better(depthAt(m2), depthAt(m1))) hi = m2; else lo = m1
  }
  let angle = (lo + hi) / 2
  const depth = depthAt(angle)
  if (!better(depth, depth0)) return null
  if (outsideBoth(depth)) {
    // An outside window the scan stepped over: its near edge, by bisection from below.
    let below = Math.max(0, best - step)
    for (let i = 0; i < CONTACT_REFINE; i++) {
      const mid = (below + angle) / 2
      if (outsideBoth(depthAt(mid))) angle = mid; else below = mid
    }
  }
  return angle
}

/**
 * The applied partner contact angle after the release rule (spec Part 3,
 * hysteresis): engaging is immediate, releasing falls by at most
 * `PARTNER_RELEASE_DEG_S` per second — max(want, prev − rate·dt, 0). Degrees.
 */
export function releasedAngle(prevDeg: number, wantDeg: number, dt: number): number {
  return Math.max(wantDeg, prevDeg - PARTNER_RELEASE_DEG_S * Math.max(0, dt), 0)
}

// --- the snapshot -----------------------------------------------------------------------------------------------

/**
 * A partner's capsules for phase B: `binding.update()` once (its pose is final
 * after phase A), then every bound capsule's id, region and world-space
 * capsule. `now` is held by reference — `update()` assigns a fresh object
 * per capsule rather than mutating it, so a later update leaves this snapshot
 * intact. `channels` is `[]` until stage 2.
 */
export function snapshotPartner(name: string, binding: CollisionBinding,
  interaction: PartnerSnapshot['interaction']): PartnerSnapshot {
  binding.update()
  return {
    name,
    capsules: binding.capsules.map(entry => ({ id: entry.capsule.id, region: entry.capsule.region, now: entry.now })),
    channels: [],
    interaction,
  }
}
