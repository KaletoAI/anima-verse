/**
 * mapTypes — what the map editor reads from the server, nothing more.
 *
 * The shapes follow the contract (`docs/schnittstellen-3d.md` § A1.3 worldmap,
 * § A1.5 terrain, § A1.7 editor CRUD). The 3D metadata block is NOT re-declared
 * here — `Map3D` lives once, in `../world/worldTypes`, and both the location
 * editor and the map read the same declaration.
 *
 * ONE TYPE PER ENDPOINT. The two location sources look alike and are not:
 * `GET /play/worldmap` rows carry only the § A1.3 fields, `GET /world/locations`
 * dicts carry the full record. Blending them into one optional-everything
 * interface would let a filter on `template_location_id` compile against
 * worldmap rows and silently return nothing. They share their geometry through
 * `MapGeometry` and part ways after it.
 */
import type { ScatterPropBox } from '@anima/scene-render'

import type { MapBounds, StrokeStyle } from './mapMath'
import type { Map3D, RoomLayout } from '../world/worldTypes'

export type { Map3D }

/**
 * The map geometry every location carries, wherever it comes from.
 *
 * `pos_x`/`pos_z` are world METRES and `null` when the location is unplaced —
 * it then stands on no map at all. `yaw_deg` is the § A1.1 rotation and is
 * written through unchanged: NO sign conversion anywhere in the editor
 * (the scene-side `map3d.rotation` that used to sit next to it is gone with
 * v6 Nr. 10 — the pin is the only turn a location has).
 */
export interface MapGeometry {
  id: string
  name: string
  pos_x?: number | null
  pos_z?: number | null
  yaw_deg?: number | null
  /** Edge length of the footprint square in metres. `null` means unplaced OR
   *  no usable anchor — either way the location has no area. */
  plan_width_m?: number | null
  map3d?: Map3D
}

/**
 * A location row of `GET /play/worldmap` — EXACTLY the fields § A1.3 lists,
 * nothing else. The gameplay payload knows no templates and no descriptions;
 * a filter on them here would silently match nothing. Use `EditorLocation`
 * when you need them.
 */
export interface WorldmapLocationRow extends MapGeometry {
  /** The DRAWN footprint (contract v6 Nr. 1), hoisted out of `map3d`: the
   *  same LOCAL-metre points, `null` when the location has no area. A map
   *  client draws it through the § A1.1 pin transform; the editor reads the
   *  nested one, because it edits the record. */
  boundary?: Array<[number, number]> | null
  /** Present only when at least one room carries a layout (AV3D-2⁺). */
  layout_sig?: string
  /** A transit place (a road, a district) is walked THROUGH, never travelled
   *  TO (§ A1.9). The player map draws it differently, the destination list
   *  drops it — it is NOT the terrain passability, which lives on
   *  `TerrainType`. */
  passable?: boolean
}

/** The running journey of a character (§ A11) — the metre polyline plus how
 *  far along it the walker is. `waypoints` is `null` for EVERYONE but the
 *  avatar in a fogged payload (§ A12), so a client that has only the point
 *  draws only the point. */
export interface WorldmapTravel {
  target_id: string
  waypoints: Array<[number, number]> | null
  /** `null` under the fog (§ A12): the row stays (the `target_id` is opaque),
   *  but route, distance and timing are thinned out for foreign travellers. */
  progress_m: number | null
  total_m: number | null
  /** Arrival on the WORLD CALENDAR as the canonical stamp
   *  `Y0002-D109T14:00:00` — there is no world timezone any more, and no
   *  client parses this. `null` under the fog (§ A12). */
  eta_game: string | null
  /** The same arrival rendered by the SERVER: `eta_hhmm` is the clock time
   *  ("14:00"), `eta_label` the full calendar label ("Summer, day 17 · 14:00
   *  · Year 3"). `null` under the fog, like everything else in this block. */
  eta_hhmm: string | null
  eta_label: string | null
  speed_m_s_real: number | null
  pace_m_s_real: number | null
}

/**
 * A location dict of `GET /world/locations` — the editor's read side. It has
 * the full record, so it is the ONLY shape that may be asked about templates
 * or clone origins, and it carries the raw scale anchor of UNPLACED locations
 * too (in `map3d.plan_width_m`, which the worldmap row would report as null).
 *
 * `passable` here means "may be walked into as a place" — it is NOT the
 * terrain flag. Ground passability lives on `TerrainType` (§ A1.5) and nowhere
 * else.
 */
