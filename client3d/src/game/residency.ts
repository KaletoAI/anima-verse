// Import-free state machine: adapters own mounts and their rollback.
type Ring = 'near' | 'far' | 'gone';
export type StepResult = 'ok' | 'aborted' | 'failed';
export interface ResidencySteps<P> {
  up(id: string, p: P, from: 'gone' | 'far', alive: () => boolean): Promise<StepResult>;
  down(id: string, p: P, from: 'near' | 'far'): void;
}
// Bounded retries tolerate temporary fetch failures without a new ring change.
export const RETRY_MS = [5000, 10000, 20000, 40000, 60000];
export interface ResidencyDriver<P> {
  want(id: string, p: P, ring: Ring, distance: () => number): void;
  ring(id: string): Ring;
  target(id: string): Ring;
  settled(id: string): Promise<void>;
  rebuild(id: string, p: P): void;
  drop(id: string): void;
  hasJob(id: string): boolean;
}
export function createResidencyDriver<P>(steps: ResidencySteps<P>,
  queue: { push(job: { key?: string; distance: () => number; run: () => Promise<unknown> }): Promise<unknown> },
  timers: { setTimeout(fn: () => void, ms: number): unknown; clearTimeout(h: unknown): void }
): ResidencyDriver<P> {
  interface Entry {
    id: string; p: P; mounted: P; ring: Ring; target: Ring; gen: number;
    stale: boolean; dropped: boolean; job?: Promise<void>; retry?: unknown;
    failures: number; distance: () => number; waiters: Array<() => void>;
    previous?: Promise<void>; finished: Promise<void>; finish: () => void;
  }
  const entries = new Map<string, Entry>();
  // A successor waits for the entire lifecycle, including follow-up teardown jobs.
  const tails = new Map<string, Promise<void>>();
  const rank = { gone: 0, far: 1, near: 2 };
  const clearRetry = (e: Entry) => {
    if (e.retry !== undefined) timers.clearTimeout(e.retry);
    e.retry = undefined;
  };
  const notify = (e: Entry) => {
    if (e.job || e.stale || e.ring !== e.target) return;
    for (const resolve of e.waiters.splice(0)) resolve();
  };
  const finalize = (e: Entry) => {
    if (e.job || e.stale || e.ring !== e.target) return;
    if (e.ring === 'gone') {
      if (entries.get(e.id) === e) entries.delete(e.id);
      if (tails.get(e.id) === e.finished) tails.delete(e.id);
      e.finish();
    }
    notify(e);
  };
  function schedule(e: Entry): void {
    if (e.job) return;
    let finish!: () => void;
    e.job = new Promise<void>(r => { finish = r; });
    // Chain before queueing so a waiting successor does not occupy a queue slot.
    void (async () => {
      if (e.previous) await e.previous;
      let failedGen: number | undefined;
      await queue.push({ key: `ring:${e.id}`, distance: () => e.distance(), run: async () => {
        while (true) {
          if (e.stale || e.dropped) {
            while (e.ring !== 'gone') {
              const from = e.ring;
              steps.down(e.id, e.mounted, from);
              e.ring = from === 'near' ? 'far' : 'gone';
            }
            e.stale = false;
            if (e.dropped) break;
          }
          if (e.ring === e.target) break;
          if (rank[e.ring] > rank[e.target]) {
            const from = e.ring as 'near' | 'far';
            steps.down(e.id, e.mounted, from);
            e.ring = from === 'near' ? 'far' : 'gone';
            continue;
          }
          const gen = e.gen, p = e.p, from = e.ring as 'gone' | 'far';
          const alive = () => entries.get(e.id) === e && !e.dropped && e.gen === gen;
          // focusQueue resolves with 'done' even on failure: result belongs here.
          let result: StepResult;
          try { result = await steps.up(e.id, p, from, alive); }
          catch { result = 'failed'; }
          if (result === 'failed') {
            if (alive()) { failedGen = e.gen; break; }
            continue;
          }
          if (result === 'aborted') continue;
          e.mounted = p;
          e.ring = from === 'gone' ? 'far' : 'near';
          e.failures = 0;
        }
      }});
      e.job = undefined;
      if (e.stale || e.ring !== e.target) {
        if (failedGen === e.gen && !e.stale && !e.dropped && rank[e.target] > rank[e.ring]) {
          const ms = RETRY_MS[Math.min(e.failures++, RETRY_MS.length - 1)];
          e.retry = timers.setTimeout(() => { e.retry = undefined; schedule(e); }, ms);
        } else {
          // A wish may arrive after run() returns, while push() is settling.
          schedule(e);
        }
      }
      finalize(e);
      finish();
    })();
  }
  return {
    want(id, p, target, distance) {
      let e = entries.get(id);
      if (!e || e.dropped) {
        if (target === 'gone') return;
        let finish!: () => void;
        const finished = new Promise<void>(resolve => { finish = resolve; });
        e = {id,p,mounted:p,ring:'gone',target,gen:0,stale:false,dropped:false,failures:0,distance,waiters:[],
          previous:tails.get(id),finished,finish};
        tails.set(id, finished);
        entries.set(id,e);
      } else {
        e.p = p; e.distance = distance;
        e.gen++;
        if (e.target !== target) { clearRetry(e); e.target = target; }
      }
      if (e.retry === undefined && (e.ring !== e.target || e.stale)) schedule(e);
      finalize(e);
    },
    ring: id => entries.get(id)?.ring ?? 'gone',
    target: id => entries.get(id)?.target ?? 'gone',
    hasJob: id => !!entries.get(id)?.job,
    settled(id) {
      const e = entries.get(id);
      if (!e || (!e.job && !e.stale && e.ring === e.target)) return Promise.resolve();
      return new Promise(resolve => e.waiters.push(resolve));
    },
    rebuild(id,p) {
      const e = entries.get(id);
      if (!e || e.dropped) return;
      e.p = p; e.gen++; e.stale = true; clearRetry(e); schedule(e);
    },
    drop(id) {
      const e = entries.get(id);
      if (!e) return;
      e.gen++; e.dropped = true; e.target = 'gone'; clearRetry(e);
      if (e.ring !== e.target || e.stale) schedule(e);
      finalize(e);
    },
  };
}
