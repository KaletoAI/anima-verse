/**
 * Which animation kinds a rig ends up WITHOUT, and which rigs may stand in for
 * a character at all — the two decisions around the shared clip library that
 * are pure bookkeeping and therefore checkable without `three`, a DOM or a
 * GPU (`client3d/scripts/smoke_clip_coverage.mjs`).
 *
 * Everything else about clips is skeleton maths and lives in `figures.ts`.
 * This module knows no bones: it is handed the kind NAMES the library offered
 * and the kind names a model can actually play, and it is handed models that
 * already carry the verdict "the library fits this skeleton".
 */

/**
 * The library kinds a model cannot play — offered minus bound, lower-cased,
 * de-duplicated, sorted.
 *
 * A kind counts as bound when the model carries a clip of that name, whether
 * embedded in the mesh or adapted from the library; the per-kind merge means
 * both sources land in the same namespace. Blank entries are ignored (a clip
 * without a name is no kind).
 */
export function missingClipKinds(offered: readonly string[], bound: readonly string[]): string[] {
  const have = new Set(bound.map((k) => k.trim().toLowerCase()).filter(Boolean));
  const missing = new Set<string>();
  for (const raw of offered) {
    const kind = raw.trim().toLowerCase();
    if (kind && !have.has(kind)) missing.add(kind);
  }
  return [...missing].sort();
}

/**
 * WHICH clip name stands in for a canonical kind — the alias layer of
 * `figures.Figure` (`CLIP_SYNONYMS`), as a rule instead of a loop.
 *
 * `names` are the clip names a model carries, in the order it carries them;
 * `needles` are the aliases of one canonical kind ("lie" → lie, lay, sleep).
 * The answer is `''` when nothing stands in.
 *
 * THE NEEDLE ORDER RANKS, AND INSIDE ONE NEEDLE THE EXACT NAME WINS: a needle
 * takes the clip that IS it before any clip that merely contains it, and only
 * when it finds neither does the next needle get its turn.
 *
 * The substring step is what makes `walk` reach `walking`, and it is also what
 * made the kinds of 2026-08-13 dangerous: since a clip kind is the whole file
 * name (`swim-idle`, `treading-water`), a needle `swim` CONTAINS-matches
 * `swim-idle` — a figure asked to swim would tread water on the spot. With the
 * exact step in front, `swim` takes `swim` whenever that clip exists at all.
 *
 * Ranking by needle rather than by exactness is deliberate: the needles of a
 * kind are ordered by how well they mean it (`lie` before `lay` before
 * `sleep`), so a `laying` clip must still beat an exactly-named `sleep` one —
 * that one was animated on a bed.
 */
export function resolveClipName(names: readonly string[],
                                needles: readonly string[]): string {
  const clean = names.map((n) => n.trim().toLowerCase());
  for (const needle of needles) {
    const hit = clean.find((n) => n === needle) ?? clean.find((n) => n.includes(needle));
    if (hit) return hit;
  }
  return '';
}

/**
 * The fallback rigs a character may be drawn from at random: those the clip
 * library fits, and every one of them otherwise.
 *
 * A rig with a skeleton the library cannot address (Blender bone names against
 * the library's Mixamo ones) can only ever play the handful of kinds baked
 * into its own file — put a swimming character on it and the terrain's
 * `move_anim` falls through to walking. So it does not get picked as long as a
 * rig exists that takes the library. The "otherwise" half is what keeps this
 * from emptying the pool: with no library loaded at all (offline dev run) no
 * rig fits, and a figure that plays its own three clips still beats no figure.
 */
export function animatablePool<T extends { libraryFits: boolean }>(pool: readonly T[]): T[] {
  const fitting = pool.filter((m) => m.libraryFits);
  return fitting.length ? fitting : [...pool];
}
