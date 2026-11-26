/**
 * The pure model of the Quests tab: the template draft the editor works on, its conversion from and to the
 * server row, and small helpers the form needs. No components and no imports but types (the node test
 * `questsModel.test.mjs` loads this file on its own).
 *
 * Shapes follow the plan decisions: an expression is D7 (`{}` = always true, a leaf `{type, params}`, or one of
 * `all` / `any` / `not`); a step is D8; issue paths are D7 (dot-joined, 0-based indices).
 */

export type RoleKind = 'character' | 'location' | 'room' | 'item'
export interface Role { key: string; kind: RoleKind; description: string }
// eslint-disable-next-line @typescript-eslint/no-empty-object-type -- `{}` IS the "always true" expression (D7)
export type Expr = {} | { type: string; params: Record<string, unknown> } | { all: Expr[] } | { any: Expr[] } | { not: Expr }
export interface Step { id: string; text: string; hint: string; condition: Expr }
export interface TemplateDraft {
  id: string; revision: number; title: string; summary: string; gm_notes: string
  state: 'draft' | 'ready'; roles: Role[]; steps: Step[]; start_condition: Expr
  prerequisites: { condition: Expr; locked_text: string }; time_limit_h: number
}
export interface Issue { path: string; code: string; message: string }

/** One parameter of a catalog type (D5: the config_schema field vocabulary plus `key`). */
export interface ParamSpec {
  key: string
  type: 'str' | 'text' | 'int' | 'float' | 'bool' | 'select' | 'role' | string
  label?: string
  description?: string
  default?: unknown
  min?: number
  max?: number
  step?: number
  choices?: string[]
  choice_labels?: string[]
  required?: boolean
  role_kinds?: RoleKind[]
}
/** A public type descriptor of `GET /quests/catalog`. */
export interface CatalogType {
  id: string
  kind: 'condition' | 'prerequisite' | 'effect' | string
  label: string
  description: string
  params: ParamSpec[]
  signals?: string[]
}
export interface Catalog {
  conditions: CatalogType[]
  prerequisites: CatalogType[]
  effects: CatalogType[]
  role_kinds: RoleKind[]
}

export const ROLE_KINDS: RoleKind[] = ['character', 'location', 'room', 'item']
const SECONDS_PER_HOUR = 3600

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function str(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

/** A deep copy of a JSON value (an expression), so a draft never shares objects with the row it came from. */
function copyExpr(value: unknown): Expr {
  return isObject(value) ? (JSON.parse(JSON.stringify(value)) as Expr) : {}
}

/** The editor draft of a template row (`GET /quests/templates/{id}`); `time_limit_s` becomes game hours. A row
 *  without an id (a new template) gets `id: ''` and revision 0. */
export function rowToDraft(row: unknown): TemplateDraft {
  const r = isObject(row) ? row : {}
  const roles = Array.isArray(r.roles) ? r.roles : []
  const steps = Array.isArray(r.steps) ? r.steps : []
  const prerequisites = isObject(r.prerequisites) ? r.prerequisites : {}
  const seconds = typeof r.time_limit_s === 'number' && Number.isFinite(r.time_limit_s) ? r.time_limit_s : 0
  return {
    id: str(r.id),
    revision: typeof r.revision === 'number' ? r.revision : 0,
    title: str(r.title),
    summary: str(r.summary),
    gm_notes: str(r.gm_notes),
    state: r.state === 'ready' ? 'ready' : 'draft',
    roles: roles.map((role) => {
      const o = isObject(role) ? role : {}
      return { key: str(o.key), kind: str(o.kind) as RoleKind, description: str(o.description) }
    }),
    steps: steps.map((step) => {
      const o = isObject(step) ? step : {}
      return { id: str(o.id), text: str(o.text), hint: str(o.hint), condition: copyExpr(o.condition) }
    }),
    start_condition: copyExpr(r.start_condition),
    prerequisites: { condition: copyExpr(prerequisites.condition), locked_text: str(prerequisites.locked_text) },
    time_limit_h: seconds / SECONDS_PER_HOUR,
  }
}

/** The body fields of a draft (the editable template keys). `id` is the URL and `revision` travels as
 *  `base_revision`, so neither is part of it. Prerequisites without a condition and without a lock text are
 *  `{}`, as the server stores "no prerequisites". */
export function draftToRow(d: TemplateDraft): Record<string, unknown> {
  const prereqEmpty = isEmptyExpr(d.prerequisites.condition) && !d.prerequisites.locked_text
  return {
    title: d.title,
    summary: d.summary,
    gm_notes: d.gm_notes,
    roles: d.roles.map((r) => ({ key: r.key, kind: r.kind, description: r.description })),
    steps: d.steps.map((s) => ({ id: s.id, text: s.text, hint: s.hint, condition: copyExpr(s.condition) })),
    start_condition: copyExpr(d.start_condition),
    prerequisites: prereqEmpty ? {} : { condition: copyExpr(d.prerequisites.condition), locked_text: d.prerequisites.locked_text },
    time_limit_s: Math.max(0, Math.round((Number.isFinite(d.time_limit_h) ? d.time_limit_h : 0) * SECONDS_PER_HOUR)),
    state: d.state,
  }
}

/** The issues at `path` or below it — a prefix match on whole path segments, so `steps.1` finds
 *  `steps.1.condition.params.item` but not `steps.10.text`. */
export function issuesAt(issues: Issue[], path: string): Issue[] {
  return issues.filter((i) => i.path === path || i.path.startsWith(path + '.'))
}

/** The first free step id of the form `s<n>`, counting from 1. */
export function newStepId(steps: Step[]): string {
  const taken = new Set(steps.map((s) => s.id))
  let n = 1
  while (taken.has('s' + n)) n += 1
  return 's' + n
}

/** The roles whose kind is one of `kinds`, in their order. */
export function rolesOfKinds(roles: Role[], kinds: RoleKind[]): Role[] {
  return roles.filter((r) => kinds.includes(r.kind))
}

/** True for `{}` (the always-true expression). */
export function isEmptyExpr(expr: Expr): boolean {
  return isObject(expr) && Object.keys(expr).length === 0
}

/** The default parameter values of a type: every spec entry that declares a `default`. */
export function defaultParams(type: CatalogType | undefined): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const p of type?.params || []) if (p.default !== undefined) out[p.key] = p.default
  return out
}

