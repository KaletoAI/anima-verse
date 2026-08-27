/**
 * Szenen-Payload des Vertrags (§ B1) — EIN Satz Typen für beide Renderer.
 * Gegenstück auf der Serverseite: `app/core/scene_recipe.py`.
 *
 * Zusammengeführt aus `frontend/src/tabs/world/worldTypes.ts` (Admin) und
 * `client3d/src/api.ts` (Client). Beide beschrieben denselben Payload, wichen
 * aber an drei Stellen auseinander; so ist es aufgelöst:
 *
 *   - `SceneStyle.elevator_*`: Admin hatte sie als PFLICHT, Client als
 *     optional. Optional gewinnt — der Server liefert sie nur, wenn die Szene
 *     überhaupt einen Fahrstuhl hat. Die Admin-Aufrufer haben ohnehin schon
 *     Fallbacks; sie sind jetzt auch typseitig ehrlich.
 *   - `SceneRoom.openings`: Admin hatte sie als Pflicht und über den
 *     Editor-Typ `RoomOpening` beschrieben, Client als optionales
 *     `ApiOpening[]`. Optional gewinnt aus demselben Grund; der Editor-Typ
 *     bleibt im Admin, weil er PLAN-Fraktionen für das Zeichnen trägt und
 *     hier nichts zu suchen hat.
 *   - `openings[].type`: Admin verengte auf 'door'|'window'|'passage', der
 *     Client ließ `string` offen. Offen gewinnt — der Vertrag nennt das
 *     Vokabular ausdrücklich erweiterbar.
 *
 * `Array<[number, number]>` und `[number, number][]` sind derselbe Typ; hier
 * steht durchgehend die kurze Schreibweise.
 */

/** Bodenplatte: Kontur-Platte je genutzter Etage oder Boden eines Raums.
 *  thickness 0 = reine Textur-Fläche ohne Körper (Outdoor-Räume, § A5). */
export interface ScenePlate {
  level: number
  outline: [number, number][]
  top_y: number
  thickness: number
  texture_kind?: string
  opacity_role: 'ground' | 'upper'
  room_id?: string
}

/**
 * ONE STOREY-0 ROOM AS DATA — what replaced the storey-0 plates ("Ein Boden"
 * E5a, § A19 no. 3).
 *
 * Storey 0 draws no plate any more: its height is the terrain (`h_final`) and
 * its material is the layer bake. What a consumer still needs is the SHAPE, so
 * the polygons travel as data — which is what they always were.
 *
 * `polygon_world` is the room hull in the SCENE FRAME (local metres around the
 * anchor pin), like every other coordinate of this payload. `floor_kind` is
 * what the ground WEARS there, the empty string for a zone that names none.
 * `closed` tells a room from an open zone (§ A5).
 *
 * THERE ARE NO HEIGHTS IN IT, on purpose: a consumer asks the height sampler at
 * the point it is really placing something — never a plate, never a ray. Since
 * W1 there is no exception either: the last absolute y in this payload
 * (`water_level_effective`) went with the room water it described.
 *
 * A ROOM HAS NO WATER OF ITS OWN ANY MORE (W1 § 6). Where a room's hull lies
 * (by area, strictly more than half) inside a painted water area, the entry
 * carries `map_water` — a REFERENCE, derived at compose time and never stored,
 * so it cannot hang. It says: the MAP paints the ground here, this room does
 * not. Room semantics (membership, perception, spots, centres) are untouched by
 * it, and a renderer draws no floor surface of its own for such a room — which
 * for storey 0 is nothing new, since E5a took the plates away from every room.
 */
export interface SceneFloor {
  room_id: string
  polygon_world: [number, number][]
  floor_kind: string
  closed: boolean
  /** The painted water area this room's floor lies in, or absent. */
  map_water?: { area_id: string; kind: string }
}

