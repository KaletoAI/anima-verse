/** Shape adapters only. Expectations and derivations live in the source smoke. */
import { readFile } from 'node:fs/promises';
import ts from 'typescript';
import { build } from 'esbuild';
import * as THREE from 'three';

async function loadTs(path) {
  const source = await readFile(new URL(path, import.meta.url), 'utf8');
  const code = ts.transpileModule(source, { compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022,
  } }).outputText.replace(/from ['"]three['"]/g, `from '${import.meta.resolve('three')}'`);
  return import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
}
export const motion = await loadTs('../src/game/propActionMotion.ts');
export const glyphs = await loadTs('../src/scene/placeGlyphs.ts');
export { THREE };
const choicesBuild = await build({
  stdin: { contents: `export { propActionChoices } from ${JSON.stringify(new URL('../../packages/player-ui/src/propActions.ts', import.meta.url).pathname)}`,
    resolveDir: new URL('../../', import.meta.url).pathname, loader: 'ts' },
  bundle: true, platform: 'node', format: 'esm', write: false,
});
const { propActionChoices } = await import(`data:text/javascript;base64,${Buffer.from(choicesBuild.outputFiles[0].text).toString('base64')}`);

function pickablePropRows({ props, entries, offers }) {
  const objects = new Map(props.map(p => [p.id, new THREE.Group()]));
  const refs = props.map(p => ({ ...p, object: p.mounted ? objects.get(p.id) : null }));
  const geometry = new Map(entries.map(([id, e]) => [id, {
    ...e, slots: e.slots.map(p => new THREE.Vector3(...p)),
  }]));
  return glyphs.pickableProps(refs, geometry, offers).map(row => ({
    id: props.find(p => objects.get(p.id) === row.object).id,
    role: row.role, places: row.places,
  }));
}

async function manualGateTrace(steps, journeys) {
  const gate = motion.createManualPropGate();
  const attempts = new Map(), deferred = new Map();
  let calls = 0;
  const rows = [];
  for (const step of steps) {
    const extra = {};
    if (step.op === 'cancel') {
      const promise = gate.cancel(step.execution, step.journey, () => {
        calls++;
        return new Promise((resolve, reject) => { deferred.set(step.id, { resolve, reject }); });
      });
      if (step.same_as) extra.samePromise = promise === attempts.get(step.same_as).promise;
      // Attach rejection handling immediately; cancellation failure is a trace result.
      attempts.set(step.id, { promise, result: promise.then(() => 'resolved', () => 'rejected') });
    } else if (step.op === 'settle') {
      const pending = deferred.get(step.id);
      if (step.accept) pending.resolve(); else pending.reject(new Error('fixture cancellation refused'));
      extra.result = await attempts.get(step.id).result;
    } else throw new Error(`Unknown manual gate operation: ${step.op}`);
    rows.push({ pending: gate.pending, calls, withdrawn: journeys.map(j => gate.withdrawn(j)), ...extra });
  }
  if (gate.pending) throw new Error('Unsettled cancellation in trace');
  return rows;
}

function preparationTrace(steps) {
  const barrier = motion.createPropPreparationBarrier();
  return steps.map(step => {
    const extra = {};
    switch (step.op) {
      case 'begin': barrier.begin(step.id, step.now); break;
      case 'changed': barrier.changed(step.id); break;
      case 'adopt': barrier.adoptFreshState(); break;
      case 'expire': extra.expired = barrier.expire(step.now); break;
      default: throw new Error(`Unknown preparation operation: ${step.op}`);
    }
    return { pending: barrier.pending, ...extra };
  });
}

async function positionDrainTrace(steps, waiters) {
  const drain = motion.createPositionDrain();
  const finishes = new Map(), settled = new Set();
  const rows = [];
  for (const step of steps) {
    switch (step.op) {
      case 'begin': finishes.set(step.id, drain.begin()); break;
      case 'finish': finishes.get(step.id)(); finishes.delete(step.id); break;
      case 'wait': void drain.wait().then(() => settled.add(step.id)); break;
      default: throw new Error(`Unknown drain operation: ${step.op}`);
    }
    await Promise.resolve();
    rows.push({ drained: waiters.map(id => settled.has(id)) });
  }
  if (finishes.size) throw new Error('Unfinished position write in trace');
  return rows;
}

export const propActionDispatch = {
  propActionChoices,
  sampleMotion: motion.sampleMotion,
  localApproachPoint: motion.localApproachPoint,
  entryPhase: motion.entryPhase,
  entrySupportLift: motion.entrySupportLift,
  entryIdentity: motion.entryIdentity,
  entryClipSample(entry, age) {
    const phase = motion.entryPhase(entry, age);
    return { phase, clip_s: phase * entry.clip_duration_s };
  },
  entrySupportSample(v) {
    const lift = motion.entrySupportLift(v.first_hips_y, v.last_hips_y, v.hips_y,
      v.access_y, v.anchor_y, v.root_offset);
    return { supported: lift !== null, lift };
  },
  pickablePropRows, manualGateTrace, preparationTrace, positionDrainTrace,
};
