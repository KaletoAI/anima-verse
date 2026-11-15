/**
 * Declared channels, the shared guidance rule (cross-person collision, stage 2;
 * spec `docs/superpowers/specs/2026-11-13-cross-person-collision-design.md`
 * Part 4 "Guidance rule"). A channel is an inside capsule of a RECEIVING body
 * that only another figure's accepted chain may enter; the server resolves it
 * per model into bind space (`ChannelRecord`, collision v7) and this module is
 * the ONE place its geometry and rules live — the client's secondary motion,
 * the admin viewer's channel wireframe and its test rod all read the same
 * numbers.
 *
 * - THE FRAME. O = the opening centre, u = the unit axis into the body, D =
 *   the depth, R = the radius, α = the funnel half-angle (`coneDeg`), F = the
 *   funnel length in front of the opening. A point P has the axial coordinate
 *   s = (P − O)·u and the radial distance ρ = |P − O − s·u| (`channelCoords`).
 * - THE ZONES (`inZone`). Cylinder C: 0 ≤ s ≤ D and ρ ≤ R. Funnel Φ:
 *   −F ≤ s < 0 and ρ ≤ R + (−s)·tan α. The grown zone of the release test adds
 *   h to F and R and δ to α (`CHANNEL_GROW`); D is not grown, but an engaged
 *   tip PAST the bottom (s > D, ρ ≤ R + h) still counts as inside it — the
 *   depth scale already compresses it, and releasing there would drop the
 *   guidance exactly where it is deepest (`pastBottom`).
 * - THE BINDING (`bindChannels`) follows the endpoint rule of `collision.ts`
 *   unchanged: `a_pos` → O and `b_pos` → the bottom, each through its joint's
 *   bind→world matrix; u and D come from those two points, R and F scale with
 *   that matrix like a capsule radius.
 * - RADIAL GUIDANCE (`radialGuidanceAngle`, `allowedRadius`): with a link tip
 *   at s ≥ 0 the allowed radius is R' = max(0, R − r_c), at −F ≤ s < 0 it is
 *   R'(s) = max(0, R + (−s)·tan α − r_c); a tip with ρ > R' turns about its
 *   joint, in the plane of its lever and the radial direction, by the smallest
 *   angle that gives ρ = R'. The caller multiplies it by w and caps it by the
 *   link's swing budget (no folding).
 * - DEPTH (`depthJoint`, `depthScale`): the links from s_e on are shortened
 *   along their levers by k = max(compress_min, (D − r_c − s_e)/(s_tip − s_e))
 *   when s_tip > D − r_c; what k cannot absorb stays past the bottom. s_e is
 *   the link joint nearest the opening: the first one at s ≥ 0, or — no joint
 *   inside — the one closest before it (s_e < 0, so a one-link chain hanging
 *   from outside the opening is still shortened from its joint).
 * - ENGAGEMENT (`channelGate`, `stepEngagement`): the gate (accepted op, state
 *   length, the same running pair interaction, its kind), a tip in Φ ∪ C and
 *   the lever within α engage; a failed gate or no tip in the grown zone
 *   release; w ramps over `CHANNEL_BLEND_S` both ways and never snaps.
 * - SUPPRESSION (`suppressedIds`): a link tip inside C skips the receiving
 *   body's `suppress` capsules; outside C (the funnel included) every capsule
 *   pushes.
 *
 * `three` is injected (the binding and the wireframe), never imported; the
 * rules themselves are pure.
 */
import type { BufferGeometry, LineSegments, Object3D } from 'three'
import { COLLISION_VERSION, bodyJoints, capsuleNow, jointRefNow } from './collision'
import type { ChannelOverride, ChannelRecord, CollisionPayload, JointRef, Vec3 } from './collision'
import type { PartnerSnapshot } from './partnerContact'
import { normBoneName } from './clipRetarget'

type Three = typeof import('three')

// --- constants ----------------------------------------------------------------------------------------------------

