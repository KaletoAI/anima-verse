/**
 * The shapes GET /improvements/* delivers. They mirror
 * app/core/improvements/{store,engine,base}.py one to one — the server
 * computes, the tab renders.
 */

/** One configurable parameter of an improvement type (ParamField.to_dict). */
export interface ParamField {
  key: string
  label: string
  /** 'mesh_backend' | 'image_backend' | 'subject_kind' | 'enum' | 'text' */
  kind: string
  options: Array<{ value: string; label: string }>
  required: boolean
}

export interface ImprovementType {
  id: string
  label: string
  params_schema: ParamField[]
}

/** A queue entry: the row plus the step counters the store joins in. */
export interface Improvement {
  id: string
  type_id: string
  label: string
  params: Record<string, string>
  /** 'one_shot' | 'standing' */
  mode: string
  /** 'open' | 'paused' | 'done' */
  status: string
  position: number
  created_at: string
  last_scan_at?: string | null
  done_count: number
  failed_count: number
  pending: number
  running: number
  done: number
  failed: number
  skipped: number
}

/** One candidate of one entry. */
export interface Step {
  improvement_id: string
  candidate_key: string
  candidate_label: string
  /** 'pending' | 'running' | 'done' | 'failed' | 'skipped' */
  status: string
  attempts: number
  error: string
  started_at?: string | null
  finished_at?: string | null
  duration_s?: number | null
}

/** A step in the running order, carrying its entry's label/type/mode. */
export interface QueueRow extends Step {
  pos: number
  label: string
  type_id: string
  mode: string
}

/** A finished step, carrying its entry's label and type. */
export interface RecentRow extends Step {
  label: string
  type_id: string
}

export interface QueueSnapshot {
  queue: QueueRow[]
  recent: RecentRow[]
}

/** The head of the panel: the gate, the countdown and the rest estimate. */
export interface EngineStatus {
  enabled: boolean
  idle_minutes: number
  idle_seconds: number
  next_allowed_in_s: number
  frozen: boolean
  /** 'disabled' | 'frozen' | 'busy' | 'active' | 'ok' */
  reason: string
  running_step: Step | null
  pending_total: number
  estimate_s: number | null
}

export interface Settings {
  enabled: boolean
  idle_minutes: number
}

export interface PreviewResult {
  count: number
  sample: string[]
}
