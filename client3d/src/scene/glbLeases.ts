/** Shared templates: active leases own GPU residency; idle templates occupy a CPU LRU. */
export interface LeaseDeps<T> {
  load(url: string, signal: AbortSignal): Promise<T | null>;
  disposeGpu(template: T): void;
  dropCpu(template: T): void;
  bytes(template: T): number;
  budgetBytes: number;
}
export interface Lease<T> { readonly template: T; release(): void }
export interface LeasePool<T> {
  lease(url: string, signal?: AbortSignal): Promise<Lease<T> | null>;
  stats(): { held: number; loading: number; lruCount: number; lruBytes: number };
}
export function createLeasePool<T>(deps: LeaseDeps<T>): LeasePool<T> {
  type Waiter = { deliver(template: T | null): void };
  type Entry = { url: string; held: number; template: T | null; controller: AbortController;
    loading: boolean; waiters: Set<Waiter>; bytes: number };
  const entries = new Map<string, Entry>();
  const lru = new Map<string, Entry>();
  let lruBytes = 0;
  function idle(entry: Entry): void {
    if (entry.held || entry.loading || entry.template === null) return;
    deps.disposeGpu(entry.template);
    entry.bytes = deps.bytes(entry.template);
    lru.set(entry.url, entry); lruBytes += entry.bytes;
    while (lruBytes > deps.budgetBytes && lru.size) {
      const oldest = lru.values().next().value!;
      lru.delete(oldest.url); lruBytes -= oldest.bytes;
      entries.delete(oldest.url); deps.dropCpu(oldest.template!);
    }
  }
  function relinquish(entry: Entry): void {
    entry.held--;
    if (!entry.held && entry.loading) entry.controller.abort();
    else if (!entry.held) idle(entry);
  }
  async function load(entry: Entry): Promise<void> {
    const controller = entry.controller;
    let template: T | null;
    try { template = await deps.load(entry.url, controller.signal); }
    catch { template = null; }
    if (template === null && controller.signal.aborted && entry.held > 0) {
      // A new waiter arrived before cancellation settled. It needs a fresh job.
      entry.controller = new AbortController();
      void load(entry); return;
    }
    entry.loading = false; entry.template = template;
    if (template === null) entries.delete(entry.url);
    for (const waiter of [...entry.waiters]) waiter.deliver(template);
    if (template !== null && entry.held === 0) idle(entry);
  }
  return {
    lease(url, signal) {
      if (signal?.aborted) return Promise.resolve(null);
      let entry = entries.get(url);
      let fresh = false;
      if (!entry) {
        entry = { url, held: 0, template: null, loading: true,
          controller: new AbortController(), waiters: new Set(), bytes: 0 };
        entries.set(url, entry); fresh = true;
      }
      const current = entry;
      if (lru.delete(url)) lruBytes -= current.bytes;
      current.held++;
      const pending = new Promise<Lease<T> | null>((resolve) => {
        let settled = false;
        const clean = () => { current.waiters.delete(waiter); signal?.removeEventListener('abort', abort); };
        const abort = () => {
          if (settled) return;
          settled = true; clean(); relinquish(current); resolve(null);
        };
        const waiter: Waiter = { deliver(template) {
          if (settled) return;
          settled = true; clean();
          if (template === null) { current.held--; resolve(null); return; }
          let released = false;
          resolve({ template, release() {
            if (released) return;
            released = true; relinquish(current);
          } });
        } };
        if (current.loading) {
          current.waiters.add(waiter); signal?.addEventListener('abort', abort, { once: true });
        } else waiter.deliver(current.template);
      });
      if (fresh) void load(current);
      return pending;
    },
    stats() {
      let held = 0, loading = 0;
      for (const entry of entries.values()) { held += entry.held; if (entry.loading) loading++; }
      return { held, loading, lruCount: lru.size, lruBytes };
    },
  };
}
