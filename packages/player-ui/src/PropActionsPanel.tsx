import { useEffect, useState, type ReactNode } from 'react'
import { apiPost } from './api'
import { HoverHint } from './HoverHint'
import { useI18n } from './I18nProvider'
import { propActionReason } from './propActionReasons'
import { usePropActions } from './usePropActions'
import { cancelPropAction, checkPropAction, holdPropActionMeter, notifyPropActionChanged, requestPropAction, respondPropAction,
  type PropActionChoice, type PropActionConsent, type PropActionExecution, type PropActionMeter, type PropActionOffer } from './propActions'

interface OfferChoice { offer: PropActionOffer; partner?: string; enabled: boolean; reason: string }
interface OfferGroup { key: string; label: string; partner?: string; entries: OfferChoice[]; usable: boolean }

const pieceText = (offer: PropActionOffer) =>
  `${offer.prop_label}${offer.distance_m == null ? '' : ` · ${offer.distance_m.toFixed(1)} m`}`

/** One group per action (and partner); its pieces usable first, then nearest first. */
function offerGroups(offers: PropActionOffer[], partner?: string): OfferGroup[] {
  const groups = new Map<string, OfferGroup>()
  for (const offer of offers) {
    if (offer.participants > 2) continue
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

/** Group actions (more than two people), one per action name; never in a
 *  menu that already belongs to one partner. */
function groupActions(offers: PropActionOffer[], partner?: string): OfferGroup[] {
  if (partner) return []
  const groups = new Map<string, OfferGroup>()
  for (const offer of offers) {
    if (!(offer.participants > 2)) continue
    const key = JSON.stringify(['group', offer.label])
    const group = groups.get(key) ?? { key, label: offer.label, entries: [], usable: false }
    group.entries.push({ offer, enabled: offer.enabled, reason: offer.reason })
    group.usable ||= offer.enabled
    groups.set(key, group)
  }
  for (const group of groups.values()) group.entries.sort((a, b) => Number(b.enabled) - Number(a.enabled)
    || (a.offer.distance_m ?? Infinity) - (b.offer.distance_m ?? Infinity))
  return [...groups.values()]
}

/** The open group action: pick the others (exactly participants − 1 of the
 *  offer's `candidates`), then ask them on one piece. Each piece's button
 *  waits for Core's preflight of that exact choice — its reason is the
 *  hover text; everyone picked must agree before it starts. */
function GroupPicker({ group, busy, nameProps, onPick, onClose }: {
  group: OfferGroup
  busy: boolean
  nameProps: boolean
  onPick: (offer: PropActionOffer, members: string[]) => void
  onClose: () => void
}) {
  const { t } = useI18n()
  const [picked, setPicked] = useState<string[]>([])
  const [verdicts, setVerdicts] = useState<Record<string, PropActionChoice>>({})
  const need = group.entries[0].offer.participants - 1
  const candidates = [...new Set(group.entries.flatMap(entry => entry.offer.candidates ?? []))]
  const complete = picked.length === need
  const entryKey = (offer: PropActionOffer) => JSON.stringify([offer.target, offer.action_id])
  const checkKey = complete ? JSON.stringify([picked, group.entries.map(entry => entryKey(entry.offer))]) : ''
  useEffect(() => {
    setVerdicts({})
    if (!checkKey) return
    let live = true
    for (const entry of group.entries) {
      const offer = entry.offer
      if (!offer.enabled || !picked.every(name => offer.candidates?.includes(name))) continue
      checkPropAction(offer.action_id, offer.target, offer.definition_revision, picked)
        .then(verdict => { if (live) setVerdicts(v => ({ ...v, [entryKey(offer)]: verdict })) })
        .catch((e: unknown) => {
          if (live) setVerdicts(v => ({ ...v, [entryKey(offer)]: { enabled: false, reason: e instanceof Error ? e.message : String(e) } }))
        })
    }
    return () => { live = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [checkKey])
  const toggle = (name: string) => setPicked(list => list.includes(name) ? list.filter(n => n !== name)
    : list.length < need ? [...list, name] : list)
  return <div className="player-prop-offers-row" style={{ display: 'flex', flexWrap: 'wrap', gap: 5, alignItems: 'center' }}>
    <span style={{ opacity: 0.7 }}>{group.label} · {t('choose {n}').replace('{n}', String(need))}:</span>
    {candidates.map(name => {
      const on = picked.includes(name)
      return <button key={`who:${name}`} type="button" className={`player-chip${on ? ' on' : ''}`} aria-pressed={on}
        disabled={busy || (!on && complete)} onClick={() => toggle(name)}>{name}</button>
    })}
    {complete && group.entries.map(entry => {
      const verdict = verdicts[entryKey(entry.offer)]
      const fits = picked.every(name => entry.offer.candidates?.includes(name))
      const enabled = entry.enabled && fits && !!verdict?.enabled
      const reason = !entry.enabled ? entry.reason : !fits ? 'participant_unavailable'
        : verdict && !verdict.enabled ? verdict.reason : ''
      const piece = group.entries.length > 1 || nameProps ? `${pieceText(entry.offer)} · ` : ''
      return <HoverHint key={`ask:${entryKey(entry.offer)}`}
        text={reason ? propActionReason(reason, t) : t('Ask {name} first').replace('{name}', picked.join(', '))}>
        <button type="button" className="player-chip" disabled={busy || !enabled} aria-disabled={!enabled ? true : undefined}
          style={{ pointerEvents: !enabled ? 'none' : undefined }}
          onClick={() => onPick(entry.offer, picked)}>
          {piece}{verdict || reason ? t('Ask') : '…'}
        </button>
      </HoverHint>
    })}
    <button type="button" className="player-chip" aria-label={t('Close')} onClick={onClose}>✕</button>
  </div>
}

/** Shared presentation for canvas menus and panels; verdicts are Core's, not UI rules.
 *  Compact: a chip per action carries only the action's name. An action one piece
 *  offers starts on click (the piece and its distance are the hover text); an action
 *  several pieces offer opens a row of those pieces, nearest first. Pair actions sit
 *  behind one "With <partner>" chip per partner, unless the menu already belongs to
 *  one partner. No native select: its width followed the longest option. A pair
 *  action always opens its row: every piece there offers "Ask" (the partner
 *  consents first) and "Just do it" (it starts, the partner reacts) — the
 *  requester chooses each time, no action is authored twice. */
export function PropActionOffers({ offers, partner, busy = false, nameProps = true, leading, onPick }: {
  offers: PropActionOffer[]
  partner?: string
  busy?: boolean
  /** Off where the menu already belongs to one piece (the canvas place menu). */
  nameProps?: boolean
  /** Standing actions and Stop share the first chip row on a character card. */
  leading?: ReactNode
  /** `members`: the people picked for a group action (then `partner` is unset). */
  onPick: (offer: PropActionOffer, partner?: string, consent?: PropActionConsent, members?: string[]) => void
}) {
  const { t } = useI18n()
  const [openPartner, setOpenPartner] = useState('')
  const [openAction, setOpenAction] = useState('')
  const groups = offerGroups(offers, partner)
  const crowds = groupActions(offers, partner)
  // Grouped by partner only where the menu is not one partner's already.
  const solo = [...groups.filter(group => partner || !group.partner), ...crowds]
  const partners = new Map<string, OfferGroup[]>()
  if (!partner) for (const group of groups) if (group.partner) partners.set(group.partner, [...partners.get(group.partner) ?? [], group])
  const shownPartner = partners.has(openPartner) ? openPartner : ''
  const visible = [...solo, ...partners.get(shownPartner) ?? []]
  const opens = (group: OfferGroup) => group.entries.length > 1 || !!group.partner || crowds.includes(group)
  const action = visible.find(group => group.key === openAction && opens(group))

  const chip = (group: OfferGroup) => {
    const first = group.entries[0]
    const several = opens(group)
    const disabled = busy || !group.usable
    // A blocked choice says why on mouse-over (HoverHint: drawn by the page, so
    // the native client shows it too); a single piece names itself there.
    const finale = group.entries.some(entry => entry.offer.finale)
    const plain = !group.usable ? propActionReason(first.reason, t)
      : !several && nameProps ? pieceText(first.offer) : undefined
    const hint = finale ? [plain, t('With finale')].filter(Boolean).join(' · ') : plain
    return <HoverHint key={group.key} text={hint}>
      <button type="button" className={`player-chip${finale ? ' player-chip-finale' : ''}${action === group ? ' on' : ''}`} disabled={disabled}
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
      {leading}
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
    {action && crowds.includes(action) && <GroupPicker key={action.key} group={action} busy={busy} nameProps={nameProps}
      onPick={(offer, members) => { setOpenAction(''); onPick(offer, undefined, 'ask', members) }}
      onClose={() => setOpenAction('')} />}
    {action && !crowds.includes(action) && row(<>
      <span style={{ opacity: 0.7 }}>{action.label}{action.partner ? ` · ${action.partner}` : ''}:</span>
      {action.entries.map(entry => {
        const disabled = busy || !entry.enabled
        const key = JSON.stringify([entry.offer.target, entry.offer.action_id])
        const button = (label: string, hint: string | undefined, consent?: PropActionConsent) =>
          <HoverHint key={`${key}:${consent ?? ''}`} text={entry.enabled ? hint : propActionReason(entry.reason, t)}>
            <button type="button" className="player-chip" disabled={disabled}
              aria-disabled={disabled ? true : undefined}
              style={{ pointerEvents: !entry.enabled ? 'none' : undefined }}
              onClick={() => { setOpenAction(''); onPick(entry.offer, entry.partner, consent) }}>
              {label}
            </button>
          </HoverHint>
        if (!entry.partner) return button(pieceText(entry.offer), undefined)
        // The piece is named where there is a choice of pieces or the menu is not one piece's.
        const piece = action.entries.length > 1 || nameProps ? `${pieceText(entry.offer)} · ` : ''
        return <span key={key} style={{ display: 'inline-flex', gap: 5 }}>
          {button(`${piece}${t('Ask')}`, t('Ask {name} first').replace('{name}', entry.partner), 'ask')}
          {button(`${piece}${t('Just do it')}`,
            t('Start at once; {name} reacts and may push you away').replace('{name}', entry.partner), 'react')}
        </span>
      })}
    </>, () => setOpenAction(''))}
  </div>
}

/** How often a filling gauge is redrawn between two state reads. */
const METER_TICK_MS = 250

/**
 * A gauge's value NOW: the server's value carried forward with its `rate`
 * (points per real second) since that read arrived. The server beats only
 * every few seconds; without this the bar jumps a whole beat at once.
 */
function useMeterValues(meters: PropActionMeter[] | undefined) {
  const key = JSON.stringify((meters || []).map(m => [m.name, m.value, m.rate || 0]))
  // When this read arrived, and the clock that redraws it — both set anew
  // per read, so a pause in the redraw never turns into a jump.
  const [clock, setClock] = useState({ key: '', at: 0, now: 0 })
  const filling = (meters || []).some(m => (m.rate || 0) > 0 && m.value < 100)
  useEffect(() => {
    const at = Date.now()
    setClock({ key, at, now: at })
    if (!filling) return
    const id = setInterval(() => setClock(c => ({ ...c, now: Date.now() })), METER_TICK_MS)
    return () => clearInterval(id)
  }, [key, filling])
  const since = clock.key === key ? Math.max(0, clock.now - clock.at) / 1000 : 0
  return (meter: PropActionMeter) => Math.max(0, Math.min(100, meter.value + (meter.rate || 0) * since))
}

export function PropActionExecutionRow({ run, kind, busy, perform }: {
  run: PropActionExecution
  kind: 'incoming' | 'outgoing' | 'current' | 'result'
  busy: boolean
  perform: (operation: () => Promise<unknown>) => void
}) {
  const { t } = useI18n()
  const meterValue = useMeterValues(run.meters)
  const state = run.phase === 'entry' && run.status === 'approaching' ? 'Entering'
    : run.status === 'approaching' && run.own_role === 'actor' && run.reaction === 'pending' ? 'Waiting for reaction'
    : ({ awaiting_consent: 'Awaiting consent', approaching: 'Approaching', active: 'Active', sleeping: 'Sleeping',
      completed: 'Completed', cancelled: 'Cancelled', failed: 'Failed' } as Record<string, string>)[run.status] || run.status
  // A row with others names them: "Kira: Hug" for one it is asked of or
  // done to, "Hug with Kira, Ben" for the one who started it.
  const title = !run.members.length ? run.label
    : run.own_role === 'partner' ? `${run.actor}: ${run.label}`
    : t('{pose} with {name}').replace('{pose}', run.label).replace('{name}', run.members.join(', '))
  return <div className="player-prop-execution" style={{ display: 'flex', flexWrap: 'wrap', gap: 5, alignItems: 'center', padding: '4px 0' }}>
    <span>{title} · {t(state)}{run.status === 'awaiting_consent' && run.members.length > 1 && run.consents
      ? ` (${Object.entries(run.consents).map(([name, answer]) => `${name} ${answer === 'yes' ? '✓' : '…'}`).join(', ')})` : ''}</span>
    {kind === 'incoming' && run.can_respond && <>
      <button type="button" className="player-chip" disabled={busy}
        onClick={() => perform(() => respondPropAction(run.execution_id, true))}>{t('Accept')}</button>
      <button type="button" className="player-chip" disabled={busy}
        onClick={() => perform(() => respondPropAction(run.execution_id, false))}>{t('Decline')}</button>
    </>}
    {run.can_cancel && <button type="button" className="player-chip" disabled={busy}
      onClick={() => perform(() => cancelPropAction(run.execution_id))}>{t(run.can_resist ? 'Push away' : kind === 'outgoing' ? 'Withdraw' : 'Stop')}</button>}
    {run.status === 'active' && run.meters?.map(meter => {
      const value = meterValue(meter)
      // Only the viewer's own gauge can be held back — the own side of the run.
      const own = run.viewer === meter.name
      return <span key={`meter:${meter.name}`} style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
        <HoverHint text={`${meter.name} · ${meter.label || t('Finale')}: ${Math.round(value)} %`}>
          <span className="player-prop-meter-row" style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
            <span>{meter.name}</span>
            <span className={`player-prop-meter${meter.held ? ' held' : ''}`} role="meter" aria-valuemin={0} aria-valuemax={100}
              aria-valuenow={Math.round(value)} aria-label={`${meter.name} · ${meter.label || t('Finale')}`}>
              <span className="player-prop-meter-fill" style={{ width: `${value}%` }} />
            </span>
          </span>
        </HoverHint>
        {own && meter.holdable && <HoverHint text={t('Slows your own gauge while on')}>
          <button type="button" className={`player-chip${meter.held ? ' on' : ''}`} disabled={busy}
            aria-pressed={!!meter.held}
            onClick={() => perform(() => holdPropActionMeter(run.execution_id, !meter.held))}>
            {t('Hold back')}
          </button>
        </HoverHint>}
      </span>
    })}
    {run.status === 'sleeping' && <button type="button" className="player-chip" disabled={busy}
      onClick={() => perform(async () => {
        // Existing player wake path; Core clears sleep and semantic bed ownership.
        await apiPost('/play/self/activity', { activity: '' })
        notifyPropActionChanged()
      })}>{t('Wake up')}</button>}
  </div>
}

/** Mounted unchanged in web frontend, browser HUD iframe and native HUD iframe. */
export function PropActionsPanel({ partner, showOffers = true, showState = true, leading }: {
  partner?: string
  showOffers?: boolean
  showState?: boolean
  leading?: ReactNode
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
    ? runs.filter(run => run.actor === partner || run.members.includes(partner)) : runs
  const hasOffers = data?.offers.some(offer => !partner || (offer.required_partner && offer.available_targets.some(choice => choice.partner === partner)))
  const groups = data && showState ? [
    ['incoming', ownRuns(data.state.incoming)], ['outgoing', ownRuns(data.state.outgoing)],
    ['current', ownRuns(data.state.current)],
  ] as const : []
  // Finished runs are not listed: the room's storyteller line already told the player.
  if (!note && !error && !leading && !hasOffers && !groups.some(([, runs]) => runs.length)) return null
  const heading = leading ? t('Actions') : t('Furniture actions')
  return <section aria-label={heading} style={{ flex: '0 0 auto', maxHeight: 230, overflow: 'auto', padding: 6, fontSize: '0.85em', borderTop: '1px solid var(--border, #30363d)' }}>
    <strong>{heading}</strong>
    {error != null && <div role="alert">{error instanceof Error ? error.message : String(error)}</div>}
    {note && <div role="alert">{note}</div>}
    {groups.map(([kind, runs]) => runs.map(run => <PropActionExecutionRow key={`${kind}:${run.execution_id}`}
      run={run} kind={kind} busy={busy} perform={operation => { void perform(operation) }} />))}
    {showOffers && (data || leading) && <PropActionOffers offers={data?.offers ?? []} partner={partner} busy={busy || error != null} leading={leading}
      onPick={(offer, selectedPartner, consent, members) => { void perform(() => requestPropAction(offer.action_id, offer.target, offer.definition_revision,
        members ?? (selectedPartner ? [selectedPartner] : []), consent)) }} />}
  </section>
}
