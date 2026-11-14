#!/usr/bin/env node
/**
 * Check of the HAAR Cut control (Ruling A71) in the Hairstyles tab: the pure helpers of
 * `frontend/src/tabs/characters/hairCut.ts` and `hairstylesModel.ts`, the Cut group rendered once (react-dom/server),
 * and the wiring of the live preview and of Save by source greps. The cut rule itself (Python = TypeScript) is
 * `scripts/smoke_hair_cut_parity.py`; the server half (save, due, CPU refit, source route) `scripts/smoke_haar_chain.py`
 * [10c].
 *
 * Usage:  node scripts/check_hair_cut_ui.mjs
 *
 * Self-bundling via esbuild (like scripts/check_hairstyles_ui.mjs); no server, no world. Exit 1 with the mismatch
 * list, 0 when every case holds.
 *
 * THE CASES, DERIVED BY HAND
 * --------------------------
 * [1] cutPostBody — what Save posts besides `item_id`, the setting and nothing else:
 *       {} → {max_cm null, at null, ends_cm null};  {at "shoulder", ends_cm 2.04} → {null, "shoulder", 2};
 *       {max_cm 30.06} → {30.1, null, null} (0.1 cm like the server);  {max_cm 30, at "chin"} → {null, "chin", null}
 *       (the control offers one of the two; "at" wins as in normaliseCut).
 * [2] cutLabel (en, Auto 3 cm): {} → "Full length · soft tip Auto (3 cm)"; {max_cm 30, ends_cm 1.5} →
 *     "Max 30 cm · soft tip 1.5 cm"; {at "mid_back"} → "Ends at Mid back · soft tip Auto (3 cm)".
 *     cutEqual({ends_cm 2}, {ends_cm 2.04}) true (both 2.0); cutEqual({}, {ends_cm 3}) false (Auto ≠ a set 3 cm).
 * [3] settingDue("cut") with stale_reasons ["cut_changed"] and step_jobs.fit 0 → "Saved, not applied — Re-fit applies
 *     it (no hub job)"; without the reason → null.
 * [4] The source S: 2 cards × 3 rows; card k rows at y 1.6, 1.5, 1.4, left x −0.01 + 0.1k, right +0.01 + 0.1k, z −0.10
 *     (card 0) / −0.12 (card 1); landmarks {shoulder 1.45}. Bounds: x −0.01 … 0.11, min z −0.12 → the ruler's z −0.14.
 *     cutRuler {at "shoulder"} → ONE line (−0.05, 1.45, −0.14) → (0.15, 1.45, −0.14).
 *     cutRuler {max_cm 20} → median root y 1.6, x 0.15: the rail (0.15, 1.6) → (0.15, 1.4); ticks at 0, 5, 10, 15,
 *     20 cm, long (0.02) at 0 / 10 / 20, short (0.01) at 5 / 15; the foot (0.12 … 0.16, 1.4) in orange → 7 lines.
 *     cutRuler {} → none; {at "waist"} (no such landmark) → none.
 * [5] cutOverride(S, {}): L 0.2 per card, p90 0.2 → clamp 0.3, keep 0.2, E = min(0.03, 0.05) = 0.03; rows at arc 0,
 *     0.17, 0.2 → card 0 row 1 left y 1.43, row 2 y 1.4; v per vertex [1, 1, 0.25, 0.25, 0.05, 0.05] per card (R = 3:
 *     one body segment, v = 1 − 0.75·r, the last row 1 − 0.95); 36 positions, 12 v.
 *     cutOverride(S, {max_cm 10}): keep 0.1, E 0.025 → row 1 y 1.6 − 0.075 = 1.525, row 2 y 1.5.
 * [6] Rendered once (en): HairLiveControls in haar mode with the panel P {saved {}, built {}, landmarks {chin 1.47,
 *     shoulder 1.44, shoulder_blades 1.27, mid_back 1.14, waist 1.04}, limits, auto_ends_cm 3, at [the five]} shows the
 *     group "Cut" with the Length choices "Full length" (selected), "Max length" and under "Ends at" "Chin · 147 cm" … "Waist ·
 *     104 cm", the "Ends" slider "3 cm auto", Save DISABLED (nothing dragged), "In use: Full length · soft tip Auto
 *     (3 cm)"; with stale_reasons ["cut_changed"] the due line "Saved, not applied — Re-fit applies it (no hub job)";
 *     built null → "In use: not cut yet — the next fit cuts it". In hairdeck mode (or without a panel) no "Cut" group.
 * [7] Wiring: Save posts `post('cut', cutPostBody(cut))` and Automatic `post('cut', cutPostBody({}))` — no other
 *     request in the Cut group, nothing runs (`…/hair/cut` only); the tab fetches `haar.cut.source_url`, computes
 *     `cutOverride(…, drafts.cut)` and hands it to the viewer as `meshAdjust.cut`, and draws `cutRuler` as the
 *     reference; the viewer writes the cut positions AND uv.y of the first vertices, keeps the base v to restore, and
 *     pauses the strands while a cut is shown (`strandOn(false)`, `paused`); the routes `POST …/hair/cut` and
 *     `GET …/garments/{item_id}/haar-cut-source` take `Depends(require_admin)`; no native dialog in the touched files.
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { mkdtemp, rm } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const require_ = createRequire(import.meta.url);

function esbuildModule() {
  for (const cand of ['esbuild', join(ROOT, 'node_modules/esbuild'), join(ROOT, 'frontend/node_modules/esbuild')]) {
    try {
      return require_(cand);
    } catch { /* next candidate */ }
  }
  console.error('esbuild not found (npm install) — nothing was checked');
  process.exit(1);
}

