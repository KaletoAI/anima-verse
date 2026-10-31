import { useState } from 'react'
import { apiPost } from './api'
import { HoverHint } from './HoverHint'
import { useI18n } from './I18nProvider'
import { propActionReason } from './propActionReasons'
import { usePropActions } from './usePropActions'
import { cancelPropAction, notifyPropActionChanged, requestPropAction, respondPropAction,
  type PropActionExecution, type PropActionOffer } from './propActions'

interface OfferChoice { offer: PropActionOffer; partner?: string; enabled: boolean; reason: string }

const metres = (offer: PropActionOffer) => offer.distance_m == null ? '' : ` · ${offer.distance_m.toFixed(1)} m`

/** Shared presentation for canvas menus and panels; verdicts are Core's, not UI rules.
 *  One entry per action (and partner): an action several pieces offer becomes a
 *  dropdown of those pieces, nearest first, each with its distance to the avatar. */
export function PropActionOffers({ offers, partner, busy = false, nameProps = true, onPick }: {
  offers: PropActionOffer[]
  partner?: string
  busy?: boolean
  /** Off where the menu already belongs to one piece (the canvas place menu). */
  nameProps?: boolean
  onPick: (offer: PropActionOffer, partner?: string) => void
}) {
  const { t } = useI18n()
  const groups = new Map<string, OfferChoice[]>()
  for (const offer of offers) {
    if (partner && !offer.required_partner) continue
    const choices = !offer.required_partner ? [{ enabled: offer.enabled, reason: offer.reason, partner: undefined }]
      : offer.available_targets.length ? offer.available_targets.filter(choice => !partner || choice.partner === partner)
        : partner ? [] : [{ enabled: false, reason: offer.reason, partner: undefined }]
    for (const choice of choices) {
      const key = JSON.stringify([offer.label, choice.partner ?? ''])
      groups.set(key, [...groups.get(key) ?? [], { offer, partner: choice.partner, enabled: choice.enabled, reason: choice.reason }])
    }
  }
  return <div className="player-prop-offers" style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
    {[...groups].map(([key, entries]) => {
      // Usable pieces first, then by distance (unknown distance last).
      entries.sort((a, b) => Number(b.enabled) - Number(a.enabled)
        || (a.offer.distance_m ?? Infinity) - (b.offer.distance_m ?? Infinity))
      const first = entries[0]
      const usable = entries.some(entry => entry.enabled)
      const disabled = busy || !usable
      const title = `${first.offer.label}${first.partner ? ` · ${first.partner}` : ''}`
      // A blocked choice says why on mouse-over (HoverHint: drawn by the page, so
      // the native client shows it too).
      const hint = !usable ? propActionReason(first.reason, t) : undefined
      const style = { opacity: disabled ? 0.5 : undefined, pointerEvents: !usable ? 'none' as const : undefined }
      if (entries.length === 1) return <HoverHint key={key} text={hint}>
        <button type="button" className="player-chip" disabled={disabled}
          aria-disabled={disabled ? true : undefined} style={style}
          onClick={() => onPick(first.offer, first.partner)}>
          {title}{nameProps ? <span style={{ opacity: 0.7 }}> · {first.offer.prop_label}{metres(first.offer)}</span> : null}
        </button>
      </HoverHint>
      return <HoverHint key={key} text={hint}>
        <select className="player-chip" value="" disabled={disabled} aria-label={title}
          aria-disabled={disabled ? true : undefined} style={style}
          onChange={event => {
            const entry = entries[Number(event.target.value)]
            if (entry?.enabled) onPick(entry.offer, entry.partner)
          }}>
          <option value="" disabled hidden>{title} ▾</option>
          {entries.map((entry, i) => <option key={JSON.stringify([entry.offer.target, entry.offer.action_id])}
            value={i} disabled={!entry.enabled}>
            {entry.offer.prop_label}{metres(entry.offer)}{entry.enabled ? '' : ` — ${propActionReason(entry.reason, t)}`}
          </option>)}
        </select>
      </HoverHint>
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
