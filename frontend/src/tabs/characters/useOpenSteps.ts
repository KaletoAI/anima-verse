/**
 * useOpenSteps — `GET /characters/open-steps` (Ruling A112, `figure_build.open_steps`) for the character list:
 * one read on mount and on every roster change, on window focus, on the push topic `generation`, and every
 * 5 s while a Build runs.
 */
import { useCallback, useEffect, useState } from 'react'
import { syncHub } from '@anima/player-ui'
import { apiGet } from '../../lib/api'

export interface OpenStep { label: string; jobs: number | null; hold: boolean; why: string }
export interface OpenGroup { count: number; hub_jobs: number | null; hold: boolean; steps: OpenStep[] }
export interface OpenSteps { building: boolean; base: OpenGroup; outfit: OpenGroup }

const BUILDING_POLL_MS = 5000

export function useOpenSteps(rosterSize: number) {
  const [data, setData] = useState<Record<string, OpenSteps>>({})
  const load = useCallback(() => {
    apiGet<{ characters?: Record<string, OpenSteps> }>('/characters/open-steps')
      .then((r) => setData(r.characters || {}))
      .catch(() => { /* badges are optional; keep the last answer */ })
  }, [])
  useEffect(() => { load() }, [load, rosterSize])
  useEffect(() => {
    const off = syncHub().onTopics(['generation'], load)
    window.addEventListener('focus', load)
    return () => { off(); window.removeEventListener('focus', load) }
  }, [load])
  const building = Object.values(data).some((d) => d.building)
  useEffect(() => {
    if (!building) return
    const id = setInterval(load, BUILDING_POLL_MS)
    return () => clearInterval(id)
  }, [building, load])
  return data
}
