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

/** A fresh, empty template draft (no id: not yet created). */
export function emptyDraft(): TemplateDraft {
  return rowToDraft({})
}
