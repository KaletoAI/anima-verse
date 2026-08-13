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