/** One wall piece — already split around every door and window. A piece is
 *  NOT necessarily a full-height run: `base_y` + `height` describe it on their
 *  own, and a band hanging in the wall is the normal case — a window's sill
 *  below and head above, its glass band as its own entry with `glass`, and
 *  since 2026-08-25 the LINTEL over a door, which starts at the doorway's
 *  `base_y + height_m`. `outward_normal` points away from the enclosed room
 *  (view-direction culling). */
export interface SceneWall {
  level: number
  from: [number, number]
  to: [number, number]
  base_y: number
  height: number
  thickness: number
  texture_kind?: string
  glass?: boolean
  /** The DOOR LEAF filling a door's clear opening (2026-08-25) — the door's
   *  counterpart to a window's glass pane: same thin body in the same hole,
   *  but opaque and dark (`style.door_color`). It is drawn, it is EXCLUDED
   *  from the facade culling exactly like a pane (a facade that hides must
   *  not leave its doors hanging in the air), and it bars nothing — one walks
   *  THROUGH a door, so 2D colliders skip it like a `lintel`. */
  leaf?: boolean
  /** A DOOR PROP fills this leaf's hole (v5) — a renderer SKIPS drawing this
   *  piece, because the prop in `models[]` (`measure: 'fit'`, with `door`) is
   *  the door now. The entry itself stays in the payload on purpose: the
   *  Blender exterior render builds its facade from `walls` and would lose
   *  the door's prism with it (user decision 2026-08-27). Only ever set
   *  together with `leaf`. */
  door_prop?: boolean
  /** This piece hangs over a WALKABLE gap (a door or passage). It is drawn
   *  like any other wall, but it bars nothing in a floor plan — whoever
   *  derives 2D colliders from `walls` skips it. */
  lintel?: boolean
  opacity_role: 'ground' | 'upper'
  room_id?: string
  outward_normal: [number, number]
}

/** Typisiertes Box-Primitiv (Fahrstuhl: Schacht/Glas/Pad/Kabine) — Zentrum
 *  plus Größe, fertig in Welt-Metern. */
export interface SceneExtra {
  kind: string
  center: [number, number, number]
  size: [number, number, number]
  side?: string
  level?: number
  /** Index of the staircase this piece belongs to (`stair_step`, `stair_pad`),
   *  i.e. its position in the location's `map3d.stairs` list. It GROUPS the
   *  pieces of ONE payload — foot pad, head pad and the steps between them —
   *  and nothing more: the index is not stable across saves, so it must never
   *  be kept as an identity beyond the payload it arrived in. */
  stair?: number
  /** Which end of a staircase a `stair_pad` marks: `foot` = lower landing on
   *  `level`, `head` = upper landing on `level`. The pad's TOP face is the
   *  floor of that storey. */
  end?: 'foot' | 'head'
}

/** Auflösungsstufen eines Meshes, in FALLBACK-Reihenfolge (§ B1 variants).
 *  Der Server liefert nur die Stufen, die es wirklich gibt. */
export const MODEL_TIERS = ['full', 'low'] as const
export type ModelTier = (typeof MODEL_TIERS)[number]

/** URL der gewünschten Stufe, sonst die beste vorhandene ('' = kein Mesh).
 *  EINE Regel für beide Renderer: eine fehlende Low-Variante darf ein Objekt
 *  nie verschwinden lassen, und kein Renderer erfindet dafür eigene Logik. */
export function pickVariant(
  variants: Record<string, string> | undefined,
  tier: string = 'full',
): string {
  if (!variants) return ''
  const order = [tier, ...MODEL_TIERS, ...Object.keys(variants)]
  for (const t of order) {
    const url = variants[t]
    if (url) return url
  }
  return ''
}

/** URL des Meshes, das DIESE Platzierung zeigt — Modell-Variante zuerst,
 *  Auflösungsstufe danach (§ B2-Nachtrag, E2.3).
 *
 *  DIE Stelle, an der ein Prop mit mehreren Varianten zu einer Datei wird, und
 *  zwar für beide Renderer: aus `model_variants` wird die Karte mit dem Index
 *  `variant` genommen, aus ihr die Stufe wie eh und je (`pickVariant`). Ohne
 *  `model_variants` ist das Ergebnis Zeichen für Zeichen das alte
 *  `pickVariant(spec.variants, tier)` — ein Prop mit einer Variante merkt von
 *  der Liste nichts.
 *
 *  Der Index wird MODULO gerechnet, nicht geklemmt: die Variantenzahl bewegt
 *  sich, wenn der Admin ein Mesh ergänzt oder löscht, und eine Platzierung
 *  darf davon nicht verschwinden. */
