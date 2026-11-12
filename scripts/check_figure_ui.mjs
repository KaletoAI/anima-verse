#!/usr/bin/env node
/**
 * Check of the figure UI's pure helpers — `frontend/src/tabs/characters/figureModel.ts`
 * (plan docs/superpowers/plans/2026-11-12-unified-worn-pieces.md, Task 9; Task 10 extends it).
 *
 * Usage:  node scripts/check_figure_ui.mjs
 *
 * Self-bundling via esbuild (like scripts/check_footwear.mjs); no server, no world. Exit 1 on the first
 * mismatch list, 0 when every case holds.
 *
 * ============================================================================
 * THE CASES, DERIVED BY HAND (plan "Global Constraints", Task 9 "Interfaces", spec rulings 3, 5, 6)
 * ============================================================================
 * [1] Labels, verbatim from the plan:
 *       MESH_MODE_LABELS  own_mesh → "Own mesh", painted → "Painted", in_body → "In the body"
 *       HAIR_MODE_LABELS  hairdeck → "HairDeck", haar → "HAAR", body → "In the body"
 *     MESH_MODES / HAIR_MODES list them in that order (the select's order).
 * [2] hairModeDisabled: HAAR is listed but not built (ruling 6) → 'haar' = "not built yet";
 *     'hairdeck' and 'body' are selectable → null.
 * [3] wearersLine(n, hubJobs) — ruling 3, "worn by K characters now" + "Build for them (cost)":
 *       (0, 0)    → text "worn by 0 characters now", button null, reason "Nobody wears it now"
 *       (2, 7)    → text "worn by 2 characters now", button "Build for them (7 hub jobs)", reason null
 *       (2, null) → button "Build for them (cost unknown)" (a wearer's cost is unknown → the total is)
 *       (1, 1)    → singular both ways: "worn by 1 character now", "Build for them (1 hub job)"
 * [4] defaultMeshMode(slots) mirrors `garment_set.default_mesh_mode` (spec Q2): exactly feet → own_mesh;
 *       outer among them, or both top and bottom → in_body; everything else → painted:
 *       ['feet'] → own_mesh · ['legs','feet'] → painted (not feet ALONE) · ['outer'] → in_body ·
 *       ['top','bottom'] → in_body · ['top'] → painted · [] → painted
 * [5] meshModeOf(stored, slots): a stored valid mode wins ('in_body' on ['feet'] → in_body); '' or an
 *       unknown word → the kind default (''/['feet'] → own_mesh, 'own'/['top'] → painted).
 * [6] figureBuildLine(changes, hubJobs) — the hair row's line after a mode change (the character's own
 *       Build, POST /characters/{c}/figure/build):
 *       (0, 0)    → text "No changes", button null, reason "Nothing to build"
 *       (2, 7)    → text "2 changes", button "Build (7 hub jobs)", reason null
 *       (1, null) → text "1 change", button "Build (cost unknown)"
 *       (1, 0)    → button "Build (0 hub jobs)" (CPU-only work is still a Build)
 * [7] Source greps: `WardrobeGarment.tsx` exports no `OwnMeshToggle` (MeshModeSelect replaces it);
 *     `ItemForm.tsx` has no mode checkbox (`mesh_mode === 'own_mesh'` gone — the mode is read-only
 *     there) and `itemsModel.ts`'s draftToBody no longer sends `mesh_mode` (a stale form never
 *     overwrites a Wardrobe choice: `inventory.update_item` keeps the stored mode when the key is
 *     absent); `FootwearSteps.tsx` no longer claims "×1.50 high" for every shoe (Ruling 15i: the
 *     height scale is only for a closed toe box, only as a second try).
 */
import { readFileSync } from 'node:fs';
import { mkdtemp, rm } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const require_ = createRequire(import.meta.url);

function esbuildModule() {
  for (const cand of ['esbuild',
                      join(ROOT, 'frontend/node_modules/esbuild'),
                      join(ROOT, 'client3d/node_modules/esbuild')]) {
    try {
      return require_(cand);
    } catch { /* next candidate */ }
  }
  console.error('esbuild not found (npm install) — nothing was checked');
  process.exit(1);
}

