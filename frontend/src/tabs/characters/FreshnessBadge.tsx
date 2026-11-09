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
 * Placed top left on every tile (RefImage) and 3D preview (Model3DViewer);
 * the top right belongs to their actions and view controls.
 */
import type { CSSProperties } from 'react'
import { useI18n } from '../../i18n/I18nProvider'

export interface Freshness {
  state: 'current' | 'stale' | 'missing'
  reason?: string
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
  const reason = (freshness.reason || '').split(' · ').filter(Boolean).map((part) => t(part)).join(' · ')
  const text = freshness.state === 'current' ? t('current')
    : freshness.state === 'stale' ? (reason ? `${t('outdated')}: ${reason}` : t('outdated'))
    : t('no data')
  return (
    <span
      role="status"
      title={freshness.state === 'missing' && reason ? `${text} · ${reason}` : text}
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
