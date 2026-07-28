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

/** EINE Platzierungs-Spec für Gebäude, Raum-Diorama und Prop gleichermaßen —
 *  Futter für die einzige place()-Routine des Vertrags (§ B2). */
export interface SceneModelSpec {
  role: 'building' | 'room' | 'prop'
  /** Nur am building-Spec: was das Modell IST. `shell` = ein Gebäude, das auf
   *  dem Boden steht und beim Reinzoomen wie ein Dach aufblendet; `ground` =
   *  eine Flächen-Location, deren Modell DER Boden ist — es bleibt stehen und
   *  bekommt Löcher (cutouts). Der Client hat das früher aus `cutouts.length`
   *  geraten und lag bei Flächen ohne Grundriss falsch (2026-07-28). */
  display?: 'shell' | 'ground'
  id: string
  /** ETag-Endpunkt; leer = kein Mesh (dann placeholder_dims) */
  url: string
  room_id?: string
  level: number
  /** Orientierungs-Fix, Euler 'XYZ' in Grad — VOR dem Messen */
  fix_euler: { x: number; y: number; z: number }
  yaw_deg: number
  /** Ziel-Ausdehnung in WELT-Metern. EIN Faktor auf alle drei Achsen
   *  (2026-07-28): `s = max_m / gemessene Ausdehnung`. Es gibt keinen
   *  Modus mehr, in dem Y anders skaliert als XZ. */
  max_m: number
  /** Woran gemessen wird: `yawed_xz` = größte XZ-Seite der GEDREHTEN Box
   *  (Location-Modelle füllen ihren Rahmen auch schräg gedreht),
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
  /** Dioramen ohne geeichtes `width_m`: `max_m` ist die Breite des
   *  Raum-Rechtecks als Notbehelf — die UI soll zur Eichung auffordern. */
  width_estimated?: boolean
  /** Flächen-Locations (plan-area-locations.md): Welt-Polygone, die aus DIESEM
   *  Modell geschnitten werden — Gebäude-Grundriss plus die Umrisse platzierter
   *  Indoor-Räume außerhalb davon. Das Modell bleibt in der Innenansicht
   *  stehen, in den Löchern steht das Rezept-Innenleben. Nur am
   *  building-Spec, nur bei `map3d.area_model`. */
  cutouts?: [number, number][][]
  /** Räume: die Höhe, die der SERVER aus dem Mesh gemessen hat (Meter über der
   *  Unterkante des Dioramas — dieselbe Einheit, die der walk_y-Regler
   *  speichert). Speist `walk_y_world`, solange der Admin nicht überschrieben
   *  hat; im Editor der Platzhalter des Reglers. Fehlt = nicht messbar.
   *  Nur die Admin-Seite wertet das aus. */
  walk_y_auto?: number
}

export interface SceneMarker {
  room_id: string
  at_world: [number, number]
  y_world: number
  animation: string
  facing?: number
  source: 'room' | 'prop'
}

export interface SceneExit {
  room_id: string
  at_world: [number, number]
  derived?: boolean
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
 *  braucht; im 3D-Client nur als Raum-Verzeichnis (Etage, Outdoor-Flag).
 *  `exit` trägt den Doppelrahmen des Rezepts: explizit = Fraktion des
 *  Raum-RECHTECKS, abgeleitet = absolute Plattenfraktion (`exit_derived`
 *  sagt, welcher gilt). */
export interface SceneRoom {
  room_id: string
  level: number
  always_visible: boolean
  outline: [number, number][]
  openings?: SceneOpening[]
  exit?: [number, number] | null
  exit_derived?: boolean
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

export interface ScenePayload {
  signature: string
  rooms: SceneRoom[]
  /** Welt-Größe des Bezugsquadrats: die EINE Zahl, die jede Fraktion dieses
   *  Payloads in Meter verwandelt (Default 10 = eine Kachel). Nie durch eine
   *  Konstante ersetzen — genau das war die 8, die Grundriss und Modell
   *  auseinanderlaufen ließ. */
  extent_m: number
  /** Welt-Meter je Real-Meter (extent_m / plan_width_m; 1 = Legacy) */
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
  exits: SceneExit[]
  outdoor_rooms: string[]
}