/** Seconds w takes from 0 to 1 on engagement and from 1 to 0 on release (spec default). */
export const CHANNEL_BLEND_S = 0.2
/** h: the release zone grows the funnel length and the radius by this (metres; spec default). */
export const CHANNEL_HYST_M = 0.005
/** δ: the release zone grows the funnel half-angle by this (degrees; spec default). */
export const CHANNEL_HYST_DEG = 10
/** The grown zone of the release test: `inZone(s, ρ, ch, CHANNEL_GROW)` — F and R grown by h, α by δ, and the
 *  cylinder open past the bottom (an engaged tip with s > D stays inside; `depthScale` compresses it). */
export const CHANNEL_GROW: Readonly<{ h: number; deg: number; pastBottom: boolean }> =
  Object.freeze({ h: CHANNEL_HYST_M, deg: CHANNEL_HYST_DEG, pastBottom: true })

const DEG = Math.PI / 180
/** Scan steps over a half turn, then bisection iterations, of the radial guidance search. */
const GUIDE_SCAN = 64
const GUIDE_REFINE = 48
/** A tip within this of R' (metres) needs no turn. */
const GUIDE_SLACK = 1e-9
const EMPTY: ReadonlySet<string> = new Set<string>()

// --- types --------------------------------------------------------------------------------------------------------

/**
 * A declared channel in the current frame (world space): `o` the opening centre, `u` the unit axis into the body,
 * `depth` D, `r` R, `coneDeg` α, `funnel` F (metres, scaled with the figure), and the record's gate fields —
 * `accepts` (ops), `minLength`, `compressMin`, `kinds` (`interaction_kinds`, null = any running pair interaction)
 * and `suppress` (the receiving body's capsule ids, payload order).
 */
export interface ChannelNow {
  id: string
  o: Vec3
  u: Vec3
  depth: number
  r: number
  coneDeg: number
  funnel: number
  accepts: readonly string[]
  minLength: number
  compressMin: number
  kinds: readonly string[] | null
  suppress: ReadonlySet<string>
}

/** An entering chain's engagement with one channel: `w` the guidance weight in [0, 1]. */
export interface Engagement { engaged: boolean; w: number }

// --- vector helpers -----------------------------------------------------------------------------------------------

const sub = (p: Vec3, q: Vec3): Vec3 => [p[0] - q[0], p[1] - q[1], p[2] - q[2]]
const add = (p: Vec3, q: Vec3): Vec3 => [p[0] + q[0], p[1] + q[1], p[2] + q[2]]
const scale = (p: Vec3, k: number): Vec3 => [p[0] * k, p[1] * k, p[2] * k]
const dot = (p: Vec3, q: Vec3) => p[0] * q[0] + p[1] * q[1] + p[2] * q[2]
const cross = (p: Vec3, q: Vec3): Vec3 => [p[1] * q[2] - p[2] * q[1], p[2] * q[0] - p[0] * q[2], p[0] * q[1] - p[1] * q[0]]
const len = (p: Vec3) => Math.hypot(p[0], p[1], p[2])

/** `v` turned about the unit `axis` by `angle` radians (Rodrigues, right-handed like three's `setFromAxisAngle`). */
function rotate(v: Vec3, axis: Vec3, angle: number): Vec3 {
  const c = Math.cos(angle), s = Math.sin(angle)
  const kxv = cross(axis, v), kv = dot(axis, v)
  return [v[0] * c + kxv[0] * s + axis[0] * kv * (1 - c), v[1] * c + kxv[1] * s + axis[1] * kv * (1 - c),
    v[2] * c + kxv[2] * s + axis[2] * kv * (1 - c)]
}

// --- the frame and the zones --------------------------------------------------------------------------------------

/** A point's channel coordinates: s = (P − O)·u along the axis, ρ = |P − O − s·u| from it. */
export function channelCoords(p: Vec3, ch: ChannelNow): { s: number; rho: number } {
  const rel = sub(p, ch.o)
  const s = dot(rel, ch.u)
  return { s, rho: len(sub(rel, scale(ch.u, s))) }
}

