/**
 * check_image_routing_model.js — the pure chain functions of the image
 * routing Rules page (development_instructions/plan-image-routing.md § 6).
 *
 * Usage:  node scripts/check_image_routing_model.js     (repo root; no server)
 *
 * Extracts // >>> harness-extract:imageRoutingModel … // <<< … out of
 * static/admin/settings-image-routing.js and runs it on synthetic data.
 *
 * Backends B (name — media/category/rig/ref):
 *   Flux Big img2img ref1 · Flux Cheap img2img ref1 · Qwen Inpaint inpaint ·
 *   Flat txt2img ref0 · Mesh-H mesh img2mesh mixamo · Mesh-O mesh img2mesh none ·
 *   Shrink mesh mesh2mesh none · Vid video
 * Occasions: photo {image}, timevariant {image, needs_ref_slot},
 *            mesh_object {mesh, rig none}, video {video}
 *
 * Expected, derived by hand (rules of § 6 + the server's backend_fits):
 *  1. irAdd(R,'photo',' Flux* ') -> true, chain ['Flux*'] (trimmed);
 *     'flux*' again -> false (duplicate, case-insensitive); '' -> false.
 *  2. add 'Qwen*' -> ['Flux*','Qwen*']; irMove(1,-1) -> true ['Qwen*','Flux*'];
 *     irMove(0,-1) -> false.
 *  3. irSet(0,'Flux Big') -> ['Flux Big','Flux*']; irSet(0,'flux*') -> false
 *     (would duplicate entry 1), unchanged; irSet(0,'  ') -> entry removed,
 *     ['Flux*'].
 *  4. irRemove(0) -> true and the key 'photo' is gone (no empty chains).
 *  5. irMatches: 'Flux*' -> [Flux Big, Flux Cheap]; 'backend:flux big' ->
 *     [Flux Big]; 'F?at' -> [Flat]; '[FQ]*' -> [Flux Big, Flux Cheap,
 *     Qwen Inpaint, Flat]; 'Mesh-[!H]' -> [Mesh-O]; 'a.b' over [axb] -> []
 *     (a dot is literal, fnmatch semantics).
 *  6. irVerdict: photo/'Qwen Inpaint' wrong_kind; timevariant/'Flat'
 *     wrong_kind; timevariant/'Flux*' ok; mesh_object/'Mesh-*' ok (Mesh-O);
 *     mesh_object/'Mesh-H' wrong_kind (rig); mesh_object/'Shrink' wrong_kind
 *     (mesh2mesh); video/'Vid' ok; photo/'Nope' no_match.
 *  7. Loading never rewrites a stored chain (the save refuses an EDITED invalid
 *     chain but only warns about an unchanged one, so a load-time dedupe or
 *     drop would turn a warning into HTTP 400). irSurvey is read-only:
 *     S = {photo:['Flux*',' ','flux*','Qwen*'], mesh_low:['x'], item:[],
 *          video:'Vid', timevariant:['Flux*', 3]}, known {photo,item,video,
 *     timevariant} -> {root_ok:true, unknown:['mesh_low'],
 *     malformed:['video','timevariant']} ('Vid' is a string, not a list;
 *     [.., 3] has a non-string member; [] is a well-formed empty list), and S
 *     is deep-equal to its copy afterwards. irSurvey(undefined) and
 *     irSurvey(null) -> loaded false, root_ok true, nothing listed: every
 *     config load seeds `routing` (even as {}), so an absent one was not
 *     loaded in this tab; irSurvey(['Flux*']) and irSurvey('x') -> loaded
 *     true, root_ok false (present, not an object).
 * 7b. irEditable (A-2): only a plain object takes an edit — {} and
 *     {photo:[]} true; undefined, null, ['Flux*'], 'x' false. An absent
 *     routing must NOT become a fresh object: its first Save would replace
 *     every stored chain with the one just edited.
 *     irEntryNotes(['Flux*',' ','flux*','Qwen*','workflow:flux*']) ->
 *     {1:'empty', 2:'duplicate', 4:'duplicate'}: index 1 is blank after the
 *     trim, 2 equals 0 case-insensitively, 4 equals 0 after the prefix strip.
 *     irWellFormed: ['a'] true, [] true, 'a' false, ['a', null] false.
 *  8. irNormSpec('workflow:Z') -> 'Z'; irNormSpec('backend: X ') -> 'X'.
 *  9. Class edge cases, by Python's fnmatch.translate (the server matches
 *     with fnmatch on lowered names):
 *     - '[^M]*': a LEADING '^' is literal in fnmatch (translate escapes it),
 *       so the class is {^, m} -> [Mesh-H, Mesh-O] — NOT a negation.
 *     - '[]x]*' over [']a', 'xa', 'a'] -> [']a', 'xa']: a ']' right after
 *       '[' is a class member, not the end of an empty class.
 *     - 'Mesh-[!]H]': negated class {], h} -> [Mesh-O].
 *     - 'a[b' over ['a[b'] -> ['a[b']: an unclosed '[' is literal.
 *     - 'Mesh-[z-a]' -> [] and no exception: fnmatch turns a reversed
 *       range into a never-matching class; a JS RegExp would throw.
 * 10. Media rule (backend_fits compares media first): video/'Flux*' matches
 *     Flux Big + Flux Cheap, both image -> wrong_kind; photo/'Vid' matches
 *     only the video backend -> wrong_kind.
 * 11. Duplicates are case-insensitive on add, but an entry may change its own
 *     case: R2 = {photo:['Flux*']}; irAdd(R2,'photo','FLUX*') -> false, chain
 *     unchanged. R3 = {photo:['Flux Big','Qwen*']}; irSet(R3,'photo',0,
 *     'flux big') -> true (the only equal entry is index 0 itself, which
 *     _irHas skips) -> ['flux big','Qwen*'].
 * 12. irRemove out of range: on ['flux big','Qwen*'] index 2 and -1 ->
 *     false, chain unchanged (idx < 0 || idx >= length).
 */
