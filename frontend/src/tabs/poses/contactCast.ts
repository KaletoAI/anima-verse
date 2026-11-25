/**
 * ONE-CLICK CONTACT HEIGHTS (owner 2026-11-25: "einmal automatisch durchgehen und speichern" — the Pose library's
 * "Store contact heights" fills the whole library with no cast to choose). Pure, three-free; the Pose library
 * (`ClipLibrary.tsx`) and its place preview (`PlacePreview.tsx`) call it.
 *
 * THE CAST (`chooseContactCast`). What each ROLE of a clip needs comes from its contact relations (target ≠ none):
 * - the `part` role needs an ATTACHED PART — a built group whose op is in `POINT_TARGET_OPS`;
 * - the `at` role of target `channel` needs a BUILT CHANNEL other than the mouth that accepts one of those ops;
 * - the mouth and the hands need nothing: every humanoid skeleton carries them (`contactTarget.ts`).
 * A role takes a person of the clip's role gender (`role_gender`; none = any gender; nobody of that gender = any
 * person). The ORDER, per role in letter order, never one person twice:
 *   1. a person who meets every need of the role,
 *   2. the person this role had on the previous clip, then a person of the previous clip's cast,
 *   3. the name (code-point order).
 * So a cast that fits is kept from clip to clip (the models load once); a person meeting the needs always beats one
 * that does not. A role nobody can serve keeps its gender-fitting person and is listed in `unmet`: its height comes
 * from the declared anchors.
 *
 * THE DECLARED ANCHORS (`GET /assets/contact-anchors`, `collision_channels.declared_contact_anchors`): a channel
 * region's joint + offset and an attached part's anchor joint + offset, both in the BODY FRAME [side, up, front] of
 * the bind skeleton (`bodyFrameOf`, the rule of `collision_channels.body_frame`: up = unit(Head − Hips); side =
 * unit(LeftArm − RightArm without its part along up); front = side × up, flipped when its dot with LeftToeBase −
 * LeftFoot is negative). The bind point P = joint + offset · [side, up, front] (`declaredPoint`) rides RIGIDLY on its
 * joint — the `declared` placement of `resolve_channels` with the channels.ts mesh switch read as on:
 * P_now = jointWorld · jointBindInverse · P (`posedPoint`, column-major 4×4). Without a built mesh only the joints
 * exist, which is all this needs; the deepest frame is the one where the part's point comes closest to the opening
 * (`deepestFrame`).
 */
import { normBoneName, POINT_TARGET_OPS } from '@anima/scene-render'

export type Vec3 = [number, number, number]

/** A person the cast may take: gender, the ops of its built groups, its built channels (on the body the preview
 *  loads). */
export interface CastPerson { name: string; gender: string; parts: readonly string[]; channels: readonly { id: string; accepts: readonly string[] }[] }
export interface CastRelation { part: string; at: string; target: string }
export interface CastChoice {
  /** The person of each role (a role nobody could take is absent). */
  byRole: Record<string, string>
  /** Per role the needs nobody of the pool meets ('part' | 'channel'). */
  unmet: Record<string, ('part' | 'channel')[]>
}

const MOUTH = 'mouth'
const byName = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0)

/** What each role needs (module docstring THE CAST). */
export function roleNeeds(roles: readonly string[], relations: readonly CastRelation[]): Record<string, ('part' | 'channel')[]> {
  const out: Record<string, ('part' | 'channel')[]> = Object.fromEntries(roles.map((r) => [r, []]))
  for (const rel of relations) {
    if (rel.target === 'none') continue
    if (out[rel.part] && !out[rel.part].includes('part')) out[rel.part].push('part')
    if (rel.target === 'channel' && out[rel.at] && !out[rel.at].includes('channel')) out[rel.at].push('channel')
  }
  return out
}

/** Whether `p` meets `need`. */
export function meets(p: CastPerson, need: 'part' | 'channel'): boolean {
  if (need === 'part') return p.parts.some((op) => POINT_TARGET_OPS.includes(op))
  return p.channels.some((c) => c.id !== MOUTH && c.accepts.some((op) => POINT_TARGET_OPS.includes(op)))
}

