/** Secondary motion in metres and real seconds; three's world is Y-up.
 * Gravity is (0,-9.81,0). No runtime three import: consumers inject it.
 *
 * CONTACT WITH THE BODY'S COLLISION CAPSULES (`setCollision`, contract
 * `docs/schnittstellen-3d.md` "Collision capsules"). Every driven link that
 * has a swing budget (`max_deg` or `sag_max_deg` > 0) has a TIP in its bone
 * frame: the next joint of its chain, else its most protruding own vertex —
 * of the bind vertices skinned > 50 % to it, the one reaching farthest along
 * its centroid lever (none: twice the centroid lever). After the link's
 * dynamics have produced its rendered frame, the garment push itself
 * (`pushOutOfCapsules`) says whether the tip is inside a capsule and which way
 * is out; the link is then ROTATED about its own joint, in the plane of its
 * lever and that way out, by the smallest angle that puts the tip outside —
 * the tip keeps its lever length, children ride the corrected frame. The
 * turn is capped at the link's swing budget (max(`max_deg`, `sag_max_deg`) ×
 * its motion share): a capsule driven through the middle of the tissue leaves
 * the rest inside rather than folding the link away. The oscillator state is not touched —
 * the contact is a constraint on the rendered frame, so it can neither inject
 * energy nor stall the spring.
 *  - OWN CAPSULES are excluded per chain: a capsule whose start joint `a` is
 *    an ancestor of the chain root (or a bone in its `anchor_blend`), the
 *    chain root itself or any bone below it carries the chain itself — a
 *    chain hanging from Spine2 is never pushed out of the Hips/Spine/chest
 *    capsules it sits in, nor out of the extension capsules riding its own
 *    links, and a child group hanging from it (a tip link) not out of them
 *    either; only out of the arms, legs, head and OTHER chains' extension
 *    capsules (Review Focus 2 of the collision plan); never out of a hair-only
 *    or a partner-only capsule (`HAIR_ONLY_REGIONS`, `PARTNER_ONLY_REGIONS` —
 *    the outer trunk set of collision v6 is another figure's collider). An extension capsule of
 *    another chain is read where its bones were at the start of the frame
 *    (the capsules are updated once, before the links move) — one frame
 *    behind that chain's own swing.
 *  - HAIR CHAINS (`MotionGroup.hair`, HairDeck's spring chains under Head) are
 *    the exception: they collide with every bound capsule of `HAIR_REGIONS`
 *    (`hairChainCapsules` — head, torso, arms, `shoulder_hair`, `chest_hair`), their ancestors'
 *    capsules INCLUDED. A strand rides the head but must not swing into it,
 *    nor into the neck/chest it hangs over; the bind rule below keeps the
 *    rest pose where the fit put it (a joint rooted inside the head capsule
 *    caps that capsule at its bind distance, and the server leaves the joints
 *    inside the head capsule out of the group — `hair_motion.served_chains`).
 *    TODAY'S SKIN UNDER THE SWING (Ruling H11): a hair group's `anchor_blend`
 *    names per chain joint the Head / Neck / Spine2 row that reproduces
 *    today's hair skin (the server's least-squares fit), its rigid joints
 *    included (carried: no swing of their own; a chain of carried joints only
 *    sends `bones: []`). The chain is solved as before (rigid under Head);
 *    then each bone's deviation from that rigid rest, L = rest⁻¹ · rendered
 *    (its swing, in its own rest frame), is scaled to the row's share of the
 *    bone the chain hangs from (`anchor_from`, Head — the swing is driven by
 *    the head's motion, so it moves only the head-carried share of the hair)
 *    and put on top of the linear blend of the row's bones:
 *    world = Σ share · (joint now · joint bind⁻¹) · bone bind · L^share.
 *    Without swing (L = identity) every bone is where today's skin puts the
 *    hair at it — a strand on the back follows Spine2, the crown the head.
 *    The contact then turns that final frame about the joint (the tip check
 *    of the solver would act on the rigid chain, not on what is drawn).
 *    Measured (Ruling H11, check_garment_collision, worst of sit/celebrating/
 *    walk): the rigid chain sank 3.6–7.9 % of the hair into the body, one
 *    blend per chain 3.6–10.9 %, today's skin under the head share
 *    0.5–2.3 % (Kira 0.5–1.1, Rosi 2.3; today 0.0–0.2 %).
 *  - BIND RULE, as for garments: per tip and capsule the radius is capped at
 *    the tip's distance to that capsule in the bind pose (bind-pose tip from
 *    the bone's `boneInverse`, bind-pose capsule `BoundCapsule.bind`), so the
 *    contact moves nothing in the bind pose.
 *  - PARTNER CAPSULES (`update(dt, { partners })`, cross-person collision
 *    spec Parts 1–3, rules in `partnerContact.ts`): the figure is the READER,
 *    each `PartnerSnapshot` another figure's capsules in world space. A
 *    reader only ever turns its OWN links — push only, along the way out of
 *    the capsules, never toward a partner; the partner is never moved. Per
 *    consumer (`partnerCapsules`): a hair chain takes every partner region,
 *    an extension chain all but `HAIR_ONLY_REGIONS`. Per chain the broad
 *    phase keeps the capsules within the chain's lever (+ the exit radius)
 *    of its ROOT joint; its links test only those — at most `COLLIDE_MAX`
 *    (the push's cap per list), the farthest from the root joint dropped
 *    (`broadPhase` + `nearestCapsules`, bit for bit, as `chainPartners`).
 *    THE SHARED CULL (plan Task 9b): the region filter runs once per partner
 *    snapshot, the pool once per update, and a consumer with three chains or
 *    more culls it once per update against a sphere about its chain roots
 *    (`cullPartnerList`); a chain inside that sphere reads the culled list,
 *    any other the whole pool — the same capsules either way.
 *    NO BIND RULE: a partner has no bind relation to the reader, so its
 *    capsules apply at FULL radius. The own and the partner capsules go
 *    through ONE search (`contactAnglePair`), capped by the same swing
 *    budget: the smallest turn outside both; when none within the budget
 *    is, the turn with the smallest OWN depth, the partner depth breaking
 *    ties — the OWN BODY WINS. HYSTERESIS, partner contacts only: a partner
 *    capsule that pushed the tip last frame (the tip inside it before the
 *    turn) tests with r + `PARTNER_HYST_M`; the applied turn falls by at
 *    most `PARTNER_RELEASE_DEG_S` (`releasedAngle`; engaging is immediate) —
 *    a held turn keeps the last way out when nothing pushes any more, and
 *    gives way to the plain turn whenever it would put the tip deeper into
 *    an own capsule. Neither rule touches the spring state. A partner's
 *    BODY capsules are exact in the frame (its pose is final before any
 *    secondary solve); its EXTENSION capsules carry that partner's swing of
 *    the PREVIOUS frame on its current body — one frame behind, as between
 *    one figure's own chains. Without `partners` (or with `[]`) and no
 *    release pending, the path is the own-only one above and allocates
 *    nothing; a link whose chain kept no partner capsule and holds no turn
 *    stays on it too.
 *  - CHANNELS (`update(dt, { partners, interaction })`, cross-person
 *    collision spec Part 4 "Guidance rule", the rule itself in `channels.ts`):
 *    a partner's declared channel (`PartnerSnapshot.channels`) is a way INTO
 *    that body that this figure's accepted chains may take. Per chain (its
 *    root link) and partner channel: THE GATE (`channelGate` — the chain's
 *    `MotionGroup.op` accepted, its state `length` ≥ `min_length`, the reader's
 *    `interaction` and the partner's the same running pair interaction, its
 *    kind among `interaction_kinds`), ENGAGEMENT (`stepEngagement`, once per
 *    update before the solve, on the zone of the chain's tips as RENDERED in
 *    the previous update: a tip in Φ ∪ C with its lever within α engages, no
 *    tip in the grown zone — past the bottom counts as inside — or a failed
 *    gate releases) and the weight w, which ramps over `CHANNEL_BLEND_S` both
 *    ways. A figure's own channels are never read (they are not a partner's).
 *    While w > 0, per link root to tip after its dynamics: the RADIAL GUIDANCE
 *    turn (`radialGuidanceAngle` with r_c = the link's own extension capsule
 *    radius × the state girth) × w, capped by the link's swing budget (the
 *    contact turn's cap, applied on its own), then the contact turn — where
 *    the guided tip lies inside C, the partner's `suppress` capsules are
 *    taken out of THAT partner's list (radius × (1 − w), gone at w = 1, so
 *    neither engaging nor releasing snaps). After the chain's last link: the
 *    DEPTH SCALE k (`depthScale`, blended 1 → k by w) shortens the levers of
 *    the links from s_e on along their tips, about that joint (`depthJoint`:
 *    the first joint past the opening, else the one nearest before it), and
 *    the chain is re-published in the same update. All of it
 *    acts on the rendered frame only: the spring state never sees it, so a
 *    released chain is exactly where the free one would be. `contactTips`
 *    rows of an engaged chain carry `channel` (id, w, k). No channel in any
 *    partner (today's worlds): nothing of this runs and nothing allocates.
 *  - INERT: no driven link, no payload, or far LOD → no binding, no work.
 */
import type { Bone, Matrix4, Quaternion, Object3D, SkinnedMesh, Vector3 } from 'three'
import { normBoneName } from './clipRetarget'
import { CHANNEL_GROW, channelCoords, channelGate, depthJoint, depthScale, inZone, radialGuidanceAngle, stepEngagement } from './channels'
import type { ChannelNow } from './channels'
import { bindCollision, bodyJoints, COLLISION_VERSION, HAIR_ONLY_REGIONS, jointRefNow, linearScale, PARTNER_ONLY_REGIONS } from './collision'
import type { BoundCapsule, CollisionBinding, CollisionPayload, JointRef, Vec3 } from './collision'
import { inGarment } from './figure'
import { COLLIDE_MAX, HAIR_REGIONS, pushOutOfCapsules } from './garmentCollision'
import type { CollideCapsule, PushOptions } from './garmentCollision'
import { chainPartners, contactAnglePair, createPartnerList, cullPartnerList, fillPartnerList, PARTNER_HYST_M,
  releasedAngle } from './partnerContact'
import type { PartnerCapsule, PartnerSnapshot } from './partnerContact'
type Three = typeof import('three')

export interface MotionGroup {
  bones: string[]
  freq_hz: number
  zeta: number
  spill: number
  translate: number
  flatten: number
  stretch: number
  spread: number
  flatten_floor: number
  length: number
  girth: number
  scale_axis?: 'centroid' | 'bone'
  /** The last N links of each chain ride rigidly on their parent: its rotation and
   * position, never its scale, and no rest, sag, stretch, swing or state extent. */
  rigid_tail?: number
  gravity_scale: number
  sag_max_deg: number
  spill_max_deg: number
  head_sag: number
  gravity: number
  axis_gain: [number, number, number]
  gain: number
  max_deg: number
  squash: [number, number]
  rest_deg: number
  rest_max_deg: number
  straighten_deg: number
  freetext_clothing_gain: number
  /** Package groups only: the group's effective op (`extension_rig.motion_payload` — `attached_part` where the
   *  mesh part turns an `appendage_chain` into one); what a declared channel's `accepts` is compared with.
   *  Hair groups carry none. */
  op?: string
  /** A HairDeck spring chain (`app/core/hair_motion.py`): its tips collide with `hairChainCapsules`
   *  instead of `extensionCapsules` (module docstring). */
  hair?: boolean
  /** Hair only: per chain joint (the group's bones and its carried, rigid
   *  ones) the body joints today's hair skin rides there, with their shares
   *  (`hair_motion` — the Head / Neck / Spine2 row the server fitted to today's
   *  skin). The joint's swing is put on top of that blend (module docstring,
   *  HAIR CHAINS). */
  anchor_blend?: Record<string, Record<string, number>>
  /** Hair only: the body bone the chain hangs from (Head); its share of a
   *  bone's `anchor_blend` row is how much of the swing that bone shows. */
  anchor_from?: string
}
/** Package metadata profiles are multipliers; runtime groups are already resolved. */
export type MotionAttributeProfiles = Record<string, Record<string, Partial<Pick<MotionGroup,
  'freq_hz' | 'zeta' | 'gravity' | 'gain' | 'max_deg' | 'sag_max_deg' | 'spill_max_deg' | 'head_sag' | 'flatten' | 'stretch' | 'spread' | 'flatten_floor' | 'spill' | 'translate'>>>>
export interface ExtensionRigDeclaration extends Omit<MotionGroup, 'bones' | 'gravity_scale' | 'rest_deg' | 'flatten_floor'> {
  controls?: string[] | null
  flatten_floor: number | null
  id: string
  op: string
  depends_on: string | null
  chains: { bone: string; parent: string }[][]
  params: Record<string, unknown>
  templates?: string[] | "*" | { feature: string } | null
  applies_to: Record<string, unknown[]>
  attribute_profiles?: MotionAttributeProfiles
}
export interface SecondaryMotionPayload {
  rev: string
  groups: Record<string, MotionGroup>
}
export interface SecondaryMotion {
  configure(payload?: SecondaryMotionPayload): void
  /** `partners`: the other figures' capsules and channels this frame (module docstring, PARTNER CAPSULES);
   *  `interaction`: the running pair interaction this figure is in (CHANNELS; null / absent = none). */
  update(realDelta: number, options?: { frozen?: boolean; far?: boolean; partners?: readonly PartnerSnapshot[];
    interaction?: { id: string } | null }): void
  /** The body's `collision` payload the extension tips are kept outside of (module docstring); null = off. */
  setCollision(payload?: CollisionPayload | null): void
  /** The longest driven lever: from a chain's root joint to the tip of one of its links (the sum of the
   *  links' joint-to-tip levers on the way), world metres at the current state `length`; 0 without links. */
  reach(): number
  /** Inspection (checks, debug overlays): every link with contacts — its tip in world space as last
   *  rendered, its bone frame tip, the ids of the own capsules it is kept outside of, and the partner
   *  capsules that pushed it in the last frame (`"<partner>:<capsule id>"`); a link of a chain guided by a
   *  partner's channel (CHANNELS, w > 0) also names it: the channel id, w and the depth scale k applied. */
  contactTips(): { bone: string; tip: Vec3; tipLocal: Vec3; capsules: string[]; partner: string[];
    channel?: { id: string; w: number; k: number } }[]
  /** Ruling A102: per engagement with w > 0, the partner, its channel id, w and the chain's links as world segments
   *  (joint → tip, the link's SURFACE radius — `r_surface` × girth, Ruling A159; links without a capsule left out) as last rendered — what the
   *  receiving figure opens its surface around (`bindChannelOpening`). */
  channelOccupants(): { partner: string; channel: string; w: number; segments: { a: Vec3; b: Vec3; r: number }[] }[]
  /** Ruling A126: every chain with an op (no hair) as last rendered, engaged or not — its links as world segments
   *  (joint → tip, the link's capsule radius r_c, 0 without one), root first. What the auto contact samples. */
  opChains(): { op: string; segments: { a: Vec3; b: Vec3; r: number }[]; raised: number }[]
  /** Ruling A145 (`chainBend.ts`): bend chain `index` of `opChains()` as rendered — per joint (a link index) its turn
   *  q [x, y, z, w] relative to its parent link in world axes, applied root-most first about the joint's world
   *  position; the links past it ride along (skinning reads the bones' world matrices at render). Acts on this
   *  frame's rendered bones only: the next update rebuilds them. */
  bendChain(index: number, turns: readonly { joint: number; q: readonly number[] }[]): void
  reset(): void
  dispose(): void
}

