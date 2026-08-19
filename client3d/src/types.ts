/** AV3D-11: Animations-Marker im Raum (generisches Clip-Vokabular). */
export interface RoomMarker {
  at: [number, number];    // Fraktion der Raum-Grundfläche
  animation: string;       // Clip-Kind (sit, lie, dance, ...)
  /** Blickrichtung der Figur in Grad: 0 = Süd, 90 = Ost, 180 = Nord, 270 = West */
  rotation?: number;
  /** Höhen-Feinjustierung in Metern, additiv zur abgetasteten Auflagehöhe */
  offset_y?: number;
}

/** AV3D-2: Platzierung eines Raums relativ zur Gebäude-Grundfläche. */
export interface RoomLayout {
  x: number;               // linke obere Ecke (Fraktion 0..1)
  y: number;
  w: number;               // Breite/Tiefe (Fraktion 0..1)
  d: number;
  level?: number;          // Etage: 0 = EG, negativ = Keller
  /** Drehung des Raum-Inhalts um die Hochachse in Grad */
  rotation?: number;
  markers?: RoomMarker[];  // AV3D-11
  /** Anker des Diorama-Modells als Fraktionen des Raum-Rechtecks
   *  (Nachtrag 2026-07-24); fehlt = zentriert */
  model_at?: [number, number];
  /** Höhen-Feinjustierung des Diorama-Modells in WELT-Metern — ersetzt für
   *  Räume das stillgelegte Sidecar-offset_y */
  model_offset_y?: number;
  /** Raum dauerhaft zeigen (unabhängig von der Innenansicht) — für
   *  Outdoor-Räume, die NICHT schon im Gebäude-Modell abgebildet sind.
   *  Default: false */
  always_visible?: boolean;
}

export interface Room {
  id: string;
  name: string;
  description?: string;
  /** "indoor" | "outdoor" — Outdoor-Räume liegen außerhalb des
   *  Gebäude-Grundrisses und sind immer sichtbar */
  indoor?: string;
  layout?: RoomLayout;
}

/** AV3D-1: optionale 3D-Metadaten einer Location. */
export interface Map3dMeta {
  style?: string;   // house | tower | shop | hall | generic | ...
  floors?: number;
  /** Flächen-Location (Dorf, See, Wald) — das Modell IST der Boden bzw.
   *  (mit Detail-Modus) eine ausblendende Hülle. Fürs Panel: Räume sind
   *  dort Zonen, keine Zimmer. */
  area_model?: boolean;
  color?: string;   // Grundfarbe der Fassade, z.B. "#8fa3b0"
  /** Drehung des Gebäude-Modells um die Hochachse in Grad (Fallback: map_rotation_2d) */
  rotation?: number;
  /** Anteil des Modells am Bezugsquadrat der Location (0..1, Default 1) */
  size?: number;
  /** AV3D-12: gezeichneter Gebäude-Grundriss — Polygonpunkte als Fraktionen
   *  des Bezugsquadrats (`plan_width_m`), automatisch geschlossen. Der Client
   *  rendert daraus pro genutzter Etage Boden und Wände (Tür im EG). */
  outline?: [number, number][];
  /** AV3D-12: Fahrstuhl-Position (Fraktion des Referenzquadrats) — wird
   *  automatisch auf allen Etagen platziert; Figuren nutzen ihn beim
   *  Etagenwechsel */
  elevator?: [number, number];
  /** Etagenhöhe in REALEN Metern. Default 3. */
  storey_height_m?: number;
  /** THE FOOTPRINT (contract v6 "Gebiete"): the drawn outline as a closed
   *  point sequence `[x, z]` in LOCAL METRES around the pin, clockwise in map
   *  view, at most 64 points. Concave outlines are allowed. Absent = the
   *  location has no area at all (only a pin) — there is no square fallback. */
  boundary?: [number, number][];
  /** Width of the boundary's bounding box in metres — a DERIVED quantity since
   *  v6 Nr. 2, not a dial: the server recomputes it from `boundary` on every
   *  save. It survives because the consumer contracts (load radius, viewport,
   *  backdrop, texture repeat) are written in terms of it; in the scene payload
   *  it is `extent_m`, and k = 1 — a world metre IS a real metre. */
  plan_width_m?: number;
  /** Bodentextur-Kind je Etage für die Grundriss-Platten (Raum-Rezept §7),
   *  Level-Schlüssel als String: {"0": "parquet", "-1": "stone"} */
  level_floors?: Record<string, string>;
  /** Authored pass-throughs at the LOCATION edge (§ B1 Nr. 13), as the world
   *  editor stores them and the server sanitises them
   *  (`world_ops._sanitize_map3d`): the key exists only when at least one
   *  valid entry survived, so a present, non-empty list IS the statement
   *  "this place has authored ways in".
   *
   *  AUTHORING DATA, not render data: the finished pass-throughs come off the
   *  worldmap row (`MapLocation.openings`, § A1.3) in world metres, and that
   *  is the ONE list anything geometric reads. Nothing anchors an opening from
   *  this raw form — the server does it, for every location, scene or no
   *  scene. */
  boundary_openings?: BoundaryOpeningMeta[];
}