/** The cast of one clip (module docstring THE CAST). `previous`: the previous clip's cast by role. */
export function chooseContactCast(input: { roles: readonly string[]; roleGender: Readonly<Record<string, string>>
  relations: readonly CastRelation[]; people: readonly CastPerson[]; previous?: Readonly<Record<string, string>> }): CastChoice {
  const needs = roleNeeds(input.roles, input.relations)
  const prev = input.previous ?? {}
  const prevNames = new Set(Object.values(prev))
  const used = new Set<string>()
  const byRole: Record<string, string> = {}
  const unmet: Record<string, ('part' | 'channel')[]> = {}
  for (const role of [...input.roles].sort(byName)) {
    const free = input.people.filter((p) => !used.has(p.name))
    const g = input.roleGender[role] || ''
    const sameGender = g ? free.filter((p) => p.gender === g) : free
    const pool = sameGender.length ? sameGender : free
    if (!pool.length) continue
    const need = needs[role] ?? []
    const fits = (p: CastPerson) => need.every((n) => meets(p, n))
    const rank = (p: CastPerson): [number, number, number] => [fits(p) ? 0 : 1, prev[role] === p.name ? 0 : 1, prevNames.has(p.name) ? 0 : 1]
    const best = [...pool].sort((a, b) => {
      const ra = rank(a), rb = rank(b)
      for (let i = 0; i < 3; i++) if (ra[i] !== rb[i]) return ra[i] - rb[i]
      return byName(a.name, b.name)
    })[0]
    byRole[role] = best.name
    used.add(best.name)
    const missing = need.filter((n) => !meets(best, n))
    if (missing.length) unmet[role] = missing
  }
  return { byRole, unmet }
}

/** The relation a clip WITHOUT declared relations is measured by — what the auto-detection finds on a full cast (the
 *  first part carrier against the first figure with a channel accepting the part): the first role (letter order)
 *  whose gender a declared part names (or names no gender) carries it, the first OTHER role whose gender a declared
 *  channel names receives it, target `channel`; without such roles B's part → A (the bare target word's rule). */
export function impliedRelation(roles: readonly string[], genderOf: Readonly<Record<string, string>>,
  anchors: ContactAnchors): CastRelation & { target: 'channel' } {
  const sorted = [...roles].sort(byName)
  const takes = (list: readonly DeclaredAnchor[], role: string) =>
    list.some((a) => !a.genders || (!!genderOf[role] && a.genders.includes(genderOf[role])))
  const part = sorted.find((r) => takes(anchors.parts, r)) ?? sorted[1] ?? sorted[0]
  const at = sorted.find((r) => r !== part && takes(anchors.channels, r)) ?? sorted.find((r) => r !== part) ?? sorted[0]
  return { part, at, target: 'channel' }
}

// ── the declared anchors ──

export interface DeclaredAnchor { id: string; bone: string; offset: Vec3; genders: string[] | null; op?: string; accepts?: string[] }
export interface ContactAnchors { channels: DeclaredAnchor[]; parts: DeclaredAnchor[] }

const vec3 = (v: unknown): Vec3 | null =>
  Array.isArray(v) && v.length === 3 && v.every((x) => typeof x === 'number' && Number.isFinite(x)) ? [v[0], v[1], v[2]] : null
/** `GET /assets/contact-anchors` read defensively (a malformed entry is dropped). */
export function contactAnchorsOf(wire: unknown): ContactAnchors {
  const list = (v: unknown): DeclaredAnchor[] => (Array.isArray(v) ? v : []).flatMap((e) => {
    const o = e as Record<string, unknown> | null
    const offset = vec3(o?.offset)
    if (!o || typeof o.id !== 'string' || typeof o.bone !== 'string' || !offset) return []
    const genders = Array.isArray(o.genders) ? o.genders.filter((x): x is string => typeof x === 'string') : null
    return [{ id: o.id, bone: o.bone, offset, genders,
      ...(typeof o.op === 'string' ? { op: o.op } : {}),
      ...(Array.isArray(o.accepts) ? { accepts: o.accepts.filter((x): x is string => typeof x === 'string') } : {}) }]
  })
  const w = (wire ?? {}) as Record<string, unknown>
  return { channels: list(w.channels), parts: list(w.parts) }
}