/**
 * Which zone (s, ρ) lies in: `cylinder` (0 ≤ s ≤ D, ρ ≤ R), `funnel` (−F ≤ s < 0, ρ ≤ R + (−s)·tan α) or null.
 * `grow` grows F and R by `h` and α by `deg` (default 0), and with `pastBottom` the cylinder has no bottom (s > D
 * counts as `cylinder`) — the release test passes `CHANNEL_GROW`.
 */
export function inZone(s: number, rho: number, ch: ChannelNow,
  grow?: { h: number; deg?: number; pastBottom?: boolean }): 'cylinder' | 'funnel' | null {
  const h = grow?.h ?? 0
  const alpha = (ch.coneDeg + (grow?.deg ?? 0)) * DEG
  if (s >= 0) return (s <= ch.depth || !!grow?.pastBottom) && rho <= ch.r + h ? 'cylinder' : null
  return s >= -(ch.funnel + h) && rho <= ch.r + h + (-s) * Math.tan(alpha) ? 'funnel' : null
}

/**
 * The radius a link of capsule radius `rC` may keep at axial position `s`: in C (s ≥ 0, also past the bottom)
 * R' = max(0, R − r_c); in the funnel (s < 0) R'(s) = max(0, R + (−s)·tan α − r_c).
 */
export function allowedRadius(s: number, ch: ChannelNow, rC: number): number {
  const open = s < 0 ? ch.r + (-s) * Math.tan(ch.coneDeg * DEG) : ch.r
  return Math.max(0, open - rC)
}

// --- radial guidance ----------------------------------------------------------------------------------------------

/**
 * The radial guidance turn of one link (joint → tip, link capsule radius `rC`): the smallest turn about the joint,
 * in the plane of the lever and the tip's radial direction, after which the tip's ρ equals `allowedRadius` at its
 * new s. `angle` in RADIANS, `axis` a unit vector (a positive right-handed turn about it moves the tip towards the
 * axis). Null when no turn is needed (ρ ≤ R'), when the tip lies in front of the funnel (s < −F), or when no turn
 * within a half turn brings it closer. When no turn reaches R' exactly (a joint too far off the axis, R' = 0), the
 * turn of the closest approach. The caller multiplies the angle by w and caps it by the link's swing budget.
 */
export function radialGuidanceAngle(joint: Vec3, tip: Vec3, ch: ChannelNow, rC: number): { angle: number; axis: Vec3 } | null {
  const lever = sub(tip, joint)
  const leverLen = len(lever)
  if (!(leverLen > 1e-12)) return null
  const { s, rho } = channelCoords(tip, ch)
  if (s < -ch.funnel) return null
  const excess = (p: Vec3) => {
    const f = channelCoords(p, ch)
    return f.rho - allowedRadius(f.s, ch, rC)
  }
  const f0 = rho - allowedRadius(s, ch, rC)
  if (f0 <= GUIDE_SLACK) return null
  // The radial direction at the tip, and the turn axis of the plane (lever, radial): k = e × lever makes the tip's
  // first motion k × lever = lever (e·lever) − e |lever|², which never points outwards. A purely radial lever
  // leaves that plane undefined: then the plane of the lever and u, turning the tip INTO the body.
  const e = scale(sub(sub(tip, ch.o), scale(ch.u, s)), 1 / rho)
  let axis = cross(e, lever)
  if (len(axis) < 1e-9 * leverLen) axis = cross(e, ch.u)
  axis = scale(axis, 1 / len(axis))
  const at = (angle: number) => excess(add(joint, rotate(lever, axis, angle)))
  const step = Math.PI / GUIDE_SCAN
  let best = 0, bestF = f0
  for (let i = 1; i <= GUIDE_SCAN; i++) {
    const angle = i * step
    const f = at(angle)
    if (f <= 0) {
      let lo = angle - step, hi = angle
      for (let k = 0; k < GUIDE_REFINE; k++) {
        const mid = (lo + hi) / 2
        if (at(mid) <= 0) hi = mid; else lo = mid
      }
      return { angle: hi, axis }
    }
    if (f < bestF) { best = angle; bestF = f }
  }
  if (!(best > 0)) return null
  // No turn reaches R': the closest approach, by ternary search around the best scan sample.
  let lo = Math.max(0, best - step), hi = Math.min(Math.PI, best + step)
  for (let k = 0; k < GUIDE_REFINE; k++) {
    const m1 = lo + (hi - lo) / 3, m2 = hi - (hi - lo) / 3
    if (at(m1) <= at(m2)) hi = m2; else lo = m1
  }
  return { angle: (lo + hi) / 2, axis }
}

