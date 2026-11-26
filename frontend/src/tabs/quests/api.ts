/** One function per /quests endpoint the Quests tab calls — no logic, just the call — plus the reader of the
 *  route's error shape (`{code, message[, issues | current]}`, see the docstring of app/routes/quests.py). */
import { ApiError, apiDelete, apiGet, apiPost, apiPut } from '../../lib/api'
import type { Catalog, Issue } from './questsModel'

/** A row of `GET /quests/templates`. */
export interface TemplateListRow {
  id: string
  title: string
  state: 'draft' | 'ready'
  origin?: string
  revision: number
  updated_at?: string
  open_runs: number
}

/** A full template as the server answers it (GET, POST, PUT), with its authoring issues. */
export type TemplateRow = Record<string, unknown> & { id: string; revision: number; issues: Issue[] }

export function fetchCatalog(): Promise<Catalog> {
  return apiGet<Catalog>('/quests/catalog')
}

export async function fetchTemplates(): Promise<TemplateListRow[]> {
  const data = await apiGet<{ templates?: TemplateListRow[] }>('/quests/templates')
  return data.templates || []
}

export function fetchTemplate(id: string): Promise<TemplateRow> {
  return apiGet<TemplateRow>(`/quests/templates/${encodeURIComponent(id)}`)
}

/** Create a template; the server always stores it as a `draft` (`state` is not a create field). */
export function createTemplate(body: Record<string, unknown>): Promise<TemplateRow> {
  return apiPost<TemplateRow>('/quests/templates', body)
}

export function updateTemplate(id: string, body: Record<string, unknown>, baseRevision: number): Promise<TemplateRow> {
  return apiPut<TemplateRow>(`/quests/templates/${encodeURIComponent(id)}`, { ...body, base_revision: baseRevision })
}

export function deleteTemplate(id: string): Promise<unknown> {
  return apiDelete(`/quests/templates/${encodeURIComponent(id)}`)
}

/** One entry of a run's step log: who fulfilled which step (0-based) at which game stamp; `game_label` is that
 *  stamp as a finished server label. */
export interface StepLogEntry { step: number; avatar: string; mind?: string; game_ts?: string; game_label?: string }

/** One created world object tracked for a quest run. */
export interface RunObject { kind: string; label: string; permanent: boolean; status: string }

/** One payout batch of a quest run (`setup`, `step:<i>` or `reward`). */
export interface RunPayout { position: string; state: string; issues: Issue[] }

/** A row of `GET /quests/runs` (`_run_row` in app/routes/quests.py); the labels are finished server strings. */
export interface RunRow {
  id: string
  title: string
  state: string
  current_step: number
  step_count: number
  step_log: StepLogEntry[]
  bindings: Record<string, Record<string, string>>
  /** role key -> display label, frozen when the run started (a character's, location's, room's or item's name). */
  binding_labels: Record<string, string>
  issues: Issue[]
  started_game_label: string
  expires_label: string
  objects: RunObject[]
  payouts: RunPayout[]
}

/** Runs, every not yet ended one first; `state` ('' = all) narrows to one state. */
export async function fetchRuns(state: string, lang: string): Promise<RunRow[]> {
  const qs = new URLSearchParams({ lang })
  if (state) qs.set('state', state)
  const data = await apiGet<{ runs?: RunRow[] }>(`/quests/runs?${qs.toString()}`)
  return data.runs || []
}

/** End a not yet ended run as cancelled; `ok` is false when it had already ended. */
export function cancelRun(id: string): Promise<{ ok: boolean }> {
  return apiPost<{ ok: boolean }>(`/quests/runs/${encodeURIComponent(id)}/cancel`, {})
}

/** Re-arm failed payouts of a run (and clear a preparing run's issues); `ok` is false when nothing is pending retry. */
export function retryRun(id: string): Promise<{ ok: boolean }> {
  return apiPost<{ ok: boolean }>(`/quests/runs/${encodeURIComponent(id)}/retry`, {})
}

/** Start a run of a ready template; a refusal is 422 `refused` with issues. */
export function startRun(templateId: string, bindings: Record<string, Record<string, string>>): Promise<Record<string, unknown>> {
  return apiPost<Record<string, unknown>>(`/quests/templates/${encodeURIComponent(templateId)}/start`, { bindings })
}

/** The parts of a /quests error the form acts on. `code` is '' for anything that is not such an error
 *  (a network failure, say); `message` is always set. */
export interface QuestError { status: number; code: string; message: string; issues: Issue[] }

export function questError(e: unknown): QuestError {
  if (e instanceof ApiError) {
    const d = e.detail && typeof e.detail === 'object' ? (e.detail as Record<string, unknown>) : {}
    return {
      status: e.status,
      code: typeof d.code === 'string' ? d.code : '',
      message: typeof d.message === 'string' ? d.message : e.message,
      issues: Array.isArray(d.issues) ? (d.issues as Issue[]) : [],
    }
  }
  return { status: 0, code: '', message: (e as Error)?.message || String(e), issues: [] }
}
