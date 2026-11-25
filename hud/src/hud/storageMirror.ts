/**
 * The native client's HUD settings across starts (gdCEF only).
 *
 * The native client's Chromium runs with an in-memory profile — the session
 * cookie must never reach a disk cache — so this page's `localStorage` (show
 * all, scatter distances, volumes, dock and chat sizes, …) would be gone at
 * every start. Instead every write is mirrored to Godot through gdCEF's JS
 * binding, `window.godotMethods.hud_storage(json)` — a method of its own, NOT a
 * bridge message, so the bridge protocol and its version stay as they are.
 * Godot keeps the entries per server origin and writes them back into
 * `localStorage` during the login handoff, before this page loads
 * (native/Hud/HudOverlay.cs `HandoffScript`, native/Core/Ui/HudStorage.cs).
 *
 * The mirror wraps `setItem`/`removeItem`/`clear` on the Storage PROTOTYPE:
 * assigning `localStorage.setItem = …` would not replace the method — Storage
 * has a named property setter, so that would store an item called "setItem".
 * Only calls on the given storage are mirrored (sessionStorage shares the
 * prototype), and only after the browser accepted them (a quota error throws
 * before anything is sent). The session never lives in `localStorage` (it is
 * an HttpOnly cookie), so nothing secret can pass here.
 */
import type { GdcefHost } from './bridge';

/** One mirrored call, as a JSON string on the wire. */
export type StorageOp =
  | { op: 'set'; key: string; value: string }
  | { op: 'remove'; key: string }
  | { op: 'clear' };

/** The gdCEF binding method the ops go to. */
export const HUD_STORAGE_METHOD = 'hud_storage';

/** Mirror every write to `target` into `send`; returns the undo (the original methods back). */
export function mirrorStorage(target: Storage, send: (op: StorageOp) => void): () => void {
  const proto = Object.getPrototypeOf(target) as Storage;
  const { setItem, removeItem, clear } = proto;
  proto.setItem = function (this: Storage, key: string, value: string): void {
    setItem.call(this, key, value);
    if (this === target) send({ op: 'set', key: String(key), value: String(value) });
  };
  proto.removeItem = function (this: Storage, key: string): void {
    removeItem.call(this, key);
    if (this === target) send({ op: 'remove', key: String(key) });
  };
  proto.clear = function (this: Storage): void {
    clear.call(this);
    if (this === target) send({ op: 'clear' });
  };
  return () => {
    proto.setItem = setItem;
    proto.removeItem = removeItem;
    proto.clear = clear;
  };
}

/** The sender over gdCEF: one JSON string per op, the binding resolved at use (one warning if it is missing). */
export function gdcefStorageSender(host: GdcefHost = window as unknown as GdcefHost,
  method = HUD_STORAGE_METHOD): (op: StorageOp) => void {
  let warned = false;
  return op => {
    const fn = host.godotMethods?.[method];
    if (fn) { fn(JSON.stringify(op)); return; }
    if (!warned) { warned = true; console.warn('[hud storage] gdCEF binding missing: settings are not kept across starts'); }
  };
}