/** One authored boundary opening as `map3d` stores it: `edge` the 0-based
 *  INDEX of the boundary edge it sits on (edge i = point i -> i+1, contract v6
 *  Nr. 5), `at` a fraction along that edge, `width_m` in world metres. */
export interface BoundaryOpeningMeta {
  edge: number;
  at: number;
  width_m: number;
  type?: string;
  room?: string;
}

/** One authored boundary pass-through as the WORLDMAP row delivers it
 *  (§ A1.3, contract v6): computed by the server with the very function the
 *  entry gate of `POST /play/pos` measures with
 *  (`boundary_entry.opening_world_frames`), so offer and crossing cannot
 *  drift. Everything here is WORLD metres — the client adds no pin, applies no
 *  rotation and derives no normal of its own. */
export interface MapOpening {
  /** boundary EDGE INDEX (edge i = point i -> i+1) */
  edge: number;
  /** the pass-through point, world metres */
  at_world: [number, number];
  /** inward unit normal at that point, world axes (x east, z south) */
  inward: [number, number];
  /** room this opening routes into; '' = none, then the arrival rule decides */
  room?: string;
}

export interface WorldLocation {
  id: string;
  name: string;
  description?: string;
  /** Free metre position of the location's CENTRE on the world plane
   *  (seamless world, E1). `null` = unplaced, i.e. not on the map at all —
   *  the grid cell it used to sit in no longer exists. */
  pos_x: number | null;
  pos_z: number | null;
  /** Rotation of the location's footprint about the up axis, in degrees,
   *  world-map convention (§ A1.1). Always present, 0 when unrotated. */
  yaw_deg?: number;
  /** THE FOOTPRINT of this location as a POLYGON in LOCAL METRES around the pin
   *  (contract v6 "Gebiete"), hoisted out of `map3d` by the server on the
   *  worldmap row. A legacy square arrives as its four synthesized corners, so
   *  the client never needs a square code path; `null`/absent = no area. */
  boundary?: [number, number][] | null;
  /** Width of the footprint's bounding box in world metres — DERIVED from
   *  `boundary` (v6 Nr. 2), hoisted out of `map3d` by the server on the
   *  worldmap row. It scales the surface texture and the selection ring;
   *  containment and area come from `boundary` alone. */
  plan_width_m?: number | null;
  /** The authored boundary pass-throughs in WORLD metres, hoisted onto this
   *  record from the worldmap row (§ A1.3) — the only opening list the client
   *  reads. Empty = FREE boundary, absent = the row said nothing (an
   *  unplaced location, which has no way in to speak of). */
  openings?: MapOpening[];
  rooms: Room[];
  passable?: boolean;
  entry_room?: string;
  template_location_id?: string;
  map_rotation_2d?: number;
  indoor?: string;
  background_images?: string[];
  terrain?: string;   // AV3D-7: grass | forest | road | water | ...
  /** The surface-library kind the server resolved `terrain` to — '' when it
   *  names no entry. THE ground kind of this location; the client does not
   *  look the mapping up itself (plan-grundflaeche.md § 5). */
  surface_kind?: string;
  map3d?: Map3dMeta;  // AV3D-1
}

/** One row of `/play/worldmap → locations` (§ A12, metre world).
 *
 *  Deliberately SLIM: the map builds a footprint from it and nothing else.
 *  Everything the detail scene needs comes from the scene recipe, and the
 *  fields the grid world carried here (terrain/surface_kind, map_rotation_2d,
 *  template_location_id) are not in the payload any more. */
