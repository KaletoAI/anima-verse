/**
 * The two-person actions (hug, dance, …) the avatar may propose to another
 * character: the catalog poses that have a complete pair clip and need no
 * place (`GET /play/interact/options` → `interaction_engine.partner_poses`).
 * Proposing goes through `POST /play/interact` (`invitePair`); the partner
 * answers, so nothing starts without consent.
 *
 * The ONE picker for every place that offers them — the Others card renders
 * `pairActionChips` inline, the chat's action tree (ActionsTree.tsx) renders
 * the same chips under each person — so the two lists cannot drift apart
 * again. The chips are made for the `leading` slot of `PropActionsPanel`,
 * beside the furniture actions.
 */
import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { ApiError, apiGet, apiPost } from './api'
import { HoverHint } from './HoverHint'
import { invitePair } from './pairInteractions'

export interface PairPose { key: string; kind: string; label: string }
/** `blocked`: why the avatar may not propose any of them (a block rule or a
 *  cost on the pair verb) — "" = free to ask. */
export interface PairOptions { poses: PairPose[]; blocked: string }
/** A character the avatar may propose to; `busy` = already in a pair with
 *  someone else (the chips stay visible, but disabled). */
export interface PairTarget { name: string; busy?: boolean }

const EMPTY: PairOptions = { poses: [], blocked: '' }
// The last answer seeds a fresh mount (no empty flash when the action tree
// reopens); one request in flight is shared by every mounted panel.
let last: PairOptions = EMPTY
let inflight: Promise<PairOptions> | null = null

function fetchPairOptions(): Promise<PairOptions> {
  if (!inflight) {
    inflight = apiGet<{ poses?: PairPose[]; blocked?: string }>('/play/interact/options')
      .then((d) => { last = { poses: d.poses || [], blocked: d.blocked || '' }; return last })
      .finally(() => { inflight = null })
  }
  return inflight
}

/** The world's two-person actions — fetched once per mount (and again when
 *  `refreshKey` changes, e.g. another avatar); the clip library does not
 *  change while a scene is being played. The list does not depend on the
 *  target: who may be asked is decided per proposal by the server. */
export function usePairOptions(refreshKey = ''): PairOptions {
  const [options, setOptions] = useState<PairOptions>(last)
  useEffect(() => {
    let cancelled = false
    fetchPairOptions()
      .then((o) => { if (!cancelled) setOptions(o) })
      .catch(() => { last = EMPTY; if (!cancelled) setOptions(EMPTY) })
    return () => { cancelled = true }
  }, [refreshKey])
  return options
}

/** Whether the picker would render anything — the caller hands it to
 *  `PropActionsPanel` as `leading` only then, because a `leading` turns an
 *  otherwise empty panel into a visible "Actions" section. */
export function hasPairActions(options: PairOptions, targets: PairTarget[], stoppable = false): boolean {
  return stoppable || (options.poses.length > 0 && targets.length > 0)
}

export interface PairPropose {
  /** A proposal is in flight — the chips wait (no double invitation). */
  pending: boolean
  propose: (name: string, pose: string) => Promise<void>
  stop: () => Promise<void>
}

/** Propose / stop, with the host's refresh after each. `onNote` gets the
 *  engine's refusal ("Kira is in another room" — that sentence is the whole
 *  point, so it is shown, not swallowed) and "" when a new proposal starts. */
export function usePairPropose(onChanged: () => void | Promise<void>,
  onNote: (message: string) => void): PairPropose {
  const [pending, setPending] = useState(false)
  const propose = useCallback(async (name: string, pose: string) => {
    if (pending) return
    setPending(true)
    onNote('')
    try { await invitePair(name, pose) }
    catch (e) { onNote(e instanceof ApiError ? String(e.detail || '') : String(e)) }
    finally { setPending(false) }
    await onChanged()
  }, [pending, onChanged, onNote])
  const stop = useCallback(async () => {
    try { await apiPost('/play/interact/end', {}) } catch { /* ignore */ }
    await onChanged()
  }, [onChanged])
  return { pending, propose, stop }
}

/** The chips for ONE target: "Stop" first when the avatar is in a pair with
 *  it, then one chip per pose. A busy target or a blocked verb keeps the
 *  chips visible but disabled, with the reason as hover text. A plain
 *  function, not a component: the chips land directly in the caller's chip
 *  row (the `leading` slot). */
export function pairActionChips({ target, options, stoppable = false, actions, t }: {
  target: PairTarget
  options: PairOptions
  stoppable?: boolean
  actions: PairPropose
  t: (s: string) => string
}): ReactNode[] {
  const hint = target.busy ? t('Busy with someone else') : (options.blocked || undefined)
  const off = actions.pending || !!hint
  return [
    ...(stoppable ? [<button key="pair:stop" type="button" onClick={actions.stop}
      className="player-chip">{t('Stop')}</button>] : []),
    ...options.poses.map((pose) => <HoverHint key={`pair:${target.name}:${pose.key}`} text={hint}>
      <button type="button" className="player-chip" disabled={off}
        aria-disabled={off ? true : undefined}
        style={{ pointerEvents: hint ? 'none' : undefined }}
        onClick={() => actions.propose(target.name, pose.key)}>
        {pose.label || pose.key}
      </button>
    </HoverHint>),
  ]
}