export function pickModelVariant(
  spec: Pick<SceneModelSpec, 'variants' | 'model_variants' | 'variant'>,
  tier: string = 'full',
): string {
  const list = spec.model_variants
  if (!Array.isArray(list) || list.length === 0) return pickVariant(spec.variants, tier)
  const n = list.length
  const raw = Number(spec.variant)
  const i = Number.isFinite(raw) ? ((raw % n) + n) % n : 0
  return pickVariant(list[i] || spec.variants, tier)
}

/** A model's baked walkable surface (spec-surface-height § 4/6): a lattice in
 *  the model's OWN frame after the orientation fix. `values[j*cols+i]` is the
 *  walkable height of node (i, j) in whole centimetres over `box_min[1]`, or
 *  null where nothing faces up. `box_min/box_max` = the hull under the exact
 *  fix (three's Box3.setFromObject measure), `extent_snapped` = the hull size
 *  under the fix rounded to 90° — what `max_m` is divided by. */
export interface SceneSurface {
  step: number
  origin: [number, number]
  cols: number
  rows: number
  values: (number | null)[]
  box_min: [number, number, number]
  box_max: [number, number, number]
  extent_snapped: [number, number, number]
}

/** EINE Platzierungs-Spec für Gebäude, Raum-Diorama und Prop gleichermaßen —
 *  Futter für die einzige place()-Routine des Vertrags (§ B2). */