async function loadBundled(src) {
  const esbuild = esbuildModule();
  const dir = await mkdtemp(join(tmpdir(), 'check-figure-ui-'));
  try {
    const file = join(dir, 'module.mjs');
    await esbuild.build({
      entryPoints: [src], outfile: file, bundle: true, format: 'esm',
      platform: 'neutral', logLevel: 'silent', absWorkingDir: ROOT,
    });
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

const failures = [];
function check(label, got, want) {
  const g = JSON.stringify(got);
  const w = JSON.stringify(want);
  if (g !== w) failures.push(`${label}: got ${g}, want ${w}`);
  else console.log(`ok  ${label}`);
}

let m;
try {
  m = await loadBundled(join(ROOT, 'frontend/src/tabs/characters/figureModel.ts'));
} catch (e) {
  console.error(`FAIL figureModel.ts not loadable: ${e.message}`);
  process.exit(1);
}

// [1]
check('[1] MESH_MODE_LABELS', m.MESH_MODE_LABELS,
  { own_mesh: 'Own mesh', painted: 'Painted', in_body: 'In the body' });
check('[1] HAIR_MODE_LABELS', m.HAIR_MODE_LABELS,
  { hairdeck: 'HairDeck', haar: 'HAAR', body: 'In the body' });
check('[1] MESH_MODES order', m.MESH_MODES, ['own_mesh', 'painted', 'in_body']);
check('[1] HAIR_MODES order', m.HAIR_MODES, ['hairdeck', 'haar', 'body']);

// [2]
check('[2] haar disabled', m.hairModeDisabled('haar'), 'not built yet');
check('[2] hairdeck selectable', m.hairModeDisabled('hairdeck'), null);
check('[2] body selectable', m.hairModeDisabled('body'), null);

// [3]
check('[3] wearersLine(0, 0)', m.wearersLine(0, 0),
  { text: 'worn by 0 characters now', button: null, reason: 'Nobody wears it now' });
check('[3] wearersLine(2, 7)', m.wearersLine(2, 7),
  { text: 'worn by 2 characters now', button: 'Build for them (7 hub jobs)', reason: null });
check('[3] wearersLine(2, null)', m.wearersLine(2, null),
  { text: 'worn by 2 characters now', button: 'Build for them (cost unknown)', reason: null });
check('[3] wearersLine(1, 1)', m.wearersLine(1, 1),
  { text: 'worn by 1 character now', button: 'Build for them (1 hub job)', reason: null });

// [4]
check('[4] feet', m.defaultMeshMode(['feet']), 'own_mesh');
check('[4] legs+feet', m.defaultMeshMode(['legs', 'feet']), 'painted');
check('[4] outer', m.defaultMeshMode(['outer']), 'in_body');
check('[4] top+bottom', m.defaultMeshMode(['top', 'bottom']), 'in_body');
check('[4] top', m.defaultMeshMode(['top']), 'painted');
check('[4] none', m.defaultMeshMode([]), 'painted');

// [5]
check('[5] stored wins', m.meshModeOf('in_body', ['feet']), 'in_body');
check('[5] empty -> default', m.meshModeOf('', ['feet']), 'own_mesh');
check('[5] unknown -> default', m.meshModeOf('own', ['top']), 'painted');

// [6]
check('[6] figureBuildLine(0, 0)', m.figureBuildLine(0, 0),
  { text: 'No changes', button: null, reason: 'Nothing to build' });
check('[6] figureBuildLine(2, 7)', m.figureBuildLine(2, 7),
  { text: '2 changes', button: 'Build (7 hub jobs)', reason: null });
check('[6] figureBuildLine(1, null)', m.figureBuildLine(1, null),
  { text: '1 change', button: 'Build (cost unknown)', reason: null });
check('[6] figureBuildLine(1, 0)', m.figureBuildLine(1, 0),
  { text: '1 change', button: 'Build (0 hub jobs)', reason: null });

// [7]
const src = (p) => readFileSync(join(ROOT, p), 'utf8');
check('[7] no OwnMeshToggle export',
  /export\s+function\s+OwnMeshToggle\b/.test(src('frontend/src/tabs/characters/WardrobeGarment.tsx')), false);
check('[7] MeshModeSelect exported',
  /export\s+function\s+MeshModeSelect\b/.test(src('frontend/src/tabs/characters/WardrobeGarment.tsx')), true);
check('[7] Items form: no mode checkbox',
  src('frontend/src/tabs/items/ItemForm.tsx').includes("mesh_mode === 'own_mesh'"), false);
const draftToBody = src('frontend/src/tabs/items/itemsModel.ts').split('export function draftToBody')[1] || '';
check('[7] draftToBody sends no mesh_mode', /mesh_mode/.test(draftToBody.split('\nexport ')[0]), false);
check('[7] footwear hint: no flat ×1.50 high claim',
  src('frontend/src/tabs/characters/FootwearSteps.tsx').includes('×1.50 high'), false);

if (failures.length) {
  console.error(`\nFAIL (${failures.length})`);
  for (const f of failures) console.error(`  ${f}`);
  process.exit(1);
}
console.log('\nALL OK');