// --- depth --------------------------------------------------------------------------------------------------------

/**
 * s_e of the depth scale, from the axial positions of a chain's link joints (root first, the tip excluded): the
 * index of the joint nearest the opening — the first one at s ≥ 0, else (no joint inside) the one with the largest
 * s < 0 (the later one on a tie). −1 without joints.
 */
export function depthJoint(sJoints: readonly number[]): number {
  let best = -1
  for (let i = 0; i < sJoints.length; i++) {
    if (sJoints[i] >= 0) return i
    if (best < 0 || sJoints[i] >= sJoints[best]) best = i
  }
  return best
}

/**
 * The depth scale of the links from s_e on: s_tip = the chain's last tip, s_e = the joint `depthJoint` picks (it may
 * lie before the opening, s_e < 0). k = max(compress_min, (D − r_c − s_e)/(s_tip − s_e)) when s_tip > D − r_c,
 * else 1. Applied to the levers from that joint on, the tip lands at s_e + k·(s_tip − s_e); what k cannot absorb
 * stays past the bottom.
 */
export function depthScale(sTip: number, sE: number, ch: ChannelNow, rC: number): number {
  const floor = ch.depth - rC
  if (!(sTip > floor) || !(sTip - sE > 1e-12)) return 1
  return Math.min(1, Math.max(ch.compressMin, (floor - sE) / (sTip - sE)))
}

// --- engagement ---------------------------------------------------------------------------------------------------

/**
 * One frame of an entering chain's engagement with a channel:
 *  - not engaged: engages when the gate passes, a link tip lies in Φ ∪ C (`tipInZone`) and that link's lever is
 *    within α of u (`leverAngleDeg` ≤ `coneDeg`);
 *  - engaged: releases when the gate fails or no link tip lies in the grown zone (`tipInGrownZone`, `CHANNEL_GROW`
 *    — a tip past the bottom counts as inside it);
 *  - w then moves towards 1 (engaged) or 0 by dt / `CHANNEL_BLEND_S` — the engaging and the releasing frame
 *    included, so guidance never snaps.
 */
export function stepEngagement(prev: Engagement, input: { gate: boolean; tipInZone: boolean; tipInGrownZone: boolean;
  leverAngleDeg: number }, ch: ChannelNow, dt: number): Engagement {
  const engaged = prev.engaged
    ? input.gate && input.tipInGrownZone
    : input.gate && input.tipInZone && input.leverAngleDeg <= ch.coneDeg
  const delta = Math.max(0, dt) / CHANNEL_BLEND_S
  const w = engaged ? Math.min(1, prev.w + delta) : Math.max(0, prev.w - delta)
  return { engaged, w }
}

/**
 * The gate of an entering chain (`group`: its motion group's op and effective state length) against a partner's
 * channel: an accepted op, length ≥ `minLength`, the reader and the partner in the SAME running pair interaction
 * (both present, equal ids), and — when the channel names `kinds` — that interaction's kind among them. A figure's
 * own channels are the caller's to leave out (a partner snapshot is never the reader).
 */
