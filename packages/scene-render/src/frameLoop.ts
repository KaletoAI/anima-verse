/**
 * PHASE B OF THE TWO-PHASE FIGURE FRAME over N figures (Ruling A110 — moved
 * out of client3d's `NpcManager.tickSecondary` so the Game-Admin preview runs
 * the same loop). Call it once every figure has posed (phase A, ending in
 * `FigureRuntime.poseStep`):
 *   1. the plan — per reader the partners it reads this frame (`planPartnerFrame`);
 *   2. every selected partner snapshot ONCE, before any solve, so the result
 *      does not depend on the order the figures are visited in;
 *   3. `updateSecondary` for each figure (a no-op for one not posed);
 *   4. the channel openings (Ruling A102): every chain engaged in a partner's
 *      channel opens that partner's surface, at most `openingBudget` recomputes
 *      per frame, receivers visited from the rotating `state.openingTurn`;
 *   5. the partners of every GPU hair-push reader re-read on their FINAL pose
 *      and handed to its hair push, which reads them at render time — no lag.
 */
import type { PartnerSnapshot } from './partnerContact'
import { consumerPartnerCapsules } from './partnerContact'
import type { CapsuleNow } from './collision'
import type { OpeningSegment } from './channelOpening'
import { planPartnerFrame } from './partnerFrame'
import type { FrameFigure } from './partnerFrame'

/** What the frame loop needs of one figure — `FigureRuntime` and client3d's `Figure` both have it. */
export interface FramePhaseB {
  frameFigure(name: string, members: readonly string[]): FrameFigure | null
  partnerSnapshot(interaction: { id: string; kind: string } | null, name: string): PartnerSnapshot | null
  updateSecondary(partners: readonly PartnerSnapshot[], interaction: { id: string } | null): unknown
  channelOccupants(): readonly { partner: string; channel: string; w: number; segments: readonly OpeningSegment[]; channelR?: number }[]
  applyChannelOpenings(occupants: readonly { channel: string; w: number; segments: readonly OpeningSegment[]; channelR?: number }[],
    budget: { left: number }): void
  readonly hasHairPush: boolean
  setGpuPartners(capsules: readonly CapsuleNow[] | null): void
}

/** One figure of the frame: its owner's name, its pair interaction (members rank first, channels engage only
 *  within it) and the figure itself (null = no figure, e.g. a sprite). */
export interface FrameEntry {
  name: string
  interaction: { id: string; kind: string; members?: readonly string[] } | null
  figure: FramePhaseB | null | undefined
}

/** Loop state that outlives a frame (the opening pass's rotating start). */
export interface FrameLoopState { openingTurn: number }

/** A102b: opening recomputes (or first binds) per frame across all figures. */
export const OPENING_BUDGET = 1

const NO_PARTNERS: readonly PartnerSnapshot[] = []

/** Run phase B for `entries` (module docstring). Names must be unique per frame. */
export function runFigureFrame(entries: readonly FrameEntry[], state: FrameLoopState,
  openingBudget = OPENING_BUDGET): void {
  const byName = new Map<string, FrameEntry>()
  for (const e of entries) byName.set(e.name, e)
  const frames: FrameFigure[] = []
  for (const e of entries) {
    const frame = e.figure?.frameFigure(e.name, e.interaction?.members ?? [])
    if (frame) frames.push(frame)
  }
  const plan = frames.length > 1 ? planPartnerFrame(frames) : new Map<string, string[]>()
  const interactionOf = (e: FrameEntry) => e.interaction ? { id: e.interaction.id, kind: e.interaction.kind } : null
  const snapshots = new Map<string, PartnerSnapshot | null>()
  for (const names of plan.values()) {
    for (const name of names) {
      if (snapshots.has(name)) continue
      const e = byName.get(name)
      snapshots.set(name, e?.figure?.partnerSnapshot(interactionOf(e), name) ?? null)
    }
  }
  const partnersOf = (name: string): readonly PartnerSnapshot[] => {
    const names = plan.get(name)
    if (!names?.length) return NO_PARTNERS
    const out: PartnerSnapshot[] = []
    for (const partner of names) {
      const snap = snapshots.get(partner)
      if (snap) out.push(snap)
    }
    return out
  }
  // Each reader passes its OWN interaction: a partner's channel engages only within the same one.
  for (const e of entries) e.figure?.updateSecondary(partnersOf(e.name), interactionOf(e))
  const occupied = new Map<string, { channel: string; w: number; segments: readonly OpeningSegment[]; channelR?: number }[]>()
  for (const e of entries) {
    for (const occ of e.figure?.channelOccupants() ?? []) {
      const list = occupied.get(occ.partner) ?? []
      list.push(occ)
      occupied.set(occ.partner, list)
    }
  }
  const budget = { left: openingBudget }
  const start = entries.length ? state.openingTurn++ % entries.length : 0
  for (let k = 0; k < entries.length; k++) {
    const e = entries[(start + k) % entries.length]
    e.figure?.applyChannelOpenings(occupied.get(e.name) ?? [], budget)
  }
  const fresh = new Map<string, PartnerSnapshot | null>()
  for (const e of entries) {
    const figure = e.figure
    if (!figure) continue
    const names = figure.hasHairPush ? plan.get(e.name) : undefined
    if (!names?.length) { figure.setGpuPartners(null); continue }
    const partners: PartnerSnapshot[] = []
    for (const name of names) {
      if (!snapshots.get(name)) continue
      if (!fresh.has(name)) {
        const partner = byName.get(name)
        fresh.set(name, partner?.figure?.partnerSnapshot(partner ? interactionOf(partner) : null, name) ?? null)
      }
      const snap = fresh.get(name)
      if (snap) partners.push(snap)
    }
    figure.setGpuPartners(partners.length ? consumerPartnerCapsules('hair', partners) : null)
  }
}