export interface SceneModelSpec {
  role: 'building' | 'room' | 'prop'
  /** Nur am building-Spec: was das Modell IST. `shell` = ein Gebäude, das auf
   *  dem Boden steht und beim Reinzoomen wie ein Dach aufblendet; `ground` =
   *  eine Flächen-Location, deren Modell DER Boden ist — es bleibt stehen und
   *  bekommt Löcher (cutouts). Der Client hat das früher aus `cutouts.length`
   *  geraten und lag bei Flächen ohne Grundriss falsch (2026-07-28).
   *  `shell_area` (v5.2, plan-area-detail-scenes.md) = Flächen-Location im
   *  Detail-Modus: ANKER wie `ground` (Gehfläche auf Etage 0), blendet aber
   *  beim Reinzoomen aus wie `shell` — darunter liegt die Detailszene. */
  display?: 'shell' | 'ground' | 'shell_area'
  /** Nur am building-Spec: das Modell ist NUR DAS DACH (Nachtrag 2026-08-20,
   *  docs/llm-blender-models.md) — parametrisch über den Umriss gebaut, ohne
   *  Wände. Ein Renderer, der eine eigene Fernsicht-Hülle aus den § B
   *  Primitiven baut, LÄSST SIE STEHEN und setzt dieses Modell obendrauf;
   *  ohne das Flag ersetzt ein Gebäudemodell die Hülle wie bisher. Fehlt =
   *  false = das Modell IST das Gebäude. */
  roof_only?: boolean
  id: string
  /** ETag-Endpunkte je Auflösungsstufe (`full` = modellierte Qualität,
   *  `low` = Fernsicht-Mesh; fehlende Stufe fehlt im Objekt). LEER = kein
   *  Mesh (dann placeholder_dims). Ein Konsument nimmt die gewünschte Stufe
   *  und sonst die beste vorhandene — `pickVariant()` macht genau das, und
   *  beide Renderer benutzen sie (plan-3d-lod-und-betreten.md, 2026-08-03). */
  variants: Partial<Record<ModelTier, string>> & Record<string, string>
  /** Props mit MEHREREN Modell-Varianten (E2.3, § B2-Nachtrag): eine
   *  Stufen-Karte je AKTIVER Variante, in der Reihenfolge des Props.
   *  Element 0 IST `variants` — die primäre Variante. Fehlt das Feld, hat das
   *  Prop genau eine Variante; nur ein Prop mit mehr als einer schickt es.
   *  Nicht anfassen ohne `variant`: welche Variante DIESE Platzierung zeigt,
   *  steht dort und wird vom Server bestimmt. */
  model_variants?: (Partial<Record<ModelTier, string>> & Record<string, string>)[]
  /** Index in `model_variants` für DIESE Platzierung (fehlt = 0 = primär).
   *  Der Server löst ihn auf — bei Streu-Kopien mit der einen Formel
   *  `(scatter_seed + Instanz) mod Anzahl`, sonst aus der Platzierung selbst.
   *  Kein Renderer würfelt hier: dieselbe Kopie zeigt in beiden Renderern
   *  dasselbe Mesh. */
  variant?: number
  room_id?: string
  level: number
  /** Orientierungs-Fix, Euler 'YXZ' in Grad — VOR dem Messen. Yaw außen,
   *  Tilt/Roll im schon gedrehten Rahmen (2026-07-28). */
  fix_euler: { x: number; y: number; z: number }
  yaw_deg: number
  /** Target extent in WORLD metres. ONE factor on all three axes
   *  (2026-07-28): `s = max_m / measured extent`. There is no mode left in
   *  which Y scales differently from XZ. Since v6 Nr. 3 the value is EVERYWHERE
   *  a declared real width (`width_m`) — for a building/an area the boundary
   *  width stands in for it, see `width_estimated`. */
  max_m?: number
  /** What is measured: `yawed_xz` = the largest XZ side of the TURNED box
   *  (location models have to fit their plot even when set at an angle),
   *  `xz` = the largest XZ side of the fixed box (dioramas: width_m is a
   *  floor-plan width), `xyz` = the largest edge of all (props) — those three
   *  scale UNIFORMLY to `max_m`.
   *  `fit` (v5) is the ONE exception and belongs to a DOOR PROP: it is fitted
   *  into the hole it fills (`size_m`), x to the width and y to the height,
   *  z with the same factor as x so the leaf keeps its depth proportion.
   *  A `fit` spec carries no `max_m` — the opening is the ruler. */
  measure: 'yawed_xz' | 'xz' | 'xyz' | 'fit'
  /** `fit` only: [width, height] of the opening in world metres — the CLEAR
   *  gap of the doorway, so a frame that is 5 cm too narrow cannot leave a
   *  lit gap in a wall. */
  size_m?: [number, number]
  /** A prop that IS a door (v5). `opening` indexes `doorways[]`, `hinge` says
   *  which end of the opening the `anchor` sits on — and the anchor is that
   *  HINGE EDGE, not the middle, so a renderer swings the leaf by rotating
   *  the placed group about its own origin. `swing` is the sign of that
   *  rotation for OPENING outward (away from the room the hole was cut out
   *  of): +1 for a left hinge, −1 for a right one. How far and when it opens
   *  is view state and stays per app. */
  door?: { opening: number; hinge: 'left' | 'right'; swing: 1 | -1 }
  anchor: [number, number]
  bottom_y: number
  /** Placeholder box (already world metres) for a missing/mesh-less prop */
  placeholder_dims?: { w: number; d: number; h: number }
  /** Rooms, opt-in per room (layout.clip_model): hull polygon in WORLD
   *  coordinates around the tile centre (max. 32 points, = the floor plate's
   *  contour). Everything outside is discarded — a real-size diorama may stick
   *  out over its floor plan, only the part inside the room stays visible. */
  clip_outline?: [number, number][]
  /** Absolute height at which a figure stands ON this model — in the diorama
   *  (§ B6 no. 7) as on an area location. With `display: 'ground'` it is the
   *  anchor at the same time: the model hangs as far below this height as its
   *  walking surface lies above its bottom edge. */
  walk_y_world?: number
  /** The baked surface (v6). A room spec carries it once its model is baked;
   *  a prop spec only when the prop is `walkable`. Read by `surfaceHeightAt`
   *  — rung 0 of the walking height, above the `walk_y_world` declaration. */
  surface?: SceneSurface
  /** Prop spec only (v6): the prop carries the `walkable` tag, so figures may
   *  stand on it. Without it a prop ships no surface. */
  walkable?: boolean
  /** Models without a calibrated `width_m`: `max_m` is only a stopgap — for a
   *  diorama the width of the room rectangle, for a building/an area the
   *  boundary width (`extent_m`, since v6 no. 3). The UI is meant to ask for
   *  calibration. */
  width_estimated?: boolean
  // `walk_y_auto` existed until 2026-07-28: the walking height MEASURED from
  // the mesh, which silently filled an empty dial. There is no automation left
  // that aligns models — the admin sets walk_y and everything else is computed
  // from that base value.
  /** Area locations (plan-area-locations.md): world polygons cut out of THIS
   *  model — the building's floor plan plus the outlines of placed indoor
   *  rooms outside it. The model stays standing in the interior view, and the
   *  recipe's own interior stands in the holes. Only on the building spec,
   *  only with `map3d.area_model`. */
  cutouts?: [number, number][][]
  /** WHAT FILLS THIS PLACEMENT'S TEXTURE SLOTS (v5). The KEY is a material
   *  name of the mesh — a slot IS a material (`props.detect_slots`) — and the
   *  value is either a picture (`image`, a same-origin gallery URL) or a look
   *  (`preset`, today only `glass`). Only slots the prop still declares are in
   *  here; the server drops the rest, so a renderer matches names and asks
   *  nothing. Absent = the prop renders as it was modelled.
   *  `applySlotMaterials` (@anima/scene-render) is the ONE routine that
   *  writes it — it clones the material per placement, because the model
   *  cache shares one group between all of them. */
  slots?: SceneSlotValues
  /** Prop placements with a DEPTH CUT (§ B2 addendum 2026-08-23): the finished
   *  cutting plane in the payload's own world metres — half a table against
   *  the wall, without a second prop in the library. Absent = uncut. The
   *  renderer builds ONE `THREE.Plane` from it and hands it to the material
   *  (`applyDepthCut`); it recalculates nothing. */
  cut_plane?: SceneCutPlane
}