export function channelGate(group: { op?: string; length: number }, ch: ChannelNow,
  reader: { interaction: { id: string } | null }, partner: PartnerSnapshot): boolean {
  if (!group.op || !ch.accepts.includes(group.op)) return false
  if (!(group.length >= ch.minLength)) return false
  const mine = reader.interaction, theirs = partner.interaction
  if (!mine || !theirs || mine.id !== theirs.id) return false
  return ch.kinds === null || ch.kinds.includes(theirs.kind)
}

/** The receiving body's capsule ids an engaged link tip at `tip` skips: the channel's `suppress` inside C, else none. */
export function suppressedIds(tip: Vec3, ch: ChannelNow): ReadonlySet<string> {
  const { s, rho } = channelCoords(tip, ch)
  return inZone(s, rho, ch) === 'cylinder' ? ch.suppress : EMPTY
}

// --- the admin test rod -------------------------------------------------------------------------------------------

/**
 * The admin viewer's test rod through the rule, root to tip, at w = 1. The rod is straight, `links` equal links of
 * `length` / `links` and capsule radius `radius`; its root sits on the axis at s = `insertion` − `length`, and it
 * points along u tilted by `tiltDeg` (about a fixed perpendicular of u: u × x, or u × y when u is near x). Each link,
 * root to tip, takes its radial guidance turn capped by `budgetDeg` and carries the links after it; then the links
 * from the joint `depthJoint` picks are scaled by `depthScale`. Returns the joints (root first, the tip
 * last), the turns in degrees, k (1 when the tip stays before D − radius), how far the tip's surface lies past the
 * bottom (s_tip − (D − radius), ≥ 0) and the suppressed ids (the channel's list when any link tip is inside C).
 */
export function guideRod(ch: ChannelNow, rod: { length: number; radius: number; links: number; insertion: number;
  tiltDeg: number; budgetDeg: number }): { joints: Vec3[]; turnsDeg: number[]; k: number; pastBottomM: number;
  suppressed: string[] } {
  const n = Math.max(1, Math.round(rod.links))
  const linkLen = Math.max(0, rod.length) / n
  const ref: Vec3 = Math.abs(ch.u[0]) < 0.9 ? [1, 0, 0] : [0, 1, 0]
  const side = cross(ch.u, ref)
  const dir = rotate(ch.u, scale(side, 1 / len(side)), rod.tiltDeg * DEG)
  const joints: Vec3[] = [add(ch.o, scale(ch.u, rod.insertion - rod.length))]
  for (let i = 0; i < n; i++) joints.push(add(joints[i], scale(dir, linkLen)))
  const budget = Math.max(0, rod.budgetDeg) * DEG
  const turnsDeg: number[] = []
  for (let i = 0; i < n; i++) {
    const guide = radialGuidanceAngle(joints[i], joints[i + 1], ch, rod.radius)
    const turn = guide ? Math.min(guide.angle, budget) : 0
    if (guide && turn > 0) {
      for (let j = i + 1; j <= n; j++) joints[j] = add(joints[i], rotate(sub(joints[j], joints[i]), guide.axis, turn))
    }
    turnsDeg.push(turn / DEG)
  }
  const sOf = (p: Vec3) => dot(sub(p, ch.o), ch.u)
  let k = 1
  const first = depthJoint(joints.slice(0, n).map(sOf))
  if (first >= 0) {
    k = depthScale(sOf(joints[n]), sOf(joints[first]), ch, rod.radius)
    if (k !== 1) for (let j = first + 1; j <= n; j++) joints[j] = add(joints[first], scale(sub(joints[j], joints[first]), k))
  }
  const pastBottomM = Math.max(0, sOf(joints[n]) - (ch.depth - rod.radius))
  const suppressed = joints.slice(1).some(p => suppressedIds(p, ch).size > 0) ? [...ch.suppress] : []
  return { joints, turnsDeg, k, pastBottomM, suppressed }
}

// --- the draft preview --------------------------------------------------------------------------------------------

