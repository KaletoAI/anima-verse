export interface ClipSource {
  kind: string; set: string; url: string; loop?: boolean; loopCount?: number | null; rootMotion?: boolean;
  rootMotionMode?: string;
  heightOffsets?: Partial<Record<'ground' | 'seat' | 'lie', number>>;
  shift?: readonly [number, number] | null;
  /** Ruling A129: a pair's partner-B turn [tilt, roll] degrees. */
  partnerTurn?: [number, number] | null;
  /** Ruling A165: a pair's partner-B yaw about its own vertical axis, degrees. */
  partnerYaw?: number | null;
  /** Ruling A139: the clip's contact relations ([] / absent = automatic). */
  contacts?: { part: string; at: string; target: 'channel' | 'mouth' | 'hand_left' | 'hand_right' | 'none' }[] | null;
  /** Ruling A145: the clip's bend limits as listed (`bend_limits.limits`). */
  bend?: unknown;
  /** Ruling A158: the clip's direct root angle as listed (`root_angle`). */
  rootAngle?: unknown;
  /** Owner decision 2026-11-20 (scene-render `pairScale.ts`): the pair clip's contact pivot as listed (`pair_pivot_cm`). */
  pivot?: unknown;
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

/** The root of every pair/group half the committed `index` holds, keyed EXACTLY like it — kind, then set — so the
 *  root path always belongs to the very file a figure plays for its set (a per-kind map let the last set listed
 *  supply the path of every set). `commitInListOrder`'s own per-kind `pairRoots` is not read by the client. */
export function pairRootsOf<C, R>(index: ReadonlyMap<string, ReadonlyMap<string, C>>, isPair: (kind: string) => boolean,
  pairRoot: (c: C) => R): Map<string, Map<string, R>> {
  const out = new Map<string, Map<string, R>>();
  for (const [kind, bySet] of index) {
    if (!isPair(kind)) continue;
    const roots = new Map<string, R>();
    for (const [set, clip] of bySet) roots.set(set, pairRoot(clip));
    out.set(kind, roots);
  }
  return out;
}

/** The root of half `kind` for a figure whose set chain is `chain` (the character's sets, then `''` — the order
 *  `FigureLibrary.clipsFor` picks the file by), or undefined when no set of the chain has that half. */
export function pairRootFor<R>(roots: ReadonlyMap<string, ReadonlyMap<string, R>>, kind: string,
  chain: readonly string[]): R | undefined {
  const bySet = roots.get(kind);
  if (!bySet) return undefined;
  for (const set of chain) {
    const r = bySet.get(set);
    if (r !== undefined) return r;
  }
  return undefined;
}
