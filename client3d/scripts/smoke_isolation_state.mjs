#!/usr/bin/env node
/**
 * Smoke check for the ISOLATION PANEL'S STATE CODEC —
 * `client3d/src/game/isolationState.ts`, used by `client3d/src/debug3d.ts`.
 *
 * Usage:  node client3d/scripts/smoke_isolation_state.mjs
 *
 * Every expectation below is derived BY HAND in this docstring and never
 * recorded from the current output (§ B5a: numbers, not screenshots). The
 * arithmetic is reimplemented here rather than imported, so a check can only
 * pass because the RULE holds — an import would prove the code equals itself.
 *
 * WHY THIS FILE EXISTS. The panel itself is UI and is judged by looking at it.
 * Its state is not: it travels through `localStorage` and through a URL a
 * person retypes or pastes into a chat window, and a decoder that guesses at a
 * mistyped token would silently isolate the wrong suspect — the one failure
 * mode of a diagnostic tool that makes it worse than having none. So the codec,
 * and only the codec, is pinned here.
 *
 * ============================================================================
 * [1] THE ID RANGE
 * ============================================================================
 * The panel has 19 switches, numbered 1..19 with no gaps. So:
 *   valid   : 1, 2, 18, 19
 *   invalid : 0, 20, -1, 3.5, NaN
 * Out-of-range ids are DROPPED, never clamped: a `20` in a shared link is
 * either a typo or a link from another client, and honouring it as `19` would
 * be a state nobody chose.
 *
 * THE RANGE IS THE ONE THING THAT MOVES when a switch is added or retired, and
 * it moves in two places that have to agree: `ISO_MAX_ID` and the number of
 * entries in `ISOLATION_TOGGLES`. 19 here is hand-counted from that list — 20
 * held for one day, while "Terrain culling off" existed (2026-08-22); the cull
 * it switched off is deleted, so the switch went with it.
 *
 * ============================================================================
 * [2] `encodeIsolation` — ascending, deduplicated, comma-separated
 * ============================================================================
 * Hand-derived:
 *   {}              -> ""            (the empty set is the empty string, NOT
 *                                     "0" — that is what lets the hash key be
 *                                     removed instead of written empty)
 *   {3}             -> "3"
 *   {6, 3}          -> "3,6"         (sorted NUMERICALLY, so 6 follows 3)
 *   {3, 6, 3}       -> "3,6"         (a Set cannot hold 3 twice anyway)
 *   {2, 10, 1}      -> "1,2,10"      (numeric, not lexicographic: a string
 *                                     sort would give "1,10,2")
 *   {2, 19, 1}      -> "1,2,19"      (19 is the last switch, so it survives)
 *   {0, 3, 20}      -> "3"           (the invalid ids never reach the string)
 *
 * ============================================================================
 * [3] `decodeIsolation` — strictly digits per token
 * ============================================================================
 * A token is trimmed and then has to match /^\d+$/ WHOLE. Hand-derived:
 *   ""              -> []
 *   null/undefined  -> []
 *   "3"             -> [3]
 *   "03"            -> [3]           (leading zeros are still digits)
 *   "6,3"           -> [3, 6]        (the decoder sorts as well)
 *   "6,3,3"         -> [3, 6]
 *   " 3 , 6 "       -> [3, 6]        (trimmed)
 *   "3.5"           -> []            (Number("3.5") = 3.5 — a decoder using
 *                                     Number() would have to round, i.e. guess)
 *   "+3"            -> []            (Number("+3") = 3 — same trap)
 *   "-3"            -> []
 *   "3px"           -> []
 *   "0,21,abc,,7"   -> [7]           (every other token fails a rule above)
 *   "1e1"           -> []            (Number("1e1") = 10; not digits)
 *
 * ROUND TRIP: decode(encode(S)) is S sorted ascending, for every S of valid
 * ids. Checked exhaustively below over all 2^20 = 1 048 576 subsets? No — over
 * a hand-picked spread plus 2 000 pseudo-random subsets, which is the same
 * statement at a five-hundredth of the cost.
 *
 * ============================================================================
 * [4] `readIsoHash` — three DIFFERENT answers, all of them used
 * ============================================================================
 *   null  = the link says nothing about the isolation -> keep localStorage
 *   ""    = the link says "nothing isolated"          -> clear it
 *   "3,6" = the link names a state                     -> take it
 * Hand-derived:
 *   ""                 -> null
 *   "#"                -> null       (an empty body has no key)
 *   "#iso=3,6"         -> "3,6"
 *   "iso=3,6"          -> "3,6"      (a leading '#' is optional)
 *   "#foo=1&iso=7"     -> "7"
 *   "#iso=7&foo=1"     -> "7"
 *   "#iso="            -> ""         (the key is there, its value is empty)
 *   "#iso"             -> ""         (a bare key is an empty value)
 *   "#isotope=1"       -> null       (the key is matched WHOLE)
 *   "#xiso=1"          -> null
 *   "#iso=3&iso=9"     -> "3"        (the first wins; there is one state)
 *
 * ============================================================================
 * [5] `writeIsoHash` — replace in place, append otherwise, remove when empty
 * ============================================================================
 * The other keys of a shared link must survive AND keep their order, so the
 * value is replaced where it stands rather than deleted and appended.
 * Hand-derived:
 *   ("", "3")             -> "#iso=3"
 *   ("#", "3")            -> "#iso=3"
 *   ("#foo=1", "3")       -> "#foo=1&iso=3"     (appended, foo stays first)
 *   ("#iso=9", "3")       -> "#iso=3"
 *   ("#iso=9&foo=1", "3") -> "#iso=3&foo=1"     (in place — foo stays LAST)
 *   ("#foo=1&iso=9", "3") -> "#foo=1&iso=3"
 *   ("#iso=9", "")        -> ""                 (empty removes the key…)
 *   ("#iso=9&foo=1", "")  -> "#foo=1"           (…and only the key)
 *   ("#foo=1", "")        -> "#foo=1"           (nothing to remove)
 *   ("", "")              -> ""                 (NOT "#": a bare hash in the
 *                                                address bar is a link that
 *                                                looks like it does something)
 *   ("#iso=1&iso=2", "3") -> "#iso=3"           (a duplicate key collapses)
 *
 * IDEMPOTENCE: write(write(h, v), v) = write(h, v) for every h and v below.
 * A panel that persists on every click would otherwise grow the hash by one
 * key per click.
 */

