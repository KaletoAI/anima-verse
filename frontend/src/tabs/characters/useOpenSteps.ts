/**
 * useOpenSteps — `GET /characters/open-steps` (Ruling A112, `figure_build.open_steps`) for the character list:
 * one read on mount and on every roster change, on window focus (at most once per 10 s), on the push topic
 * `generation` (debounced 300 ms), every 5 s while a Build runs or `batchRunning` ("Build all open" — its base
 * steps do not count as building; a tick is skipped while the last read is still pending), and whenever
 * `refreshTick` changes (that run started or ended).
 */
import { useCallback, useEffect, useState } from 'react'
import { syncHub } from '@anima/player-ui'
import { apiGet } from '../../lib/api'
import { debounced, guardedInterval, throttled } from '../../lib/guardedPoll'

export interface OpenStep { label: string; jobs: number | null; hold: boolean; why: string }
export interface OpenGroup { count: number; hub_jobs: number | null; hold: boolean; steps: OpenStep[] }
export interface OpenSteps { building: boolean; base: OpenGroup; outfit: OpenGroup }

const BUILDING_POLL_MS = 5000
const PUSH_DEBOUNCE_MS = 300
const FOCUS_THROTTLE_MS = 10000

export function useOpenSteps(rosterSize: number, batchRunning = false, refreshTick = 0) {
  const [data, setData] = useState<Record<string, OpenSteps>>({})
  const load = useCallback(() => {
    return apiGet<{ characters?: Record<string, OpenSteps> }>('/characters/open-steps')
      .then((r) => setData(r.characters || {}))
      .catch(() => { /* badges are optional; keep the last answer */ })
  }, [])
  useEffect(() => { load() }, [load, rosterSize, refreshTick])
  useEffect(() => {
    const onPush = debounced(() => { load() }, PUSH_DEBOUNCE_MS)
    const off = syncHub().onTopics(['generation'], onPush)
    const onFocus = throttled(() => { load() }, FOCUS_THROTTLE_MS)
    window.addEventListener('focus', onFocus)
    return () => { off(); onPush.cancel(); window.removeEventListener('focus', onFocus) }
  }, [load])
  const building = batchRunning || Object.values(data).some((d) => d.building)
  useEffect(() => {
    if (!building) return
    return guardedInterval(load, BUILDING_POLL_MS)
  }, [building, load])
  return data
}
