/**
 * FreshnessBadge — the ONE corner badge of the character tabs that says
 * whether an image or a 3D preview comes from current data. The server
 * decides (`app/core/model_overview.py`): every image info and model payload
 * of the Base body, Pose, Hair and 3D tabs carries
 * `freshness: {state, reason}`:
 *
 *   current  green  "current"
 *   stale    amber  "outdated: <reason>" — the reason is one or more fixed
 *                    English phrases joined by " · ", each translated here
 *   missing  grey   "no data" — nothing recorded to compare against
 *
 * A model reason that compares the model with the views it was built from
 * names the view (Ruling UI3 b — "Front view changed after this model"); WHEN
 * comes separately in `changed_views` ([{view, at, reason}]) and `built_at`,
 * and is formatted here in the viewer's clock: "Front view changed after this
 * model · 20:30". `action` names what resolves it ("Run all rebuilds it",
 * UI3 c). The tooltip carries both stamps: the model's and each view's.
 *
 * Placed top left on every tile (RefImage) and 3D preview (Model3DViewer);
 * the top right belongs to their actions and view controls.
 */
import type { CSSProperties } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { freshnessText } from './freshnessText'

/** A view that changed after the model (Ruling UI3 b): `reason` is the reason part it belongs to. */
export interface ChangedView {
  view: string
  at: string | null
  reason: string
}

export interface Freshness {
  state: 'current' | 'stale' | 'missing'
  reason?: string
  /** UI3 b: the views that changed after the model, with their SYSTEM stamps. */
  changed_views?: ChangedView[]
  /** UI3 b: when the model was built. */
  built_at?: string | null
  /** UI3 c: the action that resolves the stale state (a fixed English phrase). */
  action?: string
}

const COLORS: Record<Freshness['state'], string> = {
  current: 'rgba(46, 160, 67, 0.85)',
  stale: 'rgba(187, 128, 9, 0.9)',
  missing: 'rgba(110, 118, 129, 0.85)',
}

const BADGE: CSSProperties = {
  display: 'inline-block',
  maxWidth: '100%',
  padding: '1px 5px',
  borderRadius: 4,
  color: '#fff',
  fontSize: 11,
  lineHeight: '16px',
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap',
  boxSizing: 'border-box',
  pointerEvents: 'auto',
}

const COMPACT: CSSProperties = { padding: '0 3px', fontSize: 10, lineHeight: '14px' }

export function FreshnessBadge({ freshness, compact = false }: {
  freshness: Freshness | null | undefined
  compact?: boolean
}) {
  const { t } = useI18n()
  if (!freshness || !COLORS[freshness.state]) return null
  const { text, title } = freshnessText(freshness, t)
  return (
    <span
      role="status"
      title={title}
      style={{ ...BADGE, ...(compact ? COMPACT : null), background: COLORS[freshness.state] }}
    >
      {text}
    </span>
  )
}

/** The badge in the top left corner of a positioned container. */
export function FreshnessCorner({ freshness, compact = false, inset = 6 }: {
  freshness: Freshness | null | undefined
  compact?: boolean
  inset?: number
}) {
  if (!freshness) return null
  return (
    <div style={{ position: 'absolute', top: inset, left: inset, maxWidth: `calc(70% - ${inset}px)`,
      display: 'flex', pointerEvents: 'none', zIndex: 1 }}>
      <FreshnessBadge freshness={freshness} compact={compact} />
    </div>
  )
}
