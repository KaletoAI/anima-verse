export interface Room {
  id: string;
  name: string;
  description?: string;
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
}

export interface MapLocation {
  id: string;
  name: string;
  grid_x: number | null;
  grid_y: number | null;
  passable?: boolean;
  template_location_id?: string;
  map_rotation_2d?: number;
}

export interface MapCharacter {
  name: string;
  location_id: string;
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
