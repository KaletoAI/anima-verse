/** Task 31 test-only adapters. No config, model files or recorded expectations.
 * Public JSON signatures and units are documented in shared/test-vectors/README.md.
 */
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { build } from 'esbuild';
import * as THREE from 'three';
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
let loaded;
async function modules() {
  if (!loaded) loaded = (async () => {
    const dir = await mkdtemp(join(root, 'client3d/scripts/.smoke-'));
    try {
      const entry = ['scene/footLock', 'scene/legPin', 'scene/bridgeLift',
        'scene/bridgeTravel', 'scene/bridgeHeading', 'scene/standSettle',
        'scene/footLockMeasure', 'game/stairs', 'game/npcWalk']
        .map((p) => `export * from '${root}client3d/src/${p}.ts';`).join('\n');
      const built = await build({stdin: {contents: entry, resolveDir: root, loader: 'ts'},
        bundle: true, platform: 'node', format: 'esm', write: false,
        external: ['three', 'three/*'], logLevel: 'error'});
      const file = join(dir, 'vectors.mjs');
      await writeFile(file, built.outputFiles[0].text);
      return await import(`file://${file}`);
    } finally { await rm(dir, {recursive: true, force: true}); }
  })();
  return loaded;
}

/** Nonfinite INPUT tags follow the existing E3 convention; outputs stay finite. */
function decode(v) {
  if (Array.isArray(v)) return v.map(decode);
  if (!v || typeof v !== 'object') return v;
  if ('$number' in v) {
    if (!['NaN', 'Infinity', '-Infinity'].includes(v.$number)) throw Error('Unknown number tag');
    return Number(v.$number);
  }
  return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, decode(x)]));
}
const select = (value, fields) => fields.reduce((v, k) => v[k], value);
const sub = (a, b) => a.map((x, i) => x - b[i]);
const add = (a, b) => a.map((x, i) => x + b[i]);
function rot([w,x,y,z], v) {
  return [[1-2*(y*y+z*z), 2*(x*y-w*z), 2*(x*z+w*y)],
    [2*(x*y+w*z), 1-2*(x*x+z*z), 2*(y*z-w*x)],
    [2*(x*z-w*y), 2*(y*z+w*x), 1-2*(x*x+y*y)]]
    .map((r) => r[0]*v[0]+r[1]*v[1]+r[2]*v[2]);
}

/** Construct only the explicitly supplied bones/tracks. Positions use template units. */
function relock(m, data) {
  const rig = new THREE.Group();
  const byName = new Map();
  for (const b of data.bones) {
    const bone = new THREE.Bone();
    bone.name = b.name;
    bone.position.fromArray(b.position);
    if (b.quaternion) bone.quaternion.fromArray(b.quaternion);
    byName.set(b.name, bone);
  }
  for (const b of data.bones) (b.parent === null ? rig : byName.get(b.parent)).add(byName.get(b.name));
  rig.updateMatrixWorld(true);
  const snapshot = () => JSON.stringify([...byName.values()].map((b) =>
    [b.name, ...b.position.toArray(), ...b.quaternion.toArray()]));
  const before = snapshot();
  const clips = data.clips.map((c) => {
    const tracks = c.tracks.map((t) => new (t.name.endsWith('.quaternion')
      ? THREE.QuaternionKeyframeTrack : THREE.VectorKeyframeTrack)(t.name, t.times, t.values));
    const clip = new THREE.AnimationClip(c.name, c.duration, tracks);
    if (c.path) m.setClipRootPath(clip, {times: Float32Array.from(c.path.times), xz: Float32Array.from(c.path.xz)});
    return clip;
  });
  const prior = clips.map(m.clipRootPath);
  const logs = [];
  const reports = m.relockRootPaths(clips, rig, data.unitsPerCm, (line) => logs.push(line), data.options ?? {});
  const paths = clips.map((clip) => {
    const path = m.clipRootPath(clip);
    if (!path) return null;
    return {times: Array.from(path.times), x: Array.from(path.times, (_, i) => path.xz[2*i]),
      z: Array.from(path.times, (_, i) => path.xz[2*i+1])};
  });
  return {reports, paths, logs, samePaths: clips.map((c, i) => m.clipRootPath(c) === prior[i]),
    reportNames: reports.map((r) => r.clip), untouched: before === snapshot(),
    emptyAndSilent: reports.length === 0 && logs.length === 0,
    finite: reports.every((r) => [r.driftCm, r.importedDriftCm, ...r.travel].every(Number.isFinite))};
}

