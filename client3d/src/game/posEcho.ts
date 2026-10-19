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
