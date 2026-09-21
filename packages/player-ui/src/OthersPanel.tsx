/**
 * OthersPanel — state of the other characters present (read-only), the
 * counterpart to Self. The cards flow responsively side by side or stacked
 * (flex-wrap, depending on the window width). Source: GET /play/others.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from './I18nProvider'
import { ApiError, apiGet, apiPost } from './api'
import { usePoll } from './usePolling'
import { EmptyState } from './EmptyState'
import { useEnlarge } from './ZoomButton'
import { thumbUrl, thumbWidth } from './thumbs'

interface BarMeta { color?: string; label?: string; name?: string; name_de?: string }
/** The avatar's relationship TO this character, as `/play/others` sends it.
 *  Absent/null when there is no relationship at all. */
interface Relation { type: string; strength: number; sentiment: number }
interface CharState {
  name: string
  mood: string
  activity: string
  status_effects: Record<string, number>
  bar_meta: Record<string, BarMeta>
  conditions: Array<{ name?: string; label?: string; icon?: string }>
  profile_image: string
  /** The place held (plan-posen-plaetze.md § 7) as a finished phrase —
   *  "on the sofa". The SERVER composes it (`places.place_phrase`), because
   *  the preposition belongs to the place type and that table may only exist
   *  once; "" when nothing (or a place that is never named, such as a
   *  standing spot) is held. */
  place_phrase?: string
  in_party?: boolean
  relation?: Relation | null
  /** The running pair interaction, or null — a two-person pose says nothing
   *  without the partner it is shared with. */
  interaction?: { partner: string; pose_key: string } | null
}
interface Others { avatar: string; characters: CharState[] }
interface PairPose { key: string; kind: string }

/** "reading, on the armchair" — activity and place, either alone when the
 *  other is missing, "" when both are. A running pair replaces the activity:
 *  "dancing together" on its own reads as a solo pose next to someone.
 *
 *  The place is whatever `place_phrase` says and nothing else: no
 *  preposition table here, because the same one lives in the server
 *  (`places._PREPOSITION`) and two copies drift apart — that is what this
 *  field was added for. An empty or absent phrase prints no place. */
function whereabouts(c: CharState, t: (s: string) => string): string {
  const place = (c.place_phrase || '').trim().toLowerCase()
  const doing = c.interaction
    ? t('{pose} with {name}').replace('{pose}', c.interaction.pose_key)
      .replace('{name}', c.interaction.partner)
    : c.activity
  return [doing, place].filter(Boolean).join(', ')
}

/** Roster portrait: 44 CSS px. The magnifier opens the ORIGINAL. */
const AVATAR_W = thumbWidth(44)

function portraitUrl(c: CharState): string {
  return c.profile_image
    ? `/characters/${encodeURIComponent(c.name)}/images/${encodeURIComponent(c.profile_image)}`
    : `/characters/${encodeURIComponent(c.name)}/outfit-expression?fallback=default`
}

/** One line "type · strength". The sentiment is NOT printed — only its sign
 *  colours the line (positive/negative/neutral), and the exact value stays in
 *  the tooltip. The strength shows as the server sends it; no bucketing. */
function RelationLine({ c, t }: { c: CharState; t: (s: string) => string }) {
  const rel = c.relation
  if (!rel) return null
  const sign = rel.sentiment > 0 ? 'positive' : rel.sentiment < 0 ? 'negative' : 'neutral'
  return (
    <div className={`player-relation player-relation-${sign}`}
      title={`${t('Relationship')}: ${rel.type} · ${rel.strength} · ${rel.sentiment}`}>
      {rel.type} · {rel.strength}
    </div>
  )
}