/** What a role picker holds while the admin chooses: the union of the D6 binding keys. */
export interface RolePick { name?: string; location_id?: string; room_id?: string; item_id?: string }

/** The keys of a role kind's binding (D6), in their order. */
const BINDING_KEYS: Record<RoleKind, (keyof RolePick)[]> = {
  character: ['name'],
  location: ['location_id'],
  room: ['location_id', 'room_id'],
  item: ['item_id'],
}

/** The D6 binding of a role of `kind` built from a picker's state — only the keys of that kind, and `null` while
 *  one of them is still empty (a room needs its location AND its room) or the kind is unknown. */
export function bindingFor(kind: RoleKind, pick: RolePick): Record<string, string> | null {
  const keys = BINDING_KEYS[kind]
  if (!keys) return null
  const out: Record<string, string> = {}
  for (const k of keys) {
    const v = pick[k]
    if (typeof v !== 'string' || !v) return null
    out[k] = v
  }
  return out
}

/** True when every role has a complete binding among `picks` (keyed by role key). */
export function bindingsComplete(roles: Role[], picks: Record<string, unknown>): boolean {
  return roles.every((r) => {
    const pick = picks[r.key]
    return isObject(pick) && bindingFor(r.kind, pick as RolePick) !== null
  })
}

/** The run states of a quest run (stage 1): not yet ended first, then the ended ones. */
export const RUN_STATES = ['preparing', 'hidden', 'open', 'done', 'failed', 'cancelled', 'broken'] as const
export type RunState = typeof RUN_STATES[number]
export const RUN_OPEN_STATES: readonly string[] = ['preparing', 'hidden', 'open']

/** "current / count" with the current step 1-based; a done run (current_step == count) stays at count. */
export function stepProgress(current: number, count: number): string {
  const n = Math.max(0, count)
  return `${Math.min(Math.max(0, current) + 1, n)} / ${n}`
}

/** A fresh, empty template draft (no id: not yet created). */
export function emptyDraft(): TemplateDraft {
  return rowToDraft({})
}

/** The `{role}` placeholders a player text may use: one per declared role key, in role order, duplicates and
 *  blank keys left out (e.g. "{giver} {place} {thing}"); "" without roles. */
export function placeholderList(roles: Role[]): string {
  const keys: string[] = []
  for (const r of roles) if (r.key.trim() && !keys.includes(r.key)) keys.push(r.key)
  return keys.map((k) => `{${k}}`).join(' ')
}

/** `list` with the entry at `from` moved to `to` (both clamped to the list); the same array when nothing moves. */
export function moveItem<T>(list: T[], from: number, to: number): T[] {
  if (from < 0 || from >= list.length) return list
  const target = Math.max(0, Math.min(list.length - 1, to))
  if (target === from) return list
  const next = list.slice()
  const [item] = next.splice(from, 1)
  next.splice(target, 0, item)
  return next
}

/** The options whose label contains `query` (case-insensitive, trimmed; an empty query keeps all). The option whose
 *  value is `selected` always stays, so a select never loses the value it shows. */
export function filterOptions<T>(options: T[], query: string, label: (o: T) => string, value: (o: T) => string,
  selected: string): T[] {
  const q = query.trim().toLowerCase()
  if (!q) return options
  return options.filter((o) => (selected && value(o) === selected) || label(o).toLowerCase().includes(q))
}

/** True when the template editor's Save does something: a new template (no id yet) or unsaved edits. */
export function canSave(draft: TemplateDraft | null, dirty: boolean): boolean {
  return !!draft && (!draft.id || dirty)
}

/** The English text of each /quests route refusal `code` (app/routes/quests.py), translated by the caller. */
export const ERROR_CODE_TEXTS: Record<string, string> = {
  has_open_runs: 'End the open runs of this template before deleting it.',
  stale: 'The template changed since it was loaded.',
  not_found: 'It does not exist (any more).',
  refused: 'The run was refused.',
  invalid: 'The template has issues.',
  bad_json: 'The request was not valid JSON.',
  bad_request: 'The input was refused.',
  revision_required: 'Load the template again before saving.',
  too_large: 'The template is too large to save.',
}

/** A /quests refusal as one line for the admin: the translated text of its `code` — for `bad_request` followed by
 *  the server's (English) reason, which names the field — or the server's message for an unknown code. */
export function questErrorText(err: { code: string; message: string }, t: (s: string) => string): string {
  const text = ERROR_CODE_TEXTS[err.code]
  if (!text) return err.message
  return err.code === 'bad_request' && err.message ? `${t(text)} ${err.message}` : t(text)
}
