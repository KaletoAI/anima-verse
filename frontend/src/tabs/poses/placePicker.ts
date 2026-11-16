/**
 * The place preview's choices without React (Ruling A110b) — what `PlacePreview` asks and
 * `scripts/smoke_place_picker.mjs` checks by hand-derived numbers:
 *
 *  - `groupProps`: the prop picker's option groups by PLACE TYPE (`marker_groups` of `/assets/props`). A prop with
 *    several types appears under EACH of them (so a sofa is found under Seat and under Lie), its label naming the
 *    others. The clip's own type comes first, then the catalog order stand · seat · ground · lie, then any type an
 *    admin added (alphabetical).
 *  - `groundRoom`: the "Ground (no prop)" draft — one ROOM marker on the bare floor, exactly what a room author
 *    places: `{group, at, rotation 0, capacity}`. Spacing and row axis are NOT sent, so the server's defaults apply
 *    (`world_ops._spacing` 0.6 m, `_slot_axis` 90° = across the facing) and `scene_recipe.marker_slots` finishes the
 *    slots, as for every room marker in the game. Its type is the clip's when that is a floor type (stand/ground,
 *    root drop 0), else `ground`.
 *  - `planFill`: who goes where for "Fill all" / the default fill, and WHY nothing went anywhere.
 */

/** The pose catalog's place types in its own order (`animation_clips._RULE_GROUPS`). */
export const PLACE_TYPE_ORDER = ['stand', 'seat', 'ground', 'lie'] as const
/** The picker value of the bare floor. */
export const GROUND_PROP = '__ground__'
/** Solo figures on the bare floor: 1..4 in one row (the row stays inside the 6 m preview room at 0.6 m). */
export const GROUND_MAX = 4

export interface PickerProp { id: string; name?: string; marker_groups?: string[] }
export interface PropGroup { type: string; props: { id: string; label: string }[] }

/** Option groups of the prop picker; `want` = the clip's place type ('' = none). */
export function groupProps(props: readonly PickerProp[], want: string): PropGroup[] {
  const byType = new Map<string, { id: string; label: string }[]>()
  for (const p of props) {
    const types = (p.marker_groups ?? []).filter(Boolean)
    const own = types.length ? types : ['']
    for (const ty of own) {
      const others = types.filter((x) => x !== ty)
      const name = p.name || p.id
      const label = others.length ? `${name} (+${others.join(', ')})` : name
      byType.set(ty, [...(byType.get(ty) ?? []), { id: p.id, label }])
    }
  }
  const rank = (ty: string) => {
    if (want && ty === want) return -1
    const i = (PLACE_TYPE_ORDER as readonly string[]).indexOf(ty)
    return i >= 0 ? i : ty ? PLACE_TYPE_ORDER.length : PLACE_TYPE_ORDER.length + 1
  }
  return [...byType.entries()]
    .sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b))
    .map(([type, list]) => ({ type, props: list.sort((x, y) => x.label.localeCompare(y.label)) }))
}

/** The prop to preselect: the remembered one while it exists, else the first under the clip's type, else the bare
 *  floor for a floor-type clip, else the first prop at all. */
export function preselectProp(groups: readonly PropGroup[], want: string, memo: string): string {
  if (memo === GROUND_PROP) return GROUND_PROP
  if (memo && groups.some((g) => g.props.some((p) => p.id === memo))) return memo
  const match = groups.find((g) => g.type === want && g.props.length)
  if (match) return match.props[0].id
  if (want === 'stand' || want === 'ground') return GROUND_PROP
  return groups.find((g) => g.props.length)?.props[0].id ?? GROUND_PROP
}

/** The bare floor's marker type for a clip of type `want`. */
export function groundType(want: string): string {
  return want === 'stand' || want === 'ground' ? want : 'ground'
}

/** The draft room for the bare floor: one marker at the room centre (= world origin, as the prop's placement),
 *  facing south, `count` slots (1..GROUND_MAX; a pair's roles share one marker as on a bench). */
export function groundRoom(want: string, count: number) {
  const capacity = Math.max(1, Math.min(GROUND_MAX, Math.round(count) || 1))
  const marker: Record<string, unknown> = { id: 'floor', group: groundType(want), at: [3, 3], rotation: 0 }
  if (capacity > 1) marker.capacity = capacity
  return { id: 'place-preview', name: 'Preview', layout: { x: -3, y: -3, w: 6, d: 6, props: [], markers: [marker] } }
}

export interface FillPlace { letter: string; markerId: string; group: string }
export interface FillAssignment { character: string; role: string; body: 'outfit' | 'base'; state: string }
/** Why a fill placed nobody. */
export type FillReason = '' | 'loading' | 'no_places' | 'no_type' | 'too_few_slots'
export interface FillPlan { assign: Record<string, FillAssignment>; count: number; reason: FillReason }

/**
 * Who goes where. `names` = the pickable figures in order (built characters, then the mannequin); `null` while they
 * load. `want` = the clip's place type: only places of that type are filled — a place of another type is never
 * filled (a seat clip on a stand spot is not what the game does). Solo: one figure per place; a pair/group: one
 * marker with at least `roles.length` slots per pair. `all` = every fitting place (at most `max` figures), else the
 * first only. `body` = the figures' body choice.
 */
export function planFill(places: readonly FillPlace[], opts: { names: readonly string[] | null; want: string;
  roles: readonly string[]; all: boolean; max: number; body?: 'outfit' | 'base' }): FillPlan {
  const empty = (reason: FillReason): FillPlan => ({ assign: {}, count: 0, reason })
  if (!opts.names) return empty('loading')
  if (!places.length) return empty('no_places')
  const names = opts.names.length ? opts.names : ['']
  const who = (i: number) => names[i % names.length]
  const want = opts.want.trim()
  const fitting = want ? places.filter((p) => p.group === want) : [...places]
  if (!fitting.length) return empty('no_type')
  const byMarker = new Map<string, FillPlace[]>()
  for (const p of fitting) byMarker.set(p.markerId, [...(byMarker.get(p.markerId) ?? []), p])
  const solo = opts.roles.length < 2
  const body = opts.body ?? 'outfit'
  const assign: Record<string, FillAssignment> = {}
  let n = 0
  for (const rows of byMarker.values()) {
    if (!opts.all && n) break
    if (solo) {
      for (const p of rows) {
        if (n >= opts.max || (!opts.all && n)) break
        assign[p.letter] = { character: who(n), role: '', body, state: '' }; n++
      }
    } else if (rows.length >= opts.roles.length && n + opts.roles.length <= opts.max) {
      opts.roles.forEach((r, i) => { assign[rows[i].letter] = { character: who(n), role: r, body, state: '' }; n++ })
    }
  }
  return { assign, count: n, reason: n ? '' : 'too_few_slots' }
}
