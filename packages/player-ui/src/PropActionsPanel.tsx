import { useState, type ReactNode } from 'react'
import { apiPost } from './api'
import { HoverHint } from './HoverHint'
import { useI18n } from './I18nProvider'
import { propActionReason } from './propActionReasons'
import { usePropActions } from './usePropActions'
import { cancelPropAction, notifyPropActionChanged, requestPropAction, respondPropAction,
  type PropActionExecution, type PropActionOffer } from './propActions'

interface OfferChoice { offer: PropActionOffer; partner?: string; enabled: boolean; reason: string }
interface OfferGroup { key: string; label: string; partner?: string; entries: OfferChoice[]; usable: boolean }

const pieceText = (offer: PropActionOffer) =>
  `${offer.prop_label}${offer.distance_m == null ? '' : ` · ${offer.distance_m.toFixed(1)} m`}`

/** One group per action (and partner); its pieces usable first, then nearest first. */
function offerGroups(offers: PropActionOffer[], partner?: string): OfferGroup[] {
  const groups = new Map<string, OfferGroup>()
  for (const offer of offers) {
    if (partner && !offer.required_partner) continue
    const choices = !offer.required_partner ? [{ enabled: offer.enabled, reason: offer.reason, partner: undefined }]
      : offer.available_targets.length ? offer.available_targets.filter(choice => !partner || choice.partner === partner)
        : partner ? [] : [{ enabled: false, reason: offer.reason, partner: undefined }]
    for (const choice of choices) {
      const key = JSON.stringify([offer.label, choice.partner ?? ''])
      const group = groups.get(key) ?? { key, label: offer.label, partner: choice.partner, entries: [], usable: false }
      group.entries.push({ offer, partner: choice.partner, enabled: choice.enabled, reason: choice.reason })
      group.usable ||= choice.enabled
      groups.set(key, group)
    }
  }
  for (const group of groups.values()) group.entries.sort((a, b) => Number(b.enabled) - Number(a.enabled)
    || (a.offer.distance_m ?? Infinity) - (b.offer.distance_m ?? Infinity))
  return [...groups.values()]
}

/** Shared presentation for canvas menus and panels; verdicts are Core's, not UI rules.
 *  Compact: a chip per action carries only the action's name. An action one piece
 *  offers starts on click (the piece and its distance are the hover text); an action
 *  several pieces offer opens a row of those pieces, nearest first. Pair actions sit
 *  behind one "With <partner>" chip per partner, unless the menu already belongs to
 *  one partner. No native select: its width followed the longest option. */
export function PropActionOffers({ offers, partner, busy = false, nameProps = true, onPick }: {
  offers: PropActionOffer[]
  partner?: string
  busy?: boolean
  /** Off where the menu already belongs to one piece (the canvas place menu). */
  nameProps?: boolean
  onPick: (offer: PropActionOffer, partner?: string) => void
}) {
  const { t } = useI18n()
  const [openPartner, setOpenPartner] = useState('')
  const [openAction, setOpenAction] = useState('')
  const groups = offerGroups(offers, partner)
  // Grouped by partner only where the menu is not one partner's already.
  const solo = groups.filter(group => partner || !group.partner)
  const partners = new Map<string, OfferGroup[]>()
  if (!partner) for (const group of groups) if (group.partner) partners.set(group.partner, [...partners.get(group.partner) ?? [], group])
  const shownPartner = partners.has(openPartner) ? openPartner : ''
  const visible = [...solo, ...partners.get(shownPartner) ?? []]
  const action = visible.find(group => group.key === openAction && group.entries.length > 1)

  const chip = (group: OfferGroup) => {
    const first = group.entries[0]
    const several = group.entries.length > 1
    const disabled = busy || !group.usable
    // A blocked choice says why on mouse-over (HoverHint: drawn by the page, so
    // the native client shows it too); a single piece names itself there.
    const hint = !group.usable ? propActionReason(first.reason, t)
      : !several && nameProps ? pieceText(first.offer) : undefined
    return <HoverHint key={group.key} text={hint}>
      <button type="button" className={`player-chip${action === group ? ' on' : ''}`} disabled={disabled}
        aria-disabled={disabled ? true : undefined} aria-expanded={several ? action === group : undefined}
        style={{ pointerEvents: !group.usable ? 'none' : undefined }}
        onClick={() => several ? setOpenAction(action === group ? '' : group.key) : onPick(first.offer, first.partner)}>
        {group.label}{several ? ' ▸' : ''}
      </button>
    </HoverHint>
  }
  const row = (children: ReactNode, onClose: () => void) =>
    <div className="player-prop-offers-row" style={{ display: 'flex', flexWrap: 'wrap', gap: 5, alignItems: 'center' }}>
      {children}
      <button type="button" className="player-chip" aria-label={t('Close')} onClick={onClose}>✕</button>
    </div>

  return <div className="player-prop-offers" style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
      {solo.map(chip)}
      {[...partners].map(([name, pairs]) => {
        const usable = pairs.some(group => group.usable)
        const hint = usable ? undefined : propActionReason(pairs[0].entries[0].reason, t)
        return <HoverHint key={`partner:${name}`} text={hint}>
          <button type="button" className={`player-chip${shownPartner === name ? ' on' : ''}`}
            disabled={busy || !usable} aria-expanded={shownPartner === name}
            style={{ pointerEvents: !usable ? 'none' : undefined }}
            onClick={() => { setOpenPartner(shownPartner === name ? '' : name); setOpenAction('') }}>
            {t('With')} {name} ▸ {pairs.length}
          </button>
        </HoverHint>
      })}
    </div>
    {shownPartner && row(<>
      <span style={{ opacity: 0.7 }}>{t('With')} {shownPartner}:</span>
      {partners.get(shownPartner)!.map(chip)}
    </>, () => { setOpenPartner(''); setOpenAction('') })}
    {action && row(<>
      <span style={{ opacity: 0.7 }}>{action.label}{action.partner ? ` · ${action.partner}` : ''}:</span>
      {action.entries.map(entry => {
        const disabled = busy || !entry.enabled
        return <HoverHint key={JSON.stringify([entry.offer.target, entry.offer.action_id])}
          text={entry.enabled ? undefined : propActionReason(entry.reason, t)}>
          <button type="button" className="player-chip" disabled={disabled}
            aria-disabled={disabled ? true : undefined}
            style={{ pointerEvents: !entry.enabled ? 'none' : undefined }}
            onClick={() => { setOpenAction(''); onPick(entry.offer, entry.partner) }}>
            {pieceText(entry.offer)}
          </button>
        </HoverHint>
      })}
    </>, () => setOpenAction(''))}
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
