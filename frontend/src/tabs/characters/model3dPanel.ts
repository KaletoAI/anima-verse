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
  setModelOption: (key: 'auto_generate' | 'face_before_rig', value: boolean) => Promise<void>
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
