/**
 * Render bench — the SAME camera drive on the same scene for both renderers,
 * numbers instead of impressions (plan-webgpu-mvp.md Task 6). Nothing here
 * runs unless asked:
 *
 *   ?bench=auto[&secs=20][&r=40..12][&warm=3]
 *       starts a run after the first rendered frame + `warm` seconds of
 *       warm-up (shader builds, tile streaming), then drives the camera:
 *       target stays, yaw runs 0..2π once, distance goes r0 -> r1 -> r0 as a
 *       cosine. Position the target first with the existing `&goto=<loc>` of
 *       debug3d, or by hand — the bench never moves the target.
 *   window.__bench.start(secs?, r0?, r1?)     the same by hand (e.g. after
 *       entering a location for the detail-scene case); `.last` holds the
 *       last summary; a `<pre id="bench">` shows it in the DOM.
 *
 * Per frame it records the frame delta, the JS time of the frame
 * (`engine.lastFrameCpuMs`, render() call included — CPU only in BOTH paths,
 * because WebGPU's render() returns after submission), the GPU time where the
 * renderer can tell (WebGPU renderer with timestamp queries; resolved once per
 * frame here — three only fills `info.render.timestamp` on
 * `resolveTimestampsAsync()`), draw calls and triangles.
 *
 * Research notes: FPS is derived from the frame TIME (frames / seconds), never
 * the mean of per-frame rates; median/P95 instead of means, because a stutter
 * shows in P95 and hides in a mean; `compileAsync(scene, camera)` before the
 * warm-up takes the shader builds out of the measured window (both renderers
 * have it). The classic WebGLRenderer has no timestamp query pool — GPU time
 * is `null` there, never a misleading 0.
 */
import type { Engine } from '../scene/engine';
import { gpuFrameMs } from './backend';

export interface BenchSample {
  dt: number;
  cpuMs: number;
  gpuMs: number | null;
  calls: number;
  tris: number;
}

export interface BenchSummary {
  frames: number;
  seconds: number;
  fpsMean: number;
  frameMsMedian: number;
  frameMsP95: number;
  cpuMsMedian: number;
  cpuMsP95: number;
  gpuMsMedian: number | null;
  callsMedian: number;
  trisMedian: number;
}

/** Linear-interpolated percentile of a SORTED ascending list; 0 for empty. */
export function percentile(sorted: number[], p: number): number {
  const n = sorted.length;
  if (n === 0) return 0;
  if (n === 1) return sorted[0];
  const rank = (Math.min(Math.max(p, 0), 100) / 100) * (n - 1);
  const lo = Math.floor(rank);
  const hi = Math.min(lo + 1, n - 1);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (rank - lo);
}

const asc = (a: number, b: number) => a - b;

export function summarize(samples: BenchSample[]): BenchSummary {
  const frames = samples.length;
  const seconds = samples.reduce((s, x) => s + x.dt, 0);
  const frameMs = samples.map((x) => x.dt * 1000).sort(asc);
  const cpu = samples.map((x) => x.cpuMs).sort(asc);
  const gpu = samples.map((x) => x.gpuMs).filter((v): v is number => v !== null).sort(asc);
  const calls = samples.map((x) => x.calls).sort(asc);
  const tris = samples.map((x) => x.tris).sort(asc);
  return {
    frames,
    seconds,
    fpsMean: seconds > 0 ? frames / seconds : 0,
    frameMsMedian: percentile(frameMs, 50),
    frameMsP95: percentile(frameMs, 95),
    cpuMsMedian: percentile(cpu, 50),
    cpuMsP95: percentile(cpu, 95),
    gpuMsMedian: gpu.length ? percentile(gpu, 50) : null,
    callsMedian: percentile(calls, 50),
    trisMedian: percentile(tris, 50),
  };
}

/** The camera drive at progress t (0..1): one full turn, distance r0->r1->r0. */
export function driveAt(t: number, r0: number, r1: number): { yaw: number; dist: number } {
  const k = Math.min(Math.max(t, 0), 1);
  return {
    yaw: 2 * Math.PI * k,
    dist: r1 + (r0 - r1) * (0.5 + 0.5 * Math.cos(2 * Math.PI * k)),
  };
}