const failures = [];
const near = (a, b, tol = 1e-6) => Math.abs(a - b) <= tol;
function check(label, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`${ok ? '  OK  ' : '  FAIL'} ${label}${ok ? '' : `: got ${JSON.stringify(got)} want ${JSON.stringify(want)}`}`);
  if (!ok) failures.push(label);
}

const esbuild = esbuildModule();
const dir = await mkdtemp(join(tmpdir(), 'check-hair-cut-ui-'));
let cutM, model, render;
try {
  const at = (rel) => JSON.stringify(join(ROOT, rel));
  const entry = join(dir, 'entry.tsx');
  writeFileSync(entry, [
    `import { renderToStaticMarkup } from 'react-dom/server'`,
    `import { I18nProvider } from ${at('frontend/src/i18n/I18nProvider.tsx')}`,
    `import { ToastProvider } from ${at('frontend/src/lib/Toast.tsx')}`,
    `import { HairLiveControls } from ${at('frontend/src/tabs/characters/HairLiveControls.tsx')}`,
    `export * as cut from ${at('frontend/src/tabs/characters/hairCut.ts')}`,
    `export * as model from ${at('frontend/src/tabs/characters/hairstylesModel.ts')}`,
    `export const render = (mode, hd, info, cutPanel) => renderToStaticMarkup(<I18nProvider><ToastProvider>`,
    `  <HairLiveControls character="demo" itemId="hair_demo_1" mode={mode} hd={hd} info={info} busy={false}`,
    `    previewSwings="swing_off" cutPanel={cutPanel} onDraft={() => {}} onRuler={() => {}} onSaved={() => {}} />`,
    `</ToastProvider></I18nProvider>)`,
  ].join('\n'));
  const file = join(dir, 'ssr.cjs');
  await esbuild.build({
    entryPoints: [entry], outfile: file, bundle: true, format: 'cjs', platform: 'node', jsx: 'automatic',
    logLevel: 'silent', absWorkingDir: ROOT, nodePaths: [join(ROOT, 'node_modules')],
    define: { 'process.env.NODE_ENV': '"production"' }, loader: { '.css': 'empty' },
  });
  ({ cut: cutM, model, render } = require_(file));
} finally {
  await rm(dir, { recursive: true, force: true });
}

console.log('[1] cutPostBody');
check('[1] {}', cutM.cutPostBody({}), { max_cm: null, at: null, ends_cm: null });
check('[1] at + ends', cutM.cutPostBody({ at: 'shoulder', ends_cm: 2.04 }), { max_cm: null, at: 'shoulder', ends_cm: 2 });
check('[1] max rounded', cutM.cutPostBody({ max_cm: 30.06 }), { max_cm: 30.1, at: null, ends_cm: null });
check('[1] at wins', cutM.cutPostBody({ max_cm: 30, at: 'chin' }), { max_cm: null, at: 'chin', ends_cm: null });

console.log('[2] cutLabel / cutEqual');
check('[2] labels', [model.cutLabel({}, 3), model.cutLabel({ max_cm: 30, ends_cm: 1.5 }, 3),
  model.cutLabel({ at: 'mid_back' }, 3)],
['Full length · soft tip Auto (3 cm)', 'Max 30 cm · soft tip 1.5 cm', 'Ends at Mid back · soft tip Auto (3 cm)']);
check('[2] cutEqual', [cutM.cutEqual({ ends_cm: 2 }, { ends_cm: 2.04 }), cutM.cutEqual({}, { ends_cm: 3 })], [true, false]);

