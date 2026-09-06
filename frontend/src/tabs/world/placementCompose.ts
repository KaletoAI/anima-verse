/**
 * placementCompose — the PARENT LINK `on`, resolved for the floor plan.
 *
 * "The candle on the table" is stored as a relation, not as a position: a
 * placement may name the placement it stands ON, and its own `at`/`yaw` are
 * then read in that support's frame. Moving the table moves the candle for
 * free, because the candle never knew where it was in the room.
 *
 * The plan has to DRAW and HIT-TEST the composed positions, so it runs the
 * same arithmetic the server does (`room_recipe.compose_on_chain`, decision E1
 * of plan-furnish-v2.md). Pure, no React, no library — the vertical half of
 * the composition (the stacking height) is the server's alone and never
 * appears on the plan, which is a top view.
 *
 * KEEP THIS IN LOCKSTEP WITH `app/core/room_recipe.compose_on_chain`: same
 * frame, same turn, same repair of a link that does not hold. The numbers are
 * hand-derived in `scripts/smoke_scene_recipe.py` [7j] and re-checked here by
 * `scripts/smoke_placement_compose.mjs`.
 */

/** How deep a support chain may run — `room_recipe.ON_MAX_DEPTH`. The root
 *  stands on the floor at depth 0. */
export const ON_MAX_DEPTH = 3

/** What the composition reads off a stored placement. */
export interface ComposeInput {
  id?: string
  /** Room metres for a piece on the floor; metres in the SUPPORT's unturned
   *  frame for a child (+x = its width axis, +z = its depth axis). */
  at: [number, number]
  /** Degrees — absolute for a root, relative to the support for a child. */
  yaw?: number
  /** Placement id of the piece this one stands on. */
  on?: string
}

/** One composed pose, in ROOM metres, in input order. */
export interface ComposedPlacement {
  at: [number, number]
  yaw: number
  /** The link that SURVIVED — `''` for a root and for a broken link. */
  on: string
  /** 0 = on the floor. */
  depth: number
}

/**
 * Compose every placement of one list into room metres.
 *
 * The child frame, and the turn that leaves it (the same clockwise turn the
 * server's `_rect_corners` uses):
 *
 *     r = radians(yaw_support)
 *     x = x_support + dx·cos r − dz·sin r
 *     z = z_support + dx·sin r + dz·cos r
 *     yaw = (yaw_support + yaw_child) mod 360
 *
 * Order in the list does not matter — supports are composed before their
 * children. A link that does not hold (unknown id, self-reference, circle)
 * leaves the piece at its stored `at`; a chain deeper than `ON_MAX_DEPTH`
 * composes through its valid part and drops the link there. Nothing is ever
 * removed: the answer always has one entry per input, in input order.
 */
export function composePlacements(
  list: readonly ComposeInput[],
): ComposedPlacement[] {
  const n = list.length
  const out: ComposedPlacement[] = list.map((p) => ({
    at: [Number(p.at?.[0]) || 0, Number(p.at?.[1]) || 0],
    yaw: ((Number(p.yaw) || 0) % 360 + 360) % 360,
    on: '',
    depth: 0,
  }))
  // ── who points at whom ────────────────────────────────────────────────
  const byId = new Map<string, number>()
  list.forEach((p, i) => {
    if (p.id && !byId.has(p.id)) byId.set(p.id, i)
  })
  const parent: Array<number | null> = list.map((p, i) => {
    if (!p.on) return null
    const j = byId.get(p.on)
    // Unknown id or a self-reference: no support, so the stored `at` is read
    // as room metres and the piece stays where it was drawn.
    return j === undefined || j === i ? null : j
  })

  // ── circles ───────────────────────────────────────────────────────────
  // Every node has at most one parent, so walking upwards either ends or
  // runs into a loop. Only the nodes ON the loop lose their link; a node
  // merely pointing at one hangs off the piece that became a root.
  const state = new Array(n).fill(0)   // 0 = untouched, 1 = on the walk, 2 = done
  for (let start = 0; start < n; start += 1) {
    if (state[start]) continue
    const path: number[] = []
    let v: number | null = start
    while (v !== null && state[v] === 0) {
      state[v] = 1
      path.push(v)
      v = parent[v]
    }
    if (v !== null && state[v] === 1) {
      for (const u of path.slice(path.indexOf(v))) parent[u] = null
    }
    for (const u of path) state[u] = 2
  }

  // ── supports first, then their children ───────────────────────────────
  const placed = parent.map((j) => j === null)
  const order: number[] = []
  for (let i = 0; i < n; i += 1) if (placed[i]) order.push(i)
  let remaining: number[] = []
  for (let i = 0; i < n; i += 1) if (!placed[i]) remaining.push(i)
  while (remaining.length) {
    const still: number[] = []
    let progressed = false
    for (const i of remaining) {
      const j = parent[i]
      if (j !== null && placed[j]) {
        order.push(i)
        placed[i] = true
        progressed = true
      } else still.push(i)
    }
    remaining = still
    if (!progressed) {          // unreachable — every circle was cut above
      order.push(...remaining)
      break
    }
  }

  for (const i of order) {
    const j = parent[i]
    if (j === null) continue
    const sup = out[j]
    const child = out[i]
    const tooDeep = sup.depth + 1 > ON_MAX_DEPTH
    const r = (sup.yaw * Math.PI) / 180
    const cos = Math.cos(r)
    const sin = Math.sin(r)
    const [dx, dz] = child.at
    child.at = [sup.at[0] + dx * cos - dz * sin,
                sup.at[1] + dx * sin + dz * cos]
    child.yaw = (sup.yaw + child.yaw) % 360
    if (tooDeep) continue       // composed into room metres, no longer a child
    child.depth = sup.depth + 1
    child.on = list[i].on || ''
  }
  return out
}

/**
 * The inverse of one composition step: where a piece that is dropped at
 * `(x, z)` facing `yaw` stands in the SUPPORT's frame.
 *
 * Used when a child is dragged (only its own relative `at` may move) and when
 * "Place on top" turns a free placement into a child.
 */
export function toSupportFrame(
  at: readonly [number, number],
  yaw: number,
  support: ComposedPlacement,
): { at: [number, number]; yaw: number } {
  const r = (support.yaw * Math.PI) / 180
  const cos = Math.cos(r)
  const sin = Math.sin(r)
  const dx = at[0] - support.at[0]
  const dz = at[1] - support.at[1]
  return {
    at: [dx * cos + dz * sin, -dx * sin + dz * cos],
    yaw: ((yaw - support.yaw) % 360 + 360) % 360,
  }
}

/**
 * The placement at `index` and EVERYTHING standing on it, transitively — in
 * ascending index order, the piece itself first.
 *
 * Removing a support removes its children with it: a candle whose table is
 * gone has no frame left to be positioned in, and leaving it behind at a
 * relative `[0.3, 0]` would drop it at the room's origin. The editor asks this
 * before a delete so it can say how many pieces go.
 */
export function dependentIndices(
  list: readonly ComposeInput[],
  index: number,
): number[] {
  const doomed = new Set<number>([index])
  // The list is short (100 placements at most), so repeating until nothing
  // changes is cheaper than building a child index — and one pass adds at
  // least one piece, so the list length bounds the walk.
  for (let pass = 0; pass < list.length; pass += 1) {
    let grew = false
    list.forEach((p, i) => {
      if (doomed.has(i) || !p.on) return
      const support = list.findIndex((q) => q.id === p.on)
      if (support >= 0 && doomed.has(support)) {
        doomed.add(i)
        grew = true
      }
    })
    if (!grew) break
  }
  return [...doomed].sort((a, b) => a - b)
}
