export interface Room {
  id?: string
  name?: string
  description?: string
  // Indoor/outdoor override — the room's flag wins over the location's
  // (a pool room in an indoor house = outdoor). Empty = inherit location.
  indoor?: string
  // Decency (plan-outfit-system-rethink.md §1.1) — replaces the old outfit_type model
  decency?: '' | 'public' | 'private' | 'nude_ok'
  style_hint?: string
  swim_allowed?: boolean
  activity_hint?: string
  image_prompt_day?: string
  image_prompt_night?: string
}

export interface EventSettings {
  event_probability?: number
  max_concurrent_events?: number
  event_cooldown_hours?: number
  allowed_categories?: string[]
  event_blacklist?: string[]
}

export interface Location {
  id: string
  name: string
  description?: string
  rooms?: Room[]
  entry_room?: string
  danger_level?: number
  indoor?: string
  decency?: '' | 'public' | 'private' | 'nude_ok'
  style_hint?: string
  swim_allowed?: boolean
  activity_hint?: string
  knowledge_item_id?: string
  passable?: boolean
  image_prompt_day?: string
  image_prompt_night?: string
  image_prompt_map_2d?: string
  image_count?: number
  is_template?: boolean
  template_location_id?: string
  grid_x?: number | null
  grid_y?: number | null
  map_image_2d?: string
  event_settings?: EventSettings
}

export const EVENT_CATEGORIES = ['ambient', 'social', 'disruption', 'danger'] as const

// Danger level scale (0–5). Drives hourly stamina/stat drain (danger_system.py)
// and danger-based block rules. Labels describe what each step means.
export const DANGER_LEVELS: Array<{ value: number; label: string }> = [
  { value: 0, label: 'Safe' },
  { value: 1, label: 'Low' },
  { value: 2, label: 'Moderate' },
  { value: 3, label: 'High' },
  { value: 4, label: 'Severe' },
  { value: 5, label: 'Extreme' },
]

export interface GalleryResponse {
  images: string[]
  image_rooms?: Record<string, string>
  image_types?: Record<string, string>
  image_metas?: Record<string, { backend?: string; model?: string; loras?: string[] }>
}

export const IMAGE_TYPES = ['', 'day', 'night', 'map_2d'] as const

export type Selection =
  | { kind: 'location'; locationId: string }
  | { kind: 'room'; locationId: string; roomId: string }
  | null