export interface EditorLocation extends MapGeometry {
  passable?: boolean
  template_location_id?: string
  description?: string
  /** Chosen gallery file for the flat map icon (`PATCH .../map-image`); empty
   *  falls back to the first `map_2d` image of the gallery owner. */
  map_image_2d?: string
  /** 90°-step display rotation of that ICON (`PATCH .../map-rotation`) — it
   *  turns the artwork inside the footprint and is NOT `yaw_deg`, which turns
   *  the location itself in the world. */
  map_rotation_2d?: number
  /** Server findings about the DRAWN boundary (contract v6 Nr. 1), today only
   *  `boundary_self_intersection`. Absent = nothing to report. The scene
   *  payload reports the same kinds in its `problems[]`, but a bare location
   *  (a pin with an outline and no rooms) composes no scene at all — this
   *  field is how the map editor hears about it anyway. */
  boundary_problems?: string[]
  /** The location's ROOMS with their floor-plan layouts, exactly as the full
   *  record carries them (`world_ops.build_locations_payload` returns
   *  `list_locations()` untouched, so nothing had to be added server-side for
   *  this). The map's "Rooms" view draws their hulls over the painted ground
   *  — see `roomShapes`. Only the two fields it needs are declared: this is
   *  the MAP's read of a location, and the room EDITOR reads the same records
   *  through `worldTypes.Location`, which has the rest. */
  rooms?: Array<{ id?: string; name?: string; layout?: RoomLayout }>
}

/** A character on the worldmap (§ A1.4). `pos` is the truth; `location_id` is
 *  derived from it, and an empty one plus a `pos` means WILDERNESS. */
export interface WorldmapCharacter {
  name: string
  location_id: string
  pos: { x: number; z: number } | null
  height_cm: number | null
  room_id: string
  activity: string
  activity_animation: string
  animation_set: string
  animation_sets: string[]
  mood: string
  movement_target_id: string
  movement_target_name: string
  travel: WorldmapTravel | null
  avatar_url: string
}

/** `GET /play/worldmap` (§ A1.3). `world_bounds` is computed BEFORE the fog
 *  filter, so the frame does not jump when the avatar discovers something —
 *  and it may be degenerate. Refetch `GET /play/terrain` when `terrain_sig`
 *  changes, never otherwise. */
export interface WorldmapPayload {
  avatar: string
  current_location_id: string
  locations: WorldmapLocationRow[]
  characters: WorldmapCharacter[]
  events_by_location: Record<string, Array<{ category: string; text: string }>>
  world_bounds: MapBounds | null
  terrain_sig: string
  /** Signature of the authored RELIEF (§ A16) — the refetch trigger for the
   *  heightfield, exactly as `terrain_sig` is for the painted ground. */
  height_sig?: string
  fogged: boolean
  /** The two walk limits the server judges every reported point with
   *  (§ A1.3, § A15 Nr. 8). The map editor needs `max_slope_deg` to say when a
   *  drawn ramp is steeper than anyone can climb. Optional: an older server
   *  does not send them, and then the same defaults apply that
   *  `app/core/relief.py` falls back to. */
  max_step_height_m?: number
  max_slope_deg?: number
}

/**
 * One entry of `meta.scatter` of a painted AREA — what this piece of ground
 * grows (finding B17; it used to hang on the terrain TYPE, which could only
 * ever say "all forest everywhere grows this one tree").
 *
 * The server whitelists exactly these four fields
 * (`app/models/terrain._sanitize_scatter_list`), the 3D ground instances them
 * and the map preview draws them — all three from the ONE shared sampler
 * (`@anima/scene-render` → `scatterInstances`). No list = nothing is
 * scattered; there is no default.
 */
export interface TerrainScatterEntry {
  /** Instances per 100 m² of the painted area. 0 = nothing is scattered. */
  density_per_100m2: number
  /** TARGET height in metres: a prop model is scaled uniformly until its
   *  bounding box is this tall, and the built-in tuft is built this high.
   *  Absent = the prop's OWN height from the library (the server ships it as
   *  `prop_height_m`), and only where there is no prop record the 3D client's
   *  flat 2 m (0.8 m for a tuft) — never the model's authored file size,
   *  which is no size at all in a world measured in metres. */
  height_m?: number
  /** URL of a prop mesh to instance — `/assets/props/<id>/model`, the same
   *  URL the prop library hands out. Absent = the built-in tuft. */
  model?: string
  /** The least distance in metres THIS entry's own instances keep from each
   *  other. Absent or 0 = no constraint. The sampler subtracts a candidate
   *  that stands closer than this to a prop it has already placed, so a row
   *  whose spacing does not fit its density simply ends up thinner
   *  (`@anima/scene-render` → `minSpacingM`). */
  min_spacing_m?: number
}

/** One kind of ground in the effective catalog (§ A1.5). `passable`,
 *  `speed_factor` and the two clip keys come from HERE and nowhere else —
 *  never from an area, never from a client table. `meta` is free-form apart
 *  from those keys; what grows on ground belongs to the AREA (finding B17). */