/** The filled texture slots of one placement, keyed by MATERIAL NAME (v5).
 *  Exactly one of the two fields is set per entry — the server has already
 *  decided which by the slot's kind, so a renderer never has to. */
export type SceneSlotValues = Record<string,
  { image?: string; preset?: string }>

/** Eine Halbraum-Ebene in den Weltmetern des Szenen-Payloads. Behalten wird,
 *  wo `normal·p + constant >= 0` — three.js' eigene `Plane`-Konvention, damit
 *  aus den zwei Feldern genau ein Konstruktoraufruf wird. */
export interface SceneCutPlane {
  normal: [number, number, number]
  constant: number
}

export interface SceneMarker {
  room_id: string
  at_world: [number, number]
  /** Die OBERFLÄCHE, die der Marker benennt (Sitzfläche, Matratze, Boden). */
  y_world: number
  animation: string
  /** Wie weit UNTER dieser Fläche die Figurenwurzel sitzt, in Welt-Metern
   *  (2026-07-28). Ein sitzender Körper berührt am Gesäß, nicht an den Füßen —
   *  wie tief, ist eine Eigenschaft des CLIPS und stand bisher nur im
   *  3D-Client, und dort nur für Raum-Marker. Fehlt/0 = die Wurzel liegt auf
   *  der Fläche. Jeder Renderer zieht ihn ab, NACHDEM er die Fläche kennt. */
  root_offset?: number
  facing?: number
  /** Neigung der Figur in Grad (±90), NACH dem Facing im Figuren-System:
   *  `tilt` = Kopf hoch/tief, `roll` = seitlich kippen. Ohne die beiden kann
   *  eine Figur nur senkrecht stehen — schräg auf dem Sand liegen ging nicht
   *  (User-Befund 2026-07-28). Fehlt = 0. */
  tilt?: number
  roll?: number
  source: 'room' | 'prop'
}