/** Return a dispatch table so native consumers can mirror the small adapters. */
export async function bridgeVectorDispatch() {
  const m = await modules();
  const dispatch = {
    ...m,
    headingTrack: (...args) => Array.from(m.headingTrack(...args)),
    constant: (name) => { if (!(name in m)) throw Error(`Unknown constant ${name}`); return m[name]; },
    footLockValue: ({tracks, rest, fps}, field) => {
      const ground = m.groundHeights(tracks, rest);
      const weights = m.contactWeights(tracks, ground, fps);
      const path = m.footLockPath(tracks, weights);
      if (field === 'path') return path;
      if (field === 'drift_path') return m.maxPlantedDrift(tracks, weights, path);
      if (field === 'drift_zero_path') return m.maxPlantedDrift(tracks, weights, path.map(() => [0, 0]));
      throw Error(`Unknown foot-lock field ${field}`);
    },
    finiteLiftAt: (...args) => Number.isFinite(m.liftAt(...args)),
    legPinConstants: () => ({PIN_MIN_S:m.PIN_MIN_S, PIN_FADE_S:m.PIN_FADE_S}),
    ikValue: (args, fields) => {
      const [hip, knee, ankle] = args;
      const {upper, lower} = m.twoBoneIk(...args);
      const k = add(hip, rot(upper, sub(knee, hip)));
      const a = add(k, rot(lower, rot(upper, sub(ankle, knee))));
      return select({knee:k, ankle:a, kneeX:k[0], upperLength:Math.hypot(...sub(k, hip)),
        lowerLength:Math.hypot(...sub(a, k)), finite:[...upper,...lower,...k,...a].every(Number.isFinite)}, fields);
    },
    relockValue: (data, fields) => select(relock(m, data), fields),
    hasGroundLiftTolerance: () => m.GROUND_LIFT_TOL_CM !== undefined,
    groundValue: (tracks, rest, fields) => select(m.groundHeights(tracks, rest), fields),
    stairChainValue: (stairs, from, to, fields) => {
      const chain = m.stairChain(stairs, from, to);
      return select(fields[0] === 'landingHeights' ? {landingHeights:[chain[1].y,chain[2].y]} : chain, fields);
    },
    stairLegToValue: (stairs, dest, fields) => select(m.stairLegTo(stairs, dest), fields),
    stairLegsValue: (stairs, chain, fields) => select(m.stairLegs(stairs, chain), fields),
    rideArrivalClearsRun: () => m.RIDE_ARRIVE_M < .5,
    rideSequenceValue: (initial, points, fields) => {
      const ride = structuredClone(initial);
      let step;
      for (const [x,y,z,fromX,fromZ] of points) {
        step = fromX === undefined ? m.rideStep(ride, x, y, z)
          : m.rideStep(ride, x, y, z, {x:fromX, z:fromZ});
        ride.leg = step.leg; ride.armed = step.armed;
      }
      return select({...step, state:{leg:step.leg,armed:step.armed,done:step.done}}, fields);
    },
    // The NPC frame of `scene/npcs.ts` `tick` on dry ground, reduced to what a
    // ride touches: retire (the ride's radius while a ride runs), step, ask
    // the ride from the frame's start point, write the height back.
    rideWalkValue: (walk, dt, fields) => {
      let ride = structuredClone(walk.ride);
      const pos = {x:walk.start[0], y:walk.start[1], z:walk.start[2]};
      let frame = 0, doneFrame = null, doneAt = null;
      const orders = [];
      for (const order of walk.orders) {
        const waypoints = order.waypoints.map(([x,y,z]) => ({x,y,z}));
        const target = {x:order.target[0], y:order.target[1], z:order.target[2]};
        let peakY = -Infinity;
        for (let i = 0, n = Math.round(order.seconds / dt); i < n; i++) {
          frame += 1;
          const from = {x:pos.x, z:pos.z};
          const plan = m.npcGoal(pos, target, waypoints, ride ? m.RIDE_ARRIVE_M : undefined);
          waypoints.splice(0, plan.retired);
          if (plan.moving) {
            const {step} = m.npcStep(plan, 'walk_run', false, dt, 1, 1);
            pos.x += plan.delta.x / plan.distToGoal * step;
            pos.z += plan.delta.z / plan.distToGoal * step;
          }
          let rideY = null;
          if (ride) {
            const s = m.rideStep(ride, pos.x, pos.y, pos.z, from);
            if (s.done) { ride = null; doneFrame = frame; doneAt = [pos.x, pos.z]; }
            else { ride.leg = s.leg; ride.armed = s.armed; rideY = s.y; }
          }
          pos.y = rideY ?? m.easeNpcY(pos.y, (waypoints[0] ?? target).y, dt);
          peakY = Math.max(peakY, pos.y);
        }
        orders.push({pos:[pos.x, pos.y, pos.z], peakY});
      }
      return select({doneFrame, doneTime:doneFrame === null ? null : doneFrame * dt, doneAt,
        ride:ride && {leg:ride.leg, armed:ride.armed}, orders}, fields);
    },
  };
  return Object.fromEntries(Object.entries(dispatch).filter(([,v]) => typeof v === 'function')
    .map(([k, fn]) => [k, (...args) => fn(...decode(args))]));
}

export async function runBridgeVectors(name) {
  return runVectors(loadVectors(name), await bridgeVectorDispatch());
}