export interface TerrainType {
  kind: string
  name: string
  /** `#rrggbb` — the colour of the 2D schematic map. */
  color: string
  /** May one STAND here? The WILDERNESS answer: inside a placed footprint the
   *  footprint wins and this says nothing (§ A15). */
  passable: boolean
  /** Walking-pace multiplier, 0..2. Unlike `passable` it counts EVERYWHERE
   *  (finding 3, 2026-08-13) — a footprint only neutralises a factor of 0,
   *  which is a ground nobody meant to be walked rather than a slow one. */
  speed_factor: number
  /** WHICH GROUND MATERIAL this kind wears — the `kind` of the surface-texture
   *  library, said out loud (2026-08-16). It used to be matched by NAME, which
   *  meant a type could never wear a differently named texture and renaming a
   *  library entry undressed every ground using it. The name match is gone
   *  without a fallback: absent or empty = the default ground, exactly what a
   *  type without a same-named library entry rendered before. Nothing is
   *  validated against the library on save — the Terrain tab MARKS a value the
   *  library does not hold instead (§ A1.5). */
  surface?: string
  /** Free-form, with four contracted keys: `meta.move_anim`, the animation
   *  clip a MOVING figure plays on this ground instead of walk/run (§ A9 —
   *  "swim" on water), `meta.idle_anim`, the one a STANDING figure plays
   *  instead of its own ("treading-water"), and the two depths
   *  `meta.move_sink_m` / `meta.idle_sink_m`, how deep the figure stands IN
   *  the ground while it moves and while it waits (two numbers, because the
   *  two poses hang differently in the water). Absent = walk, run and idle as
   *  usual, on top of the ground; the server never stores an empty one. */
  meta?: Record<string, unknown>
}

/**
 * The RECIPE of an area drawn as a line: a centre line in world metres, the
 * width of the ribbon it becomes, and how the line is BENT on the way. It
 * lives in `meta.stroke` and is exactly that — a recipe. The polygon stays the
 * truth for the server, for point queries and for every renderer; this only
 * lets the editor put the handles back on the line the user drew and generate
 * the very same outline again.
 *
 * The three decoration fields are absent for a straight line, which is what
 * every stroke drawn before the styles existed is: `MapTab.readStroke` fills
 * them in for the editor, `MapTab.storedStroke` strips them again on the way
 * back, and the server whitelists all five (`app/models/terrain.py`).
 *
 * `meta` is free-form JSON the server passes through verbatim, so nothing
 * guarantees a stored `stroke` has this shape — read it through a check, never
 * by trusting the declaration.
 */
export interface TerrainStroke {
  points: Array<[number, number]>
  width_m: number
  /** absent = `straight`, the line as it was clicked */
  style?: StrokeStyle
  /** roughly how far apart the deflections sit, in metres */
  spacing_m?: number
  /** how far they swing to either side of the line, in metres */
  amplitude_m?: number
}

/** An area's `meta`. Free-form by contract — the known key is named, the rest
 *  stays open, and a foreign key written by anything else survives a round
 *  trip through the editor untouched. */
export type TerrainMeta = {
  stroke?: TerrainStroke
  scatter?: TerrainScatterEntry[]
} & TerrainWater & TerrainRelief & Record<string, unknown>

/**
 * HOW BUMPY THIS ONE PAINTED AREA IS (§ A16.2).
 *
 * The micro-relief is baked into the world heightfield — random small hills
 * wherever this area lies, in the ONE height field that the walk rules, the
 * server gate and both renderers read. Nothing renders it separately.
 *
 * IT BELONGS TO THE AREA, NOT TO THE KIND (decision 2026-08-23). It used to be
 * a terrain-TYPE field, which meant every meadow in a world was exactly as
 * bumpy as every other one: "grass" could not be a rolling upland here and a
 * flat pasture there. The kind carries no relief at all any more — there is no
 * default behind these two keys and no fallback reader, so an area that
 * authors nothing is flat.
 *
 * The PATTERN still comes from the kind (the noise seed is a hash of its
 * name), so two areas of one kind asking for the same numbers still continue
 * each other without a seam.
 */
export interface TerrainRelief {
  /** Half-swing of the hills in metres, 0.05…2. Absent = flat. The upper end
   *  is a walkability limit, not a taste one. */
  relief_amplitude_m?: number
  /** Edge length of one swell in metres, 4…200. Absent = the server's 32 m.
   *  The lower end is Nyquist on the 2 m height tiles. */
  relief_wave_m?: number
}

/**
 * WHAT A WATER AREA AUTHORS ABOUT ITSELF (§ A16.3, addendum "Ein Wasser-Gesetz
 * — W1").
 *
 * Water is a KIND (`meta.water` on the terrain type, `isWaterKind` below), and
 * a painted area of such a kind says how ITS water stands: the bake presses
 * the ground under the polygon down to `level − depth` and runs a shore ramp
 * back up to the untouched land, so no relief can poke through the mirror at
 * any distance or in any level of detail.
 *
 * EVERY FIELD IS OPTIONAL, and empty is the normal state:
 *
 * * depth and shore ramp fall back to the KIND's own defaults — which is why
 *   an unreadable value loses its key instead of becoming a number, or a
 *   stored default would silently outrank the kind forever;
 * * the level falls back to the rim median (only the server can compute it);
 * * without a flow direction the mirror is one constant level — the lake of
 *   every round before this one, not a branch beside the river.
 *
 * They live in the area's free-form `meta`, which is a FULL REPLACE on every
 * write, so an unset field is an absent key and never a stored zero.
 */
export type FlowAlong = 'forward' | 'reverse'

