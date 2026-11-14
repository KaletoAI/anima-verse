import { useCallback, useSyncExternalStore } from 'react'
import type { ExtensionRigResult, Model3DStatus } from './FieldModel3D'
import type { Physics } from '../../lib/motionDraft'

export interface Model3DPanelSnapshot {
  st: Model3DStatus
  pending: boolean
  busy: boolean
  rigless: boolean
  mixamo: boolean
  viewTier: 'full' | 'low'
  extensionResult: ExtensionRigResult | undefined
  canMeasure: boolean
  model: Model3DStatus['model']
  setModelOption: (key: 'auto_generate', value: boolean) => Promise<void>
  setExtensionOption: (id: string, key: 'enabled' | 'flip', value: boolean) => Promise<void>
  setExtensionMotion: (id: string, values?: Physics, slidersOnly?: boolean) => Promise<boolean>
  rebuildExtensions: () => Promise<void>
  playUrl: string
  setPlayUrl: (url: string) => void
}

// FieldModel3D owns all state and actions. Entries contain only its published
// snapshots; reading a slot never starts another status poll or API request.
const snapshots = new Map<string, Model3DPanelSnapshot>()
const listeners = new Map<string, Set<() => void>>()

export function publishModel3DPanel(character: string, snapshot: Model3DPanelSnapshot) {
  snapshots.set(character, snapshot)
  listeners.get(character)?.forEach(listener => listener())
}

export function clearModel3DPanel(character: string) {
  snapshots.delete(character)
  listeners.get(character)?.forEach(listener => listener())
}

const serverSnapshot = () => null

export function useModel3DPanel(character: string) {
  const subscribe = useCallback((listener: () => void) => {
    let group = listeners.get(character)
    if (!group) {
      group = new Set()
      listeners.set(character, group)
    }
    group.add(listener)
    return () => {
      group.delete(listener)
      if (!group.size) listeners.delete(character)
    }
  }, [character])
  const getSnapshot = useCallback(() => snapshots.get(character) ?? null, [character])
  return useSyncExternalStore(subscribe, getSnapshot, serverSnapshot)
}

/** The 3D tab's details panel (Model3DDetails, column 2): one DOM element per sub-tab that FieldModel3D renders
 *  its own parts into (createPortal) — the steps, the model's facts and single steps, the advanced actions. They
 *  stay in FieldModel3D's tree (its state, its handlers); only their place on screen is the panel's. */
export interface Model3DTargets { steps: HTMLElement; model: HTMLElement; advanced: HTMLElement }

const targets = new Map<string, Model3DTargets>()
const targetListeners = new Map<string, Set<() => void>>()

export function publishModel3DTargets(character: string, value: Model3DTargets | null) {
  if (value) targets.set(character, value)
  else targets.delete(character)
  targetListeners.get(character)?.forEach(listener => listener())
}

export function useModel3DTargets(character: string) {
  const subscribe = useCallback((listener: () => void) => {
    let group = targetListeners.get(character)
    if (!group) {
      group = new Set()
      targetListeners.set(character, group)
    }
    group.add(listener)
    return () => {
      group.delete(listener)
      if (!group.size) targetListeners.delete(character)
    }
  }, [character])
  const getSnapshot = useCallback(() => targets.get(character) ?? null, [character])
  return useSyncExternalStore(subscribe, getSnapshot, serverSnapshot)
}