/**
 * A channel record as the server would resolve it with `draft` instead of `applied` (the Channels panel's live
 * preview; `app/core/collision_channels.py` `resolve_channels`): `a_pos` and `b_pos` move by
 * (draft − applied)·`offset_mm` / 1000 along the record's `frame` (side, up, front); r scales by
 * draft / applied `radius_scale`; the bottom moves along the axis so the depth scales by draft / applied
 * `depth_scale`; `cone_deg` is the draft's; `applied` becomes the draft. `applied` null = no override (offset 0,
 * scales 1). `suppress` stays the record's (the server recomputes it on the next fit). The record is not mutated.
 */
export function previewChannel(record: ChannelRecord, applied: ChannelOverride | null,
  draft: ChannelOverride): ChannelRecord {
  const was = applied ?? { offset_mm: [0, 0, 0], radius_scale: 1, depth_scale: 1, cone_deg: record.cone_deg }
  const { side, up, front } = record.frame
  const d = [0, 1, 2].map(i => (draft.offset_mm[i] - was.offset_mm[i]) / 1000)
  const shift = add(add(scale(side, d[0]), scale(up, d[1])), scale(front, d[2]))
  const aPos = add(record.a_pos, shift)
  const bPos = add(aPos, scale(sub(record.b_pos, record.a_pos), draft.depth_scale / was.depth_scale))
  return {
    ...record,
    a_pos: aPos,
    b_pos: bPos,
    r: record.r * draft.radius_scale / was.radius_scale,
    cone_deg: draft.cone_deg,
    applied: { ...draft, offset_mm: [...draft.offset_mm] as [number, number, number] },
  }
}

// --- three binding ------------------------------------------------------------------------------------------------

/**
 * Bind the `channels` of a `collision` payload to a loaded figure by the endpoint rule of `collision.ts`: O and the
 * bottom are `a_pos` / `b_pos` through their joints (a BODY mesh's, `bodyJoints`), u and D follow from them, R and F
 * scale with joint `a`'s matrix like a capsule radius. `update()` recomputes from the CURRENT bone matrices (call
 * after `updateMatrixWorld`) and puts a fresh `ChannelNow` into each slot, so a snapshot that copied the array keeps
 * its frame. Null for a payload of another version, without channels, or when no channel's joint is on the figure.
 * `_three` keeps the signature of `bindCollision`; the current-frame rule needs no three object here.
 */
export function bindChannels(_three: Three, root: Object3D,
  payload: CollisionPayload | null | undefined): { channels: ChannelNow[]; update(): void } | null {
  if (!payload || payload.version !== COLLISION_VERSION || !payload.channels?.length) return null
  const joints = bodyJoints(root)
  const bound: Array<{ record: ChannelRecord; ja: JointRef; jb: JointRef; suppress: ReadonlySet<string> }> = []
  for (const record of payload.channels) {
    const ja = joints.get(normBoneName(record.a))
    const jb = joints.get(normBoneName(record.b))
    if (!ja || !jb || !(record.r > 0)) continue
    bound.push({ record, ja, jb, suppress: new Set(record.suppress) })
  }
  if (!bound.length) return null
  const channelNow = (entry: typeof bound[number]): ChannelNow | null => {
    const { record } = entry
    const cap = capsuleNow(record, jointRefNow(entry.ja), jointRefNow(entry.jb))
    const axis = sub(cap.b, cap.a)
    const depth = len(axis)
    if (!(depth > 1e-12)) return null
    return {
      id: record.id, o: cap.a, u: scale(axis, 1 / depth), depth, r: cap.r, coneDeg: record.cone_deg,
      funnel: record.funnel * (cap.r / record.r), accepts: record.accepts, minLength: record.min_length,
      compressMin: record.compress_min, kinds: record.interaction_kinds ?? null, suppress: entry.suppress,
    }
  }
  const usable = bound.filter(entry => channelNow(entry) !== null)
  if (!usable.length) return null
  const channels: ChannelNow[] = []
  const update = () => {
    usable.forEach((entry, i) => {
      const now = channelNow(entry)
      if (now) channels[i] = now
    })
  }
  update()
  return { channels, update }
}