function StatBars({ c }: { c: CharState }) {
  const bars = Object.entries(c.status_effects || {})
  // On a narrow card hide label and number, leaving the bar (with a clear end).
  const ref = useRef<HTMLDivElement | null>(null)
  const [compact, setCompact] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width || 0
      setCompact(w > 0 && w < 150)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  if (!bars.length) return null
  return (
    <div ref={ref} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2px 8px', marginTop: 4 }}>
      {bars.map(([key, val]) => {
        const m = c.bar_meta?.[key] || {}
        const pct = Math.max(0, Math.min(100, Number(val) || 0))
        return (
          <div key={key} title={`${m.name_de || m.name || key}: ${pct}/100`}
            style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
            {!compact && (
              <span style={{ width: 24, opacity: 0.7, fontSize: '0.58em', textTransform: 'uppercase' }}>{m.label || key.slice(0, 3)}</span>
            )}
            <div style={{
              flex: 1, height: compact ? 6 : 4, borderRadius: 3,
              background: 'rgba(255,255,255,0.16)',
              border: '1px solid rgba(255,255,255,0.45)',
              overflow: 'hidden', boxSizing: 'border-box',
            }}>
              <div style={{ width: `${pct}%`, height: '100%', background: m.color || 'var(--accent,#6aa9ff)' }} />
            </div>
            {!compact && (
              <span style={{ width: 14, textAlign: 'right', fontVariantNumeric: 'tabular-nums', fontSize: '0.58em', opacity: 0.65 }}>{pct}</span>
            )}
          </div>
        )
      })}
    </div>
  )
}

/** The "do something together" popover of ONE card.
 *
 *  Rendered into document.body: the panel lives in the /play react-grid
 *  layout, where an absolutely positioned child is clipped away by the grid
 *  item. Anchored to the button that opened it.
 */
function PairMenu({ anchorEl, poses, onPick, onClose, t }: {
  anchorEl: HTMLElement
  poses: PairPose[]
  onPick: (key: string) => void
  onClose: () => void
  t: (s: string) => string
}) {
  const box = useRef<HTMLDivElement | null>(null)
  // Follows the button rather than freezing where it was opened: the panel
  // is inside a resizable grid item, and a menu pinned to a stale rectangle
  // drifts away from the card it belongs to.
  const [rect, setRect] = useState<DOMRect>(() => anchorEl.getBoundingClientRect())
  useEffect(() => {
    const reposition = () => setRect(anchorEl.getBoundingClientRect())
    const away = (e: Event) => {
      // A scroll INSIDE the menu is not a scroll away from it — the list
      // has its own overflow, and closing on it would make it unscrollable.
      if (box.current && e.target instanceof Node && box.current.contains(e.target)) {
        return
      }
      onClose()
    }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('mousedown', onClose)
    window.addEventListener('scroll', away, true)
    window.addEventListener('resize', reposition)
    window.addEventListener('keydown', onKey)
    box.current?.querySelector('button')?.focus()
    return () => {
      window.removeEventListener('mousedown', onClose)
      window.removeEventListener('scroll', away, true)
      window.removeEventListener('resize', reposition)
      window.removeEventListener('keydown', onKey)
    }
  }, [anchorEl, onClose])
  return createPortal(
    <div ref={box} role="menu" onMouseDown={(e) => e.stopPropagation()} style={{
      position: 'fixed', zIndex: 4000,
      top: Math.min(rect.bottom + 4, window.innerHeight - 180),
      left: Math.min(rect.left, window.innerWidth - 200),
      minWidth: 160, maxHeight: 220, overflowY: 'auto', padding: 4,
      borderRadius: 8, background: 'var(--panel, #161b22)',
      border: '1px solid var(--border, #30363d)',
      boxShadow: '0 6px 20px rgba(0,0,0,0.45)',
    }}>
      {poses.length === 0 && (
        <div style={{ padding: '6px 8px', opacity: 0.6, fontSize: '0.78em' }}>
          {t('No two-person actions available.')}
        </div>
      )}
      {poses.map((p) => (
        <button key={p.key} role="menuitem" onClick={() => onPick(p.key)} style={{
          display: 'block', width: '100%', textAlign: 'left', padding: '5px 8px',
          background: 'none', border: 'none', color: 'inherit', cursor: 'pointer',
          borderRadius: 5, fontSize: '0.82em',
        }}
          onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(255,255,255,0.08)' }}
          onMouseLeave={(e) => { e.currentTarget.style.background = 'none' }}>
          {p.key}
        </button>
      ))}
    </div>,
    document.body)
}

