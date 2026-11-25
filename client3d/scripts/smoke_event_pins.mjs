#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/event_pins.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_event_pins.mjs
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
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
