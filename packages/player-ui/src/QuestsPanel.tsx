/**
 * QuestsPanel — the avatar's quest book (stage 6, "Spielsysteme-UI Rest").
 *
 * Source: GET /play/story-arcs. That endpoint is spoiler-free by construction
 * (whitelist, never GM fields), so this panel simply shows what it gets:
 * running arcs first as expandable cards, then the last finished ones as a
 * short chronicle under a divider.
 *
 * A card collapsed says what the arc is about (title + how tense it is + the
 * current state). Expanded it adds who is in it and the beats so far, oldest
 * first — the order the server appends them in, so the list reads like a
 * story and not like a changelog.
 */
import { useCallback, useState } from 'react'
import { useI18n } from './I18nProvider'
import { apiGet } from './api'
import { usePoll } from './usePolling'
import { EmptyState } from './EmptyState'

interface ArcBeat {
  beat: string
  timestamp: string
  summary: string
}

interface StoryArc {
  id: string
  title: string
  status: string
  current_state: string
  tension: number
  beats: ArcBeat[]
  participants: string[]
  updated_at: string
  resolution?: string
}

interface StoryArcsResp {
  arcs: StoryArc[]
}

/** How tense an arc can get — the server's scale, mirrored as bar segments. */
const TENSION_MAX = 5

/** Same compact stamp the phone and the scene recap use: day/month + clock. */
function fmtTime(ts: string): string {
  if (!ts) return ''
  const d = new Date(ts)
  if (isNaN(d.getTime())) return ''
  return d.toLocaleString([], { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' })
}

function TensionBar({ value, label }: { value: number; label: string }) {
  const filled = Math.max(0, Math.min(TENSION_MAX, Math.round(value || 0)))
  return (
    <span className="player-quest-tension" title={label} aria-label={label}>
      {Array.from({ length: TENSION_MAX }, (_, i) => (
        <i key={i} className={i < filled ? 'on' : ''} />
      ))}
    </span>
  )
}

export function QuestsPanel({ pollIntervalMs = 15000 }: { pollIntervalMs?: number } = {}) {
  const { t } = useI18n()
  const { data } = usePoll<StoryArcsResp>(
    'play-story-arcs', () => apiGet<StoryArcsResp>('/play/story-arcs'),
    { intervalMs: pollIntervalMs })
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

  const toggle = useCallback((id: string) => {
    setExpanded((prev) => ({ ...prev, [id]: !prev[id] }))
  }, [])

  const arcs = data?.arcs || []
  if (arcs.length === 0) {
    return (
      <EmptyState icon="scroll" title={t('No quests yet')}
        hint={t('Stories you take part in show up here.')} />
    )
  }

  const active = arcs.filter((a) => a.status === 'active')
  const resolved = arcs.filter((a) => a.status !== 'active')

  const card = (arc: StoryArc) => {
    const open = !!expanded[arc.id]
    const done = arc.status !== 'active'
    return (
      <div key={arc.id} className={`player-quest${done ? ' player-quest-done' : ''}`}>
        <button type="button" className="player-quest-head"
          onClick={() => toggle(arc.id)} aria-expanded={open}>
          <span className="player-quest-caret">{open ? '▾' : '▸'}</span>
          <span className="player-quest-title">{arc.title || arc.id}</span>
          {!done && (
            <TensionBar value={arc.tension}
              label={`${t('Tension')}: ${arc.tension}/${TENSION_MAX}`} />
          )}
        </button>
        {!done && arc.current_state ? (
          <div className="player-quest-state">{arc.current_state}</div>
        ) : null}
        {open && (
          <div className="player-quest-body">
            {arc.participants.length > 0 ? (
              <div className="player-quest-people">{arc.participants.join(', ')}</div>
            ) : null}
            {done && arc.resolution ? (
              <div className="player-quest-resolution">{arc.resolution}</div>
            ) : null}
            {!done && arc.beats.length === 0 ? (
              <div className="player-quest-people">{t('Nothing has happened yet.')}</div>
            ) : null}
            {!done && arc.beats.map((b, i) => (
              <div key={`${arc.id}-${i}`} className="player-quest-beat">
                <div className="player-quest-beat-time">{fmtTime(b.timestamp)}</div>
                <div className="player-quest-beat-text">{b.summary || b.beat}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="player-quests">
      {active.map(card)}
      {resolved.length > 0 ? (
        <div className="player-quest-divider">{t('Completed')}</div>
      ) : null}
      {resolved.map(card)}
    </div>
  )
}
