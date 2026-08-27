/** One function per /improvements endpoint — no logic, just the call. */
import { apiDelete, apiGet, apiPatch, apiPost, apiPut } from '../../lib/api'
import type {
  EngineStatus, Improvement, ImprovementType, PreviewResult, QueueSnapshot,
  Settings, Step,
} from './types'

export function fetchTypes(): Promise<ImprovementType[]> {
  return apiGet<ImprovementType[]>('/improvements/types')
}

export function fetchImprovements(): Promise<Improvement[]> {
  return apiGet<Improvement[]>('/improvements')
}

export function fetchQueue(): Promise<QueueSnapshot> {
  return apiGet<QueueSnapshot>('/improvements/queue')
}

export function fetchStatus(): Promise<EngineStatus> {
  return apiGet<EngineStatus>('/improvements/status')
}

export function createImprovement(body: {
  type_id: string; label: string; mode: string; params: Record<string, string>
}): Promise<Improvement> {
  return apiPost<Improvement>('/improvements', body)
}

export function previewImprovement(
  type_id: string, params: Record<string, string>,
): Promise<PreviewResult> {
  return apiPost<PreviewResult>('/improvements/preview', { type_id, params })
}

export function patchImprovement(id: string, body: {
  label?: string; params?: Record<string, string>; mode?: string
}): Promise<Improvement> {
  return apiPatch<Improvement>(`/improvements/${encodeURIComponent(id)}`, body)
}

export function deleteImprovement(id: string): Promise<unknown> {
  return apiDelete(`/improvements/${encodeURIComponent(id)}`)
}

export function pauseImprovement(id: string): Promise<Improvement> {
  return apiPost<Improvement>(`/improvements/${encodeURIComponent(id)}/pause`, {})
}

export function resumeImprovement(id: string): Promise<Improvement> {
  return apiPost<Improvement>(`/improvements/${encodeURIComponent(id)}/resume`, {})
}

export function runNow(id: string): Promise<unknown> {
  return apiPost(`/improvements/${encodeURIComponent(id)}/run-now`, {})
}

export function rescanImprovement(id: string): Promise<{ added: number; closed: number }> {
  return apiPost(`/improvements/${encodeURIComponent(id)}/rescan`, {})
}

export function fetchSteps(id: string): Promise<Step[]> {
  return apiGet<Step[]>(`/improvements/${encodeURIComponent(id)}/steps`)
}

export function retryStep(id: string, candidateKey: string): Promise<unknown> {
  return apiPost(
    `/improvements/${encodeURIComponent(id)}/steps/${encodeURIComponent(candidateKey)}/retry`,
    {})
}

export function setOrder(ids: string[]): Promise<unknown> {
  return apiPatch('/improvements/order', { ids })
}

export function saveSettings(enabled: boolean, idleMinutes: number): Promise<Settings> {
  return apiPut<Settings>('/improvements/settings',
    { enabled, idle_minutes: idleMinutes })
}
