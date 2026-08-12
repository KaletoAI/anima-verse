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
  /** Passable / transit locations are pass-through nodes (corridors,
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
  /** Shared-library item — ships with the game repo, so it is never exported. */
  _shared?: boolean
}

export async function loadItems(): Promise<ItemRef[]> {
  const data = await apiGet<{ items?: ItemRef[] }>('/inventory/items?include_shared=1')
  return data.items || []
}

export interface PropRef {
  id: string
  name?: string
  category?: string
  /** False = the record exists but has no mesh yet — a picker that hands out
   *  model URLs must skip those. */
  has_model?: boolean
}

export async function loadProps(): Promise<PropRef[]> {
  const data = await apiGet<{ props?: PropRef[] }>('/world/props')
  return data.props || []
}

/** The prop library for pickers, from the LEAN endpoint (a bare array).
 *  `/world/props` answers the same names but also spins up the image service
 *  and lists backends — nothing a picker needs. */
export async function loadPropAssets(): Promise<PropRef[]> {
  const data = await apiGet<PropRef[]>('/assets/props')
  return Array.isArray(data) ? data : []
}

export interface RuleRef {
  id?: string
  name?: string
  /** `shared` marks a baseline rule from the repo — not exportable. */
  _origin?: string
}

export async function loadRules(): Promise<RuleRef[]> {
  const data = await apiGet<{ rules?: RuleRef[] }>('/rules')
  return data.rules || []
}
