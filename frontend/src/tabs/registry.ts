import type { ComponentType } from 'react'
import { SetupTab } from './setup/SetupTab'
import { CharactersTab } from './characters/CharactersTab'
import { StorytellerTab } from './storyteller/StorytellerTab'
// ActivitiesTab + OutfitRulesTab versteckt seit Schritt 5/7 (May 2026,
// plan-outfit-system-rethink.md): Activity-Library und outfit_types werden
// durch Pose-Variants + Decency ersetzt. Source bleibt im Tree fuer finalen
// Cleanup in Schritt 8.
import { RulesTab } from './rules/RulesTab'
import { StatesTab } from './states/StatesTab'
import { ItemsTab } from './items/ItemsTab'
import { WorldTab } from './world/WorldTab'
import { MapTab } from './map/MapTab'
import { SurfaceTexturesTab } from './map/SurfaceTexturesTab'
import { TerrainTab } from './terrain/TerrainTab'
import { PropsTab } from './props/PropsTab'
import { WorldDevTab } from './world-dev/WorldDevTab'
import { SchedulerTab } from './scheduler/SchedulerTab'
import { ImprovementsTab } from './improvements/ImprovementsTab'
import { IntentsTab } from './intents/IntentsTab'
import { EventsTab } from './events/EventsTab'
import { MarketplaceTab } from './marketplace/MarketplaceTab'
import { ObserverTab } from './observer/ObserverTab'
import { MindTab } from './mind/MindTab'
import { PosesTab } from './poses/PosesTab'

export type TabId =
  | 'setup'
  | 'characters'
  | 'storyteller'
  | 'rules'
  | 'states'
  | 'items'
  | 'world'
  | 'map'
  | 'terrain'
  | 'surface-textures'
  | 'props'
  | 'world-dev'
  | 'scheduler'
  | 'improvements'
  | 'intents'
  | 'events'
  | 'marketplace'
  | 'observer'
  | 'mind'
  | 'poses'

export interface TabSpec {
  id: TabId
  label: string // English source — translated via t() at render time.
  Component: ComponentType
}

export const TABS: TabSpec[] = [
  { id: 'setup', label: 'Setup', Component: SetupTab },
  { id: 'characters', label: 'Characters', Component: CharactersTab },
  { id: 'storyteller', label: 'Storyteller', Component: StorytellerTab },
  { id: 'rules', label: 'Rules', Component: RulesTab },
  { id: 'states', label: 'States', Component: StatesTab },
  { id: 'items', label: 'Items', Component: ItemsTab },
  { id: 'world', label: 'Locations', Component: WorldTab },
  { id: 'map', label: 'Map', Component: MapTab },
  { id: 'terrain', label: 'Terrain', Component: TerrainTab },
  { id: 'surface-textures', label: 'Surface textures', Component: SurfaceTexturesTab },
  { id: 'props', label: 'Props', Component: PropsTab },
  { id: 'world-dev', label: 'World Dev', Component: WorldDevTab },
  { id: 'scheduler', label: 'Scheduler', Component: SchedulerTab },
  { id: 'improvements', label: 'Improvements', Component: ImprovementsTab },
  { id: 'intents', label: 'Intents', Component: IntentsTab },
  { id: 'events', label: 'Events', Component: EventsTab },
  { id: 'marketplace', label: 'Marketplace', Component: MarketplaceTab },
  { id: 'observer', label: 'Observer', Component: ObserverTab },
  { id: 'mind', label: 'Mind', Component: MindTab },
  { id: 'poses', label: 'Poses', Component: PosesTab },
]

const TAB_IDS: ReadonlySet<string> = new Set(TABS.map((t) => t.id))

export function isTabId(value: string): value is TabId {
  return TAB_IDS.has(value)
}
