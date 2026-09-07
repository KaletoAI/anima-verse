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
 * of plan-furnish-v2.md). Pure, no React, no library.
 *
 * The vertical half of the composition is computed here too (`offset_y`) but
 * is never DRAWN: a top view has no height. It exists only to RANK candidate
 * supports by their top surface (`pickSupport`), and it is approximate on
 * purpose — the plan does not know a prop's `ground_offset_m`. The metres a
 * renderer uses are the server's alone.
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
  /** Library id — only `withPropHeights` needs it. */
  prop_id?: string
  /** Room metres for a piece on the floor; metres in the SUPPORT's unturned
   *  frame for a child (+x = its width axis, +z = its depth axis). */
  at: [number, number]
  /** Degrees — absolute for a root, relative to the support for a child. */
  yaw?: number
  /** Metres above the floor for a piece on the floor; the trim above the
   *  SUPPORT's top surface for a child. */
  offset_y?: number
  /** The REAL height of the prop this placement shows, in metres — the plan
   *  reads it from the library (`withPropHeights`). Only the vertical
   *  composition needs it; the XZ turn does not, so a call site that just
   *  draws footprints may leave it out. */
  height_m?: number
  /** Placement id of the piece this one stands on. */
  on?: string
}

/** One composed pose, in ROOM metres, in input order. */
export interface ComposedPlacement {
  at: [number, number]
  yaw: number
  /** Metres of this piece's BASE above the floor, composed through the chain.
   *
   *  APPROXIMATE ON PURPOSE, and never a render value: the plan does not know
   *  a prop's `ground_offset_m` (how deep it sinks into its ground), so this
   *  is the server's `stack_on_support` with every sink taken as 0. It exists
   *  to RANK candidate supports by their top surface — which is what the
   *  server's own rule does — while the metres a renderer draws come from the
   *  recipe. Meaningless unless the entries carry `height_m`. */
  offset_y: number
  /** The link that SURVIVED — `''` for a root and for a broken link. */
  on: string
  /** 0 = on the floor. */
  depth: number
}

/**
 * Compose every placement of one list into room metres.
 *
 * The child frame, and the turn that leaves it — the RENDERER's `R_y(+yaw)`,
 * the same matrix `room_recipe.compose_prop_marker` applies to a marker of the
 * same support (§ B2 step 4, E4). A child stands on the support's MESH, and
 * the mesh turns with `rotation.y = +rad(yaw)`:
 *
 *     r = radians(yaw_support)
 *     x = x_support + dx·cos r + dz·sin r
 *     z = z_support − dx·sin r + dz·cos r
 *     yaw      = (yaw_support + yaw_child) mod 360
 *     offset_y = offset_y_support + height_m_support + offset_y_child
 *
 * The last line is the server's `stack_on_support` with the sinks taken as 0
 * (see `ComposedPlacement.offset_y`) — it ranks supports, it never draws.
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
    offset_y: Number(p.offset_y) || 0,
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
    child.at = [sup.at[0] + dx * cos + dz * sin,
                sup.at[1] - dx * sin + dz * cos]
    child.yaw = (sup.yaw + child.yaw) % 360
    if (tooDeep) continue       // composed into room metres, no longer a child
    // The support's FINISHED base plus its own height is its top surface, so
    // the child's stored trim sits on it — the same order the server composes
    // in, which is why supports run first.
    child.offset_y += sup.offset_y + (Number(list[j].height_m) || 0)
    child.depth = sup.depth + 1
    child.on = list[i].on || ''
  }
  return out
}

/**
 * The inverse of one composition step: where a piece that is dropped at
 * `(x, z)` facing `yaw` stands in the SUPPORT's frame.
 *
 * The transpose of the turn above — and therefore the very transform
 * `propsAtPoint` already runs to hit-test a turned footprint (`lx = X·cos θ −
 * Z·sin θ`, `lz = X·sin θ + Z·cos θ`).
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
    at: [dx * cos - dz * sin, dx * sin + dz * cos],
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

/**
 * The stored placements with the library height of the prop each one shows —
 * the ONE place the plan joins a placement to its dims for the composition.
 *
 * Without it a composed `offset_y` is only the sum of the stored trims, which
 * is not a height above the floor; with it the vertical chain is the server's
 * (minus the sinks the plan cannot see).
 */
export function withPropHeights<T extends ComposeInput>(
  list: readonly T[],
  dims: Record<string, { height_m?: number } | undefined>,
): Array<T & { height_m: number }> {
  return list.map((p) => ({
    ...p, height_m: dims[p.prop_id || '']?.height_m || 0,
  }))
}

/**
 * WHICH of the pieces under a placement carries it — the index to write into
 * `on`, or `null` when none of them may.
 *
 * `candidates` are the placements whose turned footprint covers this one's
 * anchor (`RoomLayoutEditor.propsAtPoint`, the same test that cycles a click
 * through a stack): the footprint question stays there, this answers the
 * ranking question.
 *
 * TWO RULES, and both have cost a bug:
 *
 * 1. **Never the piece's own subtree.** A tray standing centred on a table
 *    covers the table's anchor, so it IS one of the table's candidates —
 *    setting the table down on its own tray would close a circle, and the
 *    circle rule would then cut it and drop both pieces back to their raw
 *    stored `at`. `dependentIndices` names exactly what is out of bounds.
 * 2. **The TOPMOST surface wins**, ties to the later placement — the server's
 *    own rule (`props.stack_offset_y`), read off the COMPOSED base plus the
 *    prop's height. The stored `offset_y` would be the wrong number here: on
 *    a child it is a trim above ITS support, not a height above the floor.
 *    Depth does not enter it: a 1.8 m floor lamp beside the table is a higher
 *    surface than a coaster lying on the table, whatever their chain depths.
 */
export function pickSupport(
  list: readonly ComposeInput[],
  composed: readonly ComposedPlacement[],
  index: number,
  candidates: readonly number[],
): number | null {
  const own = new Set(dependentIndices(list, index))
  let best: number | null = null
  let bestTop = -Infinity
  for (const i of candidates) {
    if (own.has(i) || !composed[i]) continue
    const top = composed[i].offset_y + (Number(list[i].height_m) || 0)
    if (top >= bestTop) {
      best = i
      bestTop = top
    }
  }
  return best
}