export interface MapLocation {
  id: string;
  name: string;
  /** Centre of the footprint in world metres; `null` = unplaced. */
  pos_x: number | null;
  pos_z: number | null;
  /** Footprint rotation in degrees (world-map convention, § A1.1). */
  yaw_deg: number;
  /** THE FOOTPRINT as a polygon in LOCAL METRES around the pin (v6 "Gebiete").
   *  A legacy square arrives as its four synthesized corners; `null` = the
   *  location has no area. */
  boundary?: [number, number][] | null;
  /** Width of the footprint's bounding box in world metres, DERIVED from
   *  `boundary` by the server. `null` when the location has no area. */
  plan_width_m: number | null;
  /** THE authored pass-throughs, computed in WORLD metres (§ A1.3, v6). Always
   *  present; the EMPTY list is the free-boundary statement ("this place never
   *  said where its way in is"), and a non-empty one names the only ways in. */
  openings: MapOpening[];
  /** A transit place (a road) is walked THROUGH, never travelled TO. */
  passable?: boolean;
  map3d?: Map3dMeta;  // AV3D-1 (only emitted when set)
  /** Bumps when a room layout of this location changes — a running client
   *  loads `/world/locations` once and refetches on this. */
  layout_sig?: string;
}

/** Server-authoritative journey along a METRE polyline (contract § A11).
 *
 *  The client walks the line by DISTANCE (`progress_m`), never by re-deriving
 *  the timing: the baked cumulative game seconds stay server-internal. */
export interface MapTravel {
  target_id: string;
  /** The route as world points `[x, z]`, start to goal. `null` under the fog
   *  (§ A12): a metre-exact line to a place the avatar may not know would
   *  leak more than the opaque `target_id` — then the figure is drawn at its
   *  `pos` and no line is shown. */
  waypoints: [number, number][] | null;
  /** metres already walked, and the whole length of the polyline. `null`
   *  under the fog (§ A12) — a foreign traveller keeps its row, but distance
   *  and route length are thinned out along with the waypoints. */
  progress_m: number | null;
  total_m: number | null;
  /** Arrival on the WORLD CALENDAR as the canonical stamp
   *  `Y0002-D109T14:00:00` (§ A11) — there is no world timezone any more and
   *  no client parses this. `null` under the fog (§ A12) — the arrival time
   *  would date the hidden route. */
  eta_game: string | null;
  /** The same arrival ALREADY RENDERED by the server: `eta_hhmm` is the clock
   *  time ("14:00") the walking mark shows, `eta_label` the full calendar
   *  label ("Summer, day 17 · 14:00 · Year 3"). `null` under the fog. */
  eta_hhmm: string | null;
  eta_label: string | null;
  /** NOMINAL pace of the journey in metres per REAL second; `null` on a
   *  frozen world. The fallback when the segment pace is missing. */
  speed_m_s_real: number | null;
  /** Pace of the segment being walked RIGHT NOW (terrain `speed_factor` is
   *  baked into the stamps, not into `speed_m_s`), metres per REAL second.
   *  `null` on a frozen clock, after arrival and for a degenerate segment —
   *  the three cases where the number would be a lie. */
  pace_m_s_real: number | null;
}

export interface MapCharacter {
  name: string;
  location_id: string;
  /** Free metre point of the figure, or `null` when it has none (its
   *  location is unplaced). Clients place the figure BY `pos` and only fall
   *  back to the location centre when it is null. */
  pos: { x: number; z: number } | null;
  /** AV3D-6: Animations-Kategorie der aktuellen Aktivität (autoritativ) */
  activity_animation?: string;
  /** Fallback-Kette der Clip-Sets, z.B. ["lady","female"] */
  animation_sets?: string[];
  animation_set?: string;
  /** Körpergröße in cm — bestimmt die Skalierung der 3D-Figur */
  height_cm?: number;
  room_id?: string;   // AV3D-8
  mood?: string;      // AV3D-8
  activity?: string;
  movement_target_id?: string;
  movement_target_name?: string;
  /** running journey (§ A11); null/absent when the character is not travelling */
  travel?: MapTravel | null;
  avatar_url?: string;
}

export interface MapEvent {
  category: string;
  text: string;
}

/** Extent of the world in METRES over ALL placed locations (contract § A12) —
 *  computed BEFORE the fog filter, so the map frame does not move while one
 *  discovers. A location with a scale anchor contributes its whole footprint
 *  box, one without it only its centre point. `null` when nothing is placed. */
export interface WorldBounds {
  min_x: number;
  min_z: number;
  max_x: number;
  max_z: number;
}

/**
 * One instant on the WORLD CALENDAR, rendered by the server (§ A11,
 * plan-game-calendar): seasons and days instead of a real date, and no
 * timezone anywhere. The client displays these fields and reads
 * `hour_fraction` for the sun — it never parses `canonical`.
 */
