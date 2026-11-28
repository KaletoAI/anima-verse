#!/usr/bin/env node
/**
 * Source-level smoke check for Game-Admin -> Items -> Mesh tab
 * (plan docs/superpowers/plans/2026-11-27-items-in-world.md, Task 4).
 *
 * Usage:  node scripts/smoke_item_mesh_tab.mjs
 *
 * Plain Node, reads source files as text, no server or world DB.
 *
 * Expected checks (derived by hand from Task 4 + item face count brief):
 * [1] frontend/src/tabs/items/ItemMeshTab.tsx exists and calls /mesh/generate,
 *     /mesh/reduce, /mesh/copy, /mesh/status and /model/meta.
 * [2] No window.confirm, window.alert, window.prompt and no bare confirm(/alert(.
 * [3] Every user-visible string literal in JSX text goes through t( and all
 *     required new strings appear inside t('...').
 * [4] frontend/src/tabs/items/ItemsTab.tsx imports ItemMeshTab.
 * [5] ItemMeshTab has the "Face count" numeric input defaulting to 20000,
 *     sends face_num on /mesh/generate, and has the reduce button posting /mesh/reduce.
 */
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const MESH_TAB_PATH = join(ROOT, 'frontend/src/tabs/items/ItemMeshTab.tsx');
const ITEMS_TAB_PATH = join(ROOT, 'frontend/src/tabs/items/ItemsTab.tsx');

const failures = [];
function check(label, ok, detail = '') {
  if (ok) {
    console.log(`OK    ${label}`);
  } else {
    const msg = detail ? `${label} (${detail})` : label;
    console.log(`FAIL  ${msg}`);
    failures.push(msg);
  }
}

function stripCommentsAndStrings(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\/\/[^\n]*/g, '')
    .replace(/'(?:[^'\\\n]|\\.)*'/g, "''")
    .replace(/"(?:[^"\\\n]|\\.)*"/g, '""')
    .replace(/`(?:[^`\\]|\\.)*`/g, '``');
}

// [1] File existence & API routes
const meshExists = existsSync(MESH_TAB_PATH);
check('[1] ItemMeshTab.tsx exists', meshExists);
if (!meshExists) {
  process.exit(1);
}

const meshSrc = readFileSync(MESH_TAB_PATH, 'utf8');
for (const route of ['/mesh/generate', '/mesh/reduce', '/mesh/copy', '/mesh/status', '/model/meta']) {
  check(`[1] ItemMeshTab.tsx mentions ${route}`, meshSrc.includes(route));
}

// [2] No native dialogs
const codeOnly = stripCommentsAndStrings(meshSrc);
check(
  '[2] no window.confirm / window.alert / window.prompt',
  !/\bwindow\.(?:confirm|alert|prompt)\s*\(/.test(codeOnly),
);
check(
  '[2] no bare confirm( / alert( / prompt(',
  !/(?<![\w.$])(?:confirm|alert|prompt)\s*\(/.test(codeOnly),
);

// [3] Required UI strings wrapped in t('...') and no bare JSX text literals
const requiredStrings = [
  'Placeable in the world',
  'Size — longest edge (m)',
  'Default 0.25 m. A key is about 0.08 m, a book 0.25 m, a chair 0.9 m, a person 1.70 m.',
  'Face count',
  '{n} faces',
  'Generate mesh',
  'Regenerate mesh',
  'Reduce to {n} faces',
  'Reduction queued',
  'Already at or below {n} faces',
  'Generate the item image first',
  'Use mesh of another item',
  'Delete mesh',
  'Delete mesh?',
  'Confirm',
  'Cancel',
];
for (const str of requiredStrings) {
  const escaped = str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const re = new RegExp(`\\bt\\(\\s*['"]${escaped}['"]\\s*\\)`);
  check(`[3] t('${str}') present`, re.test(meshSrc));
}

// Check that no JSX tag directly wraps bare alphabetic text outside { ... }
function stripJsxExpressions(jsx) {
  let out = '';
  let depth = 0;
  let quote = null;
  for (let i = 0; i < jsx.length; i += 1) {
    const ch = jsx[i];
    if (quote) {
      if (ch === '\\') { i += 1; continue; }
      if (ch === quote) quote = null;
      continue;
    }
    if (depth > 0) {
      if (ch === "'" || ch === '"' || ch === '`') { quote = ch; continue; }
      if (ch === '{') depth += 1;
      else if (ch === '}') {
        depth -= 1;
        if (depth === 0) out += '{}';
      }
      continue;
    }
    if (ch === '{') {
      depth = 1;
      continue;
    }
    out += ch;
  }
  return out;
}

const returnIdx = meshSrc.indexOf('\n  return (');
const jsxOnly = returnIdx >= 0 ? stripJsxExpressions(meshSrc.slice(returnIdx)) : '';
const jsxBareText = [];
const jsxTextRe = />([^<>{}]+)</g;
let m;
while ((m = jsxTextRe.exec(jsxOnly)) !== null) {
  const txt = m[1].trim();
  if (/[A-Za-z]/.test(txt)) {
    jsxBareText.push(txt);
  }
}
check(
  '[3] no bare user-visible English text in JSX',
  returnIdx >= 0 && jsxBareText.length === 0,
  jsxBareText.join(' | '),
);

// [4] ItemsTab imports ItemMeshTab
const itemsSrc = existsSync(ITEMS_TAB_PATH) ? readFileSync(ITEMS_TAB_PATH, 'utf8') : '';
check(
  '[4] ItemsTab.tsx imports ItemMeshTab',
  /import\s+\{[^}]*\bItemMeshTab\b[^}]*\}\s+from\s+['"]\.\/ItemMeshTab['"]/.test(itemsSrc),
);

// [5] Face count field (default 20000), face_num sent on generate, reduce button posts /mesh/reduce
check(
  '[5] Face count defaults to 20000',
  /DEFAULT_FACE_NUM\s*=\s*20000\b/.test(meshSrc) &&
    /useState\(\s*(?:String\(\s*DEFAULT_FACE_NUM\s*\)|['"]20000['"]|20000)\s*\)/.test(meshSrc),
);
check(
  '[5] Face count numeric input bounds (500..200000, step 1000)',
  /MIN_FACE_NUM\s*=\s*500\b/.test(meshSrc) &&
    /MAX_FACE_NUM\s*=\s*200000\b/.test(meshSrc) &&
    /step=\{1000\}/.test(meshSrc),
);
check(
  '[5] /mesh/generate sends face_num',
  /\/mesh\/generate[`'"]\s*,\s*\{\s*face_num\b/.test(meshSrc),
);
check(
  '[5] reduce button posts /mesh/reduce with face_num',
  /\/mesh\/reduce[`'"]\s*,\s*\{\s*face_num\b/.test(meshSrc) &&
    meshSrc.includes("t('Reduce to {n} faces')"),
);

if (failures.length > 0) {
  console.error(`\nFAILED (${failures.length}): ${failures.join('; ')}`);
  process.exit(1);
}
console.log('\nALL OK');
