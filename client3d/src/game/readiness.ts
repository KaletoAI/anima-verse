/** Renderer-free readiness gates; each pin belongs to exactly one operation. */
export type ReadinessOwner = 'approach' | 'teleport' | 'entry';
export interface ReadinessDeps {
  placeAt(x: number, z: number): string | null;
  isReady(id: string): boolean;
  pin(id: string, owner: ReadinessOwner): void;
  release(id: string, owner: ReadinessOwner): void;
}
export interface PendingSnap { x: number; z: number; id: string }
export interface ReadinessState {
  approachPin: string | null;
  pendingSnap: PendingSnap | null;
}
export function holdFor(deps: ReadinessDeps, state: ReadinessState, x: number, z: number): boolean {
  const id = deps.placeAt(x, z);
  const held = id !== null && !deps.isReady(id) ? id : null;
  if (state.approachPin && state.approachPin !== held) deps.release(state.approachPin, 'approach');
  state.approachPin = held;
  if (held) deps.pin(held, 'approach');
  return held !== null;
}
/** End only the walking approach; all other pin owners retain their holds. */
export function clearApproach(deps: ReadinessDeps, state: ReadinessState): void {
  if (state.approachPin) deps.release(state.approachPin, 'approach');
  state.approachPin = null;
}
export function clearSnap(deps: ReadinessDeps, state: ReadinessState): void {
  if (state.pendingSnap) deps.release(state.pendingSnap.id, 'teleport');
  state.pendingSnap = null;
}
export function holdSnap(deps: ReadinessDeps, state: ReadinessState, snap: PendingSnap): void {
  clearApproach(deps, state);
  clearSnap(deps, state);
  state.pendingSnap = snap;
  deps.pin(snap.id, 'teleport');
}
export function trySnap(deps: ReadinessDeps, snap: PendingSnap): boolean {
  return deps.isReady(snap.id);
}
export interface EntryDeps {
  requestNear(id: string): void;
  release(id: string, owner: 'entry'): void;
  settled(id: string): Promise<void>;
  sleep(ms: number): Promise<void>;
  isReady(id: string): boolean;
  stillValid(key: string): boolean;
  exists(id: string): boolean;
  canProgress(id: string): boolean;
}
export async function enterWhenReady(deps: EntryDeps, id: string, key: string): Promise<boolean> {
  try {
    deps.requestNear(id);
    for (;;) {
      await Promise.race([deps.settled(id), deps.sleep(1000)]);
      if (!deps.exists(id) || !deps.stillValid(key)) return false;
      if (deps.isReady(id)) return true;
      if (!deps.canProgress(id)) return false;
    }
  } finally {
    deps.release(id, 'entry');
  }
}

/** Only the avatar waits for complete arrival geometry; NPC LOD stays independent. */
export function avatarWaitsForPlace(isAvatar: boolean, locationId: string,
  resident: { ring: string; ready: boolean } | undefined): boolean {
  return isAvatar && !!locationId && (resident?.ring !== 'near' || resident.ready !== true);
}
