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
  /** DER Maßstabs-Anker: reale Breite der Location in Metern („der Ort ist
   *  ≈ 12 m breit"). Seit E4 IST das Bezugsquadrat der Fußabdruck, also
   *  `extent_m = plan_width_m` und k = 1 — ein Welt-Meter ist ein echter
   *  Meter. Im Szenen-Payload als `extent_m`. */
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
   *  The scene payload delivers the same openings COMPOSED (world edge letter
   *  after `tile_rotation`, plus a tile-local point) — but only for a
   *  location that HAS a scene. This raw list is the one source that also
   *  answers for a location the scene endpoint 404s on, which is why the free
   *  boundary is judged from it (`enterLocation.freeBoundaryOf`). */
  boundary_openings?: BoundaryOpeningMeta[];
  /** Rotation of the TEMPLATE content inside the footprint, in 90° steps
   *  (contract v5.2 Nr. 15). The server turns the composed scene by it, so a
   *  scene payload never carries it — but the RAW `boundary_openings` above
   *  are stored unturned, and anything that anchors them itself has to apply
   *  it exactly as `boundary_entry._rotated_openings` does. Distinct from
   *  `WorldLocation.yaw_deg`, which turns the whole footprint in the world. */
  tile_rotation?: number;
}

/** One authored boundary opening as `map3d` stores it — TEMPLATE orientation
 *  (`tile_rotation` is applied by the server when it composes the scene), `at`
 *  a fraction along that edge, `width_m` in world metres. */
export interface BoundaryOpeningMeta {
  edge: 'N' | 'E' | 'S' | 'W';
  at: number;
  width_m: number;
  type?: string;
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
  /** Edge length of the footprint square in world metres — the ONE scale
   *  anchor (§ A1.1), hoisted out of `map3d` by the server on the worldmap
   *  row. `null`/absent = the geometry declares none, and the tile falls back
   *  loudly (`footprintWidth`). */
  plan_width_m?: number | null;
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
  /** Edge length of the footprint square in world metres — the ONE scale
   *  anchor of the location, hoisted out of `map3d` by the server. `null`
   *  when the geometry declares none. */
  plan_width_m: number | null;
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
  /** arrival in GAME wall-clock time (world timezone, ISO); `null` under the
   *  fog (§ A12) — the arrival time would date the hidden route. */
  eta_game: string | null;
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

export interface WorldMap {
  avatar: string;
  current_location_id: string;
  /** Only what the avatar knows — unless `fogged` is false (§ A12). */
  locations: MapLocation[];
  characters: MapCharacter[];
  events_by_location: Record<string, MapEvent[]>;
  /** § A12; `null` when nothing is placed */
  world_bounds: WorldBounds | null;
  /** Signature of the painted terrain (areas + world type rows). When it
   *  changes, `/play/terrain` is refetched — the poll carries the sig so the
   *  terrain itself needs no polling of its own. */
  terrain_sig: string;
  /** `true` = this is the filtered view, so unknown places stay hidden.
   *  `false` = the admin's unfiltered view (`?all=1`), no fog at all. */
  fogged: boolean;
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
// effective type catalog they reference. NEVER fogged — terrain is always
// visible, only locations hide.

/** One entry of the terrain-type catalog (`app/core/terrain_types.py`). No
 *  ground property is ever hardcoded in a client: colour, passability and
 *  pace all come from here. */
export interface TerrainType {
  /** the id — follows the surface-texture kind rule, so a kind that names a
   *  library entry gets a real texture on the 3D ground */
  kind: string;
  /** display name; falls back to the kind */
  name: string;
  /** `#rrggbb`, the schematic fill of this kind (2D map, minimap, and the
   *  3D fallback when the surface library has no texture for it) */
  color: string;
  passable: boolean;
  /** walking-pace multiplier, 0..2 */
  speed_factor: number;
  /** Open bag of extras — a type says how ground LOOKS and how it is walked,
   *  nothing about what grows on it. Ignored by this client entirely (the
   *  scatter moved to the AREA with finding B17). */
  meta?: Record<string, unknown>;
}

/** What an area GROWS — `meta.scatter[]`, one entry per prop kind. The server
 *  whitelists exactly these three fields
 *  (`app/models/terrain._sanitize_scatter_list`); `scene/ground.ts` reads them
 *  and hands them to the shared sampler. */
export interface TerrainScatterEntry {
  /** instances per 100 m2 of the painted area; 0 = nothing is scattered */
  density_per_100m2: number;
  /** URL of a model to instance; absent = the built-in tuft */
  model?: string;
  /** TARGET height in metres — the prop is scaled until its bounding box is
   *  this tall, and the built-in tuft is built this high. */
  height_m?: number;
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
