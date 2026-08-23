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
 * The FAMILY of an animation kind: everything before the FIRST `-`, trimmed and
 * lower-cased. An empty kind is the idle family.
 *
 *   walk        -> walk        walk-cmu      -> walk
 *   run-fast    -> run         RUN           -> run
 *   swim-idle   -> swim        treading-water-> treading
 *   sit_a       -> sit_a       ''            -> idle
 *
 * WHY IT EXISTS. A kind is authored as a FILE NAME in the shared clip library
 * (`app/core/animation_clips.py`: "the KIND is the semantic category … and is
 * the WHOLE file name without its extension", only a trailing `_<number>`
 * being the take numbering; CLAUDE.md sums the convention up as "the kind the
 * first token of the file name"). So the same motion can arrive under several
 * kinds once it comes from a new source: the pose catalog renamed walking's
 * kind `walk` → `walk-cmu` on 2026-08-24 and every literal `'walk'` in the
 * client stopped matching — a clip-less rig froze mid-step instead of swinging
 * its legs, a rig without a `walk-cmu` take fell to idle instead of its old
 * `walk` clip, and room markers authored `walk` matched nothing at all.
 *
 * The family is the coarse grouping that survives such a rename: the hyphen
 * separates the motion from where the take came from. It is the CLIENT'S
 * grouping for picking a stand-in — the server keeps addressing clips by their
 * full kind, and an exactly-matching kind always wins over a family relative
 * (see `matchAnimKind`).
 *
 * The inner underscore is NOT a separator (`sit_a` stays one family), matching
 * the server's parser, which cuts only the `_<number>` take suffix.
 */
export function animFamily(kind: string | null | undefined): string {
  const clean = (kind ?? '').trim().toLowerCase();
  if (!clean) return 'idle';
  const dash = clean.indexOf('-');
  return dash > 0 ? clean.slice(0, dash) : clean;
}

/**
 * WHICH of the kinds actually available stands in for a wanted one:
 * the exact kind if it is there, otherwise a relative of the same family,
 * otherwise `''`.
 *
 * EXACT ALWAYS WINS — `walk-cmu` takes the `walk-cmu` clip even when a plain
 * `walk` sits next to it. Among family relatives the FAMILY BASE wins next
 * (`walk` before `walk-mixamo`), then the order the caller listed them in, so
 * the answer never depends on Map iteration luck.
 *
 * The match runs BOTH WAYS, which is the point: a marker authored `walk` finds
 * the kind `walk-cmu`, and a character asked for `walk-cmu` finds a marker
 * authored `walk`. The returned string is the entry as it was PASSED IN (not
 * normalised), so the caller can look it up in its own map with it.
 */
export function matchAnimKind(available: readonly string[], kind: string): string {
  const want = (kind ?? '').trim().toLowerCase();
  if (!want) return '';
  const family = animFamily(want);
  let relative = '';
  for (const raw of available) {
    const name = (raw ?? '').trim().toLowerCase();
    if (!name) continue;
    if (name === want) return raw;
    if (animFamily(name) !== family) continue;
    // family base beats any other relative; otherwise the first listed one
    if (!relative || name === family) relative = raw;
  }
  return relative;
}

/** Stand-in KIND when the wanted one is nowhere to be found (before falling
 *  back to idle): someone lying down should at least sit, a runner walk fast —
 *  and a swimmer walk, because the terrain clips (`move_anim`/`idle_anim`,
 *  § A9) name kinds out of an OPEN vocabulary that not every model carries. A
 *  model without `treading-water` simply stands in the lake, which is where it
 *  stood before the key existed — no break, just no water.
 *
 *  Keys are looked up by KIND first and by FAMILY second (`clipKindChain`), so
 *  one entry covers every take of a motion: `run-fast` reaches `walk` through
 *  the `run` entry without a line of its own. */
export const CLIP_FALLBACK: Readonly<Record<string, string>> = {
  lie: 'sit',
  run: 'walk',
  swim: 'walk',
  // A clip kind is the whole file name since 2026-08-13, so `swim-idle` is a
  // kind of its own — and the nearest thing to it on a rig without it is the
  // swimming stroke, not standing. Its FAMILY is `swim`, so this line only
  // matters for the rig that has neither: `swim-idle` → `swim` → `walk`.
  'swim-idle': 'swim',
  'treading-water': 'idle',
};

/**
 * The ordered KINDS to try for a wanted one, best first:
 *
 *   1. the kind itself            (`walk-cmu`)
 *   2. its explicit stand-in      (`CLIP_FALLBACK['walk-cmu']`)
 *   3. the stand-in of its family (`CLIP_FALLBACK['walk']`)
 *   4. idle — the floor everything ends on
 *
 * The FAMILY of the wanted kind is deliberately NOT a step of its own: every
 * step is matched with `matchAnimKind`, which already accepts a family
 * relative once the exact kind is missing. That keeps the two directions
 * symmetric — step 1 finds `walk` for a wanted `walk-cmu` AND `walk-cmu` for a
 * wanted `walk` — and it keeps the curated stand-in behind the same motion:
 * a `run-fast` walks only after every `run…` take has been ruled out.
 *
 * Blank and duplicate steps are dropped, so the chain of `idle` is `['idle']`.
 */
export function clipKindChain(kind: string): string[] {
  const want = (kind ?? '').trim().toLowerCase() || 'idle';
  const family = animFamily(want);
  const chain: string[] = [];
  for (const step of [want, CLIP_FALLBACK[want], CLIP_FALLBACK[family], 'idle']) {
    if (step && !chain.includes(step)) chain.push(step);
  }
  return chain;
}

/**
 * The kind a figure actually PLAYS for a wanted one, given the kinds it has
 * bound: the first link of `clipKindChain` that `matchAnimKind` finds among
 * them, `''` when the rig has nothing of the sort (the caller then plays
 * whatever clip it carries at all).
 *
 * As above, the entry is returned as it was passed in.
 */
export function resolveClipKind(kind: string, bound: readonly string[]): string {
  for (const step of clipKindChain(kind)) {
    const hit = matchAnimKind(bound, step);
    if (hit) return hit;
  }
  return '';
}

/**
 * The procedural GAIT a clip-less rig (UniRig animals, static meshes) has to
 * fake for a kind: `'run'`, `'walk'` or `null` for "stand and breathe".
 *
 * By family, not by literal — a rig with no clips at all cannot fall back to
 * anything, so if this misses the kind the figure stands stock still while it
 * slides across the map. That is exactly what `walk-cmu` did to it.
 */
export function proceduralGait(kind: string | null | undefined): 'walk' | 'run' | null {
  const family = animFamily(kind);
  return family === 'run' ? 'run' : family === 'walk' ? 'walk' : null;
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