/** The two words `meta.flow_along` may carry — the server's own list
 *  (`heightfield.FLOW_ALONG_VALUES`). Anything else is not a third state but
 *  the SAME state as absent: still water. */
export const FLOW_ALONG_VALUES: readonly FlowAlong[] = ['forward', 'reverse']

export interface TerrainWater {
  /** The mirror of STILL water, as a world-y height in metres. Absent = the
   *  rim median. It also sets BOTH ends of a flowing mirror at once. */
  water_level?: number
  /** The UPSTREAM end of a flowing mirror, world y in metres. Absent = the
   *  rim median of the upstream third of the flow axis. */
  water_level_up?: number
  /** The DOWNSTREAM end, same units, same "absent = derived" rule. */
  water_level_down?: number
  /** Which way POLYGON water FLOWS (downstream), 0…360, wrapped not clamped —
   *  spelled like every other yaw of the contract (§ A1.1): 0° toward +z,
   *  90° toward +x. Absent = still water, one constant level. An area drawn
   *  with the LINE tool carries its own axis and uses `flow_along` instead;
   *  where both are set the line wins and this is ignored (W4a). */
  flow_dir_deg?: number
  /** Which way an area drawn as a LINE flows ALONG that line (W4a): in the
   *  order its points were drawn (`forward`), against it (`reverse`), or
   *  absent = still. A river bends, and one bearing cannot say where a
   *  meander runs — so the line the author drew IS the flow axis. */
  flow_along?: FlowAlong
  /** How fast this ONE water runs, in metres per second (0…2). Absent = the
   *  speed of its SURFACE KIND (`flow_speed` on the kind's material), which is
   *  where a world tunes all its rivers at once. It is a look and nothing else:
   *  the bake, the mirror and the flow axis do not read it. */
  flow_speed_m_s?: number
  /** How deep the bed is carved under the mirror, in metres (0.2…20).
   *  Absent = the kind's own default. */
  water_depth_m?: number
  /** Over how many metres the bed climbs back to the untouched land at the
   *  shore, in metres (0…20). 0 = a wall at the water's edge; absent = the
   *  kind's own default. */
  shore_ramp_m?: number
  /** Which terrain kind the layer bake paints UNDER this water. Absent = the
   *  bare world (`default_kind`). */
  bed_kind?: string
}

/** One knot of a flow axis: `[x, z, s, level]` — the world position, the arc
 *  length from the FIRST knot, and the mirror height there. The server's own
 *  tuple (`heightfield.WaterKnot`), field for field. */
export type TerrainWaterKnot = [number, number, number, number]

/**
 * THE MIRROR AS A FUNCTION OF THE PLACE — server OUTPUT, never authored
 * (`meta.water_profile`, W1 § 2 / W4a).
 *
 * SINCE W4a THE AXIS IS A POLYLINE, and `axis` is the truth:
 *
 *     s     = arc coordinate of the NEAREST point on the polyline
 *             (every segment projected with a clamp, shortest distance wins)
 *     level = linear between the two knots s falls between, clamped at both
 *             ends of the line
 *
 * Both older laws fall out of it instead of standing beside it: still water is
 * ONE knot (the clamp answers its level everywhere) and a straight river is
 * TWO (the projection onto that single segment IS W1's
 * `clamp((s − s_min)/span, 0, 1)`). `mapMath.waterLevelAt` is the editor's
 * twin of that function.
 *
 * The nine numbers stay what they were — the best SINGLE tilted plane through
 * the same water, for a reader that has not learned the polyline. The editor
 * only READS all of it: the two end levels are what the area panel shows back
 * where the author left them open, and the server drops both this and
 * `water_level_effective` on the way in.
 */
export interface TerrainWaterProfile {
  level_up: number
  level_down: number
  flow_dir_deg: number | null
  axis_x: number
  axis_z: number
  dir_x: number
  dir_z: number
  s_min: number
  s_max: number
  /** The knots in FLOW order, never empty: one = still, two = the straight
   *  axis of W1, N = the line the author drew (W4a). */
  axis: TerrainWaterKnot[]
}

/** A painted polygon in world metres (§ A1.5). Points are `[x, z]`, 3–256 of
 *  them, auto-closed by the server. */
export interface TerrainArea {
  id: string
  kind: string
  polygon: Array<[number, number]>
  z_order: number
  meta?: TerrainMeta
}

/**
 * The scatter list of an area, read through a check.
 *
 * `meta` is free-form JSON the server passes through, so nothing in the type
 * system guarantees a stored `scatter` has the declared shape — and most areas
 * carry none at all. The server whitelists what it STORES
 * (`app/models/terrain._sanitize_scatter_list`); this is the reader's half of
 * the same contract, and it is the ONE place the editor reads it, so the chip
 * and the preview always see the same list.
 *
 * Every field is coerced, never trusted: a junk density is 0 (scatter nothing,
 * exactly how both renderers read it), and a height that is not a height or a
 * spacing that is not a spacing loses its key — so a model keeps its own size
 * and a row nobody spaced is sampled as it always was.
 */
