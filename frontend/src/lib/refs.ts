/**
 * Loaders for reference data shared by multiple Game-Admin tabs:
 * locations (with rooms), characters, activity library. Each tab fetches
 * what it needs from its own effect; we deliberately do not share a
 * cache across tabs yet — the lists are small (handful of items each)
 * and the tabs are independent enough that re-fetching is cheaper than
 * the bookkeeping.
 */
import { apiGet } from './api'

export interface RoomRef {
  id: string
  name?: string
  description?: string
  outfit_type?: string
}

export interface LocationRef {
  id: string
  name?: string
  rooms?: RoomRef[]
  is_template?: boolean
  /** Passable / "Durchgangs"-Locations are transit nodes (corridors,
   *  doorways) — useful for routing but not as roleplay contexts. */
  passable?: boolean
}

export interface CharacterRef {
  name: string
  display_name?: string
}

export async function loadLocations(): Promise<LocationRef[]> {
  const data = await apiGet<{ locations?: LocationRef[] }>('/world/locations')
  return data.locations || []
}

export async function loadCharacters(): Promise<CharacterRef[]> {
  // /characters/list returns either a list of strings (the canonical
  // shape from list_available_characters) or a list of objects in some
  // older code paths. Normalize to {name, display_name?} so consumers
  // always have a stable shape.
  const data = await apiGet<{ characters?: unknown[] }>('/characters/list')
  const arr = data.characters || []
  return arr.map((c) =>
    typeof c === 'string'
      ? { name: c }
      : ((c && typeof c === 'object' && 'name' in (c as object))
        ? (c as CharacterRef)
        : { name: String(c) }),
  )
}


export interface ItemRef {
  id: string
  name?: string
  category?: string
}

export async function loadItems(): Promise<ItemRef[]> {
  const data = await apiGet<{ items?: ItemRef[] }>('/inventory/items?include_shared=1')
  return data.items || []
}
