#!/usr/bin/env node
/**
 * Smoke check for the event pins of the world map — client3d/src/game/eventPins.ts.
 *
 * Usage:  node client3d/scripts/smoke_event_pins.mjs
 *
 * Hand derivations (cases in shared/test-vectors/event_pins.json, shared with
 * the native client's C# tests):
 * [G] pinGlyph: no list or an empty list -> null (no pin); any event whose
 *     category is 'danger' -> 🔥; any other event (also one without a
 *     category) -> ❗.
 * [Y] pinY(groundY, placeHeight) = groundY + placeHeight + PIN_LIFT_M 3.5:
 *     0 + 4 + 3.5 = 7.5; 42.25 + 4 + 3.5 = 49.75; -3 + 0.3 + 3.5 = 0.8;
 *     12 + 0 + 3.5 = 15.5. The ground term is the point of the fix: the pin
 *     used to float at placeHeight + 3.5 ABOVE SEA LEVEL, buried in a hill.
 */
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');

async function load() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(ROOT, 'client3d/scripts/.smoke-'));
  try {
    const built = await esbuild.build({
      entryPoints: [join(ROOT, 'client3d/src/game/eventPins.ts')],
      bundle: true, platform: 'node', format: 'esm', write: false, outfile: join(dir, 'pins.mjs'),
    });
    const file = join(dir, 'pins.mjs');
    await writeFile(file, built.outputFiles[0].text, 'utf8');
    return await import(`file://${file}`);
  } finally { await rm(dir, { recursive: true, force: true }); }
}

const m = await load();
const extra = m.PIN_LIFT_M === 3.5 ? 0 : 1;
console.log(`${extra ? 'FAIL' : '  ok  '} PIN_LIFT_M is 3.5`);
const { passed, failed } = runVectors(loadVectors('event_pins'), { pinGlyph: m.pinGlyph, pinY: m.pinY });
console.log(failed + extra ? `\n${failed + extra} FAILED` : `\nall ok (${passed + 1})`);
process.exit(failed + extra ? 1 : 0);