export function readScatter(meta: TerrainMeta | undefined): TerrainScatterEntry[] {
  const raw = meta?.scatter
  if (!Array.isArray(raw)) return []
  const out: TerrainScatterEntry[] = []
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue
    const e = item as unknown as Record<string, unknown>
    const density = Number(e.density_per_100m2)
    const height = Number(e.height_m)
    const spacing = Number(e.min_spacing_m)
    const entry: TerrainScatterEntry = {
      density_per_100m2: Number.isFinite(density) && density > 0 ? density : 0,
    }
    if (Number.isFinite(height) && height > 0) entry.height_m = height
    if (Number.isFinite(spacing) && spacing > 0) entry.min_spacing_m = spacing
    if (typeof e.model === 'string' && e.model) entry.model = e.model
    out.push(entry)
  }
  return out
}

/**
 * The water numbers of an area, read through a check — the reader's half of
 * `TerrainWater`, exactly as `readScatter` is for the scatter list.
 *
 * `meta` is free-form JSON the server passes through, so nothing in the type
 * system guarantees a stored number IS a number. A value that is not finite
 * loses its key rather than becoming 0: "0 m deep" and "the server decides"
 * are different answers, and only one of them may be inferred from junk.
 */
export function readWater(meta: TerrainMeta | undefined): TerrainWater {
  const out: TerrainWater = {}
  const level = metaNum(meta?.water_level)
  const levelUp = metaNum(meta?.water_level_up)
  const levelDown = metaNum(meta?.water_level_down)
  const flow = metaNum(meta?.flow_dir_deg)
  const depth = metaNum(meta?.water_depth_m)
  const ramp = metaNum(meta?.shore_ramp_m)
  const bed = typeof meta?.bed_kind === 'string' ? meta.bed_kind.trim() : ''
  if (level !== undefined) out.water_level = level
  if (levelUp !== undefined) out.water_level_up = levelUp
  if (levelDown !== undefined) out.water_level_down = levelDown
  // WRAPPED, NOT CLAMPED — `heightfield.sanitize_flow_dir`. A bearing is an
  // angle: 370° is 10° and −90° is 270°, and clamping would turn a slip of the
  // wrist into a river flowing the wrong way along its own axis.
  if (flow !== undefined) out.flow_dir_deg = ((flow % 360) + 360) % 360
  // TWO WORDS OR NOTHING (`terrain._sanitize_water`). A third word is not a
  // third state: it is the same "still" that an absent key is, so it loses the
  // key here exactly as it does on the server.
  const along = typeof meta?.flow_along === 'string'
    ? meta.flow_along.trim().toLowerCase() : ''
  if ((FLOW_ALONG_VALUES as readonly string[]).includes(along)) {
    out.flow_along = along as FlowAlong
  }
  // CLAMPED, like the two widths on the server (`terrain._sanitize_water`) and
  // unlike the bearing: a speed is not an angle, so 5 m/s is not 5 − 2 m/s, it
  // is "as fast as this may go". An unreadable value is no override at all —
  // 0 m/s is a legible authored state (a river standing still) and must not be
  // what `null` or `''` silently means.
  const flowSpeed = metaNum(meta?.flow_speed_m_s)
  if (flowSpeed !== undefined) {
    out.flow_speed_m_s = Math.min(Math.max(flowSpeed, FLOW_SPEED_MIN_M_S),
                                  FLOW_SPEED_MAX_M_S)
  }
  if (depth !== undefined) out.water_depth_m = depth
  if (ramp !== undefined) out.shore_ramp_m = ramp
  if (bed) out.bed_kind = bed
  return out
}

/**
 * The two MICRO-RELIEF numbers of an area, read through a check — the reader's
 * half of `TerrainRelief`, exactly as `readWater` is for the water ones.
 *
 * A value that is not a finite number loses its key rather than becoming 0:
 * "flat" and "the server's default wave" are both written by leaving the key
 * out, and neither may be inferred from junk. Clamping is the SERVER's job
 * (`models.terrain._sanitize_relief`) — the field sends what was typed and
 * refills from the stored answer, so a typed 5 shows up as the stored 2.
 */
export function readRelief(meta: TerrainMeta | undefined): TerrainRelief {
  const out: TerrainRelief = {}
  const amp = metaNum(meta?.relief_amplitude_m)
  const wave = metaNum(meta?.relief_wave_m)
  if (amp !== undefined) out.relief_amplitude_m = amp
  if (wave !== undefined) out.relief_wave_m = wave
  return out
}

/** One number out of free-form `meta`, or `undefined`. `null`, `''` and `[]`
 *  all coerce to 0 in JavaScript, which would invent a stored number where the
 *  key says nothing — only a real, finite number counts. */
function metaNum(v: unknown): number | undefined {
  if (typeof v !== 'number' && typeof v !== 'string') return undefined
  if (typeof v === 'string' && v.trim() === '') return undefined
  const n = Number(v)
  return Number.isFinite(n) ? n : undefined
}

