/**
 * QuestsPanel — the avatar's quest book (quest system stage 1).
 *
 * Source: GET /play/quests (app/core/quest_book.py). That payload is spoiler-free
 * by construction (built up from a whitelist: no GM notes, no hints, no
 * conditions, no step after the current one), and every *_label is a finished
 * server string in the player's language — this panel only lays it out.
 *
 * Open quests come first, then the last ended ones under a "Completed" divider
 * (the server's order). A card shows title, summary, the done steps (who
 * fulfilled each and when) and the current one, the time left, and — when the
 * avatar does not meet the quest's requirements — a lock with the author's reason.
 *
 * `QuestBook` is the pure rendering (tests render it with fixtures);
 * `QuestsPanel` polls the endpoint. The quest engine pushes `notices` to the
 * bound avatars when a step is done or a run opens/ends, so the poll listens there.
 */
import { useI18n } from './I18nProvider'
import { apiGet } from './api'
import { usePoll } from './usePolling'
import { EmptyState } from './EmptyState'
import { Icon } from './icons'
import { SYNC_ENDPOINTS } from './syncEndpoints'

export interface QuestBookStep {
  text: string
  state: 'done' | 'current'
  /** Present on a done step: the avatar that fulfilled it. */
  done_by?: string
  /** Present on a done step: when, as a finished game-time label. */
  done_label?: string
}

export interface QuestBookEntry {
  id: string
  title: string
  summary: string
  state: 'open' | 'done' | 'failed' | 'cancelled' | 'broken'
  steps: QuestBookStep[]
  /** Open quest with a time limit: the remaining time, a finished label. */
  time_left_label?: string
  /** Present only when the avatar is locked out: the reason text to show. */
  locked?: string
  /** Ended quest: when it ended, a finished game-time label. */
  ended_label?: string
}

export interface QuestBookResp {
  avatar: string
  quests: QuestBookEntry[]
}

/** The word for an ended quest's state (the t() literals stay visible to the i18n guard). */
function endedStateLabel(state: QuestBookEntry['state'], t: (s: string) => string): string {
  switch (state) {
    case 'done': return t('Done')
    case 'failed': return t('Failed')
    case 'cancelled': return t('Cancelled')
    case 'broken': return t('Broken')
    default: return state
  }
}

function QuestCard({ quest }: { quest: QuestBookEntry }) {
  const { t } = useI18n()
  const ended = quest.state !== 'open'
  const endedLine = ended
    ? [endedStateLabel(quest.state, t), quest.ended_label].filter(Boolean).join(' · ')
    : ''
  return (
    <div className={`player-quest${ended ? ' player-quest-done' : ''}`}>
      <div className="player-quest-head">
        <span className="player-quest-title">{quest.title || quest.id}</span>
      </div>
      {quest.summary ? <div className="player-quest-summary">{quest.summary}</div> : null}
      {quest.locked ? (
        <div className="player-quest-locked">
          <Icon name="lock" size={12} />
          <span>{quest.locked}</span>
        </div>
      ) : null}
      {quest.steps.length > 0 ? (
        <ol className="player-quest-steps">
          {quest.steps.map((step, i) => {
            const done = step.state === 'done'
            const by = done ? [step.done_by, step.done_label].filter(Boolean).join(' · ') : ''
            return (
              <li key={`${quest.id}-${i}`}
                className={`player-quest-step ${done ? 'is-done' : 'is-current'}`}>
                <span className="player-quest-step-mark" aria-hidden="true">{done ? '✓' : '▸'}</span>
                <span className="player-quest-step-text">
                  {step.text}
                  {by ? <small>{by}</small> : null}
                </span>
              </li>
            )
          })}
        </ol>
      ) : null}
      {!ended && quest.time_left_label ? (
        <div className="player-quest-time">{`${t('Time left')}: ${quest.time_left_label}`}</div>
      ) : null}
      {endedLine ? <div className="player-quest-time">{endedLine}</div> : null}
    </div>
  )
}

/** The quest book itself, pure: what the server sent, laid out. */
export function QuestBook({ data }: { data: QuestBookResp }) {
  const { t } = useI18n()
  const quests = data.quests || []
  if (quests.length === 0) {
    return (
      <EmptyState icon="scroll" title={t('No quests yet')}
        hint={t('Quests open in the world show up here.')} />
    )
  }
  const open = quests.filter((q) => q.state === 'open')
  const ended = quests.filter((q) => q.state !== 'open')
  return (
    <div className="player-quests">
      {open.map((q) => <QuestCard key={q.id} quest={q} />)}
      {ended.length > 0 ? (
        <div className="player-quest-divider">{t('Completed')}</div>
      ) : null}
      {ended.map((q) => <QuestCard key={q.id} quest={q} />)}
    </div>
  )
}

export function QuestsPanel({ pollIntervalMs = SYNC_ENDPOINTS.quests.intervalMs }: { pollIntervalMs?: number } = {}) {
  const { t } = useI18n()
  const { data } = usePoll<QuestBookResp>(
    'play-quests', () => apiGet<QuestBookResp>('/play/quests'),
    { ...SYNC_ENDPOINTS.quests, intervalMs: pollIntervalMs })
  // No answer yet (first open, or the poll is backing off after failures) is
  // NOT "no quests" — a player with open quests would be told the opposite of
  // the truth. Same distinction the Others panel makes.
  if (!data) return <EmptyState small title={t('Loading…')} />
  return <QuestBook data={data} />
}
