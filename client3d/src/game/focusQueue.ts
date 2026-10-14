export interface FocusJob {
  key?: string;
  priority?: 'avatar' | 'normal';
  distance: () => number;
  run: () => Promise<unknown>;
}
export interface FocusQueue {
  push(job: FocusJob): Promise<'done' | 'cancelled'>;
  cancel(key: string): boolean;
  size(): number;
  active(): number;
}

export function createFocusQueue(opts: { max: number }): FocusQueue {
  const waiting: Array<FocusJob & { seq: number; resolve: (r: 'done' | 'cancelled') => void }> = [];
  let running = 0, seq = 0, scheduled = false;
  const pick = () => {
    let best = 0;
    for (let i = 1; i < waiting.length; i++) {
      const a = waiting[i], b = waiting[best];
      const pa = a.priority === 'avatar' ? 0 : 1, pb = b.priority === 'avatar' ? 0 : 1;
      const rawDa = a.distance(), rawDb = b.distance();
      const da = Number.isNaN(rawDa) ? Infinity : rawDa;
      const db = Number.isNaN(rawDb) ? Infinity : rawDb;
      if (pa !== pb ? pa < pb : (da !== db ? da < db : a.seq < b.seq)) best = i;
    }
    return waiting.splice(best, 1)[0];
  };
  const pump = () => {
    scheduled = false;
    while (running < opts.max && waiting.length) {
      const j = pick(); running++;
      Promise.resolve().then(j.run).catch(() => {}).finally(() => {
        running--; j.resolve('done'); pump();
      });
    }
  };
  return {
    push(job) {
      return new Promise<'done' | 'cancelled'>((resolve) => {
        waiting.push({ ...job, seq: seq++, resolve });
        if (!scheduled) { scheduled = true; queueMicrotask(pump); }
      });
    },
    cancel(key) {
      const i = waiting.findIndex(w => w.key === key);
      if (i < 0) return false;
      const [w] = waiting.splice(i, 1); w.resolve('cancelled'); return true;
    },
    size: () => waiting.length,
    active: () => running,
  };
}