/** Gemeinsames Farb-Vokabular beider Renderer — keine Hex-Konstanten hier. */
export interface SceneStyle {
  wall_color: string
  floor_color: string
  glass_color: string
  glass_opacity: number
  /** Colour of a `leaf` piece — the door itself. Opaque and dark, so a door
   *  reads as a door against `wall_color`. Callers keep a fallback: an older
   *  payload does not carry it. */
  door_color?: string
  upper_wall_opacity: number
  upper_floor_opacity: number
  room_palette: string[]
  /** Nur gesetzt, wenn die Szene einen Fahrstuhl hat — Aufrufer brauchen
   *  Fallbacks. */
  elevator_frame_color?: string
  elevator_pad_color?: string
  elevator_cabin_color?: string
  elevator_cabin_opacity?: number
  elevator_glass_opacity?: number
  /** Colour of the steps and the trigger pads of a staircase (`stair_step`,
   *  `stair_pad`). A staircase is masonry, not machinery — warm stone rather
   *  than the elevator's cold grey, so the two vertical connections read
   *  apart at a glance. Callers keep a fallback: an older payload does not
   *  carry it. */
  stair_color?: string
}

/** Öffnung einer Raumkante, im Payload bereits auf Kanten-INDIZES normalisiert
 *  (der Editor-Typ `RoomOpening` kennt zusätzlich 'N'|'S'|'E'|'W' und bleibt
 *  deshalb im Admin). Im 3D-Client rein informativ: die Wände kommen bereits
 *  um jede Öffnung geteilt als `walls`. */
export interface SceneOpening {
  /** Kanten-INDEX in outline (Kante i = Punkt i -> i+1) */
  edge: number
  /** 0..1 ENTLANG der gerichteten Kante (Öffnungs-Mitte) */
  at: number
  width_m: number
  height_m: number
  /** Brüstungshöhe in Metern — Tür = 0, Fenster ≈ 0,9 */
  sill_m: number
  /** "window" | "door" | "passage" — Vokabular ist laut Vertrag offen */
  type: string
  /** Ziel der Verbindung: Raum-ID oder 'outside' */
  to?: string
  prop_id?: string
  /** vom Nachbarraum gespiegelte Öffnung (rein informativ) */
  mirrored?: boolean
}

/** Raum-Vokabular in PLAN-FRAKTIONEN — was der 2D-Editor zum ZEICHNEN
 *  braucht; im 3D-Client nur als Raum-Verzeichnis (Etage, Outdoor-Flag). */
export interface SceneRoom {
  room_id: string
  level: number
  always_visible: boolean
  outline: [number, number][]
  openings?: SceneOpening[]
  /** Flächen-Locations: dieser Outdoor-Raum liegt AUF der Modelloberfläche
   *  statt gebaut zu werden — es gibt weder Platte noch Wände, also kommen
   *  Mitte, Rechteck und Höhe (alles Welt-Meter) von hier. Fehlt = normaler
   *  Raum. */
  overlay?: {
    centre: [number, number]
    rect: { x: number; z: number; w: number; d: number }
    y: number
  }
}

/** ONE walkable threshold — a door or passage, served as a finished
 *  primitive (plan-betreten-und-tueren.md § 4.1). It is exactly the gap the
 *  opening cuts out of the wall, in WORLD metres around the tile centre and
 *  with the tile rotation already applied, like every other scene coordinate.
 *
 *  The consumer rule is: **recompute nothing.** No edge clamp, no
 *  `width_m × k`, no measuring a contour gap back out of two wall pieces.
 *  Whoever draws a threshold, walks a figure through one or samples the floor
 *  at a door reads THIS. */