/** Scan steps over the swing budget, then refinement iterations, of a tip's contact turn. */
const CONTACT_SCAN = 12
const CONTACT_REFINE = 14
/** A tip moved less than this (metres) by the push counts as outside. */
const COLLIDE_SLACK = 1e-6
/** The hair chains' push options: the SQUEEZE rule (hair only — extension tips keep the ordinary passes, plan R10). */
const SQUEEZE: PushOptions = { squeeze: true }
/** The regions of a link's OWN extension capsule (one per chain bone, start joint = the link): its radius is the
 *  r_c of the channel guidance (CHANNELS). */
const LINK_REGIONS: readonly string[] = ['chest', 'attached_part', 'appendage']

/** One chain's engagement with one partner channel (module docstring, CHANNELS); kept on the chain's root link. */
interface ChannelState {
  /** `"<partner>:<channel id>"`. */
  key: string
  /** The partner's name (the channel id may itself hold a colon). */
  partner: string
  /** The channel as last seen (world, that update's frame): the release ramp keeps guiding a vanished one. */
  ch: ChannelNow
  /** The update in which the gate last passed (`partnerUpdate`). */
  gate: number
  engaged: boolean
  w: number
  /** The zone of the chain's rendered tips at the end of the last update — this update's engagement step. */
  inZone: boolean
  inGrown: boolean
  leverDeg: number
  /** The depth scale applied in the last update (1 = none). */
  k: number
  /** The partner's contact keys of `ch.suppress` (`"<partner>:<capsule id>"`), and the set they were made from. */
  suppressKeys: string[]
  suppressFrom: ReadonlySet<string> | null
}

/** The turn angle in [0, limit] that takes a tip out of the capsules (`depthAt(angle)` = its depth after that
 *  turn, `depth0` at 0): the first outside angle of a `CONTACT_SCAN` scan, refined by bisection; when no angle
 *  gets out, the shallowest one (null when it is no better than 0). */
function contactAngle(depthAt: (angle: number) => number, depth0: number, limit: number): number | null {
  const step = limit / CONTACT_SCAN
  let inside = 0, outside = -1, best = 0, bestDepth = depth0
  for (let k = 1; k <= CONTACT_SCAN; k++) {
    const depth = depthAt(k * step)
    if (depth < COLLIDE_SLACK) { outside = k * step; break }
    inside = k * step
    if (depth < bestDepth) { best = k * step; bestDepth = depth }
  }
  let angle: number
  if (outside > 0) {
    for (let i = 0; i < CONTACT_REFINE; i++) {
      const mid = (inside + outside) / 2
      if (depthAt(mid) < COLLIDE_SLACK) outside = mid; else inside = mid
    }
    angle = outside
  } else {
    // Shallowest tip: ternary search around the best scan sample.
    let lo = Math.max(0, best - step), hi = Math.min(limit, best + step)
    for (let i = 0; i < CONTACT_REFINE; i++) {
      const m1 = lo + (hi - lo) / 3, m2 = hi - (hi - lo) / 3
      if (depthAt(m1) <= depthAt(m2)) hi = m2; else lo = m1
    }
    angle = (lo + hi) / 2
    const depth = depthAt(angle)
    if (!(depth < depth0)) return null
    if (depth < COLLIDE_SLACK) {
      // An outside window the scan stepped over: its near edge, by bisection from below.
      let below = Math.max(0, best - step)
      for (let i = 0; i < CONTACT_REFINE; i++) {
        const mid = (below + angle) / 2
        if (depthAt(mid) < COLLIDE_SLACK) angle = mid; else below = mid
      }
    }
  }
  return angle
}

/**
 * Which capsules a chain may collide with: every bound capsule whose start
 * joint `a` is NOT one of `ancestors` (normalised names of the bones that
 * carry the chain — its root's ancestors and `anchor_blend` bones — and of
 * its own subtree: the root, its links and any child group below them), and
 * none of a hair-only region (`HAIR_ONLY_REGIONS`, outside the skin) or a
 * partner-only region (`PARTNER_ONLY_REGIONS`, the outer trunk set another
 * figure's contact reads). Pure; payload order is kept.
 */
export function extensionCapsules<T extends { capsule: { a: string; region?: string } }>(bound: readonly T[], ancestors: ReadonlySet<string>): T[] {
  return bound.filter(entry => !ancestors.has(normBoneName(entry.capsule.a))
    && !HAIR_ONLY_REGIONS.includes(entry.capsule.region ?? '')
    && !PARTNER_ONLY_REGIONS.includes(entry.capsule.region ?? ''))
}

/**
 * Which capsules a HAIR chain (`MotionGroup.hair`) may collide with: every
 * bound capsule whose region is in `HAIR_REGIONS` — the set that pushes the
 * hair cards themselves (never the partner-only `outer_trunk`) — in payload
 * order. Ancestors are NOT excluded: the
 * chain hangs from Head, and the head and torso capsules are exactly what it
 * must not swing into. Pure.
 */
export function hairChainCapsules<T extends { capsule: { region?: string } }>(bound: readonly T[]): T[] {
  return bound.filter(entry => HAIR_REGIONS.includes(entry.capsule.region ?? ''))
}

const WITHOUT_HAIR = new WeakMap<SecondaryMotionPayload, SecondaryMotionPayload>()

/**
 * The payload of a figure whose hair runs per strand (strand-hair spec § 6.2.2): every group with `hair: true`
 * dropped — its chains are not solved, the strand sim (`hairSim.ts`) moves the hair — and `rev` suffixed with
 * `:strands`, so a caller comparing revs reconfigures on the switch both ways. The same input object gives the
 * same output object (cached), so a per-frame call allocates nothing. Pure; undefined stays undefined.
 */
export function withoutHairGroups(payload: SecondaryMotionPayload | undefined): SecondaryMotionPayload | undefined {
  if (!payload) return payload
  let out = WITHOUT_HAIR.get(payload)
  if (!out) {
    const groups: Record<string, MotionGroup> = {}
    for (const [id, group] of Object.entries(payload.groups ?? {})) if (!group.hair) groups[id] = group
    out = { ...payload, rev: `${payload.rev}:strands`, groups }
    WITHOUT_HAIR.set(payload, out)
  }
  return out
}

/**
 * The bind rule of one tip: per capsule the factor (0..1] its current radius
 * is multiplied by — `min(1, d0 / r_bind)`, `d0` the tip's distance to the
 * capsule's bind-pose axis. Pure; `tipBind` and the capsules in one frame.
 */
export function tipBindFactors(tipBind: Vec3, capsules: readonly { a: Vec3; b: Vec3; r: number }[]): number[] {
  return capsules.map(c => {
    if (!(c.r > 0)) return 1
    const abx = c.b[0] - c.a[0], aby = c.b[1] - c.a[1], abz = c.b[2] - c.a[2]
    const apx = tipBind[0] - c.a[0], apy = tipBind[1] - c.a[1], apz = tipBind[2] - c.a[2]
    const len2 = abx * abx + aby * aby + abz * abz
    const t = len2 > 1e-12 ? Math.min(1, Math.max(0, (apx * abx + apy * aby + apz * abz) / len2)) : 0
    return Math.min(1, Math.hypot(apx - abx * t, apy - aby * t, apz - abz * t) / c.r)
  })
}

/** Exact propagation around a linearly moving static-equilibrium target.
 * x=p-T', w=v-v_T' gives x''+2*zeta*omega*x'+omega²*x=0.
 * Handle every damping regime without explicit-integrator instability.
 * Inputs are never mutated; the caller has already resolved static gravity.
 */
export function stepSecondaryParticle(
  p: Vector3, v: Vector3, target: Vector3, targetVelocity: Vector3,
  params: MotionGroup, h: number,
  output?: { p: Vector3; v: Vector3; x: Vector3; w: Vector3 },
): { p: Vector3; v: Vector3 } {
  const omega = 2 * Math.PI * params.freq_hz
  const x = (output?.x ?? p.clone()).copy(p).sub(target)
  const w = (output?.w ?? v.clone()).copy(v).sub(targetVelocity)
  const alpha = params.zeta * omega
  let xx: number, xw: number, wx: number, ww: number
  if (omega * omega < 1e-12) {
    xx = ww = 1; xw = h; wx = 0
  } else if (params.zeta > 1) {
    const z = params.zeta + Math.sqrt(params.zeta * params.zeta - 1)
    // Rationalized slow root avoids cancellation for large damping.
    const slow = -omega / z
    const fast = -omega * z
    const eSlow = Math.exp(slow * h), eFast = Math.exp(fast * h)
    const denominator = slow - fast
    xx = (slow * eFast - fast * eSlow) / denominator
    xw = (eSlow - eFast) / denominator
    wx = omega * omega * (eFast - eSlow) / denominator
    ww = (slow * eSlow - fast * eFast) / denominator
  } else {
    const damped = omega * Math.sqrt(1 - params.zeta * params.zeta)
    const decay = Math.exp(-alpha * h)
    const c = Math.cos(damped * h)
    const sh = damped === 0 ? h : Math.sin(damped * h) / damped
    xx = decay * (c + alpha * sh)
    xw = decay * sh
    wx = -omega * omega * xw
    ww = decay * (c - alpha * sh)
  }
  const result = output ?? { p: target.clone(), v: targetVelocity.clone() }
  result.p.copy(target).addScaledVector(targetVelocity, h)
    .addScaledVector(x, xx).addScaledVector(w, xw)
  result.v.copy(targetVelocity).addScaledVector(x, wx).addScaledVector(w, ww)
  return result
}

interface Bind {
  bone: Bone
  local: Matrix4
  centroid: Vector3
  mass: number
  /** Bone-frame point of the bind vertex skinned > 50 % to the bone that reaches farthest along the
   *  centroid lever (the tissue's most protruding point); zero when no vertex qualifies. */
  reach: Vector3
  /** Bone-local axis the extension scale acts along: towards the next chain joint, else the centroid. */
  scaleAxis: Vector3
  centroidWorld: Vector3
  gravityRest: Vector3
  gravityProjection: number
  bodyFront: Vector3
  head: Vector3
  parentHead: Vector3
  worldRotation: Quaternion
  /** World matrix of the bone WITHOUT its own extension scale (set each update). */
  pureWorld: Matrix4
  lateral: Vector3
  singleLateral: Vector3
  centeringRotation: Quaternion
  pairedLateral: Vector3
  auto: boolean
  depth: number
  rotation: Quaternion
  straightenRotation: Quaternion
  localRotation: Quaternion
  /** Inverse bind world matrix, for the anchor blend of other bones. */
  bindWorldInverse: Matrix4
  /** Bones the bone's tissue followed before it was built, with their shares
   *  (glTF extras `anchor_blend`); the rest frame follows their blend instead of
   *  the one parent. Undefined = the parent alone. */
  anchorBlend?: { bind: Bind; share: number }[]
  /** Hair: today's skin row at this bone (`MotionGroup.anchor_blend`), normalised; see HAIR CHAINS. */
  todayBlend?: { bind: Bind; share: number }[]
  /** Hair: the row's share of the bone the chain hangs from (`MotionGroup.anchor_from`). */
  swingShare?: number
  /** Hair scratch of one frame (`frame` = the update it belongs to): rigid rest, final world, bind world. */
  today?: { frame: number; rest: Matrix4; world: Matrix4; bind: Matrix4 }
}
interface Particle {
  bind: Bind
  roots: Bind[]
  chain?: Particle[]
  /** Share of the root chain's dynamic swing budget, from immutable bind spans. */
  motionShare: number
  sag?: { frame: Matrix4; rotation: Quaternion; head: Vector3; centre: Vector3; force: Vector3; torque: Vector3; weight: number; q: Quaternion }
  params: MotionGroup
  paramsFrom: MotionGroup
  paramsTo: MotionGroup
  paramsBlend: number
  staticFrequency: number
  staticFrequencyFrom: number
  staticFrequencyTo: number
  staticWeight: number
  staticWeightFrom: number
  staticWeightTo: number
  p: Vector3 | null
  v: Vector3
  target: Vector3 | null
  rest: number
  restFrom: number
  restTo: number
  blend: number
  straighten: number
  straightenFrom: number
  straightenRestFrom: number
  straightenBlend: number
  straightenThreshold: number
  anchorRotation: Quaternion | null
  /** The link's tip in its bone frame: the next chain joint, else its most protruding own vertex. */
  tipLocal: Vector3
  /** Normalised names of the bones the chain hangs from and of its own subtree (their capsules are excluded). */
  ancestors: Set<string>
  /** The capsules this tip is kept outside of, with the bind-rule radius factor; empty = no contact. */
  contacts: { bound: BoundCapsule; factor: number }[]
  /** The first link of this link's chain (itself for a root): the partner broad phase runs against its joint. */
  chainRoot: Particle | null
  /** Root only: the chain's links, root first (their levers add up to the chain's lever). */
  chainLinks: Particle[]
  /** Root only: the update the partner broad phase below belongs to, and its surviving pool entries (contact key and
   *  world capsule, pool order). */
  partnerFrame: number
  partnerNearKeys: string[]
  partnerNearNows: PartnerCapsule['now'][]
  /** The partner capsules that pushed the tip in the last frame (`"<partner>:<capsule id>"`; PARTNER CAPSULES). */
  partnerPushed: string[]
  /** The turn applied in the last frame while a partner contact held it (degrees; 0 = none), and its axis
   *  (in the frame the turn is expressed in: the anchor frame, or the hair bone's pre-contact world). */
  partnerDeg: number
  partnerAxis: Vector3 | null
  /** The bind radius (metres) of the link's own extension capsule (`LINK_REGIONS`, start joint = the link); 0 = none. */
  linkR: number
  /** Ruling A159: the bind SURFACE radius of that capsule (`r_surface`, at least `linkR`) — what a channel's opening
   *  widens to; 0 = none. */
  linkSurfaceR: number
  /** Root only: the chain's engagements with partner channels (CHANNELS); null = none. */
  channels: ChannelState[] | null
  /** Root only: the body joint the chain hangs from (its scale turns `linkR` into world metres); undefined = not looked up. */
  hangJoint?: JointRef | null
}
/** The shared partner cull's margin (metres) for a chain root's move between the cull and its own broad phase within
 *  one update: only how often the culled list is read depends on it, never what a chain keeps. */
const CULL_MARGIN_M = 0.1
/** The shared partner cull runs for a consumer with at least this many chains. */
const CULL_MIN_CHAINS = 3
/** Maximum transverse compensation: strong flattening must not inflate the mesh. */
const SPREAD_CAP = 1.6
const DEFAULT_AXIS_GAIN: [number, number, number] = [1, 1, 1]
const BLENDED_FIELDS = ['gravity', 'freq_hz', 'zeta', 'gain', 'flatten', 'stretch', 'spread', 'flatten_floor', 'spill', 'translate', 'head_sag', 'length', 'girth'] as const
/** Smooth numeric state changes over the same 1.5 seconds as the rest angle. */
export function blendMotionParams(from: MotionGroup, to: MotionGroup, elapsed: number, output?: MotionGroup): MotionGroup {
  const t = Math.max(0, Math.min(1, elapsed / 1.5))
  const weight = t * t * (3 - 2 * t)
  const result = output ?? { ...to }
  for (const field of BLENDED_FIELDS) {
    const fallback = (field === 'head_sag' || field === 'length' || field === 'girth') ? 1 : field === 'flatten_floor' ? to.squash[0] : field === 'spread' ? 0.5 : 0
    result[field] = (from[field] ?? fallback) + ((to[field] ?? fallback) - (from[field] ?? fallback)) * weight
  }
  return result
}
const centroidCache = new WeakMap<Object3D, { centroid: Vector3; mass: number; reach: Vector3 }[]>()
/** Skin weight above which a vertex counts as the bone's own for its contact tip. */
const REACH_WEIGHT = 0.5
const clamp = (x: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, x))
/** Linear below half the limit, then C1 tanh saturation: monotonic and bounded. */
export const softMotionAngle = (angle: number, limit: number) => {
  if (limit <= 0) return 0
  const knee = limit / 2
  return angle <= knee ? angle : knee + knee * Math.tanh((angle - knee) / knee)
}
const straighteningFraction = (rest: number, threshold: number) => {
  const f = threshold > 0 ? clamp(Math.abs(rest) * 180 / Math.PI / threshold, 0, 1) : 0
  return f * f * (3 - 2 * f)
}
const restAngle = (g: MotionGroup) => clamp(g.rest_deg, -g.rest_max_deg, g.rest_max_deg) * Math.PI / 180