console.log('[3] settingDue cut');
const info = (reasons) => ({ pipeline: true, method: 'haar', garment: { stale_reasons: reasons }, step_jobs: { fit: 0 } });
check('[3] due', [model.settingDue('cut', info(['cut_changed'])), model.settingDue('cut', info(['colour_changed']))],
  ['Saved, not applied — Re-fit applies it (no hub job)', null]);

console.log('[4] cutRuler');
const R = 3, K = 2;
const rails = new Float32Array(K * R * 6);
for (let k = 0; k < K; k++) {
  for (let r = 0; r < R; r++) {
    const o = (k * R + r) * 6;
    rails.set([-0.01 + 0.1 * k, 1.6 - 0.1 * r, k ? -0.12 : -0.10, 0.01 + 0.1 * k, 1.6 - 0.1 * r, k ? -0.12 : -0.10], o);
  }
}
const S = { version: 1, cards: K, rows: R, rails: '', landmarks: { shoulder: 1.45 }, source_sha256: 'x' };
const r6 = (v) => Math.round(v * 1e6) / 1e6;
const pts = (lines) => lines.map((l) => [l.points.map((p) => p.map(r6)), l.color]);
check('[4] at shoulder', pts(cutM.cutRuler(S, rails, { at: 'shoulder' })),
  [[[[-0.05, 1.45, -0.14], [0.15, 1.45, -0.14]], '#c9d1d9']]);
const maxLines = cutM.cutRuler(S, rails, { max_cm: 20 });
check('[4] max 20: count, rail, tick lengths, foot', [maxLines.length, pts(maxLines.slice(0, 1))[0][0],
  maxLines.slice(1, 6).map((l) => r6(l.points[0][0] - l.points[1][0])), maxLines.slice(1, 6).map((l) => r6(l.points[0][1])),
  pts(maxLines.slice(6))[0]],
[7, [[0.15, 1.6, -0.14], [0.15, 1.4, -0.14]], [0.02, 0.01, 0.02, 0.01, 0.02], [1.6, 1.55, 1.5, 1.45, 1.4],
  [[[0.12, 1.4, -0.14], [0.16, 1.4, -0.14]], '#f0883e']]);
check('[4] none', [cutM.cutRuler(S, rails, {}).length, cutM.cutRuler(S, rails, { at: 'waist' }).length], [0, 0]);

console.log('[5] cutOverride');
const o0 = cutM.cutOverride(S, rails, {});
check('[5] sizes', [o0.positions.length, o0.v.length], [36, 12]);
check('[5] v per vertex', Array.from(o0.v).map((v) => Math.round(v * 1e6) / 1e6),
  [1, 1, 0.25, 0.25, 0.05, 0.05, 1, 1, 0.25, 0.25, 0.05, 0.05]);
check('[5] auto rows', [near(o0.positions[6 + 1], 1.43, 1e-6), near(o0.positions[12 + 1], 1.4, 1e-6)], [true, true]);
const o10 = cutM.cutOverride(S, rails, { max_cm: 10 });
check('[5] max 10 rows', [near(o10.positions[6 + 1], 1.525, 1e-6), near(o10.positions[12 + 1], 1.5, 1e-6)], [true, true]);

console.log('[6] rendered');
const hd = {
  hsig: '', status: 'missing', attempt: null, seed: null, job_seed: null, seeds_tried: 0, backend: null, created_at: null,
  error: null, notes: [], attempts: [], images: {},
  colour: { target: null, source: 'profile', auto: null, profile: { name: 'brown', hex: '#5c3b26' }, fitted: null },
  placement: { forward_m: null, tilt_deg: null, width_scale: null, default_forward_m: 0.006,
    limits: { forward_m: 0.03, tilt_deg: 20, width_scale: [0.8, 1.3] }, fitted: null },
  chains: { count: null, links: 0, swing: true, stiffness: 1, limits: [0.5, 2], fitted: false },
};
const P = { saved: {}, built: {}, source_url: null,
  landmarks: { chin: 1.47, shoulder: 1.44, shoulder_blades: 1.27, mid_back: 1.14, waist: 1.04 },
  limits: { max_cm: [3, 150], ends_cm: [0.5, 12] }, auto_ends_cm: 3,
  at: ['chin', 'shoulder', 'shoulder_blades', 'mid_back', 'waist'] };
