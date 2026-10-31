/** HUD notices are clickable in every host, and no HUD option list is white.
 * Usage: node scripts/smoke_hud_notice_hits.mjs
 *
 * A native/iframe host passes a click to the HUD only inside the measured
 * hitRects (client3d/src/hud/Hud.tsx). The notice banner's root is zero-height
 * by design, so measuring `.hud-notices` found nothing and × on a notification
 * reached the 3D scene (no POST /notifications/{id}/read in the log,
 * 2026-10-31).
 *
 * Hand-derived from one movement block, one event and two notifications
 * (packages/player-ui/src/NoticeBanner.tsx):
 * a. Five `player-notice` rows: the block, the event, two notifications and
 *    the "Mark all as read" row (shown from the second notification on).
 * b. All three buttons (two ×, one "Mark all as read") sit inside such a row.
 * c. The hitRects selector measures `.hud-notices .player-notice`, never the
 *    bare zero-height `.hud-notices`.
 * d. client3d/src/hud/hud.css gives `#hud option` a background-color — the
 *    open list of ANY select, whatever its class (it came back white with
 *    `.player-chip` after `.ga-input` had been fixed on its own).
 */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';
const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const ts = require('typescript');
const read = path => readFile(new URL(`../${path}`, import.meta.url), 'utf8');
const jsx = (type, props) => ({ type, props });

const DATA = {
  avatar: 'Kai', events: [{ id: 'e1', category: 'danger', text: 'Storm' }],
  leave_blocked: 'Locked in', force_warning: null, unread_count: 2,
  notifications: [{ id: 1, kind: 'outfit_mismatch', body: 'one' }, { id: 2, kind: 'outfit_mismatch', body: 'two' }],
};
const module = { exports: {} };
runInNewContext(ts.transpileModule(await read('packages/player-ui/src/NoticeBanner.tsx'), { compilerOptions: {
  target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
} }).outputText, { module, exports: module.exports, require: id => ({
  react: { useState: () => [DATA, () => {}], useEffect() {}, useCallback: fn => fn },
  'react/jsx-runtime': { jsx, jsxs: jsx, Fragment: 'fragment' },
  './syncEndpoints': { SYNC_ENDPOINTS: {} }, './I18nProvider': { useI18n: () => ({ t: text => text }) },
  './api': { apiGet() {}, apiPost() {} }, './usePolling': { usePoll: () => ({ data: DATA }) },
})[id] ?? (() => { throw new Error(`Unexpected import ${id}`) })() });

const walk = (tree, inside, out) => {
  if (Array.isArray(tree)) { for (const t of tree) walk(t, inside, out); return out; }
  if (!tree || typeof tree !== 'object') return out;
  const row = tree.props?.className === 'player-notice';
  if (row) out.rows += 1;
  if (tree.type === 'button') out.buttons.push(inside || row);
  walk(tree.props?.children, inside || row, out);
  return out;
};
const found = walk(module.exports.NoticeBanner(), false, { rows: 0, buttons: [] });
assert.equal(found.rows, 5);
console.log('PASS a: every visible notice row is marked player-notice');
assert.deepEqual(found.buttons, [true, true, true]);
console.log('PASS b: every notice button lies inside a measured row');

const hud = await read('client3d/src/hud/Hud.tsx');
assert.match(hud, /\.hud-notices \.player-notice'/);
assert.doesNotMatch(hud, /\.hud-notices'/);
console.log('PASS c: hitRects measure the rows, not the zero-height root');

const css = await read('client3d/src/hud/hud.css');
const rule = css.match(/#hud option,[^{]*\{([^}]*)\}/);
assert.ok(rule && /background-color:/.test(rule[1]), 'no #hud option background-color rule');
console.log('PASS d: every HUD option list has a background colour');