export interface GameTimeInfo {
  /** sortable stamp `Y0002-D109T14:00:00` */
  canonical: string;
  total_seconds: number;
  year: number;
  day_of_year: number;
  season: string;
  season_name: string;
  day_of_season: number;
  hour: number;
  minute: number;
  /** hour of day 0..24 as a fraction — what the sun position is set from */
  hour_fraction: number;
  /** e.g. "Summer, day 17 · 14:23 · Year 3" */
  label: string;
  /** "HH:MM" */
  time: string;
  is_night: boolean;
  day_bucket: string;
}

export interface WorldMap {
  avatar: string;
  current_location_id: string;
  /** Only what the avatar knows — unless this is the admin's unfiltered view
   *  (`?all=1`, § A12). */
  locations: MapLocation[];
  characters: MapCharacter[];
  events_by_location: Record<string, MapEvent[]>;
  /** The WORLD CLOCK this payload was computed with — the instant every
   *  journey above was placed on, handed over ready to render. The sun takes
   *  its hour from `hour_fraction` HERE (one source, no extra poll); nothing
   *  in the client derives a game hour itself. */
  game_time?: GameTimeInfo;
  /** § A12; `null` when nothing is placed */
  world_bounds: WorldBounds | null;
  /** Signature of the painted terrain (areas + world type rows). When it
   *  changes, `/play/terrain` is refetched — the poll carries the sig so the
   *  terrain itself needs no polling of its own. */
  terrain_sig: string;
  /** Signature of the world RELIEF (§ A16), the same trigger one step further:
   *  when it changes, `/play/heightfield` is refetched and the ground is
   *  draped again. Missing (an older server) means a flat world. */
  height_sig?: string;
  /** `true` = this is the filtered view, so unknown places stay hidden.
   *  `false` = the admin's unfiltered view (`?all=1`).
   *
   *  NOTHING DRAWS ON IT any more (contract v6 Nr. 8, decision E1.3): the veil
   *  is gone, and what the server withholds simply has no row here. The field
   *  stays because it is the payload's own shape. */
  fogged: boolean;
  /** The two WALK LIMITS the server judges every reported point with
   *  (`game.max_step_height_m` / `game.max_slope_deg`, § A12/§ A15). The
   *  client mirrors the height gate with them so the figure never walks into
   *  a refusal it could have seen coming; missing (an older server) means the
   *  built-in defaults 0.4 m / 40° apply. */
  max_step_height_m?: number;
  max_slope_deg?: number;
  /** The far backdrop (§ A17) — the mountain silhouette at the world's
   *  horizon, pure scenery. MISSING MEANS OFF, and that is also what an older
   *  server sends: there is no default ring. */
  backdrop?: BackdropSpec;
  /** The AUTHORED props of the world plane (§ A9a) — single objects outside
   *  any location, capped at 500 per world. NEVER FOGGED: pure decoration
   *  belongs to no place and leaks no knowledge. Missing (an older server) is
   *  the same state as an empty list. */
  world_props?: WorldPropSpec[];
  /** Signature over the FINISHED `world_props` block — the same trigger shape
   *  as `terrain_sig`: when it moves the props are rebuilt, and never
   *  otherwise. */
  world_props_sig?: string;
}

/**
 * ONE authored prop on the world plane (§ A9a).
 *
 * A placement spec, not a library record: everything about the PROP
 * (`max_m`, `fix_euler`, the tier maps) is derived by the server on every
 * poll, so a size corrected in the Props tab arrives without a rewrite.
 *
 * `bottom_y` is deliberately NOT in here — the client samples the ground under
 * `(x, z)` with its own height sampler and adds `offset_y`, so a prop sticks
 * to the relief that is really drawn.
 */
export interface WorldPropSpec {
  /** Placement id — stable, and the SEED of the variant formula (§ A9a). */
  id: string;
  prop_id: string;
  /** Library display name (debug/labels); the renderer draws no text from it. */
  name?: string;
  /** World metres. */
  x: number;
  z: number;
  /** Degrees, this contract's turning sense (§ A1.1). */
  yaw_deg: number;
  /** Metres ABOVE the sampled ground — a knob for a half-buried rock. */
  offset_y: number;
  /** Largest REAL edge of the object in metres; scaled with `measure: 'xyz'`,
   *  the one scale law of `place()` (§ B2). */
  max_m: number;
  /** Always `'xyz'` — stated so the row is a complete placement spec. */
  measure?: string;
  fix_euler: { x: number; y: number; z: number };
  /** Tier map of the PRIMARY variant (`variants === model_variants[0]`). */
  variants: Record<string, string>;
  /** Only present when the prop really HAS more than one active variant. */
  model_variants?: Record<string, string>[];
  /** Resolved index into `model_variants` — the SERVER chooses it (§ A9a). */
  variant?: number;
}

