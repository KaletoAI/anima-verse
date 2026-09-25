import * as THREE from 'three';
import * as SkeletonUtils from 'three/addons/utils/SkeletonUtils.js';
import { normBoneName } from '@anima/scene-render';
import { clipRootPath, setClipRootPath, travelAt } from './bridgeTravel';
import type { RootPath } from './bridgeTravel';
import {
  CONTACT_POINTS, FULL, contactWeights, footLockPath, groundHeights, maxPlantedDrift,
} from './footLock';
import type { Tracks, Vec3 } from './footLock';

/**
 * THE FOOT LOCK PER RIG — a bridge clip's root travel rebuilt on each model's
 * OWN skeleton.
 *
 * The importer bakes a foot-locked travel into a bridge clip (`get-up-chair`,
 * `get-up-bed`), measured on the REFERENCE rig. `figures.adaptExternalClips`
 * carries it over, scaled by a hips-height ratio — but a real rig has other
 * proportions (leg length, foot length, hips width), so the planted feet of
 * the adapted clip slide by a different amount than the reference rig's did,
 * and the imported travel no longer cancels that slide (measured on the bed:
 * 4.76 cm on Test3_mia, 2.95 cm on Soldier; 1.31 cm on the reference rig).
 *
 * The rule is the importer's own (`footLock.ts`, twin of `_root_motion.py`),
 * run on the ADAPTED clip playing on a CLONE of the model's template: the
 * adapted hips track has no XZ any more, so the foot bones are read "in
 * place" — a planted foot slides backwards by exactly the travel the path
 * rebuilds — which is what `footLockPath` expects.
 *
 * The imported path stays the real fallback, never a silent zero: a rig
 * without the four contact bones, or one on which no point ever reaches full
 * contact (feet hovering because of its proportions), keeps it — a zero path
 * there would put the figure back into the chair after standing up. And it
 * is kept wherever the rebuilt path would not drift LESS than it on the same
 * contacts: the rebuild is never worse than the import.
 *
 * Units: the probe measures in TEMPLATE units; `unitsPerCm` (template units
 * per world centimetre at the model's nominal scale, `1 / (100 · scale)`)
 * turns them into the centimetres the contact bands are written in, and the
 * path back. The stored path is relative to frame 0, in template units, in the
 * clip frame — the same contract as the imported one (`clipRootPath`), so
 * `Figure` applies it unchanged (× `baseScale`).
 *
 * Side-effect free on the template: the clone is posed, never the template
 * (the `clipGround.measureGroundOffsets` pattern), and every clip is uncached
 * from the probe's mixer again.
 */

export interface RelockReport {
  clip: string;
  /** Whose travel the clip carries now: rebuilt on this rig, or the import's. */
  used: 'rig' | 'imported';
  /** Why the imported path was kept: 'no foot bones' | 'no full contact' |
   *  'imported holds better' (the rebuilt path would not drift less). */
  reason?: string;
  /** Largest planted-point drift with the path rebuilt on this rig, cm (0
   *  when nothing was measured or no full-contact run exists). */
  driftCm: number;
  /** The same measurement with the imported path, cm — the comparison. */
  importedDriftCm: number;
  /** End of the path in use, clip frame (x, z), cm at the nominal scale. */
  travel: [number, number];
}

/** How far over its bind-pose rest height a point may stand and still have
 *  its planted height taken as its ground, cm (`groundHeights`' lift
 *  tolerance; the importer uses 0).
 *
 *  The client measures ADAPTED clips, and `figures.adaptExternalClips` lifts
 *  them as a whole: the vertical hips chain scales the bounce against the
 *  idle clip's hips median (110.18 units) up to the rig's rest (113.03), so
 *  on the reference rig itself the standing feet of `get-up-chair` sit
 *  ~1.8 cm higher than in the raw take (LeftFoot 8.71 instead of 6.93 over a
 *  rest of 7.32). Capped at the rest height, the ground then left those feet
 *  1.4–3 cm "in the air", and the planted frames lost their full weight
 *  (9 instead of 88 for LeftFoot). 3 cm covers that lift with room; a point
 *  that never touches the floor (20 cm and more over its rest) still stays
 *  out, because its ground is capped at rest + 3 and it stands far above. */