'use strict';
const fs = require('fs'), path = require('path'), vm = require('vm');
const SRC = path.join(__dirname, '..', 'static', 'admin', 'settings-image-routing.js');
const BEGIN = '// >>> harness-extract:imageRoutingModel', END = '// <<< harness-extract:imageRoutingModel';
const src = fs.readFileSync(SRC, 'utf8');
const a = src.indexOf(BEGIN), b = src.indexOf(END);
if (a < 0 || b < 0 || b < a) { console.error('FAIL: markers not found'); process.exit(1); }
const sb = {}; vm.createContext(sb);
vm.runInContext(src.slice(a + BEGIN.length, b) + '\n;' +
  ['irChain','irAdd','irRemove','irMove','irSet','irNormSpec','irGlobToRegex','irMatches',
   'irFits','irVerdict','irWellFormed','irSurvey','irEntryNotes','irEditable'].map(n => `this.${n} = ${n};`).join(''), sb);
let fails = 0;
const eq = (x, y) => JSON.stringify(x) === JSON.stringify(y);
const check = (c, m) => { console.log((c ? 'ok   ' : 'FAIL ') + m); if (!c) fails++; };

const B = [
  { name: 'Flux Big', media: 'image', category: 'img2img', ref_slot_count: 1 },
  { name: 'Flux Cheap', media: 'image', category: 'img2img', ref_slot_count: 1 },
  { name: 'Qwen Inpaint', media: 'image', category: 'inpaint', ref_slot_count: 1 },
  { name: 'Flat', media: 'image', category: 'txt2img', ref_slot_count: 0 },
  { name: 'Mesh-H', media: 'mesh', category: 'img2mesh', rig: 'mixamo' },
  { name: 'Mesh-O', media: 'mesh', category: 'img2mesh', rig: 'none' },
  { name: 'Shrink', media: 'mesh', category: 'mesh2mesh', rig: 'none' },
  { name: 'Vid', media: 'video', category: 'txt2img' },
];
const O = {
  photo: { id: 'photo', media: 'image', category: 'render', rig: '', needs_ref_slot: false },
  timevariant: { id: 'timevariant', media: 'image', category: 'render', rig: '', needs_ref_slot: true },
  mesh_object: { id: 'mesh_object', media: 'mesh', category: 'img2mesh', rig: 'none', needs_ref_slot: false },
  video: { id: 'video', media: 'video', category: 'render', rig: '', needs_ref_slot: false },
};