export interface SceneDoorway {
  level: number
  /** Middle of the CLEAR opening. */
  at_world: [number, number]
  /** Unit direction of the wall — the threshold runs ALONG it. */
  along: [number, number]
  /** Which walkable opening this is: a `door` has a LEAF in its hole, a
   *  `passage` is an open gap (2026-08-25). */
  type?: 'door' | 'passage'
  /** Clear width, already clamped to the wall edge. */
  width_m: number
  /** Clear height, already clamped to the wall — `base_y + height_m` is where
   *  the LINTEL over this gap starts (its own `walls` entry). */
  height_m: number
  /** Foot of the wall the gap belongs to. */
  base_y: number
  /** The rooms it connects: 2 = party wall, 1 = door to the outside.
   *  `rooms[0]` owns the wall this entry was cut out of. The GROUND room
   *  never appears — it has no walls, and `outside` already says so. */
  rooms: string[]
  /** true = leads out of the building (onto the ground). */
  outside: boolean
}

/** A finding the SERVER made about this location (plan-betreten-und-tueren.md
 *  § 4.3) — something it refused to repair silently. Both surfaces only
 *  DISPLAY it: the floor-plan editor at the affected place, the 3D client as a
 *  hint. Neither re-derives the rule, and neither invents a repair.
 *
 *  `kind` is the stable key (`no_building_entrance` = a hull with rooms but no
 *  door leading outside — the old "one door mid in the south wall" fallback is
 *  gone; `rooms_without_layout` = a contour whose rooms ALL lack a layout, so
 *  nothing is composed inside it at all; `openings_without_walls` = rooms with
 *  drawn openings whose walls are switched off, so none of them is built;
 *  `boundary_self_intersection` = the drawn location boundary crosses itself,
 *  so inside/outside is ambiguous (v6 Nr. 1); `room_outside_boundary` = a
 *  room's floor plan reaches out of that boundary (v6 Nr. 9)).
 *  `message` is the server's English wording; a surface may translate a kind
 *  it knows and falls back to this text. Numbers never sit in `message` — it
 *  is translated as a whole sentence — so they come as their own fields
 *  (`room_count`, `room_ids`). */
export interface SceneProblem {
  kind: string
  location_id?: string
  room_id?: string
  message: string
  /** `rooms_without_layout`: how many rooms the location has.
   *  `openings_without_walls` / `room_outside_boundary`: how many rooms are
   *  affected. */
  room_count?: number
  /** `room_outside_boundary`: which rooms stick out, in recipe order. */
  room_ids?: string[]
}

/** Pass-through at the LOCATION edge (§ B1 Nr. 13) — where a road enters and
 *  leaves the cell. Pure geometry + room link, metres in the scene frame
 *  around the anchor pin like every other scene coordinate; `inward` is the
 *  measured inward unit normal of that edge.
 *
 *  SINCE v6 `edge` is the 0-based INDEX of the boundary polygon's edge
 *  (edge i = point i -> i+1) — the letters N/E/S/W are gone with the square,
 *  and so is the tile rotation that used to turn them (v6 Nr. 15).
 *
 *  client3d renders the locked threshold marks of the detail scene from these;
 *  the ENTRY offer reads the world-metre twin on the worldmap row
 *  (`locations[].openings`, § A1.3). The admin preview renders neither. */
export interface SceneBoundaryOpening {
  /** boundary EDGE INDEX (edge i = point i -> i+1) */
  edge: number
  at_world: [number, number]
  width_m: number
  /** "passage" today — vocabulary open, like room openings */
  type: string
  /** room this opening routes into (the server accepts entry here) */
  room_id?: string
  inward: [number, number]
}

// THE SCENE'S OWN 17 x 17 RELIEF IS DELETED ("Ein Boden" E5a, decision 1 of
// the plan): `SceneTerrain`, the `terrain` block of the payload, `map3d.relief`
// and `layout.relief_flat` are gone without a replacement rail. A location has
// no height field of its own any more — local relief is authored through the
// map's HEIGHT AREAS, and the one ground under everything is `h_final`
// (§ A16). With it went `sampleTerrain`/`drapeGeometry`/`TERRAIN_CELLS` and the
// grid mesh they draped over (`subdivideOnGrid`/`gridStepFor`): nothing is
// draped any more, so nothing needs cutting on a lattice.

