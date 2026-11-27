#!/usr/bin/env node
/**
 * Source-level smoke check for HUD item menu and Look modal
 * (plan docs/superpowers/plans/2026-11-27-items-in-world.md, Task 9).
 *
 * Usage:  node scripts/smoke_hud_item_menu.mjs
 *
 * Plain Node, reads source files as text, no server or world DB.
 *
 * Expected checks (derived by hand from Task 9):
 * [1] hud/src/hud/ItemMenu.tsx and hud/src/hud/ItemLookModal.tsx exist.
 * [2] ItemLookModal.tsx portals to document.body via createPortal(.
 * [3] Neither file calls native browser dialogs (window.alert / window.confirm /
 *     window.prompt or bare alert( / confirm( / prompt( — expected 0 hits).
 * [4] No bare English text in JSX: />[A-Za-z][^<{]*</ matches 0 times in both files.
 * [5] hud/src/hud/bus.ts declares itemMenu and pickItemAction (plus closeItemMenu).
 * [6] hud/src/hud/bridge.ts gameNames includes 'pickItemAction' and 'closeItemMenu'.
 * [7] hud/src/hud/Hud.tsx renders <ItemMenu and <ItemLookModal.
 */
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const ITEM_MENU_PATH = join(ROOT, 'hud/src/hud/ItemMenu.tsx');
const LOOK_MODAL_PATH = join(ROOT, 'hud/src/hud/ItemLookModal.tsx');
const BUS_PATH = join(ROOT, 'hud/src/hud/bus.ts');
const BRIDGE_PATH = join(ROOT, 'hud/src/hud/bridge.ts');
const HUD_PATH = join(ROOT, 'hud/src/hud/Hud.tsx');

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

// [1] Both files exist
const menuExists = existsSync(ITEM_MENU_PATH);
const modalExists = existsSync(LOOK_MODAL_PATH);
check('[1] ItemMenu.tsx exists', menuExists);
check('[1] ItemLookModal.tsx exists', modalExists);
if (!menuExists || !modalExists) {
  console.error(`\nFAILED (${failures.length}): ${failures.join('; ')}`);
  process.exit(1);
}

const menuSrc = readFileSync(ITEM_MENU_PATH, 'utf8');
const modalSrc = readFileSync(LOOK_MODAL_PATH, 'utf8');

// [2] ItemLookModal.tsx contains createPortal(
check('[2] ItemLookModal.tsx contains createPortal(', modalSrc.includes('createPortal('));

// [3] Neither file contains native dialog calls
const forbiddenDialogs = [
  'window.alert',
  'window.confirm',
  'window.prompt',
  'alert(',
  'confirm(',
  'prompt(',
];
for (const [name, src] of [
  ['ItemMenu.tsx', menuSrc],
  ['ItemLookModal.tsx', modalSrc],
]) {
  const hits = forbiddenDialogs.filter((tok) => src.includes(tok));
  check(`[3] ${name} has no native dialog tokens`, hits.length === 0, hits.join(', '));
}

// [4] No bare English text in JSX: />[A-Za-z][^<{]*</ must find nothing
const bareJsxRe = />[A-Za-z][^<{]*</g;
for (const [name, src] of [
  ['ItemMenu.tsx', menuSrc],
  ['ItemLookModal.tsx', modalSrc],
]) {
  const matches = src.match(bareJsxRe) || [];
  check(`[4] ${name} has no bare English JSX text`, matches.length === 0, matches.join(' | '));
}

// [5] bus.ts declares itemMenu and pickItemAction
const busSrc = readFileSync(BUS_PATH, 'utf8');
check('[5] bus.ts declares itemMenu', /\bitemMenu\s*:/.test(busSrc));
check('[5] bus.ts declares pickItemAction', /\bpickItemAction\?\s*:/.test(busSrc));
check('[5] bus.ts declares closeItemMenu', /\bcloseItemMenu\?\s*:/.test(busSrc));

// [6] bridge.ts gameNames contains 'pickItemAction' and 'closeItemMenu'
const bridgeSrc = readFileSync(BRIDGE_PATH, 'utf8');
const gameNamesMatch = bridgeSrc.match(/const\s+gameNames\s*=\s*\[([\s\S]*?)\]\s*as\s+const/);
const gameNamesBlock = gameNamesMatch ? gameNamesMatch[1] : '';
check(
  "[6] bridge.ts gameNames contains 'pickItemAction'",
  /['"]pickItemAction['"]/.test(gameNamesBlock),
);
check(
  "[6] bridge.ts gameNames contains 'closeItemMenu'",
  /['"]closeItemMenu['"]/.test(gameNamesBlock),
);

// [7] Hud.tsx renders <ItemMenu and <ItemLookModal
const hudSrc = readFileSync(HUD_PATH, 'utf8');
check('[7] Hud.tsx renders <ItemMenu', hudSrc.includes('<ItemMenu'));
check('[7] Hud.tsx renders <ItemLookModal', hudSrc.includes('<ItemLookModal'));

if (failures.length > 0) {
  console.error(`\nFAILED (${failures.length}): ${failures.join('; ')}`);
  process.exit(1);
}
console.log('\nALL OK');
