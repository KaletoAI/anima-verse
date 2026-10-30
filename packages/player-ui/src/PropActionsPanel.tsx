import { useState } from 'react'
import { apiPost } from './api'
import { useI18n } from './I18nProvider'
import { propActionReason } from './propActionReasons'
import { usePropActions } from './usePropActions'
import { cancelPropAction, notifyPropActionChanged, requestPropAction, respondPropAction,
  type PropActionExecution, type PropActionOffer } from './propActions'

/** Shared presentation for canvas menus and panels; verdicts are Core's, not UI rules. */
export function PropActionOffers({ offers, partner, busy = false, onPick }: {
  offers: PropActionOffer[]
  partner?: string
  busy?: boolean
  onPick: (offer: PropActionOffer, partner?: string) => void
}) {
  const { t } = useI18n()
  return <div className="player-prop-offers" style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
    {offers.flatMap(offer => {
      if (partner && !offer.required_partner) return []
      const choices = !offer.required_partner ? [{ enabled: offer.enabled, reason: offer.reason, partner: undefined }]
        : offer.available_targets.length ? offer.available_targets.filter(choice => !partner || choice.partner === partner)
          : partner ? [] : [{ enabled: false, reason: offer.reason, partner: undefined }]
      return choices.map(choice => <button key={JSON.stringify([offer.target, offer.action_id, choice.partner])}
        type="button" className="player-chip" disabled={busy || !choice.enabled} aria-disabled={busy || !choice.enabled ? true : undefined}
        style={{ opacity: busy || !choice.enabled ? 0.5 : undefined }}
        title={!choice.enabled ? propActionReason(choice.reason, t) : undefined}
        onClick={() => onPick(offer, choice.partner)}>
        {offer.label}{choice.partner ? ` · ${choice.partner}` : ''}
      </button>)
    })}
  </div>
}

export function PropActionExecutionRow({ run, kind, busy, perform }: {
  run: PropActionExecution
  kind: 'incoming' | 'outgoing' | 'current' | 'result'
  busy: boolean
  perform: (operation: () => Promise<unknown>) => void
}) {
  const { t } = useI18n()
  const state = run.phase === 'entry' && run.status === 'approaching' ? 'Entering'
    : ({ awaiting_consent: 'Awaiting consent', approaching: 'Approaching', active: 'Active', sleeping: 'Sleeping',
      completed: 'Completed', cancelled: 'Cancelled', failed: 'Failed' } as Record<string, string>)[run.status] || run.status
  return <div className="player-prop-execution" style={{ display: 'flex', flexWrap: 'wrap', gap: 5, alignItems: 'center', padding: '4px 0' }}>
    <span>{run.label} · {t(state)}</span>
    {kind === 'incoming' && run.can_respond && <>
      <button type="button" className="player-chip" disabled={busy}
        onClick={() => perform(() => respondPropAction(run.execution_id, true))}>{t('Accept')}</button>
      <button type="button" className="player-chip" disabled={busy}
        onClick={() => perform(() => respondPropAction(run.execution_id, false))}>{t('Decline')}</button>
    </>}
    {run.can_cancel && <button type="button" className="player-chip" disabled={busy}
      onClick={() => perform(() => cancelPropAction(run.execution_id))}>{t(kind === 'outgoing' ? 'Withdraw' : 'Stop')}</button>}
    {run.status === 'sleeping' && <button type="button" className="player-chip" disabled={busy}
      onClick={() => perform(async () => {
        // Existing player wake path; Core clears sleep and semantic bed ownership.
        await apiPost('/play/self/activity', { activity: '' })
        notifyPropActionChanged()
      })}>{t('Wake up')}</button>}
  </div>
}

/** Mounted unchanged in web frontend, browser HUD iframe and native HUD iframe. */
export function PropActionsPanel({ partner, showOffers = true, showState = true }: {
  partner?: string
  showOffers?: boolean
  showState?: boolean
}) {
  const { t } = useI18n()
  const { data, error, refresh } = usePropActions()
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const perform = async (operation: () => Promise<unknown>) => {
    if (busy) return
    setBusy(true)
    setNote('')
    try { await operation() }
    catch (e) { setNote(e instanceof Error ? e.message : String(e)) }
    finally { await refresh(); setBusy(false) }
  }
  const ownRuns = (runs: PropActionExecution[]) => partner
    ? runs.filter(run => run.actor === partner || run.partner === partner) : runs
  const hasOffers = data?.offers.some(offer => !partner || (offer.required_partner && offer.available_targets.some(choice => choice.partner === partner)))
  const groups = data && showState ? [
    ['incoming', ownRuns(data.state.incoming)], ['outgoing', ownRuns(data.state.outgoing)],
    ['current', ownRuns(data.state.current)],
  ] as const : []
  // Finished runs are not listed: the room's storyteller line already told the player.
  if (!note && !error && !hasOffers && !groups.some(([, runs]) => runs.length)) return null
  return <section aria-label={t('Furniture actions')} style={{ flex: '0 0 auto', maxHeight: 230, overflow: 'auto', padding: 6, fontSize: '0.85em', borderTop: '1px solid var(--border, #30363d)' }}>
    <strong>{t('Furniture actions')}</strong>
    {error != null && <div role="alert">{error instanceof Error ? error.message : String(error)}</div>}
    {note && <div role="alert">{note}</div>}
    {groups.map(([kind, runs]) => runs.map(run => <PropActionExecutionRow key={`${kind}:${run.execution_id}`}
      run={run} kind={kind} busy={busy} perform={operation => { void perform(operation) }} />))}
    {showOffers && data && <PropActionOffers offers={data.offers} partner={partner} busy={busy || error != null}
      onPick={(offer, selectedPartner) => { void perform(() => requestPropAction(offer.action_id, offer.target, offer.definition_revision, selectedPartner)) }} />}
  </section>
}
