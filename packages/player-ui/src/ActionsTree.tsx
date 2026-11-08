/**
 * ActionsTree — every action the avatar can START, as a tree whose levels
 * open and close like a file tree (the 3D HUD's drawer beside the chat):
 *
 *   Independent actions     the catalog poses one strikes alone, anywhere
 *                           (`GET /play/solo-poses` → `POST /play/self/activity`
 *                           with `pose_key`)
 *   All furniture           one node per piece, nearest first; under it the
 *                           piece's actions (solo: click; pair: pick a partner,
 *                           then Ask / Just do it) and ONE "Group" node for
 *                           all its group actions: pick 2..n people, then Ask
 *                           on any group action that takes that many
 *   All potential partners  one node per person; under it "Stop" while the
 *                           avatar is in a pair with them, "Invite to party"
 *                           (`POST /play/party/invite`; only with a party
 *                           package, greyed with the reason for a follower or
 *                           someone already in the party), then one row per
 *                           pair action with them — the free pair poses first
 *                           (pairActions.tsx, no furniture), then the furniture
 *                           ones (`label · piece`) — each with Ask / Just do it
 *
 * What RUNS (incoming / outgoing / current, Accept / Stop / meters) is not
 * here: that needs an immediate answer and stays in the chat window
 * (`PropActionsPanel` with `showOffers={false}`). Every verdict is Core's —
 * a blocked entry stays visible, greyed, with the reason as hover text.
 */
import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { ApiError, apiGet, apiPost } from './api'
import { HoverHint } from './HoverHint'
import { useI18n } from './I18nProvider'
import { isMember, type InteractionMembers } from './interactionMembers'
import { usePairOptions, usePairPropose } from './pairActions'
import { offerKind, partnerNodes, partyInviteVerdict, pieceGroups, pieceNodes, pieceText,
  type PartyInviteState, type PieceNode } from './actionsTreeModel'
import { propActionReason } from './propActionReasons'
import { GroupPicker, type OfferGroup } from './PropActionsPanel'
import { usePropActions } from './usePropActions'
import { notifyPropActionChanged, requestPropAction, type PropActionConsent,
  type PropActionOffer } from './propActions'

export interface SoloPose { key: string; label: string }

/** The poses the avatar can strike alone and anywhere; refetched per avatar
 *  (the catalog does not change while a scene is played). */
function useSoloPoses(avatar: string): SoloPose[] {
  const [poses, setPoses] = useState<SoloPose[]>([])
  useEffect(() => {
    let live = true
    apiGet<{ poses?: SoloPose[] }>('/play/solo-poses')
      .then(d => { if (live) setPoses(d.poses || []) })
      .catch(() => { if (live) setPoses([]) })
    return () => { live = false }
  }, [avatar])
  return poses
}

/** Only the three top levels are remembered; deeper nodes depend on the room. */
const OPEN_KEY = 'player.actionsTree.open'
const ROOTS = ['solo', 'furniture', 'partners']
function readOpen(): Set<string> {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(OPEN_KEY) || '[]')
    return new Set(Array.isArray(raw) ? raw.filter((k): k is string => ROOTS.includes(k)) : [])
  } catch { return new Set() }
}

