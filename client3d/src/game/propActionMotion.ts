type Point = readonly [number, number];
interface LocalPath {
  waypoints: readonly Point[];
  paces_m_s_real: readonly (number | null)[] | null;
  progress_m: number;
  starts_in_s?: number;
}

/** Arc-length sampling of the public projection, including every corner. */
export function localApproachPoint(path: LocalPath, ageS: number): Point {
  let distance = Math.max(0, path.progress_m);
  let time = Math.max(0, ageS - Math.max(0, path.starts_in_s ?? 0));
  const points = path.waypoints;
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1], b = points[i];
    const length = Math.hypot(b[0] - a[0], b[1] - a[1]);
    if (!length) continue;
    if (distance >= length) { distance -= length; continue; }
    const pace = path.paces_m_s_real?.[i - 1] ?? 0;
    const remaining = length - distance;
    if (pace > 0 && time * pace >= remaining) {
      time -= remaining / pace; distance = 0; continue;
    }
    const fraction = (distance + Math.max(0, pace) * time) / length;
    return [a[0] + (b[0] - a[0]) * fraction, a[1] + (b[1] - a[1]) * fraction];
  }
  return points[points.length - 1] ?? [0, 0];
}

/** Closest rendered point on the route, expressed as arc length. Ties keep the first leg. */
export function projectApproachM(points: readonly Point[], point: Point): number {
  let best = Infinity, result = 0, distance = 0;
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1], b = points[i];
    const dx = b[0] - a[0], dz = b[1] - a[1], length = Math.hypot(dx, dz);
    if (!length) continue;
    const t = Math.max(0, Math.min(1, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dz) / (length * length)));
    const error = Math.hypot(point[0] - a[0] - t * dx, point[1] - a[1] - t * dz);
    if (error < best) { best = error; result = distance + t * length; }
    distance += length;
  }
  return result;
}

/** Owned approaches retain continuity even after a delayed first poll or frame stall. */
export function ownedApproachStep(shownM: number, targetM: number, pace: number, catchUpRate: number, dt: number, startsInS = 0, ageS = 0): number {
  if (startsInS > Math.max(0, ageS)) return shownM;
  return shownM + Math.min(Math.max(0, targetM - shownM), .25,
    Math.max(0, pace, catchUpRate) * Math.max(0, dt));
}

/** Future departures hold their rendered start; only late adoption needs catch-up. */
export function ownedApproachCatchUp(shownM: number, targetM: number, totalM: number,
  pace: number, startsInS: number, ageS: number): number {
  return startsInS > Math.max(0, ageS) || targetM - shownM <= .25 ? 0
    : Math.max(2 * Math.max(0, pace), (totalM - shownM) / .6);
}

export function entryPhase(entry: { elapsed_game_s: number; duration_game_s: number;
  game_seconds_per_real_second: number }, ageS: number): number {
  return Math.min(1, Math.max(0, (entry.elapsed_game_s + Math.max(0, ageS)
    * Math.max(0, entry.game_seconds_per_real_second)) / entry.duration_game_s));
}

/** Support correction follows the measured clip's own vertical body motion,
 * not elapsed-time interpolation. The pose's offset is already in anchorY. */
export function entrySupportLift(firstY: number, lastY: number, currentY: number,
  accessY: number, anchorY: number, rootOffset: number): number | null {
  const supportY = anchorY + rootOffset;
  const lift = supportY - rootOffset - accessY;
  const span = lastY - firstY;
  if (Math.abs(span) < 1e-6) return Math.abs(lift) < 1e-6 ? 0 : null;
  return lift * Math.max(0, Math.min(1, (currentY - firstY) / span));
}

export function entryIdentity(entry: {kind: string; started_game_s: number;
  access: {x:number;y:number;z:number;yaw:number}; anchor: {x:number;y:number;z:number;yaw:number}}): string {
  const a = entry.access, b = entry.anchor;
  return `${entry.kind}|${entry.started_game_s}|${a.x},${a.y},${a.z},${a.yaw}|${b.x},${b.y},${b.z},${b.yaw}`;
}

/** Cancellation is an actual awaited mutation, never a position-write side effect. */
export function createManualPropGate() {
  const withdrawn = new Set<string>();
  let pending: Promise<void> | null = null;
  return {
    get pending() { return pending !== null; },
    withdrawn(journey: string | null | undefined) { return !!journey && withdrawn.has(journey); },
    cancel(_execution: string, journey: string | null, cancel: () => Promise<unknown>): Promise<void> {
      if (pending) return pending;
      pending = (async () => {
        await cancel();
        if (journey) withdrawn.add(journey);
      })().finally(() => { pending = null; });
      return pending;
    },
  };
}

/** The mutation preflight waits for actual position promises, including a
 * queued final report that starts while the preceding report settles. */
export function createPositionDrain() {
  let pending = 0;
  const waiters = new Set<() => void>();
  return {
    begin(): () => void {
      pending++;
      return () => {
        pending--;
        if (!pending) {
          for (const resolve of waiters) resolve();
          waiters.clear();
        }
      };
    },
    wait(): Promise<void> {
      return pending ? new Promise(resolve => { waiters.add(resolve); }) : Promise.resolve();
    },
  };
}

/** Only completion of the SAME HTTP mutation may release its control pause,
 * and only after a subsequently fetched authoritative state was adopted. */
export function createPropPreparationBarrier() {
  const requests = new Map<string, { completed: boolean; expiresAt: number }>();
  return {
    get pending() { return requests.size > 0; },
    begin(requestId: string, now = 0) { requests.set(requestId, { completed: false, expiresAt: now + 10_000 }); },
    changed(requestId?: string) {
      const request = requestId ? requests.get(requestId) : undefined;
      if (request) request.completed = true;
    },
    expire(now: number): boolean {
      let expired = false;
      for (const request of requests.values()) {
        if (!request.completed && request.expiresAt <= now) {
          request.completed = true;
          expired = true;
        }
      }
      return expired;
    },
    adoptFreshState() {
      for (const [requestId, request] of requests) if (request.completed) requests.delete(requestId);
    },
  };
}
