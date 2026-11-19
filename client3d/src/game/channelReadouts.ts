/**
 * The CHANNEL READOUTS as live values of the game (no UI yet): after every phase B (`NpcManager.tickSecondary`) the
 * receiving figures' readouts (`FigureRuntime.channelReadouts`, `@anima/scene-render` `channelReadout.ts`: how far
 * the entering part is in, how much it stretches the channel, k) are collected — named by the receiving figure —
 * and published on the HUD bus (`setChannelReadouts`):
 *
 * - THROTTLED: at most one publication per `READOUT_INTERVAL_MS` (100 ms = 10 Hz);
 * - only while something is engaged: frames without a readout publish nothing — except the FINAL `null` once the
 *   last engagement is gone (at the first frame the interval allows);
 * - a publication carries every engaged readout of that frame (raw, unsmoothed) and the keys
 *   (`channelReadoutKey`) released since the previous publication.
 *
 * Pure (no DOM, no `three`): `createReadoutPublisher` gets the clock from its caller.
 */
import { channelReadoutKey, type ChannelReadout } from '@anima/scene-render';

/** The live state the bus carries: the readouts of one frame and what was released before it; null = nothing engaged. */
export interface ChannelReadoutState {
  /** The caller's clock at publication (ms). */
  at: number;
  readouts: readonly ChannelReadout[];
  /** Keys (`channelReadoutKey`) that were published before and are gone now. */
  released: readonly string[];
}

/** 10 Hz. */
export const READOUT_INTERVAL_MS = 100;

/** A publisher: call it every frame with that frame's readouts and the clock; it calls `publish` as the module
 *  docstring says. */
export function createReadoutPublisher(publish: (state: ChannelReadoutState | null) => void,
  intervalMs = READOUT_INTERVAL_MS): (readouts: readonly ChannelReadout[], nowMs: number) => void {
  let last = -Infinity;
  let shown: Set<string> | null = null;
  return (readouts, nowMs) => {
    if (!readouts.length && !shown) return;
    if (nowMs - last < intervalMs) return;
    last = nowMs;
    if (!readouts.length) {
      shown = null;
      publish(null);
      return;
    }
    const keys = new Set(readouts.map(channelReadoutKey));
    const released = shown ? [...shown].filter((k) => !keys.has(k)) : [];
    shown = keys;
    publish({ at: nowMs, readouts: [...readouts], released });
  };
}