/** The declaration for a role of `gender`: the first whose genders include it (or name none), else the first. */
export function anchorFor(list: readonly DeclaredAnchor[], gender: string): DeclaredAnchor | null {
  return list.find((a) => !a.genders || !gender || a.genders.includes(gender)) ?? list[0] ?? null
}

const sub = (p: Vec3, q: Vec3): Vec3 => [p[0] - q[0], p[1] - q[1], p[2] - q[2]]
const dot = (p: Vec3, q: Vec3) => p[0] * q[0] + p[1] * q[1] + p[2] * q[2]
const scl = (p: Vec3, k: number): Vec3 => [p[0] * k, p[1] * k, p[2] * k]
const unit = (p: Vec3): Vec3 | null => { const l = Math.hypot(p[0], p[1], p[2]); return l > 1e-9 ? scl(p, 1 / l) : null }
const cross = (p: Vec3, q: Vec3): Vec3 => [p[1] * q[2] - p[2] * q[1], p[2] * q[0] - p[0] * q[2], p[0] * q[1] - p[1] * q[0]]

export interface BodyFrame { side: Vec3; up: Vec3; front: Vec3 }
/** The body frame of bind joint positions (module docstring); keys are read by `normBoneName`. Null when a joint is
 *  missing or the frame degenerates. */
export function bodyFrameOf(joints: Readonly<Record<string, Vec3>>): BodyFrame | null {
  const j: Record<string, Vec3> = {}
  for (const [k, v] of Object.entries(joints)) j[normBoneName(k)] = v
  const hips = j.hips, head = j.head, la = j.leftarm, ra = j.rightarm, lf = j.leftfoot, lt = j.lefttoebase
  if (!hips || !head || !la || !ra || !lf || !lt) return null
  const up = unit(sub(head, hips))
  if (!up) return null
  const across = sub(la, ra)
  const side = unit(sub(across, scl(up, dot(across, up))))
  if (!side) return null
  let front = cross(side, up)
  if (dot(front, sub(lt, lf)) < 0) front = scl(front, -1)
  return { side, up, front }
}

/** The bind point of a declaration: joint `bone` + offset · [side, up, front]; null without the joint or a frame. */
export function declaredPoint(joints: Readonly<Record<string, Vec3>>, bone: string, offset: Vec3): Vec3 | null {
  const fr = bodyFrameOf(joints)
  const key = normBoneName(bone)
  const at = Object.entries(joints).find(([k]) => normBoneName(k) === key)?.[1]
  if (!fr || !at) return null
  return [0, 1, 2].map((i) => at[i] + offset[0] * fr.side[i] + offset[1] * fr.up[i] + offset[2] * fr.front[i]) as Vec3
}

/** A bind-space point carried rigidly by its joint: jointWorld · jointBindInverse · p (column-major 4×4 matrices). */
export function posedPoint(world: ArrayLike<number>, inverse: ArrayLike<number>, p: Vec3): Vec3 {
  const ap = (m: ArrayLike<number>, v: Vec3): Vec3 => [
    m[0] * v[0] + m[4] * v[1] + m[8] * v[2] + m[12],
    m[1] * v[0] + m[5] * v[1] + m[9] * v[2] + m[13],
    m[2] * v[0] + m[6] * v[1] + m[10] * v[2] + m[14]]
  return ap(world, ap(inverse, p))
}

/** The index of the frame where the part's point comes closest to the opening; −1 for no frame. */
export function deepestFrame(samples: readonly { point: Vec3; o: Vec3 }[]): number {
  let best = -1, d = Infinity
  samples.forEach((s, i) => { const x = Math.hypot(...sub(s.point, s.o)); if (x < d) { d = x; best = i } })
  return best
}
