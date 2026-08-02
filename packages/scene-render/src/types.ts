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
  /** ETag-Endpunkt; leer = kein Mesh (dann placeholder_dims) */
  url: string
  room_id?: string
  level: number
  /** Orientierungs-Fix, Euler 'YXZ' in Grad — VOR dem Messen. Yaw außen,
   *  Tilt/Roll im schon gedrehten Rahmen (2026-07-28). */
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

/** Deterministisches Geländerelief der Detailszene (§ B1 Nr. 14). 17 × 17
 *  Stützpunkte über dem Bezugsquadrat, `grid[j][i]` in WELT-Metern; i läuft
 *  West→Ost, j Nord→Süd, der Rand ist 0. Fehlt = die Szene ist eben.
 *
 *  Der Server hat damit bereits ALLES gehoben, was in einem nicht-flachen
 *  Raum steht — Renderer drapieren nur Boden und `relief`-Platten und
 *  sampeln Figurenhöhen (`sampleTerrain`), sie heben nie ein Objekt nach. */
export interface SceneTerrain {
  /** Kantenlänge einer Gitterzelle in Welt-Metern (`extent_m / 16`). */
  step: number
  /** 17 × 17 Stützpunkte, `grid[j][i]`, Welt-Meter. */
  grid: number[][]
  /** Ausschlag in Welt-Metern (bereits × k). */
  amplitude_m: number
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
  /** Höhenfeld der Detailszene — nur wenn `map3d.relief` gesetzt ist. */
  terrain?: SceneTerrain
  /** Detail-Modus der LOCATION (v5.2 Nr. 10) — unabhängig davon, ob ein
   *  Location-Modell existiert: Backstop-Platte, Fade-Gate und Zonen-Regeln
   *  hängen hieran; `display: shell_area` am Gebäude-Spec ist nur die
   *  Modell-Konsequenz. */
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
