/** How many sent report numbers a client remembers. At ~3 reports/s that is
 *  more than 20 s — longer than a poll interval plus the slowest build. */
export const ECHO_RING_CAP = 64;

/** Remember a report number at SEND time (an aborted request may still land). */
export function pushSeq(ring: number[], seq: number, cap = ECHO_RING_CAP): void {
  ring.push(seq);
  while (ring.length > cap) ring.shift();
}

/** Is the payload's position one of OUR OWN reports (§ A15)? Only the server's
 *  origin stamp answers that — a coordinate match cannot tell a server move
 *  onto an old point from an echo. */
export function isOwnEcho(ring: number[], mySession: string,
  origin: { session: string; seq: number } | null | undefined): boolean {
  return !!origin && origin.session === mySession && ring.includes(origin.seq);
}

export const NO_CANCEL: unique symbol = Symbol('no-cancel');
export type Cancelled = string | null | typeof NO_CANCEL;
export type DriverState =
  | { kind: 'PLAYER' }
  | { kind: 'SERVER'; j: string | null }
  | { kind: 'CANCELLING'; j: string | null; s: number };
export type DriverEvent =
  | { kind: 'payload'; hasRoute: boolean; journeyId: string | null; originOwnSeq: number | null }
  | { kind: 'input'; firstSeq: number }
  | { kind: 'refused'; seq: number };
export interface DriverResult { state: DriverState; cancelled: Cancelled }
export function avatarDriver(state: DriverState, ev: DriverEvent, cancelled: Cancelled): DriverResult {
  if (ev.kind === 'input') {
    return state.kind === 'SERVER'
      ? { state: { kind: 'CANCELLING', j: state.j, s: ev.firstSeq }, cancelled: state.j }
      : { state, cancelled };
  }
  if (ev.kind === 'refused') {
    return state.kind === 'CANCELLING' && ev.seq >= state.s
      ? { state: { kind: 'SERVER', j: state.j }, cancelled: NO_CANCEL }
      : { state, cancelled };
  }
  if (state.kind === 'PLAYER') {
    return ev.hasRoute && ev.journeyId !== cancelled
      ? { state: { kind: 'SERVER', j: ev.journeyId }, cancelled }
      : { state, cancelled };
  }
  if (state.kind === 'SERVER') {
    if (!ev.hasRoute) return { state: { kind: 'PLAYER' }, cancelled };
    return ev.journeyId !== state.j
      ? { state: { kind: 'SERVER', j: ev.journeyId }, cancelled }
      : { state, cancelled };
  }
  if (ev.hasRoute && ev.journeyId !== state.j) return { state: { kind: 'SERVER', j: ev.journeyId }, cancelled };
  if (ev.originOwnSeq !== null && ev.originOwnSeq >= state.s) return { state: { kind: 'PLAYER' }, cancelled };
  if (!ev.hasRoute) return { state: { kind: 'PLAYER' }, cancelled };
  return { state, cancelled };
}

/** Keep the remembered cancelled journey out of every renderer, even after acknowledgement. */
export function suppressedJourney(state: DriverState, cancelled: Cancelled, journeyId: string | null): boolean {
  return (state.kind === 'CANCELLING' && journeyId === state.j)
    || (journeyId !== null && journeyId === cancelled);
}

/** Only answers owned by the current drive may change the avatar. */
export function answerApplies(state: DriverState, seq: number, floor: number): boolean {
  if (state.kind === 'SERVER') return false;
  if (seq < floor) return false;
  if (state.kind === 'CANCELLING') return seq >= state.s;
  return true;
}
