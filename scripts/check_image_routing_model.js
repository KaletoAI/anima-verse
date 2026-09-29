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
 *  7. irNormalize({photo:['Flux*',' ','flux*','Qwen*'], mesh_low:['x'], item:[]},
 *     known {photo,item}) -> {unknown:['mesh_low']}; photo ['Flux*','Qwen*'];
 *     'item' removed (empty); mesh_low KEPT (the page offers its removal).
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
   'irFits','irVerdict','irNormalize'].map(n => `this.${n} = ${n};`).join(''), sb);
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
const N = { photo: ['Flux*', ' ', 'flux*', 'Qwen*'], mesh_low: ['x'], item: [] };
const res = sb.irNormalize(N, new Set(['photo', 'item']));
check(eq(res, { unknown: ['mesh_low'] }) && eq(N.photo, ['Flux*', 'Qwen*']) && !('item' in N) && eq(N.mesh_low, ['x']),
      '7. normalize');
check(sb.irNormSpec('workflow:Z') === 'Z' && sb.irNormSpec('backend: X ') === 'X', '8. prefixes');
check(eq(sb.irMatches('[^M]*', B), ['Mesh-H', 'Mesh-O']), '9. leading ^ is literal');
check(eq(sb.irMatches('[]x]*', [{ name: ']a' }, { name: 'xa' }, { name: 'a' }]), [']a', 'xa']),
      '9. ] right after [ is a member');
check(eq(sb.irMatches('Mesh-[!]H]', B), ['Mesh-O']), '9. ] right after [! is a member');
check(eq(sb.irMatches('a[b', [{ name: 'a[b' }]), ['a[b']), '9. unclosed [ is literal');
let rev = null;
try { rev = sb.irMatches('Mesh-[z-a]', B); } catch (e) { rev = 'threw: ' + e.message; }
check(eq(rev, []), '9. reversed range never matches, no throw');
console.log(); if (fails) { console.log(fails + ' check(s) failed'); process.exit(1); } console.log('all checks passed');
