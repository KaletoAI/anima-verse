#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/scene_view.md (E1, 2026-11-25).
 * Usage: node client3d/scripts/smoke_scene_view.mjs
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import { build } from 'esbuild';
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';
const built = await build({ entryPoints: ['client3d/src/scene/sceneView.ts'], bundle: true,
  platform: 'node', format: 'esm', write: false });
const view = await import(`data:text/javascript;base64,${Buffer.from(built.outputFiles[0].text).toString('base64')}`);
const { passed, failed } = runVectors(loadVectors('scene_view'), view);
console.log(`${passed} ok, ${failed} failed`);
process.exitCode = failed ? 1 : 0;