export interface ScenePayload {
  signature: string
  rooms: SceneRoom[]
  /** THE FOOTPRINT of the location as a closed polygon in the scene frame
   *  (metres around the anchor pin, contract v6 Nr. 1/Nr. 4) — the drawn
   *  `map3d.boundary`, or the reference square as its four corners. Absent for
   *  a location without an area. Same points the world map draws; nothing
   *  transforms them a second time. */
  boundary?: [number, number][]
  /** World size of the reference square: the ONE number that turns every
   *  fraction of this payload into metres. Since E4 it IS the footprint edge
   *  (`plan_width_m`, § A1.1) — no default, no tile. Never replace it with a
   *  constant — that was exactly the 8 that let floor plan and model drift
   *  apart. */
  extent_m: number
  /** World metres per REAL metre — CONSTANT 1 since E4 (extent_m ==
   *  plan_width_m, § A1.8). The field stays in the payload so the ×k in the
   *  render chains keeps computing the right thing; it is no longer a dial
   *  and nothing may branch on it. */
  k: number
  storey_m: number
  levels: { level: number; floor_y: number }[]
  style: SceneStyle
  /** THE FLOORS OF THE DECLARED STOREYS ONLY (E5a): upper storeys and
   *  basements. Storey 0 has none — its floor is the terrain and its material
   *  is the layer bake; what is left of it is `floor_plan`. */
  plates: ScenePlate[]
  /** The storey-0 rooms as polygons + floor kinds (E5a, § A19 no. 3) — always
   *  present, empty for a location without a level-0 room. */
  floor_plan: SceneFloor[]
  walls: SceneWall[]
  extras: SceneExtra[]
  models: SceneModelSpec[]
  figures: { base_height_m_world: number; stand_clearance: number }
  markers: SceneMarker[]
  /** Every walkable threshold of the location (§ 4.1) — always present, empty
   *  when the location has no door at all. */
  doorways: SceneDoorway[]
  /** What the server found wrong and did NOT repair (§ 4.3) — always present,
   *  empty when the location is sound. */
  problems: SceneProblem[]
  outdoor_rooms: string[]
  /** Pass-throughs at the location edge (§ B1 Nr. 13) — only when authored. */
  boundary_openings?: SceneBoundaryOpening[]
  /** Detail mode of the LOCATION (v5.2 Nr. 10) — independent of whether a
   *  location model exists: the fade gate and the zone rules hang off this;
   *  `display: shell_area` on the building spec is merely its per-model
   *  consequence. */
  area_detail?: boolean
  // `terrain` and `natural_floor` ARE GONE (E5a, § A19 no. 1 and no. 6). The
  // first was the scene's own 17 x 17 relief; the second told a renderer that
  // THIS location stood on the terrain rather than on a slab — a distinction
  // that meant something only while there were two grounds. On storey 0 every
  // location stands on the terrain now, so the flag would be true everywhere
  // and say nothing.
}

/**
 * WHICH clip kinds are seated — the poses whose contact point is not the
 * lowest edge of the body, and by how much of the figure height.
 *
 * THE TABLE IS THE ANSWER, for every consumer alike: the server multiplies it
 * by 1.70 m into each marker's `root_offset`, and a renderer with no payload
 * (the prop viewer shows ONE prop, not a scene) reads it straight. Nobody
 * measures a posed skeleton for this any more — see `figure.ts` for what that
 * cost. Numbers measured on x-bot.fbx + the clips; the server's own copy is
 * `FIGURE_ROOT_DROP` in `app/core/scene_recipe.py`.
 */
export const FIGURE_ROOT_DROP: Record<string, number> =
  { sit: 0.314, sleep: 0.631, laying: 0.051, lie: 0.051 }

/** The drop for one clip kind (0 = the root sits on the surface). */
export const rootDropFor = (animation?: string) =>
  FIGURE_ROOT_DROP[(animation || '').trim().toLowerCase()] ?? 0
