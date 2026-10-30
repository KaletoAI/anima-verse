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

/** Own motion uses only elapsed real seconds since the answer was received. */
export function sampleMotion(plan: import('@anima/player-ui/propActions').PropActionMotion, elapsedS: number) {
  let time = Math.max(0, elapsedS);
  const y = plan.floor_y ?? plan.access.y;
  const yawOf = (a: Point, b: Point) => Math.atan2(b[0] - a[0], b[1] - a[1]) * 180 / Math.PI;
  const sample = (phase: string, point: Point, yaw: number) => ({ phase, x: point[0], y, z: point[1], yaw });
  const departure = plan.departure;
  if (departure?.exit_clip && departure.exit_s > 0) {
    if (time < departure.exit_s) {
      const t = time / departure.exit_s, a = departure.seat, b = departure.stand;
      return sample('departure', [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t], yawOf(a, b));
    }
    time -= departure.exit_s;
  }
  const points = plan.waypoints;
  for (let i = departure ? 2 : 1; i < points.length; i++) {
    const a = points[i - 1], b = points[i];
    const length = Math.hypot(b[0] - a[0], b[1] - a[1]);
    if (!length) continue;
    const yaw = yawOf(a, b);
    if (plan.paces_m_s_real === null) return sample('frozen', a, yaw);
    const pace = plan.paces_m_s_real[i - 1];
    if (pace === null) continue;
    if (!(pace > 0)) return sample('frozen', a, yaw);
    const seconds = length / pace;
    if (time < seconds) {
      const t = time / seconds;
      return sample('walking', [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t], yaw);
    }
    time -= seconds;
  }
  if (plan.paces_m_s_real === null) {
    const point = departure?.stand ?? points[0] ?? [plan.access.x, plan.access.z];
    return sample('frozen', point, plan.access.yaw);
  }
  if (plan.entry?.mode === 'bridge' && time < plan.entry.duration_s)
    return { phase: 'entry', ...plan.access };
  const { x, y: anchorY, z, yaw } = plan.anchor;
  return { phase: 'arrived', x, y: anchorY, z, yaw };
}

/** Entry time is measured from the end of departure and every walked leg. */
export function motionEntrySeconds(plan: import('@anima/player-ui/propActions').PropActionMotion, elapsedS: number): number {
  let seconds = plan.departure?.exit_clip ? Math.max(0, plan.departure.exit_s) : 0;
  for (let i = plan.departure ? 2 : 1; i < plan.waypoints.length; i++) {
    const a = plan.waypoints[i - 1], b = plan.waypoints[i], pace = plan.paces_m_s_real?.[i - 1];
    if (pace != null && pace > 0) seconds += Math.hypot(b[0] - a[0], b[1] - a[1]) / pace;
  }
  return Math.max(0, elapsedS - seconds);
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
    withdraw(journey: string | null | undefined) { if (journey) withdrawn.add(journey); },
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

/** Only the same HTTP mutation releases its preparation pause. A returned
 * answer supplies authority immediately; uncertain transport needs fresh state. */
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