export const GROUND_LIFT_TOL_CM = 3;

/** How much LESS the rebuilt path must drift than the imported one before it
 *  replaces it, cm. Anything below a tenth of a millimetre is Float32
 *  rounding of the stored keys (an exact imported path measures ~6e-7), not
 *  a better lock. */
export const RELOCK_MIN_GAIN_CM = 0.01;

/** Sample rate for a clip without a hips position track, fps. */
const FALLBACK_FPS = 30;

/** Toe ends count for the rest floor (the importer's `_rest_heights`) but
 *  are no contact points. */
const TOE_ENDS = ['lefttoe_end', 'righttoe_end', 'lefttoeend', 'righttoeend'];

/** The sample times: the keys of the clip's hips POSITION track — the keys
 *  the imported path lives on — or a uniform 30 fps over the duration. */
function sampleTimes(clip: THREE.AnimationClip): number[] {
  const hips = clip.tracks.find((t) => {
    const dot = t.name.lastIndexOf('.');
    return dot > 0 && t.name.slice(dot + 1) === 'position'
      && /hips$/.test(normBoneName(t.name.slice(0, dot)));
  });
  if (hips && hips.times.length >= 2) return Array.from(hips.times);
  const n = Math.max(2, Math.round(clip.duration * FALLBACK_FPS) + 1);
  return Array.from({ length: n }, (_, i) => (clip.duration * i) / (n - 1));
}

const IMPORTED_BETTER = 'imported holds better';

/** End of a path relative to its frame 0, in cm. */
function travelEndCm(path: RootPath, unitsPerCm: number): [number, number] {
  const n = path.times.length;
  if (!n) return [0, 0];
  const end = travelAt(path, path.times[n - 1]);
  return [end.x / unitsPerCm, end.z / unitsPerCm];
}

/** One line for the whole model, e.g.
 *  "foot lock per rig — get-up-chair 0.4 cm (imported 2.2), get-up-bed
 *  imported (no foot bones)". */
function summaryLine(reports: readonly RelockReport[]): string {
  const parts = reports.map((r) => {
    if (r.used === 'rig') {
      return `${r.clip} ${r.driftCm.toFixed(1)} cm (imported ${r.importedDriftCm.toFixed(1)})`;
    }
    if (r.reason === IMPORTED_BETTER) {
      return `${r.clip} imported ${r.importedDriftCm.toFixed(1)} cm (rig ${r.driftCm.toFixed(1)})`;
    }
    return `${r.clip} imported (${r.reason})`;
  });
  return `foot lock per rig — ${parts.join(', ')}`;
}

/**
 * Rebuild the travel of every clip that carries one (`clipRootPath`) on
 * `template`'s own skeleton and store it in place of the imported path.
 * Clips without a path are not touched and get no report. `log` receives ONE
 * summary line when at least one clip was measured or fell back.
 */
