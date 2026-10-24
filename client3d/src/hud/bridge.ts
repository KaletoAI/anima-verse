/**
 * Versioned, JSON-compatible boundary shared by browser and native hosts.
 *
 * Scene-owned game state travels to the HUD; HUD_OWNED_FIELDS (written by
 * Hud.tsx) travel back. Each endpoint publishes only changes to its own fields
 * and rejects writes to the other endpoint's fields, preventing snapshot echoes
 * from overwriting the independent writer. HudUiState belongs entirely to the
 * HUD, including input ownership and the performance measurement switch.
 *
 * gameActions travel HUD -> scene, uiActions scene -> HUD. Speech is explicitly
 * fire-and-forget here: the sender returns undefined, so the voiceover queue
 * cannot await playback as it does with the in-process speech handler.
 */
import * as bus from './bus';
import type { HudGameState, HudUiState, HudBoot, HudGameActions, HudUiActions, HudRect } from './bus';
import type { MinimapState } from '../game/minimap';
import type { PerfStats } from '../game/perfstats';

export const HUD_BRIDGE_VERSION = 1;
export type ToHud =
  | { v: 1; kind: 'state'; patch: Partial<HudGameState> }
  | { v: 1; kind: 'minimap'; value: MinimapState | null }
  | { v: 1; kind: 'perf'; value: PerfStats | null }
  | { v: 1; kind: 'boot'; value: HudBoot }
  | { v: 1; kind: 'ui'; name: keyof HudUiActions; args: unknown[] };
export type FromHud =
  | { v: 1; kind: 'state'; patch: Partial<HudGameState> }
  | { v: 1; kind: 'action'; name: keyof HudGameActions; args: unknown[] }
  | { v: 1; kind: 'hud'; patch: Partial<HudUiState> };
export interface BridgeTransport {
  send(msg: ToHud | FromHud): void;
  onMessage(fn: (msg: unknown) => void): () => void;
}
const gameNames = ['clearSelection', 'setVolumes', 'speak', 'stopSpeech', 'markResume', 'zoomTo', 'sayBubble',
  'enterEmbodied', 'takeControl', 'exitEmbodied', 'rideElevator', 'rideStairs',
  'enterLocation', 'backToTitle', 'setShowAll', 'applyAudioPrefs', 'applyScatterPrefs',
  'setChatBox'] as const satisfies readonly (keyof HudGameActions)[];
const uiNames = ['openChat', 'toast', 'toggleMenu', 'closeMenu'] as const satisfies readonly (keyof HudUiActions)[];
function reject(msg: unknown): void { console.warn('[hud bridge] Dropped invalid message', msg); }
function valid(msg: unknown): msg is ToHud | FromHud {
  return !!msg && typeof msg === 'object' && 'v' in msg && msg.v === HUD_BRIDGE_VERSION && 'kind' in msg;
}
/** Only declared commands are callable; inherited object properties never are. */
function invoke(actions: HudGameActions | HudUiActions, names: readonly string[], name: string, args: unknown[]): boolean {
  if (!names.includes(name) || !Array.isArray(args)) return false;
  const fn = (actions as Record<string, ((...args: unknown[]) => unknown) | undefined>)[name];
  if (fn) void Promise.resolve(fn(...args)).catch(error => console.warn('[hud bridge] Action failed', error));
  return true;
}
/** Install senders without losing handlers when a transport is disconnected. */
function senders<T extends object>(actions: T, names: readonly (keyof T)[], send: (name: keyof T, args: unknown[]) => void): () => void {
  const cleanups = names.map(name => {
    const previous = actions[name];
    const sender = ((...args: unknown[]) => { send(name, args); }) as T[keyof T];
    actions[name] = sender;
    return () => { if (actions[name] === sender) actions[name] = previous; };
  });
  return () => cleanups.forEach(fn => fn());
}
const gameFields = Object.keys(bus.getGameState()) as (keyof HudGameState)[];
const hudFields = new Set<keyof HudGameState>(bus.HUD_OWNED_FIELDS);
const sceneFields = gameFields.filter(key => !hudFields.has(key));

/** Cache serialized fields before sending: synchronous transports may re-enter
 *  this subscriber when the peer applies a patch from its own writer. */
function statePublisher(t: BridgeTransport, fields: readonly (keyof HudGameState)[]): (force?: boolean) => void {
  const previous = new Map<keyof HudGameState, string | undefined>();
  return (force = false) => {
    const state = bus.getGameState();
    const patch: Partial<HudGameState> = {};
    for (const key of fields) {
      const value = JSON.stringify(state[key]);
      if (force || !previous.has(key) || previous.get(key) !== value) {
        Object.assign(patch, { [key]: state[key] });
        previous.set(key, value);
      }
    }
    if (Object.keys(patch).length) t.send({ v: 1, kind: 'state', patch });
  };
}

/** Drop unauthorized keys independently, preserving legitimate keys in a mixed
 *  patch. One warning per patch identifies all rejected fields. */
