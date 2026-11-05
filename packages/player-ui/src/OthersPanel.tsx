/**
 * OthersPanel — state of the other characters present (read-only), the
 * counterpart to Self. The cards flow responsively side by side or stacked
 * (flex-wrap, depending on the window width). Source: GET /play/others.
 */
import { isMember, othersIn, type InteractionMembers } from './interactionMembers'
import { invitePair } from './pairInteractions'
import { StatFill } from './StatBoost'
import { statTitle, conditionTitle, type StatBoost, type BoostCondition } from './statBoosts'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useI18n } from './I18nProvider'
import { ApiError, apiGet, apiPost } from './api'
import { usePoll } from './usePolling'
import { SYNC_ENDPOINTS } from './syncEndpoints'
import { EmptyState } from './EmptyState'
import { HoverHint } from './HoverHint'
import { useEnlarge } from './ZoomButton'
import { thumbUrl, thumbWidth, transparentPortraitUrl } from './thumbs'
import { shownName } from './displayNames'
import { PropActionsPanel } from './PropActionsPanel'
import { onPropActionChanged } from './propActions'

interface BarMeta { color?: string; label?: string; name?: string; name_de?: string }
/** The avatar's relationship TO this character, as `/play/others` sends it.
 *  Absent/null when there is no relationship at all. */
interface Relation { type: string; strength: number; sentiment: number }
interface CharState {
  /** The REAL name — the key every action posts. */
  name: string
  /** What the card prints: the avatar's view of a disguised person. */
  display_name?: string
  /** Present only for a disguise the avatar is not in on: the persona
   *  portrait in place of the real one, `''` = the no-portrait placeholder. */
  portrait_url?: string
  mood: string
  activity: string
  status_effects: Record<string, number>
  stat_boosts?: Record<string, StatBoost>
  bar_meta: Record<string, BarMeta>
  conditions: BoostCondition[]
  profile_image: string
  expression_version?: string
  /** The place held (plan-posen-plaetze.md § 7) as a finished phrase —
   *  "on the sofa". The SERVER composes it (`places.place_phrase`), because
   *  the preposition belongs to the place type and that table may only exist
   *  once; "" when nothing (or a place that is never named, such as a
   *  standing spot) is held. */
  place_phrase?: string
  in_party?: boolean
  relation?: Relation | null
  /** The running interaction, or null — a two-person pose says nothing
   *  without the people it is shared with. `members` includes `name`. */
  interaction?: { members: InteractionMembers; pose_key: string; pose_label?: string } | null
}
interface Others {
  avatar: string
  characters: CharState[]
  /** Real name → shown name for every name a card prints (pair partners). */
  display_names?: Record<string, string>
}
interface PairPose { key: string; kind: string; label: string }

/** "reading, on the armchair" — activity and place, either alone when the
 *  other is missing, "" when both are. A running pair replaces the activity:
 *  "dancing together" on its own reads as a solo pose next to someone.
 *
 *  The place is whatever `place_phrase` says and nothing else: no
 *  preposition table here, because the same one lives in the server
 *  (`places._PREPOSITION`) and two copies drift apart — that is what this
 *  field was added for. An empty or absent phrase prints no place. */
function whereabouts(c: CharState, t: (s: string) => string,
  displayNames?: Record<string, string>): string {
  const place = (c.place_phrase || '').trim().toLowerCase()
  const doing = c.interaction
    ? t('{pose} with {name}').replace('{pose}', c.interaction.pose_label || c.interaction.pose_key)
      .replace('{name}', othersIn(c.interaction.members, c.name)
        .map((n) => shownName(displayNames, n)).join(', '))
    : c.activity
  return [doing, place].filter(Boolean).join(', ')
}

/** Roster portrait: 44 CSS px. The magnifier opens the full-size cutout. */
const AVATAR_W = thumbWidth(44)

/** The card's portrait; `''` = draw the placeholder. A persona portrait
 *  (`portrait_url`) wins over the real one whenever the field is present. */
function portraitUrl(c: CharState): string {
  if (c.portrait_url !== undefined) return c.portrait_url ? transparentPortraitUrl(c.portrait_url) : ''
  return c.profile_image
    ? transparentPortraitUrl(`/characters/${encodeURIComponent(c.name)}/images/${encodeURIComponent(c.profile_image)}`)
    : `/characters/${encodeURIComponent(c.name)}/outfit-expression?fallback=default&v=${encodeURIComponent(c.expression_version || '')}`
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
  const { t, lang } = useI18n()
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
        const boost = c.stat_boosts?.[key]
        const value = boost?.value ?? Number(val)
        const pct = Math.max(0, Math.min(100, Number(val) || 0))
        return (
          <div key={key} title={statTitle(t, (lang === 'de' ? m.name_de || m.name : m.name) || key, pct, boost)}
            style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
            {!compact && (
              <span style={{ width: 24, opacity: 0.7, fontSize: '0.58em', textTransform: 'uppercase' }}>{m.label || key.slice(0, 3)}</span>
            )}
            <div style={{
              position: 'relative', flex: 1, height: compact ? 6 : 4, borderRadius: 3,
              background: 'rgba(255,255,255,0.16)',
              border: '1px solid rgba(255,255,255,0.45)',
              overflow: 'hidden', boxSizing: 'border-box',
            }}>
              <StatFill base={pct} boost={boost} color={m.color || 'var(--accent,#6aa9ff)'} />
            </div>
            {!compact && (
              <span style={{ minWidth: 20, textAlign: 'right', fontVariantNumeric: 'tabular-nums', fontSize: '0.58em', opacity: 0.65 }}>{value}</span>
            )}
          </div>
        )
      })}
    </div>
  )
}