const R = {};
check(sb.irAdd(R, 'photo', ' Flux* ') === true && eq(R.photo, ['Flux*']), '1. add trims');
check(sb.irAdd(R, 'photo', 'flux*') === false && R.photo.length === 1, '1. duplicate refused');
check(sb.irAdd(R, 'photo', '') === false, '1. empty refused');
sb.irAdd(R, 'photo', 'Qwen*');
check(sb.irMove(R, 'photo', 1, -1) === true && eq(R.photo, ['Qwen*', 'Flux*']), '2. move up');
check(sb.irMove(R, 'photo', 0, -1) === false, '2. move past top is a no-op');
check(sb.irSet(R, 'photo', 0, 'Flux Big') === true && eq(R.photo, ['Flux Big', 'Flux*']), '3. set');
check(sb.irSet(R, 'photo', 0, 'flux*') === false && eq(R.photo, ['Flux Big', 'Flux*']), '3. set to a duplicate refused');
check(sb.irSet(R, 'photo', 0, '  ') === true && eq(R.photo, ['Flux*']), '3. set blank removes');
check(sb.irRemove(R, 'photo', 0) === true && !('photo' in R), '4. last entry removes the key');
check(eq(sb.irMatches('Flux*', B), ['Flux Big', 'Flux Cheap']), '5. glob');
check(eq(sb.irMatches('backend:flux big', B), ['Flux Big']), '5. prefix + case');
check(eq(sb.irMatches('F?at', B), ['Flat']), '5. ?');
check(eq(sb.irMatches('[FQ]*', B), ['Flux Big', 'Flux Cheap', 'Qwen Inpaint', 'Flat']), '5. class');
check(eq(sb.irMatches('Mesh-[!H]', B), ['Mesh-O']), '5. negated class');
check(eq(sb.irMatches('a.b', [{ name: 'axb' }]), []), '5. dot is literal');
check(sb.irVerdict(O.photo, 'Qwen Inpaint', B) === 'wrong_kind', '6. inpaint');
check(sb.irVerdict(O.timevariant, 'Flat', B) === 'wrong_kind', '6. no ref slot');
check(sb.irVerdict(O.timevariant, 'Flux*', B) === 'ok', '6. ref slot ok');
check(sb.irVerdict(O.mesh_object, 'Mesh-*', B) === 'ok', '6. rig none found');
check(sb.irVerdict(O.mesh_object, 'Mesh-H', B) === 'wrong_kind', '6. wrong rig');
check(sb.irVerdict(O.mesh_object, 'Shrink', B) === 'wrong_kind', '6. mesh2mesh');
check(sb.irVerdict(O.video, 'Vid', B) === 'ok', '6. video');
check(sb.irVerdict(O.photo, 'Nope', B) === 'no_match', '6. no match');
const S = { photo: ['Flux*', ' ', 'flux*', 'Qwen*'], mesh_low: ['x'], item: [], video: 'Vid', timevariant: ['Flux*', 3] };
const S0 = JSON.parse(JSON.stringify(S));
const sv = sb.irSurvey(S, new Set(['photo', 'item', 'video', 'timevariant']));
check(eq(sv, { loaded: true, root_ok: true, unknown: ['mesh_low'], malformed: ['video', 'timevariant'] }), '7. survey lists unknown + malformed');
check(eq(S, S0), '7. survey does not mutate the stored routing');
check(eq(sb.irSurvey(undefined, new Set()), { loaded: false, root_ok: true, unknown: [], malformed: [] })
      && eq(sb.irSurvey(null, new Set()), { loaded: false, root_ok: true, unknown: [], malformed: [] }),
      '7. an absent routing is "not loaded"');
check(['x', ['Flux*']].every(r => { const o = sb.irSurvey(r, new Set()); return o.loaded === true && o.root_ok === false; }),
      '7. a present non-object routing is flagged');
check(sb.irEditable({}) && sb.irEditable({ photo: [] })
      && ![undefined, null, ['Flux*'], 'x'].some(r => sb.irEditable(r)),
      '7b. only a plain object takes an edit');
check(eq(sb.irEntryNotes(['Flux*', ' ', 'flux*', 'Qwen*', 'workflow:flux*']), { 1: 'empty', 2: 'duplicate', 4: 'duplicate' }),
      '7. entry notes: empty + duplicates, shown not removed');
check(sb.irWellFormed(['a']) && sb.irWellFormed([]) && !sb.irWellFormed('a') && !sb.irWellFormed(['a', null]),
      '7. well-formed = list of strings');
check(sb.irNormSpec('workflow:Z') === 'Z' && sb.irNormSpec('backend: X ') === 'X', '8. prefixes');
check(eq(sb.irMatches('[^M]*', B), ['Mesh-H', 'Mesh-O']), '9. leading ^ is literal');
check(eq(sb.irMatches('[]x]*', [{ name: ']a' }, { name: 'xa' }, { name: 'a' }]), [']a', 'xa']),
      '9. ] right after [ is a member');
check(eq(sb.irMatches('Mesh-[!]H]', B), ['Mesh-O']), '9. ] right after [! is a member');
check(eq(sb.irMatches('a[b', [{ name: 'a[b' }]), ['a[b']), '9. unclosed [ is literal');
let rev = null;
try { rev = sb.irMatches('Mesh-[z-a]', B); } catch (e) { rev = 'threw: ' + e.message; }
check(eq(rev, []), '9. reversed range never matches, no throw');
check(sb.irVerdict(O.video, 'Flux*', B) === 'wrong_kind', '10. image backends for a video occasion');
check(sb.irVerdict(O.photo, 'Vid', B) === 'wrong_kind', '10. a video backend for an image occasion');
const R2 = { photo: ['Flux*'] };
check(sb.irAdd(R2, 'photo', 'FLUX*') === false && eq(R2.photo, ['Flux*']), '11. add FLUX* after Flux* refused');
const R3 = { photo: ['Flux Big', 'Qwen*'] };
check(sb.irSet(R3, 'photo', 0, 'flux big') === true && eq(R3.photo, ['flux big', 'Qwen*']), '11. set may change its own case');
check(sb.irRemove(R3, 'photo', 2) === false && sb.irRemove(R3, 'photo', -1) === false && eq(R3.photo, ['flux big', 'Qwen*']),
      '12. remove out of range is a no-op');
console.log(); if (fails) { console.log(fails + ' check(s) failed'); process.exit(1); } console.log('all checks passed');