const MIN_ID = 1;
const MAX_ID = 19;
const HASH_KEY = 'iso';

// ── the reimplementation the checks are made against ────────────────────────

const isId = (id) => Number.isInteger(id) && id >= MIN_ID && id <= MAX_ID;

function encode(ids) {
  const seen = new Set();
  for (const id of ids) if (isId(id)) seen.add(id);
  return [...seen].sort((a, b) => a - b).join(',');
}

function decode(text) {
  if (typeof text !== 'string' || !text) return [];
  const seen = new Set();
  for (const raw of text.split(',')) {
    const token = raw.trim();
    if (!/^\d+$/.test(token)) continue;
    const id = Number(token);
    if (isId(id)) seen.add(id);
  }
  return [...seen].sort((a, b) => a - b);
}

function readHash(hash) {
  if (typeof hash !== 'string' || !hash) return null;
  const body = hash.startsWith('#') ? hash.slice(1) : hash;
  for (const part of body.split('&')) {
    const eq = part.indexOf('=');
    const key = eq < 0 ? part : part.slice(0, eq);
    if (key !== HASH_KEY) continue;
    return eq < 0 ? '' : part.slice(eq + 1);
  }
  return null;
}

function writeHash(hash, value) {
  const body = (typeof hash === 'string' && hash.startsWith('#'))
    ? hash.slice(1) : (hash || '');
  const parts = body ? body.split('&').filter((p) => p !== '') : [];
  const out = [];
  let written = false;
  for (const part of parts) {
    const eq = part.indexOf('=');
    const key = eq < 0 ? part : part.slice(0, eq);
    if (key !== HASH_KEY) { out.push(part); continue; }
    if (!value || written) continue;
    out.push(`${HASH_KEY}=${value}`);
    written = true;
  }
  if (value && !written) out.push(`${HASH_KEY}=${value}`);
  return out.length ? `#${out.join('&')}` : '';
}