export function ActionsTree({ avatar, present, interaction, partyInvite, onChanged }: {
  /** The active avatar ('' = spectator: nothing is rendered). */
  avatar: string
  /** Who is in the room (the scene payload's `present`). */
  present: string[]
  /** The pair the avatar is in, if any — its partner's node offers "Stop". */
  interaction?: { members: InteractionMembers } | null
  /** The scene payload's party facts for "Invite to party" (absent = no leaf). */
  partyInvite?: PartyInviteState | null
  /** After an action was asked for (refresh the host's scene). */
  onChanged: () => void | Promise<void>
}) {
  const { t } = useI18n()
  const { data, error, refresh } = usePropActions()
  const poses = useSoloPoses(avatar)
  const pairOptions = usePairOptions(avatar)
  const [note, setNote] = useState('')
  const pairActions = usePairPropose(onChanged, setNote)
  const [busy, setBusy] = useState(false)
  const [open, setOpen] = useState<Set<string>>(readOpen)
  const toggle = useCallback((id: string) => setOpen(prev => {
    const next = new Set(prev)
    if (!next.delete(id)) next.add(id)
    return next
  }), [])
  const rootsOpen = ROOTS.filter(k => open.has(k)).join(',')
  useEffect(() => {
    try { localStorage.setItem(OPEN_KEY, JSON.stringify(rootsOpen ? rootsOpen.split(',') : [])) } catch { /* private mode */ }
  }, [rootsOpen])
  if (!avatar) return null

  const perform = async (operation: () => Promise<unknown>) => {
    if (busy) return
    setBusy(true)
    setNote('')
    try { await operation() }
    catch (e) { setNote(refusalText(e, t)) }
    finally { await refresh(); await onChanged(); setBusy(false) }
  }
  const request = (offer: PropActionOffer, members: string[] = [], consent?: PropActionConsent) =>
    void perform(() => requestPropAction(offer.action_id, offer.target, offer.definition_revision, members, consent))
  const strike = (pose: SoloPose) => void perform(async () => {
    await apiPost('/play/self/activity', { pose_key: pose.key })
    notifyPropActionChanged()
  })
  /** Invite one person into the avatar's party; the answer comes later (an
   *  NPC is asked at once, a player sees the question), so the note says so. */
  const inviteToParty = (name: string) => void perform(async () => {
    const res = await apiPost<{ status?: string }>('/play/party/invite', { target: name })
    const text = res?.status === 'accepted' ? t('{name} joins your party.')
      : res?.status === 'declined' ? t('{name} turns down your invitation.')
        : t('Waiting for {name}…')
    setNote(text.replace('{name}', name))
  })

  const offers = data?.offers ?? []
  const pieces = pieceNodes(offers)
  const partners = partnerNodes(offers, present, avatar)
  const off = busy || error != null
  const offerKey = (offer: PropActionOffer) => JSON.stringify([offer.target, offer.action_id])

  /** One clickable leaf; a blocked one keeps its place, greyed, and says why.
   *  `own`: a pose of the avatar's own, which a failed furniture read does
   *  not stop. */
  const leaf = (key: string, label: ReactNode, enabled: boolean, reason: string, onClick: () => void,
    hint?: string, finale = false, own = false) =>
    <HoverHint key={key} text={enabled ? hint : propActionReason(reason, t)}>
      <button type="button" className={`player-chip${finale ? ' player-chip-finale' : ''}`}
        disabled={(own ? busy : off) || !enabled} aria-disabled={!enabled ? true : undefined}
        style={{ pointerEvents: !enabled ? 'none' : undefined }} onClick={onClick}>
        {label}
      </button>
    </HoverHint>

  /** "Ask" and "Just do it" for one pair offer with one partner. */
  const consentButtons = (offer: PropActionOffer, partner: string, enabled: boolean, reason: string) => <>
    {leaf(`ask:${offerKey(offer)}:${partner}`, t('Ask'), enabled, reason, () => request(offer, [partner], 'ask'),
      t('Ask {name} first').replace('{name}', partner))}
    {leaf(`react:${offerKey(offer)}:${partner}`, t('Just do it'), enabled, reason, () => request(offer, [partner], 'react'),
      t('Start at once; {name} reacts and may push you away').replace('{name}', partner))}
  </>

  /** The same "Ask" / "Just do it" for one free pair pose (no furniture) —
   *  `POST /play/interact` with that consent. `hint`: why the pair verb is
   *  blocked, already in words ("" = usable). */
  const poseButtons = (pose: string, partner: string, hint: string) => {
    const button = (consent: PropActionConsent, label: string, title: string) =>
      <HoverHint key={`${consent}:pose:${pose}:${partner}`} text={hint || title}>
        <button type="button" className="player-chip" disabled={busy || pairActions.pending || !!hint}
          aria-disabled={hint ? true : undefined} style={{ pointerEvents: hint ? 'none' : undefined }}
          onClick={() => void pairActions.propose(partner, pose, consent)}>
          {label}
        </button>
      </HoverHint>
    return <>
      {button('ask', t('Ask'), t('Ask {name} first').replace('{name}', partner))}
      {button('react', t('Just do it'), t('Start at once; {name} reacts and may push you away').replace('{name}', partner))}
    </>
  }

  /** One solo or pair action of a furniture piece. */
  const pieceAction = (piece: string, offer: PropActionOffer) => {
    const kind = offerKind(offer)
    if (kind === 'solo') {
      return <div key={offerKey(offer)} className="player-actions-tree-leaf">
        {leaf(offerKey(offer), offer.label, offer.enabled, offer.reason, () => request(offer),
          offer.finale ? t('With finale') : undefined, !!offer.finale)}
      </div>
    }
    const id = `act:${piece}:${offer.action_id}`
    // A pair action: pick the partner — each row is Core's verdict for that person.
    const usable = offer.available_targets.some(choice => choice.enabled)
    return <Branch key={id} id={id} open={open} toggle={toggle} label={offer.label}
      count={offer.available_targets.length} disabled={!usable}
      reason={offer.available_targets[0]?.reason || offer.reason}>
      {offer.available_targets.map(choice => <div key={choice.partner}
        className={`player-actions-tree-leaf${choice.enabled ? '' : ' off'}`}>
        <HoverHint text={choice.enabled ? undefined : propActionReason(choice.reason, t)}>
          <span className="player-actions-tree-name">{choice.partner}</span>
        </HoverHint>
        {consentButtons(offer, choice.partner, choice.enabled, choice.reason)}
      </div>)}
    </Branch>
  }

  /** The piece's ONE "Group" node: the people are picked once (2 up to the
   *  largest group action's maximum), then each group action of the piece
   *  offers "Ask" — greyed where it takes fewer people than picked. A group
   *  is only ever asked, never started at once. */
  const pieceGroup = (piece: PieceNode) => {
    const offers = pieceGroups(piece).group
    if (!offers.length) return null
    const id = `group:${piece.key}`
    const group: OfferGroup = { key: id, label: t('Group'), usable: offers.some(offer => offer.enabled),
      entries: offers.map(offer => ({ offer, enabled: offer.enabled, reason: offer.reason })) }
    return <Branch key={id} id={id} open={open} toggle={toggle} label={t('Group')} count={offers.length}
      disabled={!group.usable} reason={offers[0].reason}>
      <GroupPicker group={group} busy={off} nameProps={false}
        onPick={(picked, members) => request(picked, members, 'ask')} onClose={() => toggle(id)} />
    </Branch>
  }

  return <div className="player-actions-tree" aria-label={t('Actions')}>
    {error != null && <div role="alert" className="player-actions-tree-note">
      {error instanceof Error ? error.message : String(error)}</div>}
    {note && <div role="alert" className="player-actions-tree-note">{note}</div>}

    <Branch id="solo" open={open} toggle={toggle} label={t('Independent actions')} count={poses.length} root>
      {poses.length
        ? <div className="player-actions-tree-leaf">
          {poses.map(pose => leaf(`pose:${pose.key}`, pose.label || pose.key, true, '', () => strike(pose),
            undefined, false, true))}
        </div>
        : <div className="player-actions-tree-empty">{t('No poses available.')}</div>}
    </Branch>

    <Branch id="furniture" open={open} toggle={toggle} label={t('All furniture')} count={pieces.length} root>
      {pieces.length ? pieces.map(piece => {
        const id = `piece:${piece.key}`
        return <Branch key={id} id={id} open={open} toggle={toggle} label={pieceText(piece.offers[0])}
          count={piece.offers.length} disabled={!piece.offers.some(o => o.enabled)}>
          {pieceGroups(piece).single.map(offer => pieceAction(piece.key, offer))}
          {pieceGroup(piece)}
        </Branch>
      }) : <div className="player-actions-tree-empty">{t('No furniture actions here.')}</div>}
    </Branch>

    <Branch id="partners" open={open} toggle={toggle} label={t('All potential partners')} count={partners.length} root>
      {partners.length ? partners.map(person => {
        const id = `partner:${person.name}`
        const stoppable = isMember(interaction?.members, person.name) && isMember(interaction?.members, avatar)
        const invite = partyInviteVerdict(person.name, partyInvite)
        return <Branch key={id} id={id} open={open} toggle={toggle} label={person.name}
          count={pairOptions.poses.length + person.entries.length + (invite ? 1 : 0)}>
          {stoppable && <div className="player-actions-tree-leaf">
            <button type="button" className="player-chip" onClick={() => void pairActions.stop()}>{t('Stop')}</button>
          </div>}
          {invite && <div className="player-actions-tree-leaf">
            <HoverHint text={invite.reason ? t(invite.reason).replace('{name}', invite.name)
              : t('Ask {name} to come along with you').replace('{name}', person.name)}>
              <button type="button" className="player-chip" disabled={busy || !!invite.reason}
                aria-disabled={invite.reason ? true : undefined}
                style={{ pointerEvents: invite.reason ? 'none' : undefined }}
                onClick={() => inviteToParty(person.name)}>
                {t('Invite to party')}
              </button>
            </HoverHint>
          </div>}
          {pairOptions.poses.map(pose => <div key={`pose:${pose.key}`}
            className={`player-actions-tree-leaf${pairOptions.blocked ? ' off' : ''}`}>
            <HoverHint text={pairOptions.blocked || undefined}>
              <span className="player-actions-tree-name">{pose.label || pose.key}</span>
            </HoverHint>
            {poseButtons(pose.key, person.name, pairOptions.blocked)}
          </div>)}
          {person.entries.map(entry => <div key={offerKey(entry.offer)}
            className={`player-actions-tree-leaf${entry.enabled ? '' : ' off'}`}>
            <HoverHint text={entry.enabled ? pieceText(entry.offer) : propActionReason(entry.reason, t)}>
              <span className="player-actions-tree-name">
                {entry.offer.label} <span className="player-actions-tree-piece">· {pieceText(entry.offer)}</span>
              </span>
            </HoverHint>
            {consentButtons(entry.offer, person.name, entry.enabled, entry.reason)}
          </div>)}
        </Branch>
      }) : <div className="player-actions-tree-empty">{t('Nobody else is here.')}</div>}
    </Branch>
  </div>
}