export function OthersPanel() {
  const { t } = useI18n()
  const enlarge = useEnlarge()
  const { data, refresh } = usePoll<Others>(
    'play-others', () => apiGet<Others>('/play/others'), SYNC_ENDPOINTS.others)
  useEffect(() => onPropActionChanged(() => { void refresh() }), [refresh])
  // The world's two-person actions — fetched once; the clip library does not
  // change while a scene is being played.
  const [pairPoses, setPairPoses] = useState<PairPose[]>([])
  // Why the avatar may not propose any of them (a block rule or a cost on
  // the pair verb) — fetched with the list, "" = free to ask.
  const [pairBlocked, setPairBlocked] = useState('')
  const [note, setNote] = useState('')
  useEffect(() => {
    let cancelled = false
    apiGet<{ poses: PairPose[]; blocked?: string }>('/play/interact/options')
      .then((d) => { if (!cancelled) { setPairPoses(d.poses || []); setPairBlocked(d.blocked || '') } })
      .catch(() => { if (!cancelled) setPairPoses([]) })
    return () => { cancelled = true }
  }, [])

  const propose = useCallback(async (name: string, pose: string) => {
    setNote('')
    try { await invitePair(name, pose) }
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
      {data.characters.map((c) => {
        const label = c.display_name || c.name
        const portrait = portraitUrl(c)
        const where = whereabouts(c, t, data.display_names)
        return (
        <div key={c.name} style={{
          flex: '1 1 190px', minWidth: 160, maxWidth: '100%', alignSelf: 'flex-start',
          display: 'flex', flexDirection: 'column', gap: 4, padding: 8, borderRadius: 8,
          // Party members get a card colour of their own (blue).
          background: c.in_party ? 'rgba(120,170,255,0.16)' : 'rgba(255,255,255,0.05)',
          border: c.in_party ? '1px solid rgba(120,170,255,0.55)' : '1px solid rgba(255,255,255,0.08)',
        }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {portrait
              ? <img src={thumbUrl(portrait, AVATAR_W)} alt={label} loading="lazy" decoding="async"
                  onError={(e) => { (e.target as HTMLImageElement).style.visibility = 'hidden' }}
                  {...enlarge({ src: portrait, alt: label },
                    { width: 44, height: 44, objectFit: 'contain', flex: '0 0 auto' })} />
              // No portrait to show: an empty box of the same size — what a
              // portrait that fails to load leaves behind, too.
              : <span aria-hidden="true" style={{ width: 44, height: 44, flex: '0 0 auto' }} />}
            <div style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {label}{c.in_party ? <span title={t('In your party')} style={{ marginLeft: 4 }}>👥</span> : null}
              </div>
              {c.mood && <div style={{ opacity: 0.6, fontSize: '0.78em', fontStyle: 'italic', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.mood}</div>}
              {where && <div title={where} style={{ opacity: 0.55, fontSize: '0.74em', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{where}</div>}
              <RelationLine c={c} t={t} />
            </div>
          </div>
          {c.conditions.length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3 }}>
              {c.conditions.map((cd, i) => (
                <span key={i} title={conditionTitle(t, cd)} style={{ padding: '0 6px', borderRadius: 9, fontSize: '0.7em',
                  background: 'rgba(255,170,90,0.2)', border: '1px solid rgba(255,170,90,0.4)' }}>
                  {cd.icon ? `${cd.icon} ` : ''}{cd.label || cd.name}
                </span>
              ))}
            </div>
          )}
          <StatBars c={c} />
          <PropActionsPanel partner={c.name} leading={isMember(c.interaction?.members, data.avatar) || pairPoses.length > 0 ? <>
            {isMember(c.interaction?.members, data.avatar) && (
              <button type="button" onClick={stop} className="player-chip">{t('Stop')}</button>
            )}
            {pairPoses.map((pose) => {
              const busy = !!c.interaction && !isMember(c.interaction.members, data.avatar)
              const off = busy || !!pairBlocked
              return <HoverHint key={pose.key} text={busy ? t('Busy with someone else') : (pairBlocked || undefined)}>
                <button type="button" className="player-chip" disabled={off}
                  aria-disabled={off ? true : undefined}
                  style={{ pointerEvents: off ? 'none' : undefined }}
                  onClick={() => propose(c.name, pose.key)}>
                  {pose.label || pose.key}
                </button>
              </HoverHint>
            })}
          </> : undefined} />
        </div>
        )
      })}
      {note && (
        <div style={{ flex: '1 1 100%', fontSize: '0.76em', color: '#ff9b9b' }}>{note}</div>
      )}
    </div>
  )
}