/**
 * The bake's OWN mirror of an area, read through a check
 * (`meta.water_profile`, W1 § 4) — or `null` when the area carries none.
 *
 * It is server output and it is what the panel READS BACK: where the author
 * left an end level open, this is the number the carve really used, so the
 * editor can name it without implementing a rim median a second time. All nine
 * numbers have to be there — a half profile is no profile, and guessing the
 * missing half would be exactly the second opinion this field exists to avoid.
 *
 * AND SINCE W4a THE AXIS IS ONE OF THEM. The knots ARE the mirror; the nine
 * numbers are only its shadow on one plane. So a payload without at least one
 * usable knot is no profile either: rebuilding the axis out of the nine would
 * be that second opinion again, and it would flatten every meander back onto
 * the straight chord the polyline exists to replace. A knot with an unreadable
 * number fails the whole profile for the same reason a level does — half an
 * axis is a mirror with a hole in it.
 */
export function readWaterProfile(meta: TerrainMeta | undefined
                                ): TerrainWaterProfile | null {
  const raw = meta?.water_profile
  if (!raw || typeof raw !== 'object') return null
  const r = raw as Record<string, unknown>
  const nums: Record<string, number> = {}
  for (const key of ['level_up', 'level_down', 'axis_x', 'axis_z',
    'dir_x', 'dir_z', 's_min', 's_max']) {
    const n = metaNum(r[key])
    if (n === undefined) return null
    nums[key] = n
  }
  if (!Array.isArray(r.axis) || !r.axis.length) return null
  const axis: TerrainWaterKnot[] = []
  for (const knot of r.axis as unknown[]) {
    if (!Array.isArray(knot) || knot.length < 4) return null
    const four = [metaNum(knot[0]), metaNum(knot[1]),
      metaNum(knot[2]), metaNum(knot[3])]
    if (four.some((n) => n === undefined)) return null
    axis.push(four as TerrainWaterKnot)
  }
  const flow = metaNum(r.flow_dir_deg)
  return {
    level_up: nums.level_up,
    level_down: nums.level_down,
    flow_dir_deg: flow === undefined ? null : flow,
    axis_x: nums.axis_x,
    axis_z: nums.axis_z,
    dir_x: nums.dir_x,
    dir_z: nums.dir_z,
    s_min: nums.s_min,
    s_max: nums.s_max,
    axis,
  }
}

/**
 * The CENTRE LINE of an area drawn with the line tool, read through a check —
 * or `null` for an ordinary painted polygon.
 *
 * It is the geometry half of `MapTab.readStroke` and exists beside it on
 * purpose: that one builds the whole editable RECIPE (width, style, the two
 * decoration numbers) for the handles, this one answers the single question
 * the map preview and the flow control ask — "does this area carry a line, and
 * where does it run?". Nothing here may import the editor's own minimum point
 * count; the bar is the SERVER's (`heightfield.is_flowing`): two points make
 * an axis, one does not.
 *
 * `meta` is free-form JSON passed through verbatim, so every point is checked.
 * One unreadable coordinate drops the whole line rather than bending it
 * somewhere the author never clicked.
 */
export function readStrokePoints(meta: TerrainMeta | undefined
                                ): Array<[number, number]> | null {
  const raw: unknown = meta?.stroke
  if (!raw || typeof raw !== 'object') return null
  const { points, width_m: width } = raw as Record<string, unknown>
  if (typeof width !== 'number' || !Number.isFinite(width) || width <= 0) return null
  if (!Array.isArray(points) || points.length < 2) return null
  const out: Array<[number, number]> = []
  for (const p of points as unknown[]) {
    if (!Array.isArray(p) || p.length < 2) return null
    const [x, z] = p as unknown[]
    if (typeof x !== 'number' || !Number.isFinite(x)) return null
    if (typeof z !== 'number' || !Number.isFinite(z)) return null
    out.push([x, z])
  }
  return out
}

/**
 * IS THIS TERRAIN KIND WATER? — the client's half of THE ONE PREDICATE
 * (`terrain_types.is_water_kind`, W1).
 *
 * It is the catalog's flag and NOTHING else: not the kind's name, not its
 * colour, and since W1 not the material class of a surface texture either
 * (that second book is deleted — a library texture of class `water` without
 * the flag is a wet look, not physics). A kind the catalog does not know is
 * not water, because nothing said it was.
 */
export function isWaterKind(type: TerrainType | undefined | null): boolean {
  return !!(type?.meta as Record<string, unknown> | undefined)?.water
}

/**
 * THE TWO NUMBERS A WATER KIND DEFAULTS — `terrain_types.water_kind_defaults`.
 *
 * The kind says what its water is normally like; a single painted area says
 * what IT is like and wins (`TerrainWater`). Both are read through the same
 * check, so "the kind says 2 m" and "this lake says 2 m" cannot end up meaning
 * two different things. The module fallbacks are the server's own defaults.
 */
export function waterKindDefaults(type: TerrainType | undefined | null
                                 ): { depthM: number; rampM: number } {
  const meta = type?.meta as Record<string, unknown> | undefined
  const depth = metaNum(meta?.water_depth_m)
  const ramp = metaNum(meta?.shore_ramp_m)
  return {
    depthM: depth === undefined ? WATER_DEPTH_DEFAULT_M : depth,
    rampM: ramp === undefined ? SHORE_RAMP_DEFAULT_M : ramp,
  }
}

