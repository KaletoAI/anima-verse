/**
 * The CHANNEL READOUT REPORTS to the server (`POST /play/scene/readouts`, plan pair scene Task 5): the server keeps the
 * latest report per (scene, receiver, channel, entering) and hands it to the packages on every beat of the scene
 * (`pose_scene.readouts`). The client only MEASURES; what the numbers mean is the server's (and a package's).
 *
 * Fed with every frame's raw readouts (`NpcManager.tickSecondary`, the same ones the HUD bus gets throttled,
 * `channelReadouts.ts`), the reporter keeps one window per key (the receiver's scene id from `sceneOf` + the readout
 * key) and sends, at most once per `REPORT_INTERVAL_MS` per key:
 *
 * - `insertion_of_depth` / `part_radius_m` = the MEANS over the window's frames (`insertionOfDepth`, `partRadiusM`);
 * - `rest_radius_m` / `depth_m` = the window's LAST frame (`restRadiusM`, `depthM`);
 * - `reaches` = how many times `insertionOfDepth >= 1` STARTED in the window — an edge from below 1 (or from not
 *   engaged) to at least 1. The edge state outlives the window (a reach across a window boundary counts once) and
 *   resets when the key is missing from a frame (the part came out).
 *
 * A window opens with its key's first frame and is sent with the first frame (that key's or any other's) at least
 * `intervalMs` after it opened — so a key that vanished still sends what it gathered. One send per scene and frame,
 * all its due rows together. Readouts whose receiver plays in no scene (`sceneOf` = '') are never reported.
 *
 * Pure (no DOM, no `three`, no fetch): `send` and the clock come from the caller.
 */
import type { ChannelReadout } from '@anima/scene-render';

/** One row of a report (the route's body). */
export interface ReadoutReportRow {
  receiver: string;
  channel: string;
  entering: string;
  insertion_of_depth: number;
  part_radius_m: number;
  rest_radius_m: number;
  depth_m: number;
  reaches: number;
}

/** The body of `POST /play/scene/readouts`. */
export interface ReadoutReport {
  scene_id: string;
  readouts: ReadoutReportRow[];
}

/** One report per key and second. */
export const REPORT_INTERVAL_MS = 1000;

interface Window {
  sceneId: string; receiver: string; channel: string; entering: string;
  start: number; n: number; sumDepthShare: number; sumPartR: number;
  restR: number; depth: number; reaches: number;
}

/** A reporter: call it every frame with that frame's readouts and the clock; it calls `send` as the module docstring
 *  says. `sceneOf(receiver)` = the scene id the receiving figure plays in ('' = none). */
export function createReadoutReporter(send: (report: ReadoutReport) => void, sceneOf: (receiver: string) => string,
  intervalMs = REPORT_INTERVAL_MS): (readouts: readonly ChannelReadout[], nowMs: number) => void {
  const windows = new Map<string, Window>();
  /** Keys whose part is at or past the bottom in the last frame they were in. */
  let reached = new Set<string>();
  return (readouts, nowMs) => {
    if (!readouts.length && !windows.size && !reached.size) return;
    const nowReached = new Set<string>();
    for (const r of readouts) {
      const sceneId = sceneOf(r.receiver);
      if (!sceneId) continue;
      const key = `${sceneId}|${r.receiver}|${r.channel}|${r.entering}`;
      let w = windows.get(key);
      if (!w) {
        w = { sceneId, receiver: r.receiver, channel: r.channel, entering: r.entering, start: nowMs, n: 0,
          sumDepthShare: 0, sumPartR: 0, restR: 0, depth: 0, reaches: 0 };
        windows.set(key, w);
      }
      w.n += 1;
      w.sumDepthShare += r.insertionOfDepth;
      w.sumPartR += r.partRadiusM;
      w.restR = r.restRadiusM;
      w.depth = r.depthM;
      if (r.insertionOfDepth >= 1) {
        if (!reached.has(key)) w.reaches += 1;
        nowReached.add(key);
      }
    }
    reached = nowReached;
    let due: Map<string, ReadoutReportRow[]> | null = null;
    for (const [key, w] of windows) {
      if (nowMs - w.start < intervalMs) continue;
      windows.delete(key);
      due ??= new Map();
      const rows = due.get(w.sceneId) ?? [];
      rows.push({ receiver: w.receiver, channel: w.channel, entering: w.entering,
        insertion_of_depth: w.sumDepthShare / w.n, part_radius_m: w.sumPartR / w.n,
        rest_radius_m: w.restR, depth_m: w.depth, reaches: w.reaches });
      due.set(w.sceneId, rows);
    }
    if (due) for (const [sceneId, rows] of due) send({ scene_id: sceneId, readouts: rows });
  };
}