/** A refusal as a sentence: the endpoint's own codes get words, anything
 *  else is the server's message as it came. */
function refusalText(e: unknown, t: (s: string) => string): string {
  const detail = e instanceof ApiError ? e.detail : undefined
  if (detail === 'no_free_place') return t('There is no free place for that here.')
  if (detail === 'pair_pose') return t('That takes two — use the action chips on their card.')
  return e instanceof Error ? e.message : String(e)
}

/** One level of the tree: a ▸/▾ row that opens its children. A disabled
 *  branch (nothing under it is usable) is greyed but still opens, so the
 *  reasons below stay readable. */
function Branch({ id, open, toggle, label, count, disabled = false, reason, root = false, children }: {
  id: string
  open: Set<string>
  toggle: (id: string) => void
  label: ReactNode
  count?: number
  disabled?: boolean
  reason?: string
  root?: boolean
  children: ReactNode
}) {
  const { t } = useI18n()
  const expanded = open.has(id)
  return <div className={`player-actions-tree-node${root ? ' root' : ''}${disabled ? ' off' : ''}`}>
    <HoverHint text={disabled && reason ? propActionReason(reason, t) : undefined}>
      <button type="button" className="player-actions-tree-toggle" aria-expanded={expanded}
        onClick={() => toggle(id)}>
        <span className="player-actions-tree-caret" aria-hidden="true">{expanded ? '▾' : '▸'}</span>
        <span className="player-actions-tree-label">{label}</span>
        {count != null && <span className="player-actions-tree-count">{count}</span>}
      </button>
    </HoverHint>
    {expanded && <div className="player-actions-tree-children">{children}</div>}
  </div>
}
