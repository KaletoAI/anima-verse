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
  /**
   * The choices, when the type ships them. `enum`/`subject_kind` always do;
   * a backend field may, to narrow the global list to the backends its
   * subject can actually use. `own_options` preserves an explicitly empty list.
   */
  options: Array<{ value: string; label: string }>
  own_options?: boolean
  default?: string
  show_if?: Record<string, string[]>
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
  /** "Run now" is active: the entry runs past idle window, engine switch and freeze. */
  forced: boolean
  pending: number
  running: number
  done: number
  failed: number
  skipped: number
  /** The hub jobs its PENDING steps would still submit (first attempts);
   *  null when any of them could not be estimated. */
  pending_hub_jobs: number | null
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
  /** Estimated hub jobs of this step (first attempts); null = unknown. */
  hub_jobs?: number | null
  /** One line: what the estimate counts, or the dry-run summary. */
  note?: string
  /** A skipped step its subject's own gates refused — terminal, Retry answers
   *  409 "refused" (SQLite hands the flag over as 0/1). */
  refused?: number | boolean
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
  /** 'media_off' | 'disabled' | 'frozen' | 'paused' | 'busy' | 'active' | 'ok' */
  reason: string
  /** An entry runs by "Run now" — past idle window, engine switch, freeze, pause. */
  forced: boolean
  running_step: Step | null
  pending_total: number
  /** The hub jobs the open entries still owe; null when any is unknown. */
  pending_hub_jobs: number | null
  estimate_s: number | null
}

export interface Settings {
  enabled: boolean
  idle_minutes: number
}

/** One candidate of a preview, with its hub cost (null = unknown). */
export interface PreviewSample {
  label: string
  hub_jobs: number | null
  note: string
}

export interface PreviewResult {
  count: number
  /** The sum of the known estimates over ALL candidates, not just the sample. */
  hub_jobs: number
  /** How many candidates could not be estimated. */
  unknown: number
  sample: PreviewSample[]
}

/**
 * The step statuses, as English UI strings — the raw enum is not one. Both
 * views translate through this map, so a step reads the same in the queue and
 * in an entry's step log. It lives next to the types it labels rather than in
 * a view, which is also what keeps either view hot-reloadable.
 */
export const STEP_STATUS_LABELS: Record<string, string> = {
  pending: 'Pending',
  running: 'Running',
  done: 'Done',
  failed: 'Failed',
  skipped: 'Skipped',
  // Not a status of its own: a skipped step with the `refused` flag. The
  // views ask `stepStatus(step)` for the key, so both read it the same way.
  refused: 'Refused',
}

/** The label key of a step: `refused` for a refused skip, else its status. */
export function stepStatus(step: Pick<Step, 'status' | 'refused'>): string {
  return step.refused ? 'refused' : step.status
}

/** A step's hub cost as a short UI string: "{n} hub jobs" / "hub jobs unknown". */
export function hubJobsText(n: number | null | undefined,
                            t: (s: string) => string): string {
  return n === null || n === undefined
    ? t('hub jobs unknown')
    : t('{n} hub jobs').replace('{n}', String(n))
}