/**
 * The `backdrop` block of the worldmap payload (§ A17). The server authors it
 * (`app/core/backdrop.py`) and hands the arcs over ALREADY RESOLVED to
 * degrees — the client never translates a compass point, it draws what it is
 * given.
 */
export interface BackdropSpec {
  /** ridge height in world metres, server-clamped to [20; 300] */
  height_m: number;
  /** uint32 — the ridge is a pure function of it */
  seed: number;
  /** wrap-free ranges on the figure compass (§ A1.8, 0 = south, 90 = east):
   *  `0 <= start < 360`, `start < end <= start + 360`. The full ring is the
   *  one arc `[0, 360]`. */
  arcs: Array<[number, number]>;
}

/**
 * Answer of `POST /play/pos` — the free walker's position report (§ task 5).
 *
 * `ok: true` is the accepted report: `pos` is what the server stored (its own
 * rounding), `location_id`/`room_id` are what the point derived, which is how
 * a crossing announces itself before the next worldmap poll repeats it.
 *
 * `ok: false` with `throttled` is the ONE non-error refusal: the report came
 * in faster than the server accepts them (~4 a second) and was dropped. It is
 * not a failure and never reaches the player — the next report carries the
 * same position anyway.
 *
 * Everything else is a 4xx and arrives as an `ApiError` with the server's
 * `reason`, its player-facing `message` and the LAST VALID point to snap the
 * figure back onto.
 */
export interface PosReport {
  ok: boolean;
  throttled?: boolean;
  pos?: { x: number; z: number };
  location_id?: string;
  room_id?: string;
}

// --- Painted terrain (`GET /play/terrain`) -----------------------------------
// The ground of the seamless world: areas drawn on the metre plane plus the
// effective type catalog they reference. NEVER withheld — terrain is always
// visible, only locations hide.

/** One entry of the terrain-type catalog (`app/core/terrain_types.py`). No
 *  ground property is ever hardcoded in a client: colour, passability and
 *  pace all come from here. */
export interface TerrainType {
  /** the id — of the terrain catalog alone. It says NOTHING about the ground
   *  material any more: which surface a kind wears is `surface` below. */
  kind: string;
  /** display name; falls back to the kind */
  name: string;
  /** WHICH SURFACE-LIBRARY ENTRY SKINS THIS GROUND (2026-08-16) — a kind of
   *  `/assets/surface-textures`, said by the author instead of matched by
   *  name. Absent = no material was named, and the ground keeps the
   *  procedural fallback in `color`; a value the library does not hold means
   *  the same, and is the admin tab's business to flag, never the renderer's
   *  to guess around. There is NO fallback to `kind`: two types may share one
   *  material, a type may wear a differently named one, and renaming a
   *  library entry no longer undresses a ground behind the author's back. */
  surface?: string;
  /** `#rrggbb`, the schematic fill of this kind (2D map, minimap, and the
   *  3D fallback when the surface library has no texture for it) */
  color: string;
  /** may one STAND here — the wilderness answer; inside a placed footprint
   *  the footprint wins (§ A15) */
  passable: boolean;
  /** walking-pace multiplier, 0..2 — it counts EVERYWHERE (§ A1.5, finding 3),
   *  a footprint only neutralises a factor of 0 */
  speed_factor: number;
  /** Open bag of extras — a type says how ground LOOKS and how it is walked,
   *  nothing about what grows on it (the scatter moved to the AREA with
   *  finding B17). FOUR keys in it are a contract: `move_anim`, `idle_anim`
   *  and the two depths `move_sink_m` / `idle_sink_m`. */
  meta?: TerrainTypeMeta;
}

/** A type's `meta`. Free-form by contract — the two keys with a meaning are
 *  named, the rest stays open. */
