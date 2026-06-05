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
import { WorldDevTab } from './world-dev/WorldDevTab'
import { SchedulerTab } from './scheduler/SchedulerTab'
import { IntentsTab } from './intents/IntentsTab'
import { MarketplaceTab } from './marketplace/MarketplaceTab'
import { ObserverTab } from './observer/ObserverTab'

export type TabId =
  | 'setup'
  | 'characters'
  | 'storyteller'
  | 'rules'
  | 'states'
  | 'items'
  | 'world'
  | 'map'
  | 'world-dev'
  | 'scheduler'
  | 'intents'
  | 'marketplace'
  | 'observer'

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
  { id: 'world', label: 'World', Component: WorldTab },
  { id: 'map', label: 'Map', Component: MapTab },
  { id: 'world-dev', label: 'World Dev', Component: WorldDevTab },
  { id: 'scheduler', label: 'Scheduler', Component: SchedulerTab },
  { id: 'intents', label: 'Intents', Component: IntentsTab },
  { id: 'marketplace', label: 'Marketplace', Component: MarketplaceTab },
  { id: 'observer', label: 'Observer', Component: ObserverTab },
]

const TAB_IDS: ReadonlySet<string> = new Set(TABS.map((t) => t.id))

export function isTabId(value: string): value is TabId {
  return TAB_IDS.has(value)
}