const html = render('haar', hd, info([]), P);
const text = html.replace(/<[^>]+>/g, '|');
const group = (html.match(/>Cut<\/span>[\s\S]*?(?=<\/div><div class="ga-fieldset|$)/) || [''])[0];
check('[6] the group and its choices', [/>Cut</.test(html), /<option value="full" selected="">Full length<\/option>/.test(html),
  /<option value="max">Max length<\/option>/.test(html), /<optgroup label="Ends at"><option value="at:chin">Chin · 147 cm<\/option>/.test(html),
  /<option value="at:shoulder_blades">Shoulder blades · 127 cm<\/option>/.test(html), />Waist · 104 cm<\/option><\/optgroup>/.test(html), /3 cm auto/.test(text)],
[true, true, true, true, true, true, true]);
const saveBtn = (group.match(/<button[^>]*title="Saves the cut — nothing runs"[^>]*>/) || [''])[0];
check('[6] Save disabled without a drag', [!!saveBtn, /disabled=""/.test(saveBtn)], [true, true]);
check('[6] in use', /In use\|*: Full length · soft tip Auto \(3 cm\)/.test(text), true);
check('[6] due line', /Saved, not applied — Re-fit applies it \(no hub job\)/.test(
  render('haar', hd, info(['cut_changed']), P)), true);
check('[6] not cut yet', /In use[^<]*: not cut yet — the next fit cuts it/.test(
  render('haar', hd, info([]), { ...P, built: null })), true);
check('[6] no group in hairdeck mode / without a panel', [/>Cut</.test(render('hairdeck', hd, info([]), P)),
  />Cut</.test(render('haar', hd, info([]), null))], [false, false]);

console.log('[7] wiring');
const src = (rel) => readFileSync(join(ROOT, rel), 'utf8');
const live = src('frontend/src/tabs/characters/HairLiveControls.tsx');
const tab = src('frontend/src/tabs/characters/FieldHairstyles.tsx');
const viewer = src('frontend/src/tabs/characters/Model3DViewer.tsx');
const route = src('app/routes/characters.py');
const cutGroup = (live.match(/<Group title=\{t\('Cut'\)\}>[\s\S]*?<\/Group>/) || [''])[0];
check('[7] Save / Automatic post the setting only', [
  /post\('cut', cutPostBody\(cut\)\)/.test(cutGroup), /post\('cut', cutPostBody\(\{\}\)\)/.test(cutGroup),
  (cutGroup.match(/post\(/g) || []).length, /apiPost|apiGet|fetch\(/.test(cutGroup),
  /apiPost\(`\/characters\/\$\{enc\}\/hair\/\$\{path\}`, \{ \.\.\.body, item_id: itemId \}\)/.test(live)],
[true, true, 2, false, true]);
check('[7] the tab previews live', [
  /haarPanel\?\.cut\?\.source_url/.test(tab), /cutOverride\(cutSource\.source, cutSource\.rails, drafts\.cut\)/.test(tab),
  /\{ match: `garment_hair_\$\{info\.item_id\}`, map, tint, cut \}/.test(tab), /cutRuler\(/.test(tab),
  /cutPanel=\{isHaar \? haarPanel\?\.cut \?\? null : null\} cutLive=\{cutLive\}/.test(tab)],
[true, true, true, true, true]);
check('[7] the viewer writes positions and v, restores, pauses the strands', [
  /uv\.setY\(i, i < nCut && cut \? cut\.v\[i\] : target\.baseV\[i\]\)/.test(viewer),
  /cut\.positions\[i \* 3\]/.test(viewer), /baseV\[i\] = uv\.getY\(i\)/.test(viewer),
  /if \(adjust\?\.map \|\| adjust\?\.cut \|\| match !== adjustMatch\) strandOn\(false\)/.test(viewer),
  /const paused = !!meshAdjustRef\.current\?\.map \|\| !!meshAdjustRef\.current\?\.cut/.test(viewer)],
[true, true, true, true, true]);
const block = (re) => (route.match(re) || [''])[0];
check('[7] routes are admin-only', [
  /Depends\(require_admin\)/.test(block(/@router\.post\("\/\{character_name\}\/hair\/cut"\)[\s\S]*?\n\n\n/)),
  /Depends\(require_admin\)/.test(block(/@router\.get\("\/\{character_name\}\/garments\/\{item_id\}\/haar-cut-source"\)[\s\S]*?\n\n\n/))],
[true, true]);
check('[7] no native dialog', [live, tab, src('frontend/src/tabs/characters/hairCut.ts')]
  .some((s) => /window\.(prompt|alert|confirm)\(/.test(s)), false);

if (failures.length) {
  console.error(`\nFAIL (${failures.length})`);
  for (const f of failures) console.error(`  ${f}`);
  process.exit(1);
}
console.log('\nALL OK');