/** Server mirrors — `heightfield.WATER_DEPTH_*` / `WATER_SHORE_RAMP_*`. They
 *  live HERE, next to the readers that fall back to them, so the kind editor
 *  and the area panel quote one pair of numbers. */
export const WATER_DEPTH_DEFAULT_M = 2
export const WATER_DEPTH_MIN_M = 0.2
export const WATER_DEPTH_MAX_M = 20
export const SHORE_RAMP_DEFAULT_M = 3
export const SHORE_RAMP_MIN_M = 0
export const SHORE_RAMP_MAX_M = 20
/** A bearing is an angle: the field sweeps a whole turn and 360 wraps to 0. */
export const FLOW_DIR_MIN_DEG = 0
export const FLOW_DIR_MAX_DEG = 360
/** How fast ONE water may be dialled to run, in m/s — the same range the
 *  SURFACE KIND's own `flow_speed` dial has
 *  (`surface_textures._MATERIAL_RANGES`), because an area may say anything its
 *  kind could have said and nothing more. */
export const FLOW_SPEED_MIN_M_S = 0
export const FLOW_SPEED_MAX_M_S = 2
/** What a water kind flows at while it declares nothing — the mirror of
 *  `@anima/scene-render WATER_FLOW_SPEED_DEFAULT_M_S`. Only the hint under the
 *  area's speed field quotes it: the terrain panel does not hold the surface
 *  catalog, so it names the number in force for an untouched kind rather than
 *  guessing at a kind that was edited. */
export const FLOW_SPEED_DEFAULT_M_S = 0.15

/** Server mirrors — `models.terrain.RELIEF_*`. The amplitude's upper end is a
 *  WALKABILITY limit (two neighbouring support points may differ by at most
 *  2·amp over one 2 m tile step, i.e. 63° at the maximum), the wave's lower
 *  one is NYQUIST on that same raster. An area that authors no wave gets the
 *  server's 32 m, which is what the field's placeholder says. */
export const RELIEF_AMP_MIN_M = 0.05
export const RELIEF_AMP_MAX_M = 2
export const RELIEF_WAVE_MIN_M = 4
export const RELIEF_WAVE_MAX_M = 200
export const RELIEF_WAVE_DEFAULT_M = 32

/** `GET /play/terrain`. `areas` arrive BOTTOM to TOP — the last entry is on
 *  top, and the topmost area that contains a point owns it. */
export interface TerrainPayload {
  default_kind: string
  types: TerrainType[]
  areas: TerrainArea[]
  sig: string
  /** `{id: updated_at}` — the VERSION TOKEN of every area, for the map
   *  editor's batch save. A buffered change carries the stamp its area was
   *  loaded with, and the bulk route refuses exactly the objects somebody else
   *  saved in the meantime (`pendingBuffer`, `app/core/bulk_edit.py`). Game
   *  clients ignore it; it is deliberately not part of `sig`, or a re-save
   *  that changes no shape would re-bake every client's ground. */
  stamps?: Record<string, string>
}

/**
 * What a bulk save answers (`PUT /world/{terrain-areas,height-areas,
 * world-props}/bulk`), one shape for all three.
 *
 * ALWAYS HTTP 200, even when parts were refused: the request as a whole
 * succeeded, and `rejected` says per object why. `saved` names the client's
 * `temp_id` next to the object the server stored, which is how a locally drawn
 * shape gets its real, server-minted id.
 */
export interface BulkSaveResp<T> {
  status?: string
  saved?: Array<{ temp_id?: string, area?: T, world_prop?: T }>
  deleted?: string[]
  rejected?: Array<{ op: 'upsert' | 'delete', id: string, temp_id: string,
    reason: string }>
  /** Height batch only: the grid step the world has AFTERWARDS. */
  step_m?: number
}

/**
 * One authored HEIGHT AREA of the world relief (§ A16, `GET /world/height-areas`).
 *
 * The ground inside `polygon` stands at `height_m` and ramps there linearly
 * over the last `falloff_m` metres before the outline, so the area meets the
 * world at 0 exactly ON its own outline. A negative height is a hollow, not a
 * mistake; `falloff_m` 0 is a wall at the edge (legal, and warned about when
 * it is steeper than a walker can climb).
 *
 * It carries NO kind and NO layer: heights are not terrain (the ground under a
 * painted meadow may well rise), and overlaps are resolved by the server
 * arithmetically — the strongest deflection from the flat world wins.
 */
export interface HeightArea {
  id: string
  polygon: Array<[number, number]>
  height_m: number
  falloff_m: number
  meta?: Record<string, unknown>
}

/** `GET /world/height-areas` — the editor's read side of the relief. `sig` is
 *  the same signature the worldmap payload carries as `height_sig`. */
