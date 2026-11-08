/**
 * The pure side of the chat's action tree (`ActionsTree.tsx`): how Core's
 * furniture offers (`GET /play/prop-actions`) are folded into the tree's
 * "All furniture" and "All potential partners" levels. No React, no fetch —
 * the verdicts (`enabled`/`reason`) are Core's and are carried through
 * untouched, never recomputed here.
 */
import type { PropActionOffer } from './propActions'

/** A piece as a chip names it: its label and, with a position, its distance. */
export const pieceText = (offer: PropActionOffer) =>
  `${offer.prop_label}${offer.distance_m == null ? '' : ` · ${offer.distance_m.toFixed(1)} m`}`

/** What an offer asks of the player: start it alone, pick ONE partner, or
 *  pick several people (participants > 2, the group picker). */
export type OfferKind = 'solo' | 'pair' | 'group'
export function offerKind(offer: PropActionOffer): OfferKind {
  return offer.participants > 2 ? 'group' : offer.required_partner ? 'pair' : 'solo'
}

/** The fewest people the player picks for a group action, the avatar not
 *  counted — Core's `GROUP_MIN_PEOPLE` (prop_action_engine.py) minus the
 *  avatar. A group action's `participants` is the MOST it takes (its clip's
 *  role count); the roles nobody takes stay empty (schnittstellen-3d § A8a). */
export const GROUP_MIN_OTHERS = 2

/** The most others one group action takes beside the avatar. */
export const groupMostOthers = (offer: PropActionOffer) => Math.max(0, offer.participants - 1)

/** Whether one group action takes `count` picked others: from
 *  `GROUP_MIN_OTHERS` up to its own maximum. */
export type GroupFit = 'fits' | 'too_few' | 'too_many'
export function groupFit(offer: PropActionOffer, count: number): GroupFit {
  return count < GROUP_MIN_OTHERS ? 'too_few' : count > groupMostOthers(offer) ? 'too_many' : 'fits'
}

/** What the group picker offers for a set of group actions: the candidates
 *  of all of them (first seen first) and how many of them may be picked —
 *  `fewest` = `GROUP_MIN_OTHERS`, `most` = the largest action's maximum, but
 *  never more than there are candidates. */
export function groupPickRange(offers: PropActionOffer[]): { fewest: number; most: number; candidates: string[] } {
  const candidates = [...new Set(offers.flatMap(offer => offer.candidates ?? []))]
  const most = Math.min(candidates.length, Math.max(0, ...offers.map(groupMostOthers)))
  return { fewest: GROUP_MIN_OTHERS, most, candidates }
}

/** One furniture piece and every action it offers. */
export interface PieceNode {
  /** Exact identity of the piece (Core's target minus the action). */
  key: string
  /** The piece's own label (`prop_label`). */
  label: string
  /** Metres to the piece; null without a position. */
  distance_m: number | null
  /** Its actions: usable first, then by label. */
  offers: PropActionOffer[]
}

const byDistance = (a: number | null, b: number | null) => (a ?? Infinity) - (b ?? Infinity)
const byLabel = (a: string, b: string) => a.localeCompare(b)

/** One node per furniture piece (placement + variant), nearest first, then
 *  by label; a piece without a position sorts last. */
export function pieceNodes(offers: PropActionOffer[]): PieceNode[] {
  const pieces = new Map<string, PieceNode>()
  for (const offer of offers) {
    const t = offer.target
    const key = JSON.stringify([t.location_id, t.room_id, t.placement_id, t.variant_uid])
    const piece = pieces.get(key) ?? { key, label: offer.prop_label, distance_m: offer.distance_m, offers: [] }
    piece.offers.push(offer)
    if (byDistance(offer.distance_m, piece.distance_m) < 0) piece.distance_m = offer.distance_m
    pieces.set(key, piece)
  }
  for (const piece of pieces.values()) {
    piece.offers.sort((a, b) => Number(b.enabled) - Number(a.enabled) || byLabel(a.label, b.label))
  }
  return [...pieces.values()].sort((a, b) => byDistance(a.distance_m, b.distance_m)
    || byLabel(a.label, b.label) || byLabel(a.key, b.key))
}

/** A piece's actions split for the tree: the ones listed one by one (solo
 *  and pair, in the piece's order) and its group actions, which share ONE
 *  "Group" node — the people are picked once, then every group action of the
 *  piece is shown for that choice. */
export function pieceGroups(piece: PieceNode): { single: PropActionOffer[]; group: PropActionOffer[] } {
  return { single: piece.offers.filter(offer => offerKind(offer) !== 'group'),
    group: piece.offers.filter(offer => offerKind(offer) === 'group') }
}

/** One furniture action possible with one partner — Core's verdict for
 *  exactly that partner. */
export interface PartnerEntry { offer: PropActionOffer; enabled: boolean; reason: string }
export interface PartnerNode { name: string; entries: PartnerEntry[] }

/** One node per person the avatar could act with: everyone present in the
 *  room plus everyone a pair offer names as a possible partner, the avatar
 *  itself never, sorted by name. Each carries the pair furniture actions
 *  with that person (usable first, then nearest, then by label); a group
 *  action (participants > 2) belongs to no single person and is left out. */
export function partnerNodes(offers: PropActionOffer[], present: string[], avatar: string): PartnerNode[] {
  const nodes = new Map<string, PartnerNode>()
  const node = (name: string) => {
    let found = nodes.get(name)
    if (!found) { found = { name, entries: [] }; nodes.set(name, found) }
    return found
  }
  for (const name of present) if (name && name !== avatar) node(name)
  for (const offer of offers) {
    if (offerKind(offer) !== 'pair') continue
    for (const choice of offer.available_targets) {
      if (!choice.partner || choice.partner === avatar) continue
      node(choice.partner).entries.push({ offer, enabled: choice.enabled, reason: choice.reason })
    }
  }
  for (const found of nodes.values()) {
    found.entries.sort((a, b) => Number(b.enabled) - Number(a.enabled)
      || byDistance(a.offer.distance_m, b.offer.distance_m) || byLabel(a.offer.label, b.offer.label))
  }
  return [...nodes.values()].sort((a, b) => byLabel(a.name, b.name))
}