export interface TerrainTypeMeta {
  /** The clip a MOVING figure plays on this ground instead of walk/run
   *  (§ A9, finding 3) — a kind out of the open clip vocabulary, e.g.
   *  `swim` on water. Absent = walk/run as always; the server never stores
   *  an empty one. */
  move_anim?: string;
  /** The clip a STANDING figure plays on this ground instead of its own
   *  standing one (§ A9, the water round of 2026-08-13) — e.g.
   *  `treading-water` on water. Absent = the standing clip as always. */
  idle_anim?: string;
  /** How deep a figure stands IN this ground while it MOVES over it, in metres
   *  (§ A9, 0…1.5). The clip is normalised onto the surface, which puts a
   *  swimmer on top of the lake; this is the extra drop. Absent = nothing
   *  sinks. */
  move_sink_m?: number;
  /** The same for a figure WAITING on it — a second number, because the pose
   *  is a different one (finding 13): a swimmer lies flat and its knee is a
   *  hand's width down, a treader hangs upright and its foot is a body length
   *  down. Only in force where the ground also names an `idle_anim`. */
  idle_sink_m?: number;
  /** How far what GROWS on this ground bends in the wind, in metres (§ A9,
   *  0.01…0.5) — the sideways deflection of a blade's TIP, quadratic in the
   *  height above the ground. Read per painted AREA, so every scatter entry
   *  of one shape sways together; the area's FILL never moves. Absent = the
   *  scatter stands still. */
  sway_m?: number;
  /** How much grows on this ground WITHOUT anybody authoring it (§ A9,
   *  0…1) — the share of the client's full undergrowth density the kind
   *  carries, seeded 0.6 on `forest` and 0.3 on `grass`. Absent = bare
   *  ground. Everything else about the layer (where the tufts stand, how
   *  tall they are, how far they are drawn) belongs to the renderer. */
  undergrowth?: number;
  [key: string]: unknown;
}

/** What an area GROWS — `meta.scatter[]`, one entry per prop kind. The server
 *  STORES exactly three fields (`app/models/terrain._sanitize_scatter_list`)
 *  and adds `variants`, `prop_height_m` + `sway_factor` on delivery;
 *  `scene/ground.ts` reads them and hands them to the shared sampler. */
export interface TerrainScatterEntry {
  /** instances per 100 m2 of the painted area; 0 = nothing is scattered */
  density_per_100m2: number;
  /** URL of a model to instance; absent = the built-in tuft */
  model?: string;
  /** TARGET height in metres — the prop is scaled until its bounding box is
   *  this tall, and the built-in tuft is built this high. Absent = the prop's
   *  own `prop_height_m`, see there. */
  height_m?: number;
  /** The REAL height of the prop behind `model`, in metres, from its library
   *  record — added by `GET /play/terrain`, never stored and never authored.
   *  It is the target height when the entry authors none, so a tree scatters
   *  as a tree instead of at the flat fallback (`scatterTargetH`). Absent
   *  (a foreign URL, no model, an old cached answer) = the fallback. */
  prop_height_m?: number;
  /** How much of its ground's wind the prop behind `model` takes part in
   *  (0..1) — added by `GET /play/terrain` from the library record, never
   *  stored on the entry and never authored here. The effective deflection is
   *  the kind's `meta.sway_m` times this (`scatterSway`), so a boulder at 0
   *  stands still in a meadow whose ferns bend fully. Absent = 1, the full
   *  amount: the server ships the key only when it differs. */
  sway_factor?: number;
  /** The resolution tiers this prop REALLY has, per tier token
   *  (`{full: "/assets/props/<id>/model?tier=full", …}`) — added by
   *  `GET /play/terrain`, never stored and never authored. Resolved with the
   *  one `pickVariant` rule; absent (an old cached answer, a foreign URL)
   *  means `model` is all there is. */
  variants?: Record<string, string>;
}

/** An area's `meta`. Free-form by contract — the known key is named, the rest
 *  stays open. */
export interface TerrainMeta {
  scatter?: TerrainScatterEntry[];
  [key: string]: unknown;
}

/** One painted area. `polygon` is a ring of world points `[x, z]` in metres;
 *  the list is sorted BOTTOM TO TOP by the server (z_order, then paint
 *  order), so the LAST entry is drawn on top. */
export interface TerrainArea {
  id: string;
  kind: string;
  polygon: [number, number][];
  z_order: number;
  meta?: TerrainMeta;
}

export interface TerrainPayload {
  /** the kind of the unpainted ground — the same resolver the walk rules use */
  default_kind: string;
  types: TerrainType[];
  areas: TerrainArea[];
  /** matches `WorldMap.terrain_sig`; a change means refetch */
  sig: string;
}

export interface AtLocationChar {
  name: string;
  avatar_url?: string;
  same_room?: boolean;
  room?: string;
}

export interface AuthUser {
  id: string;
  username: string;
  role: string;
}
