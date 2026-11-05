/**
 * PartyStrip — who the avatar is travelling with, as one compact line.
 *
 * Purely presentational: the host passes the `party` block out of its own
 * `/play/scene` poll and owns the Leave action, so nothing here fetches and
 * the only state is the inline Leave confirmation (no `window.confirm`).
 *
 * Invitations are deliberately NOT shown here. ScenePanel already carries the
 * invite banner, and a second place to answer the same invite would let one
 * invitation be answered twice from two surfaces.
 *
 * The HUD's one party surface; NoticeBanner deliberately shows no party line.
 */
import { useState } from 'react'
import { useI18n } from './I18nProvider'
import type { SceneData } from './ScenePanel'
import { shownName } from './displayNames'

export interface PartyStripProps {
  /** The party block of `/play/scene`; the host renders nothing when it is null. */
  party: NonNullable<SceneData['party']>
  /** `display_names` of the same payload: the leader and members are real
   *  keys, this says what to print for them. Left out = the keys. */
  displayNames?: Record<string, string>
  /** Leave the party. The host posts and refreshes — no optimistic UI here. */
  onLeave: () => void
}

export function PartyStrip({ party, displayNames, onLeave }: PartyStripProps) {
  const { t } = useI18n()
  const [confirming, setConfirming] = useState(false)
  // `members` are the FOLLOWERS (the leader is not among them), so the avatar
  // itself is in the list exactly when it follows.
  const followers = party.members || []

  return (
    <div className="player-party">
      <span aria-hidden="true">👥</span>
      <span className="player-party-leader" title={t('Party leader')}>
        ⭐ {shownName(displayNames, party.leader)}
      </span>
      {followers.length > 0 && (
        <span className="player-party-members">{followers.map((n) => shownName(displayNames, n)).join(', ')}</span>
      )}
      <span className="player-party-role">
        {party.role === 'leader' ? t('You lead') : t('You follow')}
      </span>
      {confirming ? (
        <>
          <span className="player-party-ask">{t('Leave the party?')}</span>
          <button className="player-party-btn" onClick={() => { setConfirming(false); onLeave() }}>
            {t('Yes')}
          </button>
          <button className="player-party-btn" onClick={() => setConfirming(false)}>
            {t('Cancel')}
          </button>
        </>
      ) : (
        <button className="player-party-btn" onClick={() => setConfirming(true)}>
          {t('Leave party')}
        </button>
      )}
    </div>
  )
}