export function OthersPanel() {
  const { t } = useI18n()
  const enlarge = useEnlarge()
  const { data, refresh } = usePoll<Others>(
    'play-others', () => apiGet<Others>('/play/others'), { intervalMs: 5000 })
  // The world's two-person actions — fetched once; the clip library does not
  // change while a scene is being played.
  const [pairPoses, setPairPoses] = useState<PairPose[] | null>(null)
  const [menu, setMenu] = useState<{ name: string; el: HTMLElement } | null>(null)
  const [note, setNote] = useState('')

  const openMenu = useCallback((name: string, el: HTMLElement) => {
    setNote('')
    setMenu({ name, el })
    if (pairPoses === null) {
      apiGet<{ poses: PairPose[] }>('/play/interact/options')
        .then((d) => setPairPoses(d.poses || []))
        .catch(() => setPairPoses([]))
    }
  }, [pairPoses])

  // Stable identity: PairMenu keys its window listeners on this, and a new
  // function each render would re-register them on every 5 s poll.
  const closeMenu = useCallback(() => setMenu(null), [])

  const propose = useCallback(async (name: string, pose: string) => {
    setMenu(null)
    try { await apiPost('/play/interact', { partner: name, pose }) }
    catch (e) {
      // 409 carries the engine's own reason ("Kira is in another room") —
      // that sentence is the whole point, so it is shown, not swallowed.
      setNote(e instanceof ApiError ? String(e.detail || '') : String(e))
    }
    refresh()
  }, [refresh])

  const stop = useCallback(async () => {
    try { await apiPost('/play/interact/end', {}) } catch { /* ignore */ }
    refresh()
  }, [refresh])

  if (!data) return <EmptyState small title={t('Loading…')} />
  if (!data.characters.length) {
    return <EmptyState icon="others" title={t('Nobody else is here.')} />
  }

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignContent: 'flex-start', height: '100%', minHeight: 0, overflow: 'auto', fontSize: '0.9em' }}>
      {data.characters.map((c) => (
        <div key={c.name} style={{
          flex: '1 1 190px', minWidth: 160, maxWidth: '100%', alignSelf: 'flex-start',
          display: 'flex', flexDirection: 'column', gap: 4, padding: 8, borderRadius: 8,
          // Party members get a card colour of their own (blue).
          background: c.in_party ? 'rgba(120,170,255,0.16)' : 'rgba(255,255,255,0.05)',
          border: c.in_party ? '1px solid rgba(120,170,255,0.55)' : '1px solid rgba(255,255,255,0.08)',
        }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <img src={thumbUrl(portraitUrl(c), AVATAR_W)} alt={c.name} loading="lazy" decoding="async"
              onError={(e) => { (e.target as HTMLImageElement).style.visibility = 'hidden' }}
              {...enlarge({ src: portraitUrl(c), alt: c.name },
                { width: 44, height: 44, borderRadius: 6, objectFit: 'cover', flex: '0 0 auto', background: 'rgba(255,255,255,0.08)' })} />
            <div style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {c.name}{c.in_party ? <span title={t('In your party')} style={{ marginLeft: 4 }}>👥</span> : null}
              </div>
              {c.mood && <div style={{ opacity: 0.6, fontSize: '0.78em', fontStyle: 'italic', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.mood}</div>}
              {whereabouts(c, t) && <div title={whereabouts(c, t)} style={{ opacity: 0.55, fontSize: '0.74em', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{whereabouts(c, t)}</div>}
              <RelationLine c={c} t={t} />
            </div>
          </div>
          {c.conditions.length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3 }}>
              {c.conditions.map((cd, i) => (
                <span key={i} style={{ padding: '0 6px', borderRadius: 9, fontSize: '0.7em',
                  background: 'rgba(255,170,90,0.2)', border: '1px solid rgba(255,170,90,0.4)' }}>
                  {cd.icon ? `${cd.icon} ` : ''}{cd.label || cd.name}
                </span>
              ))}
            </div>
          )}
          <StatBars c={c} />
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            {c.interaction?.partner === data.avatar ? (
              <button onClick={stop} className="player-chip">{t('Stop')}</button>
            ) : (
              <button className="player-chip"
                disabled={!!c.interaction}
                title={c.interaction ? t('Busy with someone else') : t('Ask to do something together')}
                onClick={(e) => openMenu(c.name, e.currentTarget)}>
                {t('Together…')}
              </button>
            )}
          </div>
        </div>
      ))}
      {note && (
        <div style={{ flex: '1 1 100%', fontSize: '0.76em', color: '#ff9b9b' }}>{note}</div>
      )}
      {menu && (
        <PairMenu anchorEl={menu.el} poses={pairPoses || []} t={t}
          onClose={closeMenu}
          onPick={(key) => propose(menu.name, key)} />
      )}
    </div>
  )
}
