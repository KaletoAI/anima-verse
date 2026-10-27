import { useState } from 'react'
import { apiPost } from './api'
import { useI18n } from './I18nProvider'
import { usePropActions } from './usePropActions'
import { cancelPropAction, notifyPropActionChanged, propActionChoices, requestPropAction, respondPropAction,
  type PropActionExecution, type PropActionOffer } from './propActions'

/** Shared presentation for canvas menus and panels; verdicts are Core's, not UI rules. */
export function PropActionOffers({ offers, partner, busy = false, onPick }: {
  offers: PropActionOffer[]
  partner?: string
  busy?: boolean
  onPick: (offer: PropActionOffer, partner?: string) => void
}) {
  const { t } = useI18n()
  return <div className="player-prop-offers" style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
    {offers.map(offer => {
      if (partner && !offer.required_partner) return null
      const choices = propActionChoices(offer).filter(choice => !partner || choice.partner === partner)
      if (!choices.length) return null
      return <div key={JSON.stringify([offer.target, offer.action_id])}>
        {offer.description && <div style={{ opacity: 0.7, fontSize: '0.8em' }}>{offer.description}</div>}
        {choices.map(choice => <div key={choice.partner || 'solo'} style={{ marginTop: 3 }}>
          <button type="button" className="player-chip" disabled={busy || !choice.enabled}
            title={choice.reason || offer.description}
            onClick={() => onPick(offer, choice.partner)}>
            {offer.label} · {t(offer.required_partner ? '2 people' : '1 person')}
            {choice.partner ? ` · ${choice.partner}` : ''}
          </button>
          {!choice.enabled && <div role="note" style={{ opacity: 0.75, fontSize: '0.8em' }}>
            {t('Unavailable')}: {choice.reason}
          </div>}
        </div>)}
        {offer.effects.length > 0 && <div style={{ opacity: 0.65, fontSize: '0.75em' }}>
          {offer.effects.map(effect => [effect.when, effect.target,
            effect.stat ? `${effect.stat} ${effect.amount ?? ''}` : effect.mood || effect.condition_id || effect.type].join(' · ')).join('; ')}
        </div>}
      </div>
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
    <span>{run.label} · {t(state)}{run.partner ? ` · ${run.actor} / ${run.partner}` : ''}
      {run.phase_label ? ` · ${run.phase_label}` : ''}{run.reason ? ` · ${run.reason}` : ''}</span>
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
    {kind === 'result' && run.effects && Object.keys(run.effects).length > 0 &&
      <span style={{ fontSize: '0.8em', opacity: 0.8 }}>{t('Results')}: {JSON.stringify(run.effects)}</span>}
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
    ['current', ownRuns(data.state.current)], ['result', ownRuns(data.state.recent_results)],
  ] as const : []
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