function receiveState(patch: Partial<HudGameState>, fields: readonly (keyof HudGameState)[]): void {
  const allowed = new Set<string>(fields);
  const accepted: Partial<HudGameState> = {};
  const dropped: string[] = [];
  for (const key of Object.keys(patch)) {
    if (allowed.has(key)) Object.assign(accepted, { [key]: patch[key as keyof HudGameState] });
    else dropped.push(key);
  }
  if (dropped.length) console.warn('[hud bridge] Dropped state fields not owned by sender', dropped);
  if (Object.keys(accepted).length) bus.setGameState(accepted);
}

/** HUD endpoint: local writers publish independently of incoming scene state. */
export function connectHudSide(t: BridgeTransport): () => void {
  const restore = senders(bus.gameActions, gameNames, (name, args) => t.send({ v: 1, kind: 'action', name, args }));
  const publishState = statePublisher(t, bus.HUD_OWNED_FIELDS);
  let previousUi = '';
  const publish = (force = false) => {
    const patch = bus.getHudUiState();
    const next = JSON.stringify(patch);
    if (force || next !== previousUi) {
      previousUi = next;
      t.send({ v: 1, kind: 'hud', patch });
    }
  };
  let firstMessage = true;
  const off = t.onMessage(msg => {
    if (!valid(msg)) return reject(msg);
    // The host may attach only on iframe load, after our initial publications.
    // Repeat ownership once on its first message, never on every scene update.
    if (firstMessage) {
      firstMessage = false;
      publish(true);
      publishState(true);
    }
    switch (msg.kind) {
      case 'state': receiveState(msg.patch, sceneFields); break;
      case 'minimap': bus.setMinimap(msg.value); break;
      case 'perf': bus.setPerfStats(msg.value); break;
      case 'boot': bus.setBoot(msg.value); break;
      case 'ui': if (!invoke(bus.uiActions, uiNames, msg.name, msg.args)) reject(msg); break;
      default: reject(msg);
    }
  });
  const unsubscribe = bus.subscribeHudUiState(() => publish());
  const unsubscribeState = bus.subscribeGameState(() => publishState());
  publish(); publishState();
  return () => { off(); unsubscribe(); unsubscribeState(); restore(); };
}
/** Scene endpoint: HUD patches update the local bus used by scene handlers. */
export function connectSceneSide(t: BridgeTransport): () => void {
  const restore = senders(bus.uiActions, uiNames, (name, args) => t.send({ v: 1, kind: 'ui', name, args }));
  const off = t.onMessage(msg => {
    if (!valid(msg)) return reject(msg);
    switch (msg.kind) {
      case 'state': receiveState(msg.patch, bus.HUD_OWNED_FIELDS); break;
      case 'action': if (!invoke(bus.gameActions, gameNames, msg.name, msg.args)) reject(msg); break;
      case 'hud': bus.setHudUiState(msg.patch); break;
      default: reject(msg);
    }
  });
  const publishState = statePublisher(t, sceneFields);
  const stores = [
    [bus.subscribeGameState, () => publishState()],
    [bus.subscribeMinimap, () => t.send({ v: 1, kind: 'minimap', value: bus.getMinimap() })],
    [bus.subscribePerfStats, () => t.send({ v: 1, kind: 'perf', value: bus.getPerfStats() })],
    [bus.subscribeBoot, () => t.send({ v: 1, kind: 'boot', value: bus.getBoot() })],
  ] as const;
  const unsubscribes = stores.map(([subscribe, publish]) => { const unsubscribe = subscribe(publish); publish(); return unsubscribe; });
  return () => { off(); unsubscribes.forEach(fn => fn()); restore(); };
}
/** Pin both origin and source; other same-origin frames are not this peer. */
export function postMessageTransport(target: Window, origin: string): BridgeTransport {
  return {
    send: msg => target.postMessage(msg, origin),
    onMessage: fn => {
      const listener = (e: MessageEvent) => { if (e.source === target && e.origin === origin) fn(e.data); };
      window.addEventListener('message', listener);
      return () => window.removeEventListener('message', listener);
    },
  };
}
/** JSON cloning gives tests independent snapshots, like a real wire transport. */
export function loopbackPair(): [BridgeTransport, BridgeTransport] {
  const listeners = [new Set<(msg: unknown) => void>(), new Set<(msg: unknown) => void>()];
  return [0, 1].map(i => ({
    send: (msg: ToHud | FromHud) => { for (const fn of listeners[1 - i]) fn(JSON.parse(JSON.stringify(msg))); },
    onMessage: (fn: (msg: unknown) => void) => { listeners[i].add(fn); return () => { listeners[i].delete(fn); }; },
  })) as [BridgeTransport, BridgeTransport];
}
/** Keep independent surfaces: merging overlapping boxes can swallow canvas gaps. */
export function mergeRects(rects: HudRect[]): HudRect[] { return rects.map(rect => ({ ...rect })); }
export function pointInRects(rects: HudRect[], x: number, y: number): boolean {
  return rects.some(r => x >= r.x && y >= r.y && x < r.x + r.w && y < r.y + r.h);
}
