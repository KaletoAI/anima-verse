export interface Room {
  id: string;
  name: string;
  description?: string;
}

/** AV3D-1: optionale 3D-Metadaten einer Location. */
export interface Map3dMeta {
  style?: string;   // house | tower | shop | hall | generic | ...
  floors?: number;
  color?: string;   // Grundfarbe der Fassade, z.B. "#8fa3b0"
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