export interface HeightAreasResp {
  areas: HeightArea[]
  sig: string
  /** `{id: updated_at}` — the batch save's version tokens, see
   *  `TerrainPayload.stamps`. */
  stamps?: Record<string, string>
  /** The grid step the world relief is rastered at RIGHT NOW, in metres
   *  (finding 14). Nobody sets it: the server doubles it until the grid over
   *  the whole painted extent fits its point budget, so an area drawn far out
   *  coarsens the relief everywhere. The editor shows it and warns when a save
   *  moves it — see `heightMath.reliefStepNotice`. */
  step_m?: number
  /** The finest step the OVERVIEW gets (`heightfield.DEFAULT_STEP_M`) — what
   *  "coarser than normal" is measured against, so the editor holds no
   *  constant of its own. */
  default_step_m?: number
  /** The step of the fine height TILES (`heightfield.TILE_STEP_M`), a
   *  different number since 2026-08-14. The micro-relief warning of the
   *  terrain tab is measured against it (`heightMath.reliefWarnAmpM`). It
   *  comes from the server for the same reason the two above do: the number
   *  halved the day the tiles did. */
  tile_step_m?: number
  /** The walk gate: steepest slope a figure climbs (`game.max_slope_deg`) and
   *  the highest single step it takes (`game.max_step_height_m`). The same two
   *  numbers `/play/worldmap` carries — here so an editor that shows a relief
   *  amplitude can say when it becomes unwalkable without pulling the whole
   *  map for two floats. */
  max_slope_deg?: number
  max_step_height_m?: number
}

/** What `POST`/`PUT /world/height-areas` answer. The step is the one the world
 *  has AFTERWARDS (the write re-rasters synchronously), which is what makes
 *  the coarsening warning a fact rather than a forecast. */
export interface HeightAreaWriteResp {
  area?: HeightArea
  step_m?: number
}

/** ONE authored prop on the world plane (§ A9a) as the EDITOR reads it —
 *  `GET /world/world-props`, not the worldmap block.
 *
 *  `x`/`z`/`offset_y` are world metres, `yaw_deg` the § A1.1 rotation written
 *  through unchanged. `variant` is `null` for "the placement id decides"
 *  (`world_props.variant_index`) and a number for "this mesh, always".
 *  `missing` marks a placement whose prop was deleted: it renders nothing and
 *  can only be removed. */
export interface WorldProp {
  id: string
  prop_id: string
  x: number
  z: number
  yaw_deg: number
  offset_y: number
  variant: number | null
  /** Library display name; '' together with `missing` when the prop is gone. */
  name?: string
  /** How many ACTIVE variants WITH a mesh the prop has — the editor offers
   *  exactly that many indices instead of holding a ceiling of its own
   *  (`image_generation.prop_variant_max` is configurable). */
  variant_count?: number
  /** The STORE index behind each of those positions, in the same order —
   *  `variant` is a POSITION in the published list (§ B2 addendum), while the
   *  prop page numbers its chips by store index. This is what lets the picker
   *  name the same variant the prop page names. */
  variant_indices?: number[]
  /** Which position the SERVER's formula picks for this placement when
   *  `variant` is null (`world_props.resolved_variant`) — the mesh behind
   *  "Auto". Never recomputed here: the md5 rule lives on the server alone. */
  variant_auto?: number
  missing?: boolean
}

/** One placement's ground box as the world-prop routes ship it: the shared
 *  `ScatterPropBox` (centre, turn, the two half-extents) plus the PLACEMENT it
 *  belongs to. The sampler never needs that id — it only keeps ground clear —
 *  but the editor does: it draws each rectangle on its own prop. */
export interface WorldPropBox extends ScatterPropBox {
  id: string
}

/** `GET /world/world-props` — the placements plus the two cap numbers, so the
 *  editor holds no ceiling of its own (§ A9a: refuse at `max`, warn from
 *  `warn_at`). */
export interface WorldPropsResp {
  world_props: WorldProp[]
  count: number
  /** `{id: updated_at}` — the batch save's version tokens, see
   *  `TerrainPayload.stamps`. */
  stamps?: Record<string, string>
  /**
   * The GROUND BOX of every placement the scatter has to stay out of (§ A9b),
   * the same block `GET /play/terrain` serves the 3D client — centre, turn and
   * the two half-extents of the prop's real size plus the server's margin.
   *
   * It rides on THIS answer because this is what the editor refetches after
   * every prop write, so the preview around a moved bench is right in the same
   * breath the bench moves. `ScatterPropBox` of `@anima/scene-render` is the
   * shape; `propBoxFootprints` turns it into the footprints the preview keeps
   * clear. Absent from an older server = nothing extra is excluded.
   */
  prop_boxes?: WorldPropBox[]
  max: number
  warn_at: number
  sig: string
}

/** `GET /world/terrain-types` — the admin view: the catalog plus where each
 *  entry comes from. */
export interface TerrainTypesResp {
  types: TerrainType[]
  sources: Record<string, 'shared' | 'world'>
}

/** Extent of the world in metres (§ A1.3), the `world_bounds` root field. May
 *  be degenerate (`min == max`); anyone dividing by it must cope. Declared
 *  once, in `mapMath` — the math and the payload mean the same box. */
export type { MapBounds } from './mapMath'