/** Build once while the skeleton is in bind pose, after its up-axis correction.
 * Centroids use ALL positive skin weights, aggregated over every skinned mesh.
 * bindMatrix maps each raw vertex into skeleton bind space; boneInverse maps
 * it into the bone's anchor frame. Imported joint axes are never geometry.
 * Rest axes follow bind-pose attachment geometry; only chain roots rotate.
 * This owns only CPU state and each driven bone's matrixAutoUpdate setting.
 */
export function createSecondaryMotion(
  three: Three, root: Object3D, payload?: SecondaryMotionPayload,
  template?: Object3D,
): SecondaryMotion {
  // A hair group's carried joints (`anchor_blend` rows) count as its bones here.
  const groupBones = (g: MotionGroup) => [...g.bones, ...Object.keys(g.anchor_blend ?? {})].map(normBoneName)
  const names = new Set(Object.values(payload?.groups ?? {}).flatMap(groupBones))
  let matching = false
  if (names.size) root.traverse(o => { if ((o as Bone).isBone && names.has(normBoneName(o.name))) matching = true })
  if (!matching) {
    let delegate: SecondaryMotion | undefined
    let stopped = false
    // Held, not bound: without a driven bone there is nothing to collide (inert).
    let collision: CollisionPayload | null | undefined
    return {
      configure(next) {
        if (stopped) return
        if (delegate) { delegate.configure(next); return }
        const requested = new Set(Object.values(next?.groups ?? {}).flatMap(groupBones))
        let found = false
        if (requested.size) root.traverse(o => { if ((o as Bone).isBone && requested.has(normBoneName(o.name))) found = true })
        if (found) {
          delegate = createSecondaryMotion(three, root, next, template)
          if (collision) delegate.setCollision(collision)
        }
      },
      update(dt, options) { delegate?.update(dt, options) },
      setCollision(payload) {
        if (stopped) return
        collision = payload
        delegate?.setCollision(payload)
      },
      contactTips() { return delegate?.contactTips() ?? [] },
      channelOccupants() { return delegate?.channelOccupants() ?? [] },
      opChains() { return delegate?.opChains() ?? [] },
      bendChain(index, turns) { delegate?.bendChain(index, turns) },
      reach() { return delegate?.reach() ?? 0 },
      reset() { delegate?.reset() },
      dispose() { delegate?.dispose(); stopped = true },
    }
  }
  root.updateWorldMatrix(true, false)
  root.updateMatrixWorld(true)
  const gravity = new three.Vector3(0, -9.81, 0)
  const binds = new Map<Bone, Bind>()
  /** Each bone's boneInverse from a BODY skin (bind frame of the collision capsules) — the bind rule's tip. */
  const boneInverses = new Map<Bone, Matrix4>()
  const sums = new Map<Bone, { sum: Vector3; weight: number }>()
  const bindUp = new three.Vector3(0, 1, 0)
  const cached = template && centroidCache.get(template)
  root.traverse(o => {
    const mesh = o as SkinnedMesh
    if (!mesh.isSkinnedMesh) return
    const pos = mesh.geometry.getAttribute('position')
    const indices = mesh.geometry.getAttribute('skinIndex')
    const weights = mesh.geometry.getAttribute('skinWeight')
    if (!pos || !indices || !weights) return
    const body = !inGarment(mesh)
    mesh.skeleton.bones.forEach((bone, index) => {
      if (body && !boneInverses.has(bone) && mesh.skeleton.boneInverses[index]) boneInverses.set(bone, mesh.skeleton.boneInverses[index])
      if (!binds.has(bone)) {
        const q = bone.getWorldQuaternion(new three.Quaternion()).invert()
        let depth = 0
        for (let parent = bone.parent; parent; parent = parent.parent) depth++
        binds.set(bone, { bone, local: bone.matrix.clone(), centroid: new three.Vector3(), mass: 0, reach: new three.Vector3(), scaleAxis: new three.Vector3(), centroidWorld: new three.Vector3(),
          gravityRest: gravity.clone().applyQuaternion(q), gravityProjection: 0, bodyFront: new three.Vector3(),
          head: bone.getWorldPosition(new three.Vector3()), parentHead: bone.parent!.getWorldPosition(new three.Vector3()), worldRotation: q.clone().invert(), pureWorld: new three.Matrix4(),
          singleLateral: new three.Vector3(), centeringRotation: new three.Quaternion(), lateral: new three.Vector3(), pairedLateral: new three.Vector3(), auto: bone.matrixAutoUpdate, depth, rotation: new three.Quaternion(), straightenRotation: new three.Quaternion(), localRotation: bone.quaternion.clone(),
          bindWorldInverse: bone.matrixWorld.clone().invert() })
      }
    })
    // One pass over four influences per vertex, not one pass per skeleton bone.
    // Each primitive may have its own bind transform and skeleton indexing.
    if (cached) return
    const toBone = mesh.skeleton.boneInverses.map(inv => inv.clone().multiply(mesh.bindMatrix))
    const vertex = new three.Vector3()
    for (let i = 0; i < pos.count; i++) {
      for (let j = 0; j < 4; j++) {
        const weight = weights.getComponent(i, j)
        const index = indices.getComponent(i, j)
        const bone = mesh.skeleton.bones[index]
        if (weight <= 0 || !bone) continue
        const acc = sums.get(bone) ?? { sum: new three.Vector3(), weight: 0 }
        vertex.fromBufferAttribute(pos, i).applyMatrix4(toBone[index])
        acc.sum.addScaledVector(vertex, weight)
        acc.weight += weight
        sums.set(bone, acc)
      }
    }
  })
  for (const [bone, acc] of sums) {
    if (acc.weight > 0) {
      binds.get(bone)!.centroid.copy(acc.sum).divideScalar(acc.weight)
      binds.get(bone)!.mass = acc.weight
    }
  }
  if (!cached) {
    // Second pass, now that the centroids are known: each bone's most protruding own vertex (contact tip).
    const best = new Map<Bone, number>()
    root.traverse(o => {
      const mesh = o as SkinnedMesh
      if (!mesh.isSkinnedMesh) return
      const pos = mesh.geometry.getAttribute('position')
      const indices = mesh.geometry.getAttribute('skinIndex')
      const weights = mesh.geometry.getAttribute('skinWeight')
      if (!pos || !indices || !weights) return
      const toBone = mesh.skeleton.boneInverses.map(inv => inv.clone().multiply(mesh.bindMatrix))
      const vertex = new three.Vector3()
      for (let i = 0; i < pos.count; i++) {
        for (let j = 0; j < 4; j++) {
          if (weights.getComponent(i, j) <= REACH_WEIGHT) continue
          const index = indices.getComponent(i, j)
          const bind = binds.get(mesh.skeleton.bones[index])
          if (!bind || bind.mass <= 0) continue
          vertex.fromBufferAttribute(pos, i).applyMatrix4(toBone[index])
          const along = vertex.dot(bind.centroid)
          if (along > (best.get(bind.bone) ?? -Infinity)) { best.set(bind.bone, along); bind.reach.copy(vertex) }
        }
      }
    })
  }
  if (cached) [...binds.values()].forEach((b, i) => { b.centroid.copy(cached[i].centroid); b.mass = cached[i].mass; b.reach.copy(cached[i].reach) })
  else if (template) centroidCache.set(template, [...binds.values()].map(b => ({ centroid: b.centroid.clone(), mass: b.mass, reach: b.reach.clone() })))
  for (const b of binds.values()) {
    b.centroidWorld.copy(b.centroid).applyMatrix4(b.bone.matrixWorld)
    // Capture the actual bind lever, including non-uniform model scale.
    b.gravityProjection = gravity.dot(b.centroidWorld.clone().sub(b.head).normalize()) / 9.81
  }
  const bindHeads = new Map<Bone, Vector3>()
  root.traverse(o => { if ((o as Bone).isBone) bindHeads.set(o as Bone, o.getWorldPosition(new three.Vector3())) })
  const byName = new Map([...binds.values()].map(b => [normBoneName(b.bone.name), b]))
  // The rigger spread the tissue a built bone takes over across several bones
  // (breast tissue: 22-63 % Spine1, the rest Spine2). Following the one parent
  // alone made it sag with the upper chest in clips that bend it against the
  // lower one; the build measures the shares and stores them on the joint.
  const anchorEntries = (b: Bind, raw: unknown) => {
    if (!raw || typeof raw !== 'object') return undefined
    const entries = Object.entries(raw as Record<string, unknown>)
      .map(([name, share]) => ({ bind: byName.get(normBoneName(name)), share: Number(share) }))
      .filter((e): e is { bind: Bind; share: number } => !!e.bind && e.bind !== b && Number.isFinite(e.share) && e.share > 0)
    const total = entries.reduce((sum, e) => sum + e.share, 0)
    return total > 0 ? entries.map(e => ({ bind: e.bind, share: e.share / total })) : undefined
  }
  for (const b of binds.values()) {
    const blend = anchorEntries(b, (b.bone.userData as { anchor_blend?: unknown } | undefined)?.anchor_blend)
    if (blend) b.anchorBlend = blend
  }
  let particles: Particle[] = []
  /** rigid_tail links, parent first: carried by their parent, never driven. */
  let rigids: Bind[] = []
  /** Hair bones with today's skin row (HAIR CHAINS), parents first. */
  let hairBones: Bind[] = []
  let far = false
  let disposed = false
  let collisionPayload: CollisionPayload | null | undefined
  let collision: CollisionBinding | null = null
  /** Bind the capsules (lazily — only with a driven link) and give each moving tip its contacts. */
  const prepareCollision = () => {
    // Each link's own extension capsule radius (CHANNELS r_c), from the payload — no binding needed.
    for (const st of particles) {
      const name = normBoneName(st.bind.bone.name)
      const own = collisionPayload?.version === COLLISION_VERSION ? collisionPayload.capsules?.find(c =>
        LINK_REGIONS.includes(c.region) && normBoneName(c.a) === name) : undefined
      st.linkR = own && own.r > 0 ? own.r : 0
      st.linkSurfaceR = st.linkR > 0 ? Math.max(st.linkR, own?.r_surface ?? 0) : 0
    }
    if (!collisionPayload || !particles.length) {
      collision = null
      for (const st of particles) st.contacts = []
      return
    }
    collision ??= bindCollision(three, root, collisionPayload)
    const bindTip = new three.Vector3()
    for (const st of particles) {
      st.contacts = []
      const budget = Math.max(st.paramsTo.max_deg ?? 0, st.paramsTo.sag_max_deg ?? 0)
      if (!collision || !(budget > 0)) continue
      const bound = st.paramsTo.hair ? hairChainCapsules(collision.capsules) : extensionCapsules(collision.capsules, st.ancestors)
      const inverse = boneInverses.get(st.bind.bone)
      let factors = bound.map(() => 1)
      if (inverse) {
        // The tip in the BIND frame of the capsules: bone frame → inverse(boneInverse).
        bindTip.copy(st.tipLocal).applyMatrix4(new three.Matrix4().copy(inverse).invert())
        factors = tipBindFactors([bindTip.x, bindTip.y, bindTip.z], bound.map(entry => entry.bind))
      }
      st.contacts = bound.map((entry, i) => ({ bound: entry, factor: factors[i] }))
    }
    if (!particles.some(st => st.contacts.length)) collision = null
  }
  const restore = (b: Bind) => {
    b.bone.matrix.copy(b.local)
    b.bone.matrixAutoUpdate = b.auto
    b.bone.matrixWorldNeedsUpdate = true
  }
  const configure = (next?: SecondaryMotionPayload) => {
    if (disposed) return
    const previous = new Map(particles.map(p => [p.bind.bone, p]))
    const selected = new Set<Bone>()
    const extensionNames = new Set(Object.values(next?.groups ?? {}).flatMap(group =>
      group.bones.map(normBoneName)))
    const nextParticles: Particle[] = []
    const nextRigids: Bind[] = []
    const nextHair: Bind[] = []
    /** Each new particle's chain root bone (the partner broad phase's joint). */
    const rootBinds = new Map<Particle, Bind>()
    for (const b of hairBones) b.todayBlend = undefined
    for (const params of Object.values(next?.groups ?? {})) {
      const chain = params.bones.map(name => byName.get(normBoneName(name)))
      // Absent/partial groups and vertices without influence are ordinary skips.
      if (chain.some(b => !b || b.centroid.lengthSq() < 1e-12)) continue
      const members = new Set((chain as Bind[]).map(b => b.bone))
      const roots = (chain as Bind[]).filter(b => !members.has(b.bone.parent as Bone))
      // A hair chain's bones take today's skin rows from the payload (HAIR CHAINS).
      // A carried joint of the chain (server-side rigid, outside `bones`) has a
      // row too: it rides today's skin without a swing of its own.
      if (params.hair && params.anchor_blend) {
        const from = normBoneName(params.anchor_from ?? '')
        for (const [name, row] of Object.entries(params.anchor_blend)) {
          const b = byName.get(normBoneName(name))
          if (!b || nextHair.includes(b)) continue
          b.todayBlend = anchorEntries(b, row)
          if (!b.todayBlend) continue
          b.swingShare = b.todayBlend.filter(e => normBoneName(e.bind.bone.name) === from).reduce((sum, e) => sum + e.share, 0)
          nextHair.push(b)
        }
      }
      // A hair chain whose every joint is carried sends no bone, only its rows.
      if (!chain.length) continue
      // A link with a successor scales along the axis to that joint, so girth
      // (perpendicular) never pushes the next link off its line; the last link
      // uses its declared bind-frame axis.
      for (const b of chain as Bind[]) {
        const child = (chain as Bind[]).find(c => c.bone.parent === b.bone)
        if (child) b.scaleAxis.setFromMatrixPosition(child.local)
        else if (params.scale_axis === 'bone') b.scaleAxis.set(0, 1, 0)
        else b.scaleAxis.copy(b.centroid)
        if (b.scaleAxis.lengthSq() < 1e-12) b.scaleAxis.copy(b.centroid)
        b.scaleAxis.normalize()
      }
      // Derive front once from immutable bind geometry, never a model axis.
      const meanRoot = new three.Vector3(), meanParent = new three.Vector3(), meanTarget = new three.Vector3()
      for (const b of roots) {
        meanRoot.add(b.head)
        meanParent.add(b.parentHead)
      }
      meanRoot.divideScalar(roots.length); meanParent.divideScalar(roots.length)
      for (const b of chain as Bind[]) meanTarget.add(b.centroidWorld)
      meanTarget.divideScalar(chain.length)
      const front = meanRoot.clone().sub(meanParent)
      front.addScaledVector(bindUp, -front.dot(bindUp))
      if (front.lengthSq() < 1e-10) {
        front.copy(meanTarget).sub(meanRoot)
        front.addScaledVector(bindUp, -front.dot(bindUp))
      }
      front.normalize()
      if (roots.length === 1) {
        // The root may sit off the midline, so front comes from the widest
        // symmetric pair of the parent's other children, not the root offset.
        const parent = roots[0].bone.parent!
        const candidates = parent.children.filter(o => (o as Bone).isBone &&
          o !== roots[0].bone && !extensionNames.has(normBoneName(o.name))) as Bone[]
        const horizontal = (v: Vector3) => v.addScaledVector(bindUp, -v.dot(bindUp))
        let maxDistance = 0, maxSeparation = 0
        const widest = new three.Vector3()
        for (let i = 0; i < candidates.length; i++) {
          const head = bindHeads.get(candidates[i])!
          maxDistance = Math.max(maxDistance, horizontal(head.clone().sub(roots[0].parentHead)).length())
          for (let j = 0; j < i; j++) {
            const separation = horizontal(head.clone().sub(bindHeads.get(candidates[j])!))
            const length = separation.length()
            if (length > maxSeparation) { maxSeparation = length; widest.copy(separation) }
          }
        }
        if (maxSeparation > 1e-4 && maxSeparation >= .25 * maxDistance) {
          const corrected = bindUp.clone().cross(widest.normalize()).normalize()
          const centroidFront = horizontal(meanTarget.clone().sub(roots[0].parentHead))
          const signDirection = centroidFront.length() < 1e-6 ? front : centroidFront.normalize()
          const alignment = corrected.dot(signDirection)
          if (Math.abs(alignment) >= 1e-6) front.copy(alignment > 0 ? corrected : corrected.negate())
        }
      }
      for (const b of chain as Bind[]) {
        b.bodyFront.copy(front)
        if (b.bodyFront.lengthSq() < 1e-10) b.bodyFront.set(0, 0, 1)
        b.bodyFront.applyQuaternion(b.worldRotation.clone().invert())
        // Each link uses its chain root's horizontal bind-pose side direction.
        let chainRoot = b
        for (let n = b.bone.parent; n && members.has(n as Bone); n = n.parent) chainRoot = binds.get(n as Bone)!
        b.pairedLateral.set(0, 0, 0)
        if (roots.length >= 2) {
          b.pairedLateral.copy(chainRoot.head).sub(meanRoot)
          b.pairedLateral.addScaledVector(bindUp, -b.pairedLateral.dot(bindUp)).normalize()
          b.pairedLateral.applyQuaternion(b.worldRotation.clone().invert())
        }
        b.straightenRotation.identity()
        if (!roots.includes(b)) {
          const parent = binds.get(b.bone.parent as Bone)!
          const child = (chain as Bind[]).find(c => c.bone.parent === b.bone)
          const ownLever = child ? child.head.clone().sub(b.head) : b.centroidWorld.clone().sub(b.head)
          const parentLever = b.head.clone().sub(parent.head)
          if (ownLever.lengthSq() > 1e-12 && parentLever.lengthSq() > 1e-12) {
            const inverseBind = b.worldRotation.clone().invert()
            b.straightenRotation.setFromUnitVectors(ownLever.normalize().applyQuaternion(inverseBind),
              parentLever.normalize().applyQuaternion(inverseBind))
          }
        }
        b.lateral.set(0, 0, 0)
        if (!roots.includes(b)) continue
        const child = (chain as Bind[]).find(c => c.bone.parent === b.bone)
        const lever = child ? child.head.clone().sub(b.head) : b.centroidWorld.clone().sub(b.head)
        lever.normalize()
        const toward = front.clone().addScaledVector(lever, -front.dot(lever))
        if (toward.lengthSq() < 1e-10) toward.copy(bindUp).addScaledVector(lever, -bindUp.dot(lever))
        b.lateral.crossVectors(lever, toward).normalize().applyQuaternion(b.worldRotation.clone().invert())
        if (roots.length === 1) {
          const inverseBind = b.worldRotation.clone().invert()
          const axis = front.clone().cross(bindUp).normalize()
          // Match the existing positive raise direction in the sagittal plane.
          if (axis.dot(lever.clone().cross(toward)) < 0) axis.negate()
          const sagittal = lever.clone().addScaledVector(axis, -lever.dot(axis))
          b.singleLateral.copy(axis).applyQuaternion(inverseBind)
          b.centeringRotation.identity()
          if (sagittal.lengthSq() > 1e-12) {
            b.centeringRotation.setFromUnitVectors(lever.clone().applyQuaternion(inverseBind),
              sagittal.normalize().applyQuaternion(inverseBind))
          }
        }
      }
      // Links within rigid_tail of a chain end are carried, not simulated.
      const tail = Math.max(0, Math.floor(params.rigid_tail ?? 0))
      const fromLeaf = (b: Bind): number => {
        const child = (chain as Bind[]).find(c => c.bone.parent === b.bone)
        return child ? 1 + fromLeaf(child) : 0
      }
      for (const bind of chain as Bind[]) {
        if (selected.has(bind.bone)) continue
        if (tail > 0 && !roots.includes(bind) && fromLeaf(bind) < tail) {
          selected.add(bind.bone)
          bind.bone.matrixAutoUpdate = false
          nextRigids.push(bind)
          continue
        }
        selected.add(bind.bone)
        const to = restAngle(params)
        const old = previous.get(bind.bone)
        const particle: Particle = old ?? { bind, roots, motionShare: 1, params, paramsFrom: params, paramsTo: params, paramsBlend: 1.5, p: null, v: new three.Vector3(),
          target: null, anchorRotation: null, rest: to, restFrom: to, restTo: to, blend: 1.5,
          straighten: straighteningFraction(to, params.straighten_deg ?? 0),
          straightenFrom: straighteningFraction(to, params.straighten_deg ?? 0), straightenRestFrom: Math.abs(to),
          straightenBlend: 1.5, straightenThreshold: params.straighten_deg ?? 0,
          staticFrequency: params.freq_hz, staticFrequencyFrom: params.freq_hz, staticFrequencyTo: params.freq_hz,
          staticWeight: (2 * Math.PI * params.freq_hz) ** 2 < 1e-12 ? 0 : 1,
          staticWeightFrom: (2 * Math.PI * params.freq_hz) ** 2 < 1e-12 ? 0 : 1,
          staticWeightTo: (2 * Math.PI * params.freq_hz) ** 2 < 1e-12 ? 0 : 1,
          tipLocal: new three.Vector3(), ancestors: new Set(), contacts: [],
          chainRoot: null, chainLinks: [], partnerFrame: 0, partnerNearKeys: [], partnerNearNows: [], partnerPushed: [], partnerDeg: 0, partnerAxis: null,
          linkR: 0, linkSurfaceR: 0, channels: null }
        if (particle.restTo !== to) {
          particle.restFrom = particle.rest
          particle.restTo = to
          particle.blend = 0
        }
        if (particle.straightenThreshold !== (params.straighten_deg ?? 0)) {
          particle.straightenFrom = particle.straighten
          particle.straightenRestFrom = Math.abs(particle.rest)
          particle.straightenThreshold = params.straighten_deg ?? 0
          particle.straightenBlend = 0
        }
        particle.roots = roots
        // Contact geometry (immutable bind data): the tip, and the bones the chain hangs from.
        const child = (chain as Bind[]).find(c => c.bone.parent === bind.bone)
        if (child) particle.tipLocal.setFromMatrixPosition(child.local)
        else if (bind.reach.lengthSq() > 1e-12) particle.tipLocal.copy(bind.reach)
        else particle.tipLocal.copy(bind.centroid).multiplyScalar(2)
        let chainRoot = bind
        for (let n = bind.bone.parent; n && members.has(n as Bone); n = n.parent) chainRoot = binds.get(n as Bone)!
        rootBinds.set(particle, chainRoot)
        particle.ancestors.clear()
        for (let n = chainRoot.bone.parent; n; n = n.parent) if ((n as Bone).isBone) particle.ancestors.add(normBoneName(n.name))
        for (const blend of [chainRoot.anchorBlend, bind.anchorBlend]) {
          for (const e of blend ?? []) particle.ancestors.add(normBoneName(e.bind.bone.name))
        }
        // Its own chain and what hangs from it (a child group's links): their capsules ride this chain.
        chainRoot.bone.traverse(o => { if ((o as Bone).isBone) particle.ancestors.add(normBoneName(o.name)) })
        if (BLENDED_FIELDS.some(field => particle.paramsTo[field] !== params[field])) {
          particle.paramsFrom = { ...particle.params }
          // Preserve an interrupted static transition's frequency and weight.
          const zero = (2 * Math.PI * params.freq_hz) ** 2 < 1e-12
          particle.staticFrequencyTo = zero ? particle.staticFrequency : params.freq_hz
          particle.staticFrequencyFrom = particle.staticWeight === 0
            ? particle.staticFrequencyTo : particle.staticFrequency
          particle.staticWeightFrom = particle.staticWeight
          particle.staticWeightTo = zero ? 0 : 1
          particle.paramsBlend = 0
        }
        particle.paramsTo = { ...params, bones: [...params.bones], squash: [...params.squash] }
        particle.params = blendMotionParams(particle.paramsFrom, particle.paramsTo, particle.paramsBlend)
        bind.bone.matrixAutoUpdate = false
        nextParticles.push(particle)
      }
    }
    for (const rootParticle of nextParticles.filter(p => p.roots.includes(p.bind))) {
      const chain = nextParticles.filter(p => {
        if (p.roots !== rootParticle.roots) return false
        for (let n: Object3D | null = p.bind.bone; n; n = n.parent) if (n === rootParticle.bind.bone) return true
        return false
      }).sort((a, b) => a.bind.depth - b.bind.depth)
      // The same span convention as sag: joint-to-joint, with twice the
      // centroid lever for the final link. Bind geometry keeps shares fixed
      // through rest, extent and dynamic changes; each root owns its budget.
      const spans = chain.map((st, j) => j + 1 < chain.length
        ? st.bind.head.distanceTo(chain[j + 1].bind.head)
        : 2 * st.bind.centroidWorld.distanceTo(st.bind.head))
      let remaining = 0, sum = 0
      for (let j = chain.length - 1; j >= 0; j--) {
        remaining += spans[j]
        chain[j].motionShare = remaining * remaining * spans[j]
        sum += chain[j].motionShare
      }
      for (const st of chain) {
        st.chain = chain
        st.motionShare = chain.length === 1 ? 1 : sum > 0 ? st.motionShare / sum : 1 / chain.length
        if (chain.length >= 2) st.sag ??= { frame: new three.Matrix4(), rotation: new three.Quaternion(),
          head: new three.Vector3(), centre: new three.Vector3(), force: new three.Vector3(), torque: new three.Vector3(), weight: 0, q: new three.Quaternion() }
      }
    }
    for (const b of nextHair) if (!selected.has(b.bone)) { selected.add(b.bone); b.bone.matrixAutoUpdate = false }
    for (const old of [...particles.map(p => p.bind), ...rigids, ...hairBones]) if (!selected.has(old.bone)) {
      restore(old)
      old.bone.updateWorldMatrix(false, true)
    }
    rigids = nextRigids.sort((a, b) => a.depth - b.depth)
    hairBones = nextHair.sort((a, b) => a.depth - b.depth)
    const drivenBones = new Set(nextParticles.map(st => st.bind.bone))
    const drivenDepth = (st: Particle) => {
      let depth = 0
      for (let parent = st.bind.bone.parent; parent; parent = parent.parent) if (drivenBones.has(parent as Bone)) depth++
      return depth
    }
    particles = nextParticles.sort((a, b) => drivenDepth(a) - drivenDepth(b))
    // Partner broad phase per chain: each link's root particle (itself when its root is not driven), root first.
    const particleOf = new Map(particles.map(st => [st.bind, st]))
    for (const st of particles) { st.chainLinks = []; st.partnerFrame = 0; st.partnerNearKeys = []; st.partnerNearNows = [] }
    for (const st of particles) {
      st.chainRoot = particleOf.get(rootBinds.get(st) ?? st.bind) ?? st
      st.chainRoot.chainLinks.push(st)
      st.hangJoint = undefined
    }
    // A link that stopped being a chain root drops its engagements (a root keeps them across a state change).
    for (const st of particles) if (st.chainRoot !== st) st.channels = null
    prepareCollision()
  }
  const reset = () => {
    for (const st of particles) {
      st.p = null; st.target = null; st.anchorRotation = null; st.v.set(0, 0, 0)
      st.partnerDeg = 0; st.partnerPushed = []
      st.channels = null
    }
    releasing = 0
    channelLive = 0
  }
  /** Links whose last frame held a partner turn (PARTNER CAPSULES): while > 0 the partner path runs on. */
  let releasing = 0
  /** The last update ran the partner path: the first one without it clears the links' partner state. */
  let pairedLast = false
  /** Chain engagements with partner channels alive after the last update (CHANNELS): while > 0 the partner path
   *  runs on, so a release ramps down even when the partner is gone. */
  let channelLive = 0
  /** A chain's lever: the sum of its links' joint-to-tip levers, world metres at the current state `length`
   *  (the scale of the body bone the chain hangs from); `stretch` adds the longitudinal squash maximum. */
  const chainLever = (root: Particle, stretch: boolean) => {
    const scale = root.bind.bone.parent?.matrixWorld.getMaxScaleOnAxis() ?? 1
    let sum = 0
    for (const st of root.chainLinks) {
      sum += st.tipLocal.length() * Math.max(0, st.params.length ?? 1) * (stretch ? Math.max(1, st.params.squash[1]) : 1)
    }
    return sum * scale
  }
  const bendPos = new three.Vector3(), bendOff = new three.Vector3(), bendQ = new three.Quaternion()
  const bendM = new three.Matrix4(), bendW = new three.Matrix4(), bendInv = new three.Matrix4()
  const anchor = new three.Matrix4(), anchorFull = new three.Matrix4(), inverseAnchor = new three.Matrix4(), scale = new three.Matrix4(), rotationMatrix = new three.Matrix4()
  const anchorQ = new three.Quaternion(), restQ = new three.Quaternion(), dynamicQ = new three.Quaternion(), identityQ = new three.Quaternion()
  const restVector = new three.Vector3(), target = new three.Vector3(), head = new three.Vector3(), vTarget = new three.Vector3(), deltaG = new three.Vector3(), t = new three.Vector3(), base = new three.Vector3(), rendered = new three.Vector3(), localRendered = new three.Vector3(), u = new three.Vector3(), temp = new three.Vector3()
  const bodyVertical = new three.Vector3(), dynamicDelta = new three.Vector3(), previousDeviation = new three.Vector3(), nextDeviation = new three.Vector3()
  const headShift = new three.Vector3(), shiftPart = new three.Vector3(), originalLever = new three.Vector3()
  const translationMatrix = new three.Matrix4()
  const lateral = new three.Vector3(), localLateral = new three.Vector3(), staticVector = new three.Vector3(), equilibrium = new three.Vector3()
  const frameQ = new three.Quaternion(), frontLocal = new three.Vector3()
  const integration = { p: new three.Vector3(), v: new three.Vector3(), x: new three.Vector3(), w: new three.Vector3() }
  const centeringQ = new three.Quaternion()
  const chainCentre = new three.Vector3(), chainForce = new three.Vector3()
  const driven = new Map<Bone, Particle>()
  const delta = new three.Matrix4(), localBase = new three.Matrix4()
  const deviation = new three.Matrix4(), todayDelta = new three.Matrix4()
  let hairFrame = 0
  const blendQ = new three.Quaternion(), deltaQ = new three.Quaternion(), firstQ = new three.Quaternion()
  const blendHead = new three.Vector3(), blendPos = new three.Vector3(), blendScale = new three.Vector3()
  const contactLocal = new three.Matrix4(), contactInverse = new three.Matrix4(), contactQ = new three.Quaternion()
  const tipAnchor = new three.Vector3(), tipWorld = new three.Vector3(), lever = new three.Vector3(), contactAxis = new three.Vector3()
  /**
   * Keep a link's tip outside its contact capsules (module docstring). The
   * link's frame `T·R(dynamicQ·restQ)·S` (anchor frame) is evaluated at the
   * tip; the garment push says how deep the tip is (`depthAt` = how far
   * `pushOutOfCapsules` moves it) and which way out. The link turns about its
   * joint (`T`'s origin) in the plane of its lever and that way out, by the
   * SMALLEST angle in (0, limit] that puts the tip outside — a scan of
   * `CONTACT_SCAN` steps, then bisection; when no angle gets it out (a capsule
   * through the tissue's middle) the angle with the shallowest tip. A turn
   * keeps the lever length, so a push along the lever turns nothing.
   */
  const keepTipOutside = (st: Particle, dynamic: Quaternion, rest: Quaternion, limit: number) => {
    if (!(limit > 0)) return
    const capsules: CollideCapsule[] = st.contacts.map(({ bound, factor }) =>
      ({ a: bound.now.a, b: bound.now.b, r: bound.now.r * factor }))
    contactLocal.makeRotationFromQuaternion(contactQ.copy(dynamic).multiply(rest))
      .premultiply(translationMatrix).multiply(scale)
    tipAnchor.copy(st.tipLocal).applyMatrix4(contactLocal)
    tipWorld.copy(tipAnchor).applyMatrix4(anchor)
    const pushed = pushOutOfCapsules([tipWorld.x, tipWorld.y, tipWorld.z], capsules)
    const depth0 = Math.hypot(pushed[0] - tipWorld.x, pushed[1] - tipWorld.y, pushed[2] - tipWorld.z)
    if (depth0 < COLLIDE_SLACK) return
    // The way out, in the anchor frame: the pushed point minus the tip.
    contactInverse.copy(anchor).invert()
    lever.copy(tipAnchor).sub(shiftPart)
    contactAxis.set(pushed[0], pushed[1], pushed[2]).applyMatrix4(contactInverse).sub(tipAnchor)
    contactAxis.crossVectors(lever, contactAxis)
    if (contactAxis.lengthSq() < 1e-20 || lever.lengthSq() < 1e-12) return
    contactAxis.normalize()
    const depthAt = (angle: number) => {
      tipWorld.copy(lever).applyAxisAngle(contactAxis, angle).add(shiftPart).applyMatrix4(anchor)
      const p = pushOutOfCapsules([tipWorld.x, tipWorld.y, tipWorld.z], capsules)
      return Math.hypot(p[0] - tipWorld.x, p[1] - tipWorld.y, p[2] - tipWorld.z)
    }
    const angle = contactAngle(depthAt, depth0, limit)
    if (angle === null) return
    dynamic.premultiply(contactQ.setFromAxisAngle(contactAxis, angle))
  }
  /** A hair bone's contact on today's skin (HAIR CHAINS): its final world is
   *  turned about its own head, the same search as `keepTipOutside`, with the
   *  hair's SQUEEZE push (`garmentCollision.ts`): a tip between two capsules
   *  (a raised upper arm over the chest) reads its depth and way out along
   *  their combined normal, never from the capsule applied last. */
  const keepHairTipOutside = (st: Particle, world: Matrix4, limit: number) => {
    if (!(limit > 0)) return
    const capsules: CollideCapsule[] = st.contacts.map(({ bound, factor }) =>
      ({ a: bound.now.a, b: bound.now.b, r: bound.now.r * factor }))
    head.setFromMatrixPosition(world)
    tipWorld.copy(st.tipLocal).applyMatrix4(world)
    const pushed = pushOutOfCapsules([tipWorld.x, tipWorld.y, tipWorld.z], capsules, 1, undefined, SQUEEZE)
    const depth0 = Math.hypot(pushed[0] - tipWorld.x, pushed[1] - tipWorld.y, pushed[2] - tipWorld.z)
    if (depth0 < COLLIDE_SLACK) return
    lever.copy(tipWorld).sub(head)
    contactAxis.set(pushed[0], pushed[1], pushed[2]).sub(tipWorld)
    contactAxis.crossVectors(lever, contactAxis)
    if (contactAxis.lengthSq() < 1e-20 || lever.lengthSq() < 1e-12) return
    contactAxis.normalize()
    const angle = contactAngle(turn => {
      tipWorld.copy(lever).applyAxisAngle(contactAxis, turn).add(head)
      const p = pushOutOfCapsules([tipWorld.x, tipWorld.y, tipWorld.z], capsules, 1, undefined, SQUEEZE)
      return Math.hypot(p[0] - tipWorld.x, p[1] - tipWorld.y, p[2] - tipWorld.z)
    }, depth0, limit)
    if (angle === null) return
    // world' = T(head) · R · T(-head) · world
    rotationMatrix.makeRotationAxis(contactAxis, angle)
    world.premultiply(translationMatrix.makeTranslation(-head.x, -head.y, -head.z))
      .premultiply(rotationMatrix).premultiply(translationMatrix.makeTranslation(head.x, head.y, head.z))
  }
  // --- partner contact (module docstring, PARTNER CAPSULES) ---
  /** The frame's partner pool per consumer (rebuilt each update with partners), and the update counter. */
  const partnerPool = { hair: createPartnerList(), extension: createPartnerList() }
  let partnerUpdate = 0
  const fillPartnerPool = (partners: readonly PartnerSnapshot[]) => {
    partnerUpdate++
    fillPartnerList(partnerPool.hair, 'hair', partners)
    fillPartnerList(partnerPool.extension, 'extension', partners)
  }
  /**
   * THE SHARED CULL (module docstring, PARTNER CAPSULES): once per consumer and update, at its first chain, the pool
   * is culled against the consumer's reach sphere — centre the mean of its chain roots' joints as they stand now,
   * radius the largest joint distance + chain lever + exit radius, plus `CULL_MARGIN_M` for the joints' own move
   * within the solve. A chain whose root joint and lever lie inside it reads the culled list, any other the whole
   * pool; either way it keeps the same capsules (`cullPartnerList`).
   */
  const partnerCull = {
    hair: { frame: 0, centre: [0, 0, 0] as Vec3, radius: -1, list: createPartnerList() },
    extension: { frame: 0, centre: [0, 0, 0] as Vec3, radius: -1, list: createPartnerList() },
  }
  const cullOf = (consumer: 'hair' | 'extension') => {
    const cull = partnerCull[consumer]
    if (cull.frame === partnerUpdate) return cull
    cull.frame = partnerUpdate
    const c = cull.centre
    let roots = 0
    c[0] = 0; c[1] = 0; c[2] = 0
    for (const st of particles) {
      if (st.chainRoot !== st || (st.paramsTo.hair ? 'hair' : 'extension') !== consumer) continue
      const e = st.bind.bone.matrixWorld.elements
      c[0] += e[12]; c[1] += e[13]; c[2] += e[14]
      roots++
    }
    // One or two chains: the cull would cost what it saves — they read the whole pool.
    if (roots < CULL_MIN_CHAINS) { cull.radius = -1; cull.list.n = 0; return cull }
    c[0] /= roots; c[1] /= roots; c[2] /= roots
    let radius = 0
    for (const st of particles) {
      if (st.chainRoot !== st || (st.paramsTo.hair ? 'hair' : 'extension') !== consumer) continue
      const e = st.bind.bone.matrixWorld.elements
      radius = Math.max(radius, Math.hypot(e[12] - c[0], e[13] - c[1], e[14] - c[2]) + chainLever(st, true) + PARTNER_HYST_M)
    }
    cull.radius = radius + CULL_MARGIN_M
    cullPartnerList(partnerPool[consumer], c, cull.radius, cull.list)
    return cull
  }
  /** `chainPartners` output (indices into the list read) and its scratch. */
  const nearIndex: number[] = [], nearDist: number[] = []
  /** One link's capsules for the pair search: own (bind rule) and partner (full radius, + the exit radius for a
   *  capsule that pushed last frame), the partner keys alongside. The partner entries are reused objects. */
  const pairOwn: CollideCapsule[] = [], pairPartner: CollideCapsule[] = [], pairKeys: string[] = []
  const pairStore: CollideCapsule[] = []
  const pairJoint = new three.Vector3()
  const gatherPair = (st: Particle, own: boolean, joint: Vector3, suppress: ReadonlyMap<string, number> | null = null) => {
    pairOwn.length = 0; pairPartner.length = 0; pairKeys.length = 0
    if (own) for (const { bound, factor } of st.contacts) pairOwn.push({ a: bound.now.a, b: bound.now.b, r: bound.now.r * factor })
    const root = st.chainRoot ?? st
    const consumer = st.paramsTo.hair ? 'hair' : 'extension'
    if (root.partnerFrame !== partnerUpdate) {
      // The broad phase per chain, against its root joint: this link's when it is the root, else the root's
      // bone as already written this update (roots are solved before their links).
      if (root !== st) joint = pairJoint.setFromMatrixPosition(root.bind.bone.matrixWorld)
      root.partnerFrame = partnerUpdate
      root.partnerNearKeys.length = 0
      root.partnerNearNows.length = 0
      const pool = partnerPool[consumer]
      if (pool.n) {
        const at: Vec3 = [joint.x, joint.y, joint.z]
        const lever = chainLever(root, true) + PARTNER_HYST_M
        // The shared cull's list when the chain lies inside its sphere, else the whole pool (the same capsules).
        const cull = cullOf(consumer)
        const inside = cull.radius >= 0
          && Math.hypot(at[0] - cull.centre[0], at[1] - cull.centre[1], at[2] - cull.centre[2]) + lever <= cull.radius
        const list = inside ? cull.list : pool
        // The push takes at most COLLIDE_MAX capsules per list: beyond it the FARTHEST from the root joint drop
        // (`nearestCapsules` order), the survivors keep their pool order.
        const n = chainPartners(list, at, lever, COLLIDE_MAX, nearIndex, nearDist)
        for (let k = 0; k < n; k++) {
          root.partnerNearKeys.push(list.keys[nearIndex[k]])
          root.partnerNearNows.push(list.nows[nearIndex[k]])
        }
      }
    }
    const keys = root.partnerNearKeys, nows = root.partnerNearNows
    for (let k = 0; k < keys.length; k++) {
      const now = nows[k]
      // A channel's `suppress` capsule while the guided tip is inside C (CHANNELS): its radius × (1 − w).
      const keep = suppress === null ? 1 : suppress.get(keys[k]) ?? 1
      if (!(keep > 0)) continue
      const c = pairStore[pairPartner.length] ??= { a: now.a, b: now.b, r: 0 }
      c.a = now.a; c.b = now.b
      c.r = (keep === 1 ? now.r : now.r * keep) + (st.partnerPushed.includes(keys[k]) ? PARTNER_HYST_M : 0)
      pairPartner.push(c)
      pairKeys.push(keys[k])
    }
  }
  /** [own, partner] depth of `tipWorld`: how far each push moves it (the own one with `options`, SQUEEZE for hair). */
  const pairDepth = (options: PushOptions | undefined): [number, number] => {
    const p: Vec3 = [tipWorld.x, tipWorld.y, tipWorld.z]
    const o = pairOwn.length ? pushOutOfCapsules(p, pairOwn, 1, undefined, options) : p
    const q = pairPartner.length ? pushOutOfCapsules(p, pairPartner) : p
    return [Math.hypot(o[0] - p[0], o[1] - p[1], o[2] - p[2]), Math.hypot(q[0] - p[0], q[1] - p[1], q[2] - p[2])]
  }
  /** The way out of `tipWorld`: the partner push first, then the own one on top (the own body has the last word). */
  const pairWayOut = (options: PushOptions | undefined): Vec3 => {
    const p: Vec3 = [tipWorld.x, tipWorld.y, tipWorld.z]
    const q = pairPartner.length ? pushOutOfCapsules(p, pairPartner) : p
    return pairOwn.length ? pushOutOfCapsules(q, pairOwn, 1, undefined, options) : q
  }
  /** The partner keys whose capsule holds `tipWorld` (at its test radius): the capsules that push this frame. The
   *  plain square root rules out a capsule surely farther than r − `COLLIDE_SLACK`; the exact `Math.hypot` decides
   *  every other one (the band is far wider than either's rounding). */
  const pairPushing = (): string[] => {
    const out: string[] = []
    const x = tipWorld.x, y = tipWorld.y, z = tipWorld.z
    for (let i = 0; i < pairPartner.length; i++) {
      const c = pairPartner[i]
      const abx = c.b[0] - c.a[0], aby = c.b[1] - c.a[1], abz = c.b[2] - c.a[2]
      const apx = x - c.a[0], apy = y - c.a[1], apz = z - c.a[2]
      const len2 = abx * abx + aby * aby + abz * abz
      const t = len2 > 1e-12 ? Math.min(1, Math.max(0, (apx * abx + apy * aby + apz * abz) / len2)) : 0
      const dx = apx - abx * t, dy = apy - aby * t, dz = apz - abz * t
      const s = Math.sqrt(dx * dx + dy * dy + dz * dz)
      if (c.r - s < COLLIDE_SLACK - 1e-9 - 1e-9 * s) continue
      if (c.r - Math.hypot(dx, dy, dz) >= COLLIDE_SLACK) out.push(pairKeys[i])
    }
    return out
  }
  /**
   * The pair search of one link (PARTNER CAPSULES), shared by both contact
   * kinds: `tipAt(angle)` puts `tipWorld` at the tip turned by `angle` about
   * `contactAxis` (in the caller's frame), `wayOut()` sets `contactAxis` from
   * the way out at angle 0 (false: no usable axis), `options` is the own push's.
   * Returns the turn to apply (radians; 0 = none) with `contactAxis` set to its
   * axis, and updates the link's hysteresis state; `storeAxis` / `loadAxis`
   * keep the held turn's axis in a frame that rides the body.
   */
  const pairTurn = (st: Particle, limit: number, dt: number, options: PushOptions | undefined,
    tipAt: (angle: number) => void, wayOut: (out: Vec3) => boolean,
    storeAxis: () => void, loadAxis: () => void): number => {
    tipAt(0)
    const depth0 = pairDepth(options)
    const pushed = pairPushing()
    let want = 0, axis = false
    if (depth0[0] >= COLLIDE_SLACK || depth0[1] >= COLLIDE_SLACK) {
      axis = wayOut(pairWayOut(options))
      if (axis) {
        const angle = contactAnglePair(turn => { tipAt(turn); return pairDepth(options) }, depth0, limit)
        if (angle !== null) want = angle
      }
    }
    let applied = want
    const held = Math.min(limit, releasedAngle(st.partnerDeg, want * 180 / Math.PI, dt) * Math.PI / 180)
    if (held > want && (axis || st.partnerAxis)) {
      if (!axis) loadAxis()
      // The own body wins: a held turn may not put the tip deeper into an own capsule than the plain turn does.
      tipAt(want)
      const ownWant = pairOwn.length ? pairDepth(options)[0] : 0
      tipAt(held)
      const ownHeld = pairOwn.length ? pairDepth(options)[0] : 0
      if (ownHeld <= Math.max(ownWant, COLLIDE_SLACK)) { applied = held; axis = true }
    }
    if (applied > 0 && axis) storeAxis()
    st.partnerDeg = pushed.length || applied > want ? applied * 180 / Math.PI : 0
    st.partnerPushed = pushed
    return axis ? applied : 0
  }
  /** `keepTipOutside` with the partners (PARTNER CAPSULES): the same frame and turn, the pair search. */
  const keepTipOutsidePair = (st: Particle, dynamic: Quaternion, rest: Quaternion, limit: number, dt: number,
    own: boolean, suppress: ReadonlyMap<string, number> | null = null) => {
    if (!(limit > 0)) { st.partnerDeg = 0; st.partnerPushed = []; return }
    gatherPair(st, own, pairJoint.setFromMatrixPosition(anchor), suppress)
    if (!pairPartner.length && st.partnerDeg === 0) {
      st.partnerPushed = []
      if (own && st.contacts.length) keepTipOutside(st, dynamic, rest, limit)
      return
    }
    contactLocal.makeRotationFromQuaternion(contactQ.copy(dynamic).multiply(rest))
      .premultiply(translationMatrix).multiply(scale)
    tipAnchor.copy(st.tipLocal).applyMatrix4(contactLocal)
    lever.copy(tipAnchor).sub(shiftPart)
    contactInverse.copy(anchor).invert()
    const angle = pairTurn(st, limit, dt, undefined,
      turn => { tipWorld.copy(lever).applyAxisAngle(contactAxis, turn).add(shiftPart).applyMatrix4(anchor) },
      out => {
        // The way out, in the anchor frame: the pushed point minus the tip.
        contactAxis.set(out[0], out[1], out[2]).applyMatrix4(contactInverse).sub(tipAnchor)
        contactAxis.crossVectors(lever, contactAxis)
        if (contactAxis.lengthSq() < 1e-20 || lever.lengthSq() < 1e-12) return false
        contactAxis.normalize()
        return true
      },
      () => { (st.partnerAxis ??= new three.Vector3()).copy(contactAxis) },
      () => { contactAxis.copy(st.partnerAxis!) })
    if (angle > 0) dynamic.premultiply(contactQ.setFromAxisAngle(contactAxis, angle))
  }
  /** `keepHairTipOutside` with the partners: the turn about the bone's head in world space; the held axis is
   *  kept in the bone's pre-contact world frame. */
  const keepHairTipOutsidePair = (st: Particle, world: Matrix4, limit: number, dt: number, own: boolean) => {
    if (!(limit > 0)) { st.partnerDeg = 0; st.partnerPushed = []; return }
    head.setFromMatrixPosition(world)
    gatherPair(st, own, head)
    if (!pairPartner.length && st.partnerDeg === 0) {
      st.partnerPushed = []
      if (own && st.contacts.length) keepHairTipOutside(st, world, limit)
      return
    }
    tipWorld.copy(st.tipLocal).applyMatrix4(world)
    lever.copy(tipWorld).sub(head)
    const angle = pairTurn(st, limit, dt, SQUEEZE,
      turn => { tipWorld.copy(lever).applyAxisAngle(contactAxis, turn).add(head) },
      out => {
        tipWorld.copy(lever).add(head)
        contactAxis.set(out[0], out[1], out[2]).sub(tipWorld)
        contactAxis.crossVectors(lever, contactAxis)
        if (contactAxis.lengthSq() < 1e-20 || lever.lengthSq() < 1e-12) return false
        contactAxis.normalize()
        return true
      },
      () => { (st.partnerAxis ??= new three.Vector3()).copy(contactAxis).transformDirection(contactInverse.copy(world).invert()) },
      () => { contactAxis.copy(st.partnerAxis!).transformDirection(world) })
    if (!(angle > 0)) return
    rotationMatrix.makeRotationAxis(contactAxis, angle)
    world.premultiply(translationMatrix.makeTranslation(-head.x, -head.y, -head.z))
      .premultiply(rotationMatrix).premultiply(translationMatrix.makeTranslation(head.x, head.y, head.z))
  }
  // --- declared channels (module docstring, CHANNELS) ---
  /** The figure's body joints by name (looked up once, for the joint a chain hangs from). */
  let channelJoints: Map<string, JointRef> | null = null
  /** r_c of a link: its own extension capsule radius in world metres (the scale of the body joint its chain hangs
   *  from, as a capsule radius scales) × the state girth; 0 without such a capsule. `surface`: its SURFACE radius instead (Ruling A159). */
  const linkRadius = (st: Particle, chain: Particle, surface = false): number => {
    if (!(st.linkR > 0)) return 0
    if (chain.hangJoint === undefined) {
      const parent = chain.bind.bone.parent
      channelJoints ??= bodyJoints(root)
      chain.hangJoint = parent ? channelJoints.get(normBoneName(parent.name)) ?? null : null
    }
    const world = chain.hangJoint ? linearScale(jointRefNow(chain.hangJoint).bindToWorld) : 1
    return (surface ? st.linkSurfaceR : st.linkR) * world * Math.max(0, st.params.girth ?? 1)
  }
  /**
   * ENGAGEMENT, once per update before the solve (CHANNELS): per chain root with an op and per partner channel
   * whose gate passes, its state (made on first sight); then every state of the chain steps (`stepEngagement`) on
   * the zone its tips had at the end of the last update — a state whose gate failed releases. A state is dropped once
   * it is released, at w = 0 and without a passing gate. Sets `channelLive`.
   */
  const stepChannels = (partners: readonly PartnerSnapshot[], interaction: { id: string } | null, dt: number) => {
    const reader = { interaction }
    let live = 0
    for (const chain of particles) {
      if (chain.chainRoot !== chain) continue
      const op = chain.paramsTo.op
      if (op && !chain.paramsTo.hair) {
        for (const snap of partners) {
          if (!snap.channels?.length) continue
          for (const ch of snap.channels) {
            if (!channelGate({ op, length: chain.params.length ?? 1 }, ch, reader, snap)) continue
            const key = `${snap.name}:${ch.id}`
            const states = chain.channels ??= []
            let state = states.find(x => x.key === key)
            if (!state) {
              state = { key, partner: snap.name, ch, gate: 0, engaged: false, w: 0, inZone: false, inGrown: false, leverDeg: Infinity, k: 1,
                suppressKeys: [], suppressFrom: null }
              states.push(state)
            }
            state.ch = ch
            state.gate = partnerUpdate
            if (state.suppressFrom !== ch.suppress) {
              state.suppressKeys = [...ch.suppress].map(id => `${snap.name}:${id}`)
              state.suppressFrom = ch.suppress
            }
          }
        }
      }
      const states = chain.channels
      if (!states) continue
      for (let i = states.length - 1; i >= 0; i--) {
        const state = states[i]
        const gate = state.gate === partnerUpdate
        const next = stepEngagement(state, { gate, tipInZone: state.inZone, tipInGrownZone: state.inGrown,
          leverAngleDeg: state.leverDeg }, state.ch, dt)
        state.engaged = next.engaged
        state.w = next.w
        if (!gate && !next.engaged && !(next.w > 0)) states.splice(i, 1)
      }
      if (!states.length) chain.channels = null
      else live += states.length
    }
    channelLive = live
  }
  const guideJoint = new three.Vector3(), guideAxis = new three.Vector3()
  /** The partner keys a link skips this update (CHANNELS), with the factor their radius keeps (1 − w). */
  const suppressNow = new Map<string, number>()
  /** The world tip and joint of a link from its anchor-frame rotation (the frame `keepTipOutside` reads). */
  const linkTipWorld = (st: Particle, dynamic: Quaternion, rest: Quaternion) => {
    contactLocal.makeRotationFromQuaternion(contactQ.copy(dynamic).multiply(rest))
      .premultiply(translationMatrix).multiply(scale)
    tipWorld.copy(st.tipLocal).applyMatrix4(contactLocal).applyMatrix4(anchor)
  }
  /**
   * RADIAL GUIDANCE of one link, after its dynamics (CHANNELS): per engagement of its chain with w > 0, the turn of
   * `radialGuidanceAngle` × w, capped by `limit`, about the link's joint (in the anchor frame, onto `dynamic`); then,
   * where the guided tip lies inside C, that partner's `suppress` keys with the factor 1 − w. Returns the keys
   * (null: none).
   */
  const guideLink = (st: Particle, chain: Particle, dynamic: Quaternion, rest: Quaternion,
    limit: number): ReadonlyMap<string, number> | null => {
    suppressNow.clear()
    let rC = -1
    for (const state of chain.channels!) {
      if (!(state.w > 0)) continue
      const ch = state.ch
      if (rC < 0) rC = linkRadius(st, chain)
      linkTipWorld(st, dynamic, rest)
      if (limit > 0) {
        guideJoint.copy(shiftPart).applyMatrix4(anchor)
        const guide = radialGuidanceAngle([guideJoint.x, guideJoint.y, guideJoint.z],
          [tipWorld.x, tipWorld.y, tipWorld.z], ch, rC)
        const turn = guide ? Math.min(guide.angle * state.w, limit) : 0
        if (guide && turn > 0) {
          // A world turn about the joint is, in the anchor frame (rotation × uniform scale), the same turn about
          // the axis carried back.
          guideAxis.set(guide.axis[0], guide.axis[1], guide.axis[2]).transformDirection(contactInverse.copy(anchor).invert())
          dynamic.premultiply(contactQ.setFromAxisAngle(guideAxis, turn))
          linkTipWorld(st, dynamic, rest)
        }
      }
      const { s, rho } = channelCoords([tipWorld.x, tipWorld.y, tipWorld.z], ch)
      if (inZone(s, rho, ch) === 'cylinder') {
        for (const key of state.suppressKeys) suppressNow.set(key, Math.min(suppressNow.get(key) ?? 1, 1 - state.w))
      }
    }
    return suppressNow.size ? suppressNow : null
  }
  const chainHead = new three.Vector3(), chainFirst = new three.Vector3(), chainTip = new three.Vector3()
  /** The axial positions of a chain's link joints (`depthJoint`'s input; reused). */
  const depthS: number[] = []
  const depthAxis = new three.Vector3(), depthMatrix = new three.Matrix4(), parentInverse = new three.Matrix4()
  /** Is `bone` `top` or below it? */
  const below = (bone: Object3D, top: Object3D) => {
    for (let n: Object3D | null = bone; n; n = n.parent) if (n === top) return true
    return false
  }
  /**
   * After a chain's last link (CHANNELS): per engagement with w > 0 the DEPTH SCALE — s_tip the last link's tip,
   * s_e the link joint `depthJoint` picks (the first at s ≥ 0, else the one nearest before the opening),
   * k = `depthScale` blended 1 → k by w — shortens the levers of that link and the links below it along their tips, about its joint: each joint moves to h_e + k (h − h_e), each lever is scaled by
   * k along its tip direction, and the bones are re-published (world, pure world and local matrix). Then the zone of
   * every engagement's channel for the next update's step: any link tip in Φ ∪ C (with the smallest lever angle to
   * u among those) and any in the grown zone.
   */
  const finishChain = (chain: Particle) => {
    const links = chain.chainLinks
    const last = links[links.length - 1]
    for (const state of chain.channels!) {
      state.k = 1
      if (!(state.w > 0)) continue
      const ch = state.ch
      const sOf = (p: Vector3) => (p.x - ch.o[0]) * ch.u[0] + (p.y - ch.o[1]) * ch.u[1] + (p.z - ch.o[2]) * ch.u[2]
      depthS.length = links.length
      for (let j = 0; j < links.length; j++) depthS[j] = sOf(chainHead.setFromMatrixPosition(links[j].bind.bone.matrixWorld))
      const first = depthJoint(depthS)
      if (first < 0) continue
      const top = links[first].bind.bone
      chainFirst.setFromMatrixPosition(top.matrixWorld)
      const sTip = sOf(chainTip.copy(last.tipLocal).applyMatrix4(last.bind.bone.matrixWorld))
      const k = depthScale(sTip, sOf(chainFirst), ch, linkRadius(last, chain))
      const kEff = 1 + state.w * (k - 1)
      if (!(kEff < 1)) continue
      state.k = kEff
      for (let j = first; j < links.length; j++) {
        const link = links[j], bone = link.bind.bone
        if (j > first && !below(bone, top)) continue
        const world = bone.matrixWorld
        chainHead.setFromMatrixPosition(world).sub(chainFirst).multiplyScalar(kEff).add(chainFirst)
        // k along the tip direction in the bone frame: I + (k − 1) a aᵀ.
        depthAxis.copy(link.tipLocal).normalize()
        const a = depthAxis
        depthMatrix.set(
          1 + (kEff - 1) * a.x * a.x, (kEff - 1) * a.x * a.y, (kEff - 1) * a.x * a.z, 0,
          (kEff - 1) * a.y * a.x, 1 + (kEff - 1) * a.y * a.y, (kEff - 1) * a.y * a.z, 0,
          (kEff - 1) * a.z * a.x, (kEff - 1) * a.z * a.y, 1 + (kEff - 1) * a.z * a.z, 0,
          0, 0, 0, 1)
        world.multiply(depthMatrix).setPosition(chainHead)
        link.bind.pureWorld.setPosition(chainHead)
        bone.matrix.copy(parentInverse.copy(bone.parent!.matrixWorld).invert()).multiply(world)
        bone.matrixWorldNeedsUpdate = true
      }
    }
    for (const state of chain.channels!) {
      const ch = state.ch
      let tipIn = false, tipGrown = false, lever = Infinity
      for (const link of links) {
        const world = link.bind.bone.matrixWorld
        chainHead.setFromMatrixPosition(world)
        chainTip.copy(link.tipLocal).applyMatrix4(world)
        const { s, rho } = channelCoords([chainTip.x, chainTip.y, chainTip.z], ch)
        if (inZone(s, rho, ch, CHANNEL_GROW)) tipGrown = true
        if (!inZone(s, rho, ch)) continue
        tipIn = true
        chainTip.sub(chainHead)
        const len = chainTip.length()
        if (len > 1e-12) {
          const cos = (chainTip.x * ch.u[0] + chainTip.y * ch.u[1] + chainTip.z * ch.u[2]) / len
          lever = Math.min(lever, Math.acos(Math.max(-1, Math.min(1, cos))) * 180 / Math.PI)
        }
      }
      state.inZone = tipIn
      state.inGrown = tipGrown
      state.leverDeg = lever
    }
  }
  /** The engagement a link's `contactTips` row names: the one of its chain with the largest w > 0. */
  const channelRow = (st: Particle): { id: string; w: number; k: number } | null => {
    let best: ChannelState | null = null
    for (const state of st.chainRoot?.channels ?? []) if (state.w > 0 && (!best || state.w > best.w)) best = state
    return best ? { id: best.ch.id, w: best.w, k: best.k } : null
  }
  /** Rest frame at the blend of the anchor bones' motions since bind: the bind
   *  head moved as linear skinning moved the tissue (sum of share x delta x head),
   *  the rotation is the normalised share-weighted sum of their delta rotations.
   *  At bind every delta is identity, so bind values are unchanged. */
  const blendAnchor = (b: Bind) => {
    blendQ.set(0, 0, 0, 0); blendHead.set(0, 0, 0)
    b.anchorBlend!.forEach(({ bind: x, share }, i) => {
      delta.copy(x.bone.matrixWorld).multiply(x.bindWorldInverse)
      blendHead.addScaledVector(temp.copy(b.head).applyMatrix4(delta), share)
      delta.decompose(blendPos, deltaQ, blendScale)
      if (i === 0) firstQ.copy(deltaQ)
      else if (firstQ.dot(deltaQ) < 0) deltaQ.set(-deltaQ.x, -deltaQ.y, -deltaQ.z, -deltaQ.w)
      blendQ.set(blendQ.x + share * deltaQ.x, blendQ.y + share * deltaQ.y, blendQ.z + share * deltaQ.z, blendQ.w + share * deltaQ.w)
    })
    blendQ.normalize()
    anchorQ.copy(blendQ).multiply(b.worldRotation)
    anchor.decompose(blendPos, deltaQ, blendScale)
    anchor.compose(blendHead, anchorQ, blendScale)
    anchorFull.copy(anchor)
  }
  const pureParent = (node: Object3D | null): Quaternion => {
    anchorQ.identity()
    // Multiply local rotations from leaf toward root, replacing driven transforms.
    for (let n = node; n; n = n.parent) {
      const parent = driven.get(n as Bone)
      if (parent) return anchorQ.premultiply(parent.bind.rotation)
      anchorQ.premultiply(n.quaternion)
    }
    return anchorQ
  }
  configure(payload)
  return {
    configure, reset,
    setCollision(next) {
      if (disposed) return
      collisionPayload = next
      collision = null
      prepareCollision()
    },
    channelOccupants() {
      const rows: ReturnType<SecondaryMotion['channelOccupants']> = []
      if (!(channelLive > 0)) return rows
      const head = new three.Vector3(), tip = new three.Vector3()
      for (const chain of particles) {
        if (chain.chainRoot !== chain || !chain.channels) continue
        for (const state of chain.channels) {
          if (!(state.w > 0)) continue
          const segments: { a: Vec3; b: Vec3; r: number }[] = []
          for (const link of chain.chainLinks) {
            // Ruling A159: the opening widens to the part's SURFACE radius (× the state girth), not its contact core.
            const r = linkRadius(link, chain, true)
            if (!(r > 0)) continue
            head.setFromMatrixPosition(link.bind.bone.matrixWorld)
            tip.copy(link.tipLocal).applyMatrix4(link.bind.bone.matrixWorld)
            segments.push({ a: [head.x, head.y, head.z], b: [tip.x, tip.y, tip.z], r })
          }
          if (segments.length) rows.push({ partner: state.partner, channel: state.ch.id, w: state.w, segments })
        }
      }
      return rows
    },
    opChains() {
      const rows: ReturnType<SecondaryMotion['opChains']> = []
      const head = new three.Vector3(), tip = new three.Vector3()
      for (const chain of particles) {
        const op = chain.paramsTo.op
        if (chain.chainRoot !== chain || !op || chain.paramsTo.hair) continue
        const segments: { a: Vec3; b: Vec3; r: number }[] = []
        for (const link of chain.chainLinks) {
          head.setFromMatrixPosition(link.bind.bone.matrixWorld)
          tip.copy(link.tipLocal).applyMatrix4(link.bind.bone.matrixWorld)
          segments.push({ a: [head.x, head.y, head.z], b: [tip.x, tip.y, tip.z], r: Math.max(0, linkRadius(link, chain) || 0) })
        }
        // Ruling A145: the raised state = the chain's straightening fraction.
        if (segments.length) rows.push({ op, segments, raised: chain.straighten })
      }
      return rows
    },
    bendChain(index, turns) {
      let k = -1
      for (const chain of particles) {
        const op = chain.paramsTo.op
        if (chain.chainRoot !== chain || !op || chain.paramsTo.hair || !chain.chainLinks.length) continue
        if (++k !== index) continue
        const order = [...turns].sort((x, y) => x.joint - y.joint)
        for (const t of order) {
          const link = chain.chainLinks[t.joint]
          if (!link || !(Math.abs(t.q[3]) < 1 - 1e-12)) continue
          const bone = link.bind.bone
          const p = bendPos.setFromMatrixPosition(bone.matrixWorld)
          bendQ.set(t.q[0], t.q[1], t.q[2], t.q[3])
          // newWorld = T(p) R T(−p) · world;  local = parentWorld⁻¹ · newWorld.
          bendM.makeRotationFromQuaternion(bendQ)
          bendM.setPosition(bendOff.copy(p).applyQuaternion(bendQ).negate().add(p))
          bendW.multiplyMatrices(bendM, bone.matrixWorld)
          if (bone.parent) bendInv.copy(bone.parent.matrixWorld).invert()
          else bendInv.identity()
          bone.matrix.multiplyMatrices(bendInv, bendW)
          bone.matrix.decompose(bone.position, bone.quaternion, bone.scale)
          bone.updateMatrixWorld(true)
        }
        return
      }
    },
    contactTips() {
      const tip = new three.Vector3()
      const rows: ReturnType<SecondaryMotion['contactTips']> = []
      for (const st of particles) {
        const channel = channelLive > 0 ? channelRow(st) : null
        if (!(st.contacts.length || st.partnerPushed.length || st.partnerDeg > 0 || channel)) continue
        tip.copy(st.tipLocal).applyMatrix4(st.bind.bone.matrixWorld)
        rows.push({ bone: st.bind.bone.name, tip: [tip.x, tip.y, tip.z] as Vec3,
          tipLocal: [st.tipLocal.x, st.tipLocal.y, st.tipLocal.z] as Vec3,
          capsules: st.contacts.map(c => c.bound.capsule.id), partner: [...st.partnerPushed],
          ...(channel ? { channel } : {}) })
      }
      return rows
    },
    reach() {
      let longest = 0
      for (const st of particles) if (st.chainRoot === st) longest = Math.max(longest, chainLever(st, false))
      return longest
    },
    update(realDelta, options = {}) {
      if (disposed || (!particles.length && !hairBones.length)) return
      const dt = Number.isFinite(realDelta) ? Math.max(0, realDelta) : 0
      if (!!options.far !== far) { far = !!options.far; reset() }
      root.updateWorldMatrix(true, false)
      root.updateMatrixWorld(true)
      // Capsules ride body joints no extension link drives: read them once, before the links.
      const colliding = !!collision && !far
      if (colliding) collision!.update()
      // Partner contact (PARTNER CAPSULES): with partners, or while a held turn is still releasing.
      const partners = options.partners
      const pairing = !far && (!!partners?.length || releasing > 0 || channelLive > 0)
      if (pairing) fillPartnerPool(partners ?? [])
      else if (pairedLast) for (const st of particles) { st.partnerPushed = []; st.partnerDeg = 0 }
      pairedLast = pairing
      // Channels (CHANNELS): only when a partner brings one, or an engagement is still alive.
      let channeling = false
      if (pairing) {
        if (channelLive > 0) channeling = true
        else for (const snap of partners ?? []) if (snap.channels?.length) { channeling = true; break }
      }
      driven.clear()
      // A carried hair joint is at its rigid rest for the solve (HAIR CHAINS).
      for (const b of hairBones) b.bone.matrix.copy(b.local)
      for (const st of particles) {
        st.paramsBlend = Math.min(1.5, st.paramsBlend + dt)
        st.params = blendMotionParams(st.paramsFrom, st.paramsTo, st.paramsBlend, st.params)
        // Rest blending is real time, including far LOD. Freeze stops dynamics.
        st.blend = Math.min(1.5, st.blend + dt)
        const fraction = st.blend / 1.5
        const limit = st.params.rest_max_deg * Math.PI / 180
        st.rest = clamp(st.restFrom + (st.restTo - st.restFrom) * fraction * fraction * (3 - 2 * fraction), -limit, limit)
        // Blend the derived amount: interpolating a threshold through zero
        // would snap raised chains fully straight on their first frame.
        st.straightenBlend = Math.min(1.5, st.straightenBlend + dt)
        const straightT = st.straightenBlend / 1.5
        const straightWeight = straightT * straightT * (3 - 2 * straightT)
        const straightTarget = straighteningFraction(st.rest, st.straightenThreshold)
        // The carried amount must also vanish smoothly when a simultaneous
        // rest transition passes through zero, including signed changes.
        const carried = st.straightenFrom * straighteningFraction(st.rest, st.straightenRestFrom * 180 / Math.PI)
        st.straighten = carried + (straightTarget - carried) * straightWeight
      }
      if (channeling) stepChannels(partners ?? [], options.interaction ?? null, dt)
      for (const st of particles) {
        const b = st.bind
        const motionLimit = st.params.max_deg * st.motionShare * Math.PI / 180
        anchor.copy(b.local)
        anchorFull.copy(b.local)
        // A driven ancestor contributes its frame WITHOUT its own extension
        // scale (otherwise girth/length/squash compound down a chain), while
        // the position follows the fully deformed ancestor so a lengthened
        // parent still carries its child outward.
        let drivenAncestor = false
        for (let n = b.bone.parent; n; n = n.parent) {
          const ancestor = driven.get(n as Bone)
          if (ancestor) { anchor.premultiply(ancestor.bind.pureWorld); anchorFull.premultiply(n.matrixWorld); drivenAncestor = true; break }
          anchor.premultiply(n.matrix); anchorFull.premultiply(n.matrix)
        }
        if (drivenAncestor) anchor.setPosition(temp.setFromMatrixPosition(anchorFull))
        pureParent(b.bone.parent).multiply(b.localRotation)
        const blended = !drivenAncestor && !!b.anchorBlend
        if (blended) blendAnchor(b)
        if (st.roots.length === 1 && st.roots[0] === b && b.singleLateral.lengthSq() > 1e-12) {
          centeringQ.identity().slerp(b.centeringRotation, st.straighten)
          restQ.setFromAxisAngle(b.singleLateral, st.rest).multiply(centeringQ)
        }
        else if (st.roots.includes(b) && b.lateral.lengthSq() > 1e-12) restQ.setFromAxisAngle(b.lateral, st.rest)
        else {
          restQ.identity().slerp(b.straightenRotation, st.straighten)
        }
        if (st.chain && st.chain.length >= 2 && st.chain[0] === st) {
          const chain = st.chain
          let mass = 0
          const centre = chainCentre.set(0, 0, 0), force = chainForce.set(0, 0, 0)
          for (const link of chain) {
            const data = link.sag!, bind = link.bind
            const parent = chain.find(p => p.bind.bone === bind.bone.parent)
            if (parent) {
              data.frame.copy(parent.sag!.frame).multiply(bind.local)
              data.rotation.copy(parent.sag!.rotation).multiply(bind.localRotation)
            } else { data.frame.copy(anchor); data.rotation.copy(anchorQ) }
            if (link === st) data.q.copy(restQ)
            else data.q.identity().slerp(bind.straightenRotation, link.straighten)
            data.head.setFromMatrixPosition(data.frame)
            data.centre.copy(bind.centroid).applyQuaternion(data.q).applyMatrix4(data.frame)
            u.copy(data.centre).sub(data.head).normalize()
            data.force.copy(gravity).multiplyScalar(link.params.gravity_scale ?? 1)
              .sub(temp.copy(bind.gravityRest).applyQuaternion(data.q).applyQuaternion(data.rotation)).multiplyScalar(link.params.gravity)
            const axial = data.force.dot(u)
            if (axial < 0) data.force.addScaledVector(u, -axial)
            centre.addScaledVector(data.centre, bind.mass); force.addScaledVector(data.force, bind.mass); mass += bind.mass
            rotationMatrix.makeRotationFromQuaternion(data.q)
            data.frame.multiply(rotationMatrix); data.rotation.multiply(data.q)
          }
          originalLever.copy(centre).divideScalar(mass).sub(head.setFromMatrixPosition(anchor))
          const staticT = clamp(st.paramsBlend / 1.5, 0, 1)
          const staticBlend = staticT * staticT * (3 - 2 * staticT)
          const frequency = st.staticFrequencyFrom + (st.staticFrequencyTo - st.staticFrequencyFrom) * staticBlend
          const omegaSquared = (2 * Math.PI * frequency) ** 2
          equilibrium.copy(force).divideScalar(mass).multiplyScalar(omegaSquared >= 1e-12 ? 1 / omegaSquared : 0)
          const total = Math.min(originalLever.angleTo(temp.copy(originalLever).add(equilibrium)),
            (st.params.sag_max_deg ?? st.params.max_deg) * Math.PI / 180)
          let sum = 0
          // Torques are evaluated on the unsagged configuration (small-angle
          // approximation); this keeps total droop independent of link count
          // and puts the largest bend at the root.
          for (let j = 0; j < chain.length; j++) {
            const data = chain[j].sag!
            data.torque.set(0, 0, 0)
            for (let i = j; i < chain.length; i++) {
              const distal = chain[i]
              data.torque.addScaledVector(temp.copy(distal.sag!.centre).sub(data.head).cross(distal.sag!.force), distal.bind.mass)
            }
            const span = j + 1 < chain.length ? data.head.distanceTo(chain[j + 1].sag!.head) : 2 * data.centre.distanceTo(data.head)
            data.weight = data.torque.length() * span; sum += data.weight
          }
          for (const link of chain) {
            const data = link.sag!
            data.q.identity()
            if (sum > 1e-12) data.q.setFromAxisAngle(data.torque.normalize(), total * data.weight / sum)
          }
        }
        restVector.copy(b.centroid).applyQuaternion(restQ)
        target.copy(restVector).applyMatrix4(anchor)
        head.setFromMatrixPosition(anchor)
        // Static gravity acts against the baked bind gravity, before dynamics.
        u.copy(target).sub(head).normalize()
        lateral.set(0, 0, 0)
        if (st.roots.length >= 2) {
          lateral.copy(b.pairedLateral).applyQuaternion(anchorQ)
          lateral.addScaledVector(u, -lateral.dot(u)).normalize()
        }
        deltaG.copy(gravity).multiplyScalar(st.params.gravity_scale ?? 1)
          .sub(temp.copy(b.gravityRest).applyQuaternion(restQ).applyQuaternion(anchorQ)).multiplyScalar(st.params.gravity)
        const bindProjection = b.gravityProjection
        const projection = gravity.dot(u) / 9.81
        const inward = clamp(-projection - Math.max(0, -bindProjection), 0, 1)
        const outward = clamp(projection - Math.max(0, bindProjection), 0, 1)
        const axial = deltaG.dot(u)
        if (axial < 0) deltaG.addScaledVector(u, -axial)
        // When crossing zero, blend the bounded static result rather than
        // dividing by an interpolated frequency that approaches zero.
        const staticT = clamp(st.paramsBlend / 1.5, 0, 1)
        const staticBlend = staticT * staticT * (3 - 2 * staticT)
        st.staticFrequency = st.staticFrequencyFrom + (st.staticFrequencyTo - st.staticFrequencyFrom) * staticBlend
        st.staticWeight = st.staticWeightFrom + (st.staticWeightTo - st.staticWeightFrom) * staticBlend
        const omegaSquared = (2 * Math.PI * st.staticFrequency) ** 2
        equilibrium.copy(deltaG).multiplyScalar(omegaSquared >= 1e-12 ? 1 / omegaSquared : 0)
        originalLever.copy(target).sub(head)
        const restLength = originalLever.length()
        staticVector.copy(originalLever).add(equilibrium)
        // Static angle and length have their own limits, independent of swing.
        const sagLimit = (st.params.sag_max_deg ?? st.params.max_deg) * Math.PI / 180
        if (st.chain && st.chain.length >= 2) dynamicQ.copy(st.sag!.q)
        else {
          dynamicQ.setFromUnitVectors(u, temp.copy(staticVector).normalize())
          const sagAngle = dynamicQ.angleTo(identityQ)
          if (sagAngle > sagLimit) dynamicQ.slerp(identityQ, 1 - sagLimit / sagAngle)
        }
        dynamicQ.slerp(identityQ, 1 - st.staticWeight)
        const staticLength = Math.max(1e-12, restLength * (1 - (st.params.flatten ?? 0) * (1 - (st.params.flatten_floor ?? st.params.squash[0])) * inward
          + (st.params.stretch ?? 0) * (st.params.squash[1] - 1) * outward))
        // Scale only the bounded force displacement along bind body up.
        staticVector.copy(u).applyQuaternion(dynamicQ).multiplyScalar(restLength).sub(originalLever)
        bodyVertical.copy(b.gravityRest).multiplyScalar(-1 / 9.81).applyQuaternion(anchorQ).normalize()
        staticVector.addScaledVector(bodyVertical, ((st.params.head_sag ?? 1) - 1) * staticVector.dot(bodyVertical))
        staticVector.add(originalLever)
        // Direct paired outward target in radians, independent of force/frequency.
        const spillAngle = (st.params.spill ?? 0) * (st.params.spill_max_deg ?? st.params.sag_max_deg ?? st.params.max_deg) * Math.PI / 180 * inward
        if (lateral.lengthSq() > 1e-12) {
          temp.copy(u).cross(lateral).normalize()
          staticVector.applyAxisAngle(temp, spillAngle)
        }
        staticVector.multiplyScalar(restLength > 1e-12 ? staticLength / restLength : 1)
        target.copy(head).add(staticVector)
        const extremeAnchor = dt > 0 && st.anchorRotation !== null
          && st.anchorRotation.angleTo(anchorQ) / dt > 2 * Math.PI
        if (far || !st.p || !st.target || (!options.frozen && dt > 0.25)) {
          (st.p ??= new three.Vector3()).copy(target); st.v.set(0, 0, 0)
        } else if (options.frozen) {
          st.p.add(temp.copy(target).sub(st.target))
        } else if (dt > 0) {
          vTarget.copy(target).sub(st.target).divideScalar(dt)
          const steps = Math.ceil(dt / (1 / 240))
          const h = dt / steps
          for (let i = 0; i < steps; i++) {
            t.copy(st.target).lerp(target, i / steps)
            previousDeviation.copy(st.p).sub(t)
            const result = stepSecondaryParticle(st.p, st.v, t, vTarget, st.params, h, integration)
            if (extremeAnchor) {
              // Cap each deviation increment and its total displacement during
              // extreme anchor turns. Carry the bounded target velocity on hit
              // so stored momentum cannot inject another burst on the next step.
              const budget = staticVector.length() * Math.sin(Math.min(Math.PI / 2, motionLimit))
              nextDeviation.copy(result.p).sub(t).addScaledVector(vTarget, -h)
              temp.copy(nextDeviation).sub(previousDeviation).clampLength(0, budget * Math.min(1, h * 120))
              nextDeviation.copy(previousDeviation).add(temp).clampLength(0, budget)
              temp.copy(t).addScaledVector(vTarget, h).add(nextDeviation)
              if (temp.distanceToSquared(result.p) > 1e-20) result.v.copy(vTarget)
              result.p.copy(temp)
            }
            if (!Number.isFinite(result.p.lengthSq()) || !Number.isFinite(result.v.lengthSq())) {
              result.p.copy(t).addScaledVector(vTarget, h); result.v.set(0, 0, 0)
            }
            st.p.copy(result.p); st.v.copy(result.v)
          }
        }
        (st.anchorRotation ??= new three.Quaternion()).copy(anchorQ);
        (st.target ??= new three.Vector3()).copy(target)
        base.copy(target).sub(head)
        // Filter only p-T' in the current rest lever frame. Bind body up
        // follows the anchor, not the rest/sag rotation. Vertical levers use
        // projected bind body front instead of the degenerate up projection.
        u.copy(base).normalize()
        bodyVertical.copy(b.gravityRest).multiplyScalar(-1 / 9.81).applyQuaternion(anchorQ)
        bodyVertical.addScaledVector(u, -bodyVertical.dot(u))
        if (bodyVertical.lengthSq() < 1e-10) {
          bodyVertical.copy(b.bodyFront).applyQuaternion(anchorQ)
          bodyVertical.addScaledVector(u, -bodyVertical.dot(u))
        }
        bodyVertical.normalize()
        dynamicDelta.copy(st.p!).sub(target)
        const gains = st.params.axis_gain ?? DEFAULT_AXIS_GAIN
        const longitudinal = dynamicDelta.dot(u)
        const vertical = dynamicDelta.dot(bodyVertical)
        dynamicDelta.multiplyScalar(gains[0])
          .addScaledVector(bodyVertical, (gains[1] - gains[0]) * vertical)
          .addScaledVector(u, (gains[2] - gains[0]) * longitudinal)
        rendered.copy(base).add(dynamicDelta)
        // Compression cannot flip the lever and manufacture axial swing.
        rendered.addScaledVector(u, Math.max(0, 1e-12 - base.length() - gains[2] * longitudinal))
        // Saturate the swing angle around the static target, not around bind T.
        dynamicQ.setFromUnitVectors(temp.copy(base).normalize(), u.copy(rendered).normalize())
        const angle = dynamicQ.angleTo(identityQ)
        const limited = softMotionAngle(angle, motionLimit)
        if (angle > 0) dynamicQ.slerp(identityQ, 1 - limited / angle)
        // Only longitudinal dynamics change length; transverse displacement
        // supplies direction. Static length/flatten remain untouched.
        const renderedLength = Math.max(1e-12, base.length() + gains[2] * longitudinal)
        rendered.copy(base).applyQuaternion(dynamicQ).multiplyScalar(renderedLength / base.length())
        const gain = far ? 0 : st.params.gain
        rendered.sub(base).multiplyScalar(gain).add(base)
        rendered.normalize().multiplyScalar(Math.max(1e-12, base.length() + gain * gains[2] * longitudinal))
        // Split bounded transverse static and dynamic offsets; axial length is unchanged.
        const translate = st.params.translate ?? 0
        headShift.copy(base).sub(originalLever)
        temp.copy(originalLever).normalize()
        headShift.addScaledVector(temp, -headShift.dot(temp))
        headShift.clampLength(0, restLength * Math.max(0, Math.sin(sagLimit)))
        shiftPart.copy(rendered).sub(base)
        // Use the same rest lever projection for both components so full
        // translation leaves no residual rotation when neither cap is active.
        temp.copy(originalLever).normalize()
        shiftPart.addScaledVector(temp, -shiftPart.dot(temp))
        shiftPart.clampLength(0, base.length() * Math.max(0, Math.sin(motionLimit)))
        headShift.add(shiftPart).multiplyScalar(translate)
        const totalLength = rendered.length()
        rendered.sub(headShift).normalize().multiplyScalar(totalLength)
        localRendered.copy(rendered).add(head).applyMatrix4(inverseAnchor.copy(anchor).invert())
        dynamicQ.setFromUnitVectors(temp.copy(restVector).normalize(), u.copy(localRendered).normalize())
        // head_sag acts after force/length limits. Preserve that static target
        // even when it is shorter than squash_min; only dynamics hit the cap.
        const staticRatio = temp.copy(target).applyMatrix4(inverseAnchor).length() / restVector.length()
        const s = clamp(localRendered.length() / restVector.length(), Math.min(st.params.squash[0], staticRatio), st.params.squash[1])
        const spread = st.params.spread ?? 0.5
        const perpendicular = s < 1 ? Math.min(SPREAD_CAP, 1 + spread * (1 / Math.sqrt(s) - 1)) : 1 / Math.sqrt(s)
        u.copy(b.scaleAxis)
        scale.identity()
        const e = scale.elements
        // Gram-Schmidt gives the orthonormal frame (u, L, u cross L).
        // Its spectral scale has no shear; the third paired axis stays 1.
        const pairedWidth = Math.min(SPREAD_CAP, 1 + spread * (1 / s - 1))
        // Paired flattening presses along the BODY FRONT (where gravity acts
        // when lying) and widens along the body lateral axis, not along the
        // oblique lever: an outward-pointing lever would otherwise tilt the
        // width axis into the height. Both axes are expressed in the frame the
        // scale acts in (bind bone frame rotated by dynamic·rest), and the
        // frame (front, L, front×L) is orthonormal, so the scale has no shear.
        frameQ.copy(dynamicQ).multiply(restQ).invert()
        frontLocal.copy(b.bodyFront).applyQuaternion(frameQ).normalize()
        localLateral.copy(lateral).transformDirection(inverseAnchor.copy(anchor).invert()).applyQuaternion(frameQ)
        localLateral.addScaledVector(frontLocal, -localLateral.dot(frontLocal))
        if (localLateral.lengthSq() > 1e-12) localLateral.normalize(); else localLateral.set(0, 0, 0)
        const pairedFlatten = s < 1 && st.roots.length >= 2 && localLateral.lengthSq() > 1e-12
        for (let row = 0; row < 3; row++) for (let col = 0; col < 3; col++) {
          e[col * 4 + row] = pairedFlatten
            ? (row === col ? 1 : 0) + (s - 1) * frontLocal.getComponent(row) * frontLocal.getComponent(col)
              + (pairedWidth - 1) * localLateral.getComponent(row) * localLateral.getComponent(col)
            : (row === col ? perpendicular : 0) + (s - perpendicular) * u.getComponent(row) * u.getComponent(col)
        }
        // State extent is applied after static/dynamic scaling, in the same
        // immutable lever frame; it does not alter volume compensation.
        const stateLength = st.params.length ?? 1, stateGirth = st.params.girth ?? 1
        for (let row = 0; row < 3; row++) for (let col = 0; col < 3; col++) {
          e[col * 4 + row] = stateGirth * e[col * 4 + row]
            + (stateLength - stateGirth) * s * u.getComponent(row) * u.getComponent(col)
        }
        shiftPart.copy(head).add(headShift).applyMatrix4(inverseAnchor)
        translationMatrix.makeTranslation(shiftPart.x, shiftPart.y, shiftPart.z)
        if (pairing && !b.todayBlend) {
          const limit = Math.max(st.params.max_deg, st.params.sag_max_deg ?? 0) * st.motionShare * Math.PI / 180
          const chain = st.chainRoot ?? st
          const suppress = chain.channels ? guideLink(st, chain, dynamicQ, restQ, limit) : null
          keepTipOutsidePair(st, dynamicQ, restQ, limit, dt, colliding, suppress)
        } else if (colliding && st.contacts.length && !b.todayBlend) {
          keepTipOutside(st, dynamicQ, restQ,
            Math.max(st.params.max_deg, st.params.sag_max_deg ?? 0) * st.motionShare * Math.PI / 180)
        }
        b.bone.matrix.copy(blended ? localBase.copy(b.bone.parent!.matrixWorld).invert().multiply(anchor) : b.local)
          .multiply(translationMatrix)
          .multiply(rotationMatrix.makeRotationFromQuaternion(dynamicQ.multiply(restQ)))
          .multiply(scale)
        b.rotation.copy(anchorQ).multiply(dynamicQ)
        driven.set(b.bone, st)
        b.bone.matrixWorldNeedsUpdate = true
        b.pureWorld.copy(anchor).multiply(translationMatrix).multiply(rotationMatrix)
        b.bone.matrixWorld.copy(b.pureWorld).multiply(scale)
        // Keep the local matrix consistent with that world matrix, so a later
        // updateMatrixWorld (parent.matrixWorld x matrix) does not re-apply the
        // parent's scale: parentFull = anchorFull x local^-1, hence
        // matrix = local x anchorFull^-1 x world.
        if (drivenAncestor) b.bone.matrix.copy(b.local).multiply(inverseAnchor.copy(anchorFull).invert()).multiply(b.bone.matrixWorld)
        // The chain's last link is done: its depth scale and the zone for the next engagement step (CHANNELS).
        if (pairing && st.chainRoot?.channels && st === st.chainRoot.chainLinks[st.chainRoot.chainLinks.length - 1]) {
          finishChain(st.chainRoot)
        }
      }
      // A rigid tail link takes its parent's frame without the parent's own
      // extension scale, at the parent's fully deformed position — the same
      // rule as a driven child, minus every motion of its own.
      for (const b of rigids) {
        const parent = b.bone.parent!
        const owner = driven.get(parent as Bone)
        anchorFull.copy(parent.matrixWorld).multiply(b.local)
        anchor.copy(owner ? owner.bind.pureWorld : parent.matrixWorld).multiply(b.local)
        anchor.setPosition(temp.setFromMatrixPosition(anchorFull))
        b.bone.matrixWorld.copy(anchor)
        b.pureWorld.copy(anchor)
        // parent.matrixWorld x matrix must reproduce that world on the publish below.
        b.bone.matrix.copy(inverseAnchor.copy(parent.matrixWorld).invert()).multiply(anchor)
        b.bone.matrixWorldNeedsUpdate = true
      }
      // Hair: today's skin under the swing (HAIR CHAINS), parents first.
      if (!far && hairBones.length) {
        hairFrame++
        for (const b of hairBones) {
          const st = driven.get(b.bone)
          const parent = b.bone.parent!
          const owner = binds.get(parent as Bone)
          const hairParent = owner?.today?.frame === hairFrame ? owner.today : undefined
          if (!hairParent) parent.updateWorldMatrix(false, false)
          const today = b.today ??= { frame: 0, rest: new three.Matrix4(), world: new three.Matrix4(),
            bind: b.bindWorldInverse.clone().invert() }
          today.frame = hairFrame
          const rest = today.rest.copy(hairParent ? hairParent.rest : parent.matrixWorld).multiply(b.local)
          // L = rest⁻¹ · rendered (identity for a carried joint); world = blend · bind · L
          if (st) deviation.copy(rest).invert().multiply(b.bone.matrixWorld)
          else deviation.identity()
          // Only the share of the hair that rides the chain's hanging bone swings (HAIR CHAINS).
          deviation.decompose(blendPos, deltaQ, blendScale)
          deltaQ.slerp(identityQ, 1 - b.swingShare!)
          deviation.compose(blendPos.multiplyScalar(b.swingShare!), deltaQ, blendScale)
          todayDelta.set(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
          for (const { bind: x, share } of b.todayBlend!) {
            delta.copy(x.bone.matrixWorld).multiply(x.bindWorldInverse)
            for (let i = 0; i < 16; i++) todayDelta.elements[i] += share * delta.elements[i]
          }
          const world = today.world.copy(todayDelta).multiply(today.bind).multiply(deviation)
          if (st && pairing) {
            keepHairTipOutsidePair(st, world, Math.max(st.params.max_deg, st.params.sag_max_deg ?? 0) * st.motionShare * Math.PI / 180, dt, colliding)
          } else if (st && colliding && st.contacts.length) {
            keepHairTipOutside(st, world, Math.max(st.params.max_deg, st.params.sag_max_deg ?? 0) * st.motionShare * Math.PI / 180)
          }
          b.bone.matrix.copy(localBase.copy(hairParent ? hairParent.world : parent.matrixWorld).invert().multiply(world))
          b.bone.matrixWorld.copy(world)
          b.bone.matrixWorldNeedsUpdate = true
        }
      }
      if (pairing) {
        releasing = 0
        for (const st of particles) if (st.partnerDeg > 0) releasing++
      }
      // Publish all non-driven descendants once after the chain is complete.
      root.updateMatrixWorld(true)
    },
    dispose() {
      for (const st of particles) restore(st.bind)
      for (const b of rigids) restore(b)
      for (const b of hairBones) restore(b)
      particles = []; rigids = []; hairBones = []; binds.clear(); sums.clear(); byName.clear(); boneInverses.clear(); collision = null; disposed = true
    },
  }
}