// --- the wireframe ------------------------------------------------------------------------------------------------

/**
 * Line segments of a channel wireframe in its own frame (+y = u, the opening at the origin): the cylinder (rings at
 * 0, D/2 and D, `meridians` lines from 0 to D) and the funnel cone (a ring of radius R + F·tan α at −F, the same
 * meridians from the opening ring out to it). Flat `[x, y, z, …]` pairs.
 */
export function channelLineSegments(r: number, depth: number, funnel: number, coneDeg: number, meridians = 8,
  segments = 24): number[] {
  const out: number[] = []
  const mouth = r + funnel * Math.tan(coneDeg * DEG)
  const circle = (y: number, radius: number) => {
    for (let i = 0; i < segments; i++) {
      const t0 = (i / segments) * Math.PI * 2, t1 = ((i + 1) / segments) * Math.PI * 2
      out.push(Math.cos(t0) * radius, y, Math.sin(t0) * radius, Math.cos(t1) * radius, y, Math.sin(t1) * radius)
    }
  }
  circle(0, r)
  circle(depth / 2, r)
  circle(depth, r)
  if (funnel > 0) circle(-funnel, mouth)
  for (let m = 0; m < meridians; m++) {
    const theta = (m / meridians) * Math.PI * 2
    const cx = Math.cos(theta), cz = Math.sin(theta)
    out.push(cx * r, 0, cz * r, cx * r, depth, cz * r)
    if (funnel > 0) out.push(cx * r, 0, cz * r, cx * mouth, -funnel, cz * mouth)
  }
  return out
}

interface ChannelWireState { r: number; depth: number; funnel: number; coneDeg: number }

/**
 * A wireframe of one channel in the current frame (world space): cylinder plus funnel cone, a `LineSegments` drawn
 * on top of the figure (`depthTest` off). Move it with `placeChannelWireframe` every frame; it owns its geometry and
 * material (the caller disposes both).
 */
export function channelWireframe(three: Three, ch: ChannelNow, color: number): LineSegments {
  const material = new three.LineBasicMaterial({ color, depthTest: false, transparent: true, opacity: 0.9 })
  const line = new three.LineSegments(new three.BufferGeometry(), material)
  line.renderOrder = 999
  line.userData.channelWire = { r: -1, depth: -1, funnel: -1, coneDeg: -1 } as ChannelWireState
  placeChannelWireframe(three, line, ch)
  return line
}

/** Put a channel wireframe onto `ch` (rebuilding its lines when R, D, F or α changed). */
export function placeChannelWireframe(three: Three, line: LineSegments, ch: ChannelNow): void {
  const state = line.userData.channelWire as ChannelWireState
  const tol = Math.max(1e-5, ch.r * 1e-3)
  if (Math.abs(state.r - ch.r) > tol || Math.abs(state.depth - ch.depth) > tol
    || Math.abs(state.funnel - ch.funnel) > tol || Math.abs(state.coneDeg - ch.coneDeg) > 1e-6) {
    const geometry = line.geometry as BufferGeometry
    geometry.setAttribute('position',
      new three.Float32BufferAttribute(channelLineSegments(ch.r, ch.depth, ch.funnel, ch.coneDeg), 3))
    geometry.computeBoundingSphere()
    Object.assign(state, { r: ch.r, depth: ch.depth, funnel: ch.funnel, coneDeg: ch.coneDeg })
  }
  line.position.set(ch.o[0], ch.o[1], ch.o[2])
  line.quaternion.setFromUnitVectors(new three.Vector3(0, 1, 0), new three.Vector3(ch.u[0], ch.u[1], ch.u[2]))
  line.updateMatrix()
  line.updateMatrixWorld()
}