export function relockRootPaths(clips: readonly THREE.AnimationClip[],
                                template: THREE.Object3D, unitsPerCm: number,
                                log?: (msg: string) => void): RelockReport[] {
  const todo = clips.filter((c) => clipRootPath(c));
  if (!todo.length || !(unitsPerCm > 0)) return [];

  const probe = SkeletonUtils.clone(template);
  probe.updateMatrixWorld(true);
  const byKey = new Map<string, THREE.Object3D>();
  probe.traverse((o) => {
    if ((o as THREE.Bone).isBone) {
      const key = normBoneName(o.name);
      if (!byKey.has(key)) byKey.set(key, o);
    }
  });
  const points = CONTACT_POINTS.map((p) => byKey.get(p.toLowerCase()));
  const reports: RelockReport[] = [];

  if (points.some((b) => !b)) {
    for (const clip of todo) {
      reports.push({ clip: clip.name, used: 'imported', reason: 'no foot bones',
        driftCm: 0, importedDriftCm: 0, travel: travelEndCm(clipRootPath(clip)!, unitsPerCm) });
    }
    log?.(summaryLine(reports));
    return reports;
  }
  const bones = points as THREE.Object3D[];

  // Rest heights, cm: each point's bind-pose height over the lowest foot
  // point of the rest (the four points and the toe ends, as the importer's
  // `_rest_heights` does).
  const v = new THREE.Vector3();
  const restY = bones.map((b) => b.getWorldPosition(v).y);
  const floorY = Math.min(...restY,
    ...TOE_ENDS.map((k) => byKey.get(k)).filter((b): b is THREE.Object3D => !!b)
      .map((b) => b.getWorldPosition(v).y));
  const rest: Record<string, number> = {};
  CONTACT_POINTS.forEach((p, i) => { rest[p] = (restY[i] - floorY) / unitsPerCm; });

  const mixer = new THREE.AnimationMixer(probe);
  for (const clip of todo) {
    const imported = clipRootPath(clip)!;
    const times = sampleTimes(clip);
    const span = times[times.length - 1] - times[0];
    const fps = span > 0 ? (times.length - 1) / span : FALLBACK_FPS;

    // Play once, clamped: a looping action wraps t = duration back to 0.
    const action = mixer.clipAction(clip);
    action.setLoop(THREE.LoopOnce, 1);
    action.clampWhenFinished = true;
    action.play();
    const tracks: Tracks = {};
    for (const p of CONTACT_POINTS) tracks[p] = [];
    for (const t of times) {
      action.paused = false;   // the last key pauses a clamped action
      mixer.setTime(t);
      probe.updateMatrixWorld(true);
      bones.forEach((b, i) => {
        b.getWorldPosition(v);
        const pt: Vec3 = [v.x / unitsPerCm, v.y / unitsPerCm, v.z / unitsPerCm];
        tracks[CONTACT_POINTS[i]].push(pt);
      });
    }
    action.stop();
    mixer.uncacheClip(clip);

    const weights = contactWeights(tracks, groundHeights(tracks, rest, GROUND_LIFT_TOL_CM), fps);
    const importedCm: Array<[number, number]> = times.map((t) => {
      const o = travelAt(imported, t);
      return [o.x / unitsPerCm, o.z / unitsPerCm];
    });
    const anyFull = Object.values(weights).some((w) =>
      w.some((x, f) => f + 1 < w.length && Math.min(x, w[f + 1]) >= FULL));
    if (!anyFull) {
      reports.push({ clip: clip.name, used: 'imported', reason: 'no full contact',
        driftCm: 0, importedDriftCm: 0, travel: travelEndCm(imported, unitsPerCm) });
      continue;
    }
    const path = footLockPath(tracks, weights);
    const driftCm = maxPlantedDrift(tracks, weights, path);
    const importedDriftCm = maxPlantedDrift(tracks, weights, importedCm);
    // Never worse than the import: measured by the same contacts, a rebuilt
    // path that does not hold the planted points better is not taken.
    if (!(driftCm < importedDriftCm - RELOCK_MIN_GAIN_CM)) {
      reports.push({ clip: clip.name, used: 'imported', reason: IMPORTED_BETTER,
        driftCm, importedDriftCm, travel: travelEndCm(imported, unitsPerCm) });
      continue;
    }
    const xz = new Float32Array(path.length * 2);
    path.forEach(([x, z], i) => { xz[i * 2] = x * unitsPerCm; xz[i * 2 + 1] = z * unitsPerCm; });
    setClipRootPath(clip, { times: Float32Array.from(times), xz });
    const end = path[path.length - 1];
    reports.push({ clip: clip.name, used: 'rig', driftCm, importedDriftCm,
      travel: [end[0], end[1]] });
  }
  log?.(summaryLine(reports));
  return reports;
}
