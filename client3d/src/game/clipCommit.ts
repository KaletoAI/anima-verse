export interface ClipSource {
  kind: string; set: string; url: string; loop?: boolean; rootMotion?: boolean;
}
export interface ClipResult<C> { clip: C | null }
export interface CommitOps<C> {
  setFlags(c: C, s: ClipSource): void;
  isPair(kind: string): boolean;
  pairRoot(c: C): unknown;
  rename(c: C, kind: string): C;
}

/** Downloads may finish in any order; listing order owns precedence. */
export function commitInListOrder<C>(sources: ClipSource[], results: ClipResult<C>[], ops: CommitOps<C>) {
  const index = new Map<string, Map<string, C>>();
  const pairRoots = new Map<string, unknown>();
  sources.forEach((s, i) => {
    const r = results[i];
    if (!r || !r.clip) return;
    const clip = ops.rename(r.clip, s.kind);
    ops.setFlags(clip, s);
    if (ops.isPair(s.kind)) pairRoots.set(s.kind, ops.pairRoot(clip));
    if (!index.has(s.kind)) index.set(s.kind, new Map());
    const bySet = index.get(s.kind)!;
    if (!bySet.has(s.set)) bySet.set(s.set, clip);
  });
  return { index, pairRoots };
}