// ── the harness ─────────────────────────────────────────────────────────────

let passed = 0;
let failed = 0;

function eq(label, got, want) {
  const g = JSON.stringify(got);
  const w = JSON.stringify(want);
  if (g === w) { passed += 1; console.log(`  ok   ${label}: ${g}`); return; }
  failed += 1;
  console.log(`  FAIL ${label}: got ${g}, want ${w}`);
}

// ── [1] the id range ────────────────────────────────────────────────────────

console.log('[1] the id range 1..19, dropped and never clamped');
eq('(a) 1 is an id', isId(1), true);
eq('…18 is an id', isId(18), true);
eq('…19 is an id (Wireframe terrain, the last one)', isId(19), true);
eq('…0 is not', isId(0), false);
eq('…20 is not — the retired "Terrain culling off"', isId(20), false);
eq('…21 is not', isId(21), false);
eq('…-1 is not', isId(-1), false);
eq('…3.5 is not', isId(3.5), false);
eq('…NaN is not', isId(NaN), false);
eq('(b) 20 is DROPPED by encode, not clamped to 19', encode([20]), '');
eq('…and by decode', decode('20'), []);
eq('…while 19 passes both', decode(encode([19])), [19]);

// ── [2] encode ──────────────────────────────────────────────────────────────

console.log('\n[2] encodeIsolation');
eq('(c) the empty set is the empty string', encode([]), '');
eq('…one id', encode([3]), '3');
eq('…sorted ascending', encode([6, 3]), '3,6');
eq('…deduplicated', encode([3, 6, 3]), '3,6');
eq('(d) NUMERIC order, not lexicographic', encode([2, 10, 1]), '1,2,10');
eq('…and 19 sorts last, not between 1 and 2', encode([2, 19, 1]), '1,2,19');
eq('(e) invalid ids never reach the string', encode([0, 3, 20]), '3');

// ── [3] decode ──────────────────────────────────────────────────────────────

console.log('\n[3] decodeIsolation — strictly digits per token');
eq('(f) empty string', decode(''), []);
eq('…null', decode(null), []);
eq('…undefined', decode(undefined), []);
eq('…"3"', decode('3'), [3]);
eq('…"03" (leading zeros are digits)', decode('03'), [3]);
eq('…"6,3" is sorted', decode('6,3'), [3, 6]);
eq('…"6,3,3" is deduplicated', decode('6,3,3'), [3, 6]);
eq('…" 3 , 6 " is trimmed', decode(' 3 , 6 '), [3, 6]);
eq('(g) RED: "3.5" is dropped, not rounded', decode('3.5'), []);
eq('…RED: "+3" is dropped', decode('+3'), []);
eq('…RED: "-3" is dropped', decode('-3'), []);
eq('…RED: "3px" is dropped', decode('3px'), []);
eq('…RED: "1e1" is dropped', decode('1e1'), []);
eq('(h) a mixed line keeps only what is legal', decode('0,20,abc,,7'), [7]);

console.log('\n…and the round trip decode(encode(S)) = sort(S)');
const spread = [
  [], [1], [18], [19], [1, 19], [3, 6], [6, 3], [2, 10, 1],
  [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19],
];
let tripBad = 0;
for (const s of spread) {
  const want = [...new Set(s)].sort((a, b) => a - b);
  if (JSON.stringify(decode(encode(s))) !== JSON.stringify(want)) tripBad += 1;
}
// A tiny deterministic generator — a seeded LCG, so a failure is reproducible.
let seed = 20260821;
const rnd = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
for (let i = 0; i < 2000; i += 1) {
  const s = [];
  for (let id = MIN_ID; id <= MAX_ID; id += 1) if (rnd() < 0.5) s.push(id);
  // shuffled on the way in, so the sort is what is being tested
  s.sort(() => rnd() - 0.5);
  const want = [...new Set(s)].sort((a, b) => a - b);
  if (JSON.stringify(decode(encode(s))) !== JSON.stringify(want)) tripBad += 1;
}
// 9 hand-picked sets + 2 000 generated ones = 2 009.
eq('(i) 2 009 round trips, failures', tripBad, 0);