interface BenchApi {
  start(secs?: number, r0?: number, r1?: number): void;
  last: (BenchSummary & Record<string, unknown>) | null;
  running: boolean;
}

/** Wire the bench into the engine; a no-op unless `?bench=` is set or
 *  `window.__bench.start()` is called later. */
export function initBench(engine: Engine): void {
  const params = new URLSearchParams(location.search);
  const api: BenchApi = { start, last: null, running: false };
  (window as unknown as { __bench: BenchApi }).__bench = api;

  let samples: BenchSample[] = [];
  let runSecs = 0, elapsed = 0, r0 = 40, r1 = 12, warmLeft = 0;
  let phase: 'idle' | 'warm' | 'run' = 'idle';
  let yaw0 = 0;
  const canResolve = 'resolveTimestampsAsync' in engine.renderer;

  function start(secs = 20, radius0 = 40, radius1 = 12, warm = 3): void {
    if (phase !== 'idle') return;
    runSecs = secs; r0 = radius0; r1 = radius1; warmLeft = warm;
    samples = []; elapsed = 0; yaw0 = engine.yaw;
    api.running = true;
    phase = 'warm';
    // Shader builds out of the window: both renderers offer compileAsync.
    const r = engine.renderer as { compileAsync?: (s: unknown, c: unknown) => Promise<unknown> };
    void r.compileAsync?.(engine.scene, engine.camera);
    console.info(`[bench] warm-up ${warm}s, then ${secs}s drive r=${radius0}..${radius1} on ${engine.active}`);
  }

  function finish(): void {
    phase = 'idle';
    api.running = false;
    const summary = summarize(samples);
    const dpr = Math.min(window.devicePixelRatio, 2);
    api.last = {
      backend: engine.active,
      ua: navigator.userAgent,
      dpr,
      size: `${innerWidth}x${innerHeight}`,
      r: `${r0}..${r1}`,
      ...summary,
    };
    console.info('[bench] result', api.last);
    console.table(summary);
    let el = document.getElementById('bench') as HTMLPreElement | null;
    if (!el) {
      el = document.createElement('pre');
      el.id = 'bench';
      el.style.cssText = 'position:fixed;right:4px;bottom:4px;z-index:9999;'
        + 'background:rgba(0,0,0,0.8);color:#ffd;font:11px monospace;padding:6px;'
        + 'max-width:48vw;white-space:pre-wrap;pointer-events:auto;user-select:text;';
      document.body.appendChild(el);
    }
    el.textContent = JSON.stringify(api.last, null, 1);
  }

  engine.addFrameHook((dt) => {
    if (phase === 'idle') return;
    if (phase === 'warm') {
      warmLeft -= dt;
      if (warmLeft <= 0) { phase = 'run'; elapsed = 0; }
      return;
    }
    // record the frame that was just measured (dt = its delta), then drive
    const gl = engine.renderer;
    samples.push({
      dt,
      cpuMs: engine.lastFrameCpuMs,
      gpuMs: gpuFrameMs(gl),
      calls: engine.lastDrawCalls,
      tris: engine.lastTriangles,
    });
    if (canResolve) {
      // fills info.render.timestamp for a later frame; three coalesces
      // overlapping resolves itself (pendingResolve)
      void (gl as { resolveTimestampsAsync(): Promise<number> }).resolveTimestampsAsync();
    }
    elapsed += dt;
    const t = Math.min(elapsed / runSecs, 1);
    const d = driveAt(t, r0, r1);
    engine.yaw = engine.targetYaw = yaw0 + d.yaw;
    engine.dist = engine.targetDist = d.dist;
    if (elapsed >= runSecs) finish();
  });

  if (params.get('bench') === 'auto') {
    const secs = parseFloat(params.get('secs') || '20') || 20;
    const warm = parseFloat(params.get('warm') || '3') || 3;
    const rr = (params.get('r') || '40..12').split('..').map(parseFloat);
    const radius0 = Number.isFinite(rr[0]) ? rr[0] : 40;
    const radius1 = Number.isFinite(rr[1]) ? rr[1] : 12;
    // after the first rendered frame, so the world had a chance to appear
    let armed = false;
    engine.addFrameHook(() => {
      if (armed) return;
      armed = true;
      start(secs, radius0, radius1, warm);
    });
  }
}
