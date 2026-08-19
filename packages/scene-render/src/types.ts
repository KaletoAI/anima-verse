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
  /** Terrain relief (v5.2 Nr. 14): THIS plate follows the height field —
   *  the renderer subdivides it and raises its vertices via `sampleTerrain`
   *  instead of laying it flat on `top_y`. Only outdoor plates of non-flat
   *  rooms carry it; storey plates, walls and every other plate stay flat. */
  relief?: boolean
}

/** Ein Wandstück — um Türen/Fenster bereits geteilt; das Glasband eines
 *  Fensters kommt als eigener Eintrag mit `glass`. `outward_normal` zeigt vom
 *  umschlossenen Raum weg (Blickrichtungs-Culling). */
export interface SceneWall {
  level: number
  from: [number, number]
  to: [number, number]
  base_y: number
  height: number
  thickness: number
  texture_kind?: string
  glass?: boolean
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
  /** Ziel-Ausdehnung in WELT-Metern. EIN Faktor auf alle drei Achsen
   *  (2026-07-28): `s = max_m / gemessene Ausdehnung`. Es gibt keinen
   *  Modus mehr, in dem Y anders skaliert als XZ. Seit v6 Nr. 3 ist der Wert
   *  ÜBERALL eine deklarierte reale Breite (`width_m`) — beim Gebäude/der
   *  Fläche ersatzweise die Boundary-Breite, siehe `width_estimated`. */
  max_m: number
  /** Woran gemessen wird: `yawed_xz` = größte XZ-Seite der GEDREHTEN Box
   *  (Location-Modelle passen auch schräg gedreht auf ihr Grundstück),
   *  `xz` = größte XZ-Seite der gefixten Box (Dioramen: width_m ist eine
   *  Grundriss-Breite), `xyz` = größte Kante überhaupt (Props). */
  measure: 'yawed_xz' | 'xz' | 'xyz'
  anchor: [number, number]
  bottom_y: number
  /** Platzhalter-Box (schon Welt-Meter) für fehlendes/mesh-loses Prop */
  placeholder_dims?: { w: number; d: number; h: number }
  /** Räume, Opt-in je Raum (layout.clip_model): Hüllen-Polygon in WELT-
   *  Koordinaten um das Kachelzentrum (max. 32 Punkte, = Bodenplatten-Kontur).
   *  Alles außerhalb wird verworfen — ein real-size-Diorama darf über seinen
   *  Grundriss hinausragen, sichtbar bleibt nur der Teil im Raum. */
  clip_outline?: [number, number][]
  /** Absolute Höhe, auf der eine Figur AUF diesem Modell steht — im Diorama
   *  (§ B6 Nr. 7) wie auf einer Flächen-Location. Bei `display: 'ground'` ist
   *  das zugleich der Anker: das Modell hängt so weit unter dieser Höhe, wie
   *  seine Gehfläche über seiner Unterkante liegt. */
  walk_y_world?: number
  /** Modelle ohne geeichtes `width_m`: `max_m` ist nur ein Notbehelf — beim
   *  Diorama die Breite des Raum-Rechtecks, beim Gebäude/der Fläche die
   *  Boundary-Breite (`extent_m`, seit v6 Nr. 3). Die UI soll zur Eichung
   *  auffordern. */
  width_estimated?: boolean
  // `walk_y_auto` gab es bis 2026-07-28: die aus dem Mesh GEMESSENE Gehhöhe,
  // die einen leeren Regler still ausfüllte. Eine Automatik, die Modelle
  // ausrichtet, gibt es nicht mehr — der Admin setzt walk_y, alles andere
  // rechnet von diesem Basiswert aus.
  /** Flächen-Locations (plan-area-locations.md): Welt-Polygone, die aus DIESEM
   *  Modell geschnitten werden — Gebäude-Grundriss plus die Umrisse platzierter
   *  Indoor-Räume außerhalb davon. Das Modell bleibt in der Innenansicht
   *  stehen, in den Löchern steht das Rezept-Innenleben. Nur am
   *  building-Spec, nur bei `map3d.area_model`. */
  cutouts?: [number, number][][]
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
  /** Clear width, already clamped to the wall edge. */
  width_m: number
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

/** The detail scene's deterministic terrain relief (§ B1 Nr. 14):
 *  (n+1) × (n+1) support points over the reference square, `grid[j][i]` in
 *  WORLD metres; i runs west→east, j north→south, the border is 0. Absent =
 *  the scene is flat.
 *
 *  The RESOLUTION n is not a constant — it follows the author's wave width,
 *  so it is read from the payload (`grid.length - 1`, or `step`), never
 *  assumed.
 *
 *  The server has already lifted EVERYTHING standing in a non-flat room —
 *  renderers only drape ground and `relief` plates and sample figure heights
 *  (`sampleTerrain`); they never lift an object themselves. */
export interface SceneTerrain {
  /** Edge length of ONE grid cell in world metres (`extent_m / n`). */
  step: number
  /** (n+1) × (n+1) support points, `grid[j][i]`, world metres. */
  grid: number[][]
  /** Swing in world metres (already × k). */
  amplitude_m: number
  /** MIN CORNER of the support lattice in payload metres (contract v6 Nr. 2,
   *  § B1 Nr. 14 — `scene_recipe.terrain_frame`). Since v6 the lattice spans a
   *  square of edge `extent_m` over the BOUNDARY's bounding box, not a square
   *  around the pin, so a lattice coordinate is
   *  `u = (x − origin[0]) / (step · n)` — never `x / extent_m + 0.5`.
   *  Optional in the TYPE only because a payload composed before the metric
   *  wave carries no such field; where it IS present it is mandatory in the
   *  arithmetic (`sampleTerrain`). For a boundary drawn around its own pin
   *  both formulas give the same number. */
  origin?: [number, number]
}

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
  plates: ScenePlate[]
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
  /** Height field of the detail scene — only when `map3d.relief` is set. */
  terrain?: SceneTerrain
  /** Detail mode of the LOCATION (v5.2 Nr. 10) — independent of whether a
   *  location model exists: backstop plate, fade gate and zone rules hang off
   *  this; `display: shell_area` on the building spec is merely its
   *  per-model consequence. */
  area_detail?: boolean
}

/**
 * WHICH clip kinds are seated — the poses whose contact point is not the
 * lowest edge of the body. The prop viewer only asks IF (it then reads the
 * amount off the posed skeleton); the value is the server's number
 * (`FIGURE_ROOT_DROP` in `app/core/scene_recipe.py`, measured on x-bot.fbx +
 * sit.fbx) for anything that needs a figure without a scene payload.
 */
export const FIGURE_ROOT_DROP: Record<string, number> =
  { sit: 0.314, sleep: 0.631, laying: 0.051, lie: 0.051 }

/** The drop for one clip kind (0 = the root sits on the surface). */
export const rootDropFor = (animation?: string) =>
  FIGURE_ROOT_DROP[(animation || '').trim().toLowerCase()] ?? 0