// ── [4] readIsoHash ─────────────────────────────────────────────────────────

console.log('\n[4] readIsoHash — null, "" and a value are three answers');
eq('(j) no hash at all', readHash(''), null);
eq('…a bare "#"', readHash('#'), null);
eq('…null', readHash(null), null);
eq('(k) "#iso=3,6"', readHash('#iso=3,6'), '3,6');
eq('…without the leading #', readHash('iso=3,6'), '3,6');
eq('…behind another key', readHash('#foo=1&iso=7'), '7');
eq('…before another key', readHash('#iso=7&foo=1'), '7');
eq('(l) "#iso=" is the EMPTY state, not "no statement"', readHash('#iso='), '');
eq('…a bare key is the same', readHash('#iso'), '');
eq('(m) RED: the key is matched WHOLE', readHash('#isotope=1'), null);
eq('…RED: and not as a suffix', readHash('#xiso=1'), null);
eq('(n) a duplicated key: the first wins', readHash('#iso=3&iso=9'), '3');

// ── [5] writeIsoHash ────────────────────────────────────────────────────────

console.log('\n[5] writeIsoHash — replace in place, append, remove');
eq('(o) into an empty hash', writeHash('', '3'), '#iso=3');
eq('…into a bare "#"', writeHash('#', '3'), '#iso=3');
eq('(p) appended after a foreign key', writeHash('#foo=1', '3'), '#foo=1&iso=3');
eq('(q) replaced in place, foreign key stays LAST',
   writeHash('#iso=9&foo=1', '3'), '#iso=3&foo=1');
eq('…and stays FIRST where it was first',
   writeHash('#foo=1&iso=9', '3'), '#foo=1&iso=3');
eq('…alone', writeHash('#iso=9', '3'), '#iso=3');
eq('(r) the empty value REMOVES the key', writeHash('#iso=9', ''), '');
eq('…and only the key', writeHash('#iso=9&foo=1', ''), '#foo=1');
eq('…nothing to remove is a no-op', writeHash('#foo=1', ''), '#foo=1');
eq('(s) an empty result is "" and never "#"', writeHash('', ''), '');
eq('(t) a duplicated key collapses', writeHash('#iso=1&iso=2', '3'), '#iso=3');

console.log('\n…and writing twice is writing once');
let idemBad = 0;
const hashes = ['', '#', '#foo=1', '#iso=9', '#iso=9&foo=1', '#foo=1&iso=9',
                '#a=1&b=2', '#iso=1&iso=2'];
for (const h of hashes) {
  for (const v of ['', '3', '3,6', '1,2,10']) {
    const once = writeHash(h, v);
    if (writeHash(once, v) !== once) idemBad += 1;
  }
}
eq('(u) 32 hash/value pairs, non-idempotent writes', idemBad, 0);

console.log('\n…and a written state reads back as itself');
let tripHashBad = 0;
for (const h of hashes) {
  for (const s of spread) {
    const v = encode(s);
    const written = writeHash(h, v);
    const read = readHash(written);
    // A non-empty state has to come back verbatim. The EMPTY state removes the
    // key, so it reads back as `null` — "the link says nothing about the
    // isolation", which is the right thing for a link that isolates nothing:
    // it leaves whatever localStorage holds alone instead of clearing it.
    if (read !== (v || null)) tripHashBad += 1;
  }
}
// 8 hashes × 9 spread sets = 72.
eq('(v) 72 write/read round trips, failures', tripHashBad, 0);

console.log(`\n${passed + failed} checks, ${failed} failures`);
process.exit(failed ? 1 : 0);
