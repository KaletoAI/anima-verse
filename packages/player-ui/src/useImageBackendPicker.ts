/** Shared options loading and backend-scoped LoRA state for player dialogs.
 * The "video" occasion lists the video backends (the animate dialog). */
import { useEffect, useMemo, useState } from 'react'
import { apiGet } from './api'
import type { PoseCheckOption } from './PromptImprover'

/** One backend entry of `GET /world/imagegen-options` — the fields read here. */
interface BackendOption {
  name: string
  label?: string
  available?: boolean
  has_loras?: boolean
  /** This backend's LoRAs from the LoRA library; `missing` = vanished from
   *  its listing but still offered. */
  lora_options?: Array<{ name: string; missing?: boolean }>
}

interface LoraSlot { name: string; strength: number }

const LORA_SLOTS = 4
const emptySlots = (): LoraSlot[] =>
  Array.from({ length: LORA_SLOTS }, () => ({ name: '', strength: 1.0 }))

export interface BackendOptions {
  options?: BackendOption[]
  /** What "Auto (routing)" resolves this scene's occasion to right now. */
  resolved?: string | null
  media_generation_enabled?: boolean
  /** Whether the occasion offers the LLM pose check + the checkbox preset. */
  pose_check?: PoseCheckOption
}

export function useImageBackendPicker(occasion: 'photo' | 'scene_view' | 'regenerate' | 'video', avatar?: string,
  backendOptions?: BackendOptions) {
  const [backend, setBackend] = useState('')
  const [backends, setBackends] = useState<BackendOptions | null>(backendOptions ?? null)
  const [loraSlots, setLoraSlots] = useState<LoraSlot[]>(emptySlots)
  useEffect(() => {
    if (backendOptions !== undefined) {
      setBackends(backendOptions)
      return
    }
    let stale = false
    const q = `?occasion=${occasion}${occasion === 'photo' && avatar ? `&character=${encodeURIComponent(avatar)}` : ''}`
    apiGet<BackendOptions>(`/world/imagegen-options${q}`)
      .then((d) => { if (!stale) setBackends(d || {}) })
      .catch(() => { if (!stale) setBackends({}) })
    return () => { stale = true }
  }, [avatar, occasion, backendOptions])
  // Reachable backends first; offline ones keep the server's "(offline?)" label.
  const backendList = useMemo(() => {
    const list = backends?.options || []
    return [...list.filter((o) => o.available !== false),
            ...list.filter((o) => o.available === false)]
  }, [backends])
  const mediaOff = backends?.media_generation_enabled === false
  // The backend the LoRAs belong to: the pick, or what Auto resolves to.
  const current = useMemo(
    () => backendList.find((o) => o.name === (backend || backends?.resolved || '')) || null,
    [backendList, backend, backends])
  const loraOptions = useMemo(
    () => (current?.has_loras ? current.lora_options || [] : []), [current])
  // A backend switch clears the picks the new backend does not offer.
  useEffect(() => {
    const offered = new Set(loraOptions.map((l) => l.name))
    setLoraSlots((prev) => (prev.every((s) => !s.name || offered.has(s.name))
      ? prev
      : prev.map((s) => (!s.name || offered.has(s.name) ? s : { name: '', strength: 1.0 }))))
  }, [loraOptions])
  const setSlot = (i: number, patch: Partial<LoraSlot>) =>
    setLoraSlots((prev) => prev.map((s, idx) => (idx === i ? { ...s, ...patch } : s)))

  const picked = loraSlots.filter((s) => s.name && loraOptions.some((l) => l.name === s.name))
  return { backend, setBackend, backends, backendList, mediaOff, loraOptions, loraSlots, setSlot, picked }
}

