/** Pure measurement statistics ported from 183d873; seconds are wall time. */
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

