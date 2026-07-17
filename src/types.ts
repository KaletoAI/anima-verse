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
  /** Raum dauerhaft zeigen (unabhängig von der Innenansicht) — für
   *  Outdoor-Räume, die NICHT schon im Gebäude-Modell abgebildet sind.
   *  Default: false */
  always_visible?: boolean;
  /** Boden-Textur dieses Raums für die Etagen-Platte übernehmen
   *  (Checkbox im Editor; Default: false) */
  floor_source?: boolean;
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
  /** Grundflächen-Anteil an der Kachel (0..1, Default 0.92) */
  size?: number;
  /** AV3D-12: gezeichneter Gebäude-Grundriss — Polygonpunkte als Fraktionen
   *  des 8x8-Referenzquadrats, automatisch geschlossen. Der Client rendert
   *  daraus pro genutzter Etage Boden und Wände (Tür im EG). */
  outline?: [number, number][];
  /** AV3D-12: Fahrstuhl-Position (Fraktion des Referenzquadrats) — wird
   *  automatisch auf allen Etagen platziert; Figuren nutzen ihn beim
   *  Etagenwechsel */
  elevator?: [number, number];
  /** Skalierungsfaktor der Figuren in den Räumen dieser Location
   *  (0..1 der Kartengröße; Default 1/3) */
  figure_scale?: number;
  /** Etagenhöhe in Welt-Metern (Kartenmaßstab!). Realistische Innenhöhe
   *  ≈ 3 x figure_scale (z.B. 1,2 bei figure_scale 0,4). Default: 3 */
  level_height?: number;
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
