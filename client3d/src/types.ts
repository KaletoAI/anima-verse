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
  exit?: [number, number]; // Ausgangspunkt (Fraktion der Raum-Grundfläche)
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
  color?: string;   // Grundfarbe der Fassade, z.B. "#8fa3b0"
  /** Drehung des Gebäude-Modells um die Hochachse in Grad (Fallback: map_rotation_2d) */
  rotation?: number;
  /** Anteil des Modells am Bezugsquadrat der Location (0..1, Default 1) */
  size?: number;
  /** AV3D-12: gezeichneter Gebäude-Grundriss — Polygonpunkte als Fraktionen
   *  des Bezugsquadrats (extent_m), automatisch geschlossen. Der Client
   *  rendert daraus pro genutzter Etage Boden und Wände (Tür im EG). */
  outline?: [number, number][];
  /** AV3D-12: Fahrstuhl-Position (Fraktion des Referenzquadrats) — wird
   *  automatisch auf allen Etagen platziert; Figuren nutzen ihn beim
   *  Etagenwechsel */
  elevator?: [number, number];
  /** Breite der Location in WELT-Metern — das Bezugsquadrat, in dem alle
   *  Fraktionen leben, und die Box, die das Modell füllt. Default 10 =
   *  genau eine Kachel. Im Szenen-Payload als `extent_m`. */
  extent_m?: number;
  /** Etagenhöhe in REALEN Metern (× k zur Renderzeit). Default 3. */
  storey_height_m?: number;
  /** Maßstabs-Anker: reale Breite des Bezugsquadrats in Metern („der Ort ist
   *  ≈ 12 m breit") → k = extent_m / plan_width_m */
  plan_width_m?: number;
  /** Bodentextur-Kind je Etage für die Grundriss-Platten (Raum-Rezept §7),
   *  Level-Schlüssel als String: {"0": "parquet", "-1": "stone"} */
  level_floors?: Record<string, string>;
}

export interface WorldLocation {
  id: string;
  name: string;
  description?: string;
  grid_x: number | null;
  grid_y: number | null;
  rooms: Room[];
  passable?: boolean;
  entry_room?: string;
  template_location_id?: string;
  map_rotation_2d?: number;
  indoor?: string;
  background_images?: string[];
  terrain?: string;   // AV3D-7: grass | forest | road | water | ...
  map3d?: Map3dMeta;  // AV3D-1
}

export interface MapLocation {
  id: string;
  name: string;
  grid_x: number | null;
  grid_y: number | null;
  passable?: boolean;
  template_location_id?: string;
  map_rotation_2d?: number;
  terrain?: string;   // AV3D-7
  map3d?: Map3dMeta;  // AV3D-1 (nur emittiert, wenn gesetzt)
}

/** Server-authoritative journey along the tile chain (contract § A11). */
export interface MapTravel {
  path: string[];
  target_id: string;
  seg: number;
  frac: number;
  progress_cells: number;
  eta_game: string;
  /** real seconds per cell for client-side extrapolation; null = frozen */
  cell_seconds_real: number | null;
}

export interface MapCharacter {
  name: string;
  location_id: string;
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

export interface WorldMap {
  avatar: string;
  current_location_id: string;
  locations: MapLocation[];
  characters: MapCharacter[];
  events_by_location: Record<string, MapEvent[]>;
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
