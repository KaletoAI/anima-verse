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
