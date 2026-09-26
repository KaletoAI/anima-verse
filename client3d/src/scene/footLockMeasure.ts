import * as THREE from 'three';
import * as SkeletonUtils from 'three/addons/utils/SkeletonUtils.js';
import { normBoneName } from '@anima/scene-render';
import { clipRootPath, setClipRootPath, travelAt } from './bridgeTravel';
import type { RootPath } from './bridgeTravel';
import { setClipBridgeLift } from './bridgeLift';
import {
  CONTACT_POINTS, FULL, contactWeights, footLockPath, groundHeights, maxPlantedDrift,
} from './footLock';
import type { Tracks, Vec3 } from './footLock';
import { pinRuns, soleDown, twoBoneIk } from './legPin';
import type { Quat } from './legPin';

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
 * THE LEG PIN, after the path is decided — the per-rig counterpart of the
 * importer's foot plant (`cmu_clip._plant_feet` / `_pin_feet`). The importer
 * bends the legs so a planted foot stands still, but for the REFERENCE rig's
 * leg lengths; a figure only takes over the rotations, so on other proportions
 * the feet glide again (the re-imported get-up-chair, feet planted through the
 * whole rise: 3.86 cm on Test3_mia, 1.59 cm on Soldier). The same two steps
 * therefore run here once per model, on its own skeleton, and are baked into
 * the adapted clip (no cost at run time). Per foot:
 *   DOWN — its contact weight (the larger of ankle and ball, as sampled),
 *     zero wherever the foot is not SOLE-DOWN (`legPin.soleDown`, the twin
 *     of `_foot_plant.sole_down`: ankle over ball by at least half the rig's
 *     rest rise), goes through the importer's run rule and fade
 *     (`legPin.pinRuns`); the foot
 *     comes down by that weight × its LIFT, the least height of its two points
 *     over their own grounds (`groundHeights` — the importer's `foot_lift` with
 *     the rig's ground in place of its rest heights).
 *   HOLD — the contacts again, of the LOWERED foot, through the same gate and
 *     rule: a
 *     frame the lift puts on the ground is planted and is held in full (a foot
 *     hovering 3 cm up weighs 0.67 before and stands after; held at 0.67 it
 *     skated — Test3_mia get-up-chair, right ankle 1.78 cm). In each held run
 *     one point of the foot stands still: between ankle and ball, weighted by
 *     how planted each is over the run (the middle of a flat foot, the ball of
 *     one on its toes). Holding the ankle alone, as the importer does, swings
 *     the ball round it when the actor's foot turns while planted — the ball
 *     then drifted MORE than without any pin (Soldier get-up-chair 1.78 against
 *     1.59 cm, get-up-bed 2.59 cm; the reference rig's chair 1.27 against the
 *     import's 1.04). The anchor is that point's mean WORLD XZ (track + the
 *     path in use) over the run's full frames; per frame the ankle's target
 *     moves it back onto the anchor, blended with the frame's hold weight
 *     against the unpinned position.
 * A two-bone IK on UpLeg/Leg (`legPin.twoBoneIk`, the twin of
 * `_foot_plant.two_bone_ik`, the knee in its own bending plane) reaches the
 * target, the Foot keeps its world rotation (the toes stay flat), and the new
 * local quaternions of UpLeg/Leg/Foot replace their tracks on the sample times.
 * Every other track stays as it is. A rig without the six leg bones is not
 * pinned (`pinReason` 'no leg bones'). The drift in the report is measured
 * AFTER the pin, on a fresh sampling of the baked clip, on the contacts as
 * sampled before it.
 *
 * THE BRIDGE'S HEIGHT, measured in the same probe run (Task C5,
 * `bridgeLift.ts`), for every clip measured here — the fallback 'no foot
 * bones' has nothing to measure and stores nothing:
 *   endLift — how far the clip's LAST frame, as it now plays (after the pin),
 *     has to be lifted so that its lowest foot point (the four contact points
 *     and the toe ends) stands on the rig's REST floor, the floor of
 *     `rest`: `restFloor − lowest`, template units. On the figure the rest
 *     floor is where the soles of the bind pose are drawn, so the feet land
 *     the way the rig stands in its bind pose.
 *   firstContactS — the clip time of the first frame in which any contact
 *     point is in FULL contact (`contactWeights`, the contacts the path was
 *     judged on); the clip's duration when there is none.
 * Stored on the clip (`setClipBridgeLift`); `Figure.beginBridgeLift` reads it.
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
  /** Largest planted-point drift of the clip as it now plays — the path in
   *  use, measured AFTER the leg pin, cm (0 when nothing was measured or no
   *  full-contact run exists). */
  driftCm: number;
  /** The same measurement with the path rebuilt on this rig, before the pin,
   *  cm — one side of the path decision. */
  rebuiltDriftCm: number;
  /** The same measurement with the imported path, before the pin, cm — the
   *  other side, and the comparison. */
  importedDriftCm: number;
  /** Largest HORIZONTAL correction the leg pin applied to an ankle (the
   *  hold), cm (0 = nothing held). */
  pinnedCm: number;
  /** Largest VERTICAL correction the leg pin applied to an ankle (the
   *  lift), cm (0 = nothing lowered or raised). */
  liftCm: number;
  /** Why no foot was pinned although the clip was measured: 'no leg bones'
   *  (UpLeg/Leg/Foot of both sides are needed). */
  pinReason?: string;
  /** End of the path in use, clip frame (x, z), cm at the nominal scale. */
  travel: [number, number];
}

/** How much LESS the rebuilt path must drift than the imported one before it
 *  replaces it, cm — hysteresis against flips at the edge of the contact
 *  band. A smaller gain is inside what the classification itself resolves,
 *  not a better lock. The case behind the number (measured while adapted
 *  clips, scaled against the idle clip's hips, stood ~1.8 cm higher than
 *  the raw take and the ground followed them up to 3 cm over the rest): on
 *  the reference rig, `get-up-chair` gained 0.03 cm here (0.26 against
 *  0.29), yet the same rule fed without the bridge's 0.3 s fade-in frames
 *  moved the 5th-percentile ground of LeftFoot by ~0.8 cm, turned the whole
 *  standing phase into one planted run and ranked the two paths the other
 *  way round: imported 0.42 cm, re-locked 0.76 cm.
 *  With the rig's rest as the standing reference and the ground capped at
 *  the rest, the reference rig's rebuild ties its import (chair 0.42 against
 *  0.42, bed 1.44 against 1.43) and the real rigs gain 0.7–1.5 cm
 *  (`smoke_bridge_root.mjs` [6]); the rig the import was measured on keeps
 *  its own path. */
export const RELOCK_MIN_GAIN_CM = 0.1;

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
 *  "foot lock per rig — get-up-chair 3.9 cm (imported 5.0), held 3.1 cm,
 *  lifted 1.2 cm → 0.5 cm, get-up-bed imported (no foot bones)". The pin
 *  part is left out when it moved nothing visible (both < 0.05 cm). */
function summaryLine(reports: readonly RelockReport[]): string {
  const parts = reports.map((r) => {
    let head: string;
    if (r.used === 'rig') {
      head = `${r.clip} ${r.rebuiltDriftCm.toFixed(1)} cm (imported ${r.importedDriftCm.toFixed(1)})`;
    } else if (r.reason === IMPORTED_BETTER) {
      head = `${r.clip} imported ${r.importedDriftCm.toFixed(1)} cm (rig ${r.rebuiltDriftCm.toFixed(1)})`;
    } else {
      return `${r.clip} imported (${r.reason})`;
    }
    if (r.pinReason) return `${head}, not pinned (${r.pinReason})`;
    if (r.pinnedCm < 0.05 && r.liftCm < 0.05) return head;
    return `${head}, held ${r.pinnedCm.toFixed(1)} cm, lifted ${r.liftCm.toFixed(1)} cm`
      + ` → ${r.driftCm.toFixed(1)} cm`;
  });
  return `foot lock per rig — ${parts.join(', ')}`;
}

/** The two legs the pin bends: the contact points it reads (ankle, ball)
 *  and the bone keys of the chain above the ankle. */
const LEGS = [
  { ankle: 'LeftFoot', ball: 'LeftToeBase', upper: 'leftupleg', lower: 'leftleg' },
  { ankle: 'RightFoot', ball: 'RightToeBase', upper: 'rightupleg', lower: 'rightleg' },
] as const;

/** One leg of the probe: UpLeg, Leg, Foot. */
interface LegBones { upper: THREE.Object3D; lower: THREE.Object3D; foot: THREE.Object3D }

/** What the pin needs of one leg in one UNPINNED frame: joint positions (cm,
 *  the probe's frame), world rotations of the three bones and of their
 *  parents, and the three local rotations as the clip poses them. */
interface LegFrame {
  hip: Vec3; knee: Vec3; ankle: Vec3;
  wUpperParent: THREE.Quaternion; wUpper: THREE.Quaternion;
  wLowerParent: THREE.Quaternion; wLower: THREE.Quaternion;
  wFootParent: THREE.Quaternion; wFoot: THREE.Quaternion;
  local: [THREE.Quaternion, THREE.Quaternion, THREE.Quaternion];
}

function isBelow(bone: THREE.Object3D, ancestor: THREE.Object3D): boolean {
  for (let p = bone.parent; p; p = p.parent) if (p === ancestor) return true;
  return false;
}

/** Both legs' chains, or null when a bone is missing or the chain is not
 *  UpLeg → … → Leg → … → Foot. */
function legBonesOf(byKey: Map<string, THREE.Object3D>): LegBones[] | null {
  const out: LegBones[] = [];
  for (const leg of LEGS) {
    const upper = byKey.get(leg.upper);
    const lower = byKey.get(leg.lower);
    const foot = byKey.get(leg.ankle.toLowerCase());
    if (!upper || !lower || !foot || !upper.parent || !isBelow(lower, upper) || !isBelow(foot, lower)) {
      return null;
    }
    out.push({ upper, lower, foot });
  }
  return out;
}

/** Play `clip` once on the probe and call `visit(frame)` at every sample
 *  time with the probe posed; the clip is uncached again afterwards. */
function sampleOnProbe(mixer: THREE.AnimationMixer, probe: THREE.Object3D,
                       clip: THREE.AnimationClip, times: readonly number[],
                       visit: (frame: number) => void): void {
  // Play once, clamped: a looping action wraps t = duration back to 0.
  const action = mixer.clipAction(clip);
  action.setLoop(THREE.LoopOnce, 1);
  action.clampWhenFinished = true;
  action.play();
  times.forEach((t, f) => {
    action.paused = false;   // the last key pauses a clamped action
    mixer.setTime(t);
    probe.updateMatrixWorld(true);
    visit(f);
  });
  action.stop();
  mixer.uncacheClip(clip);
}

const toThree = (q: Quat): THREE.Quaternion => new THREE.Quaternion(q[1], q[2], q[3], q[0]);

/** Replace the quaternion track of `bone` in `clip` (whatever spelling of the
 *  bone name it used) by one on `times`, in place of the old one. */
function replaceQuatTrack(clip: THREE.AnimationClip, bone: THREE.Object3D,
                          times: Float32Array, values: Float32Array): void {
  const key = normBoneName(bone.name);
  const track = new THREE.QuaternionKeyframeTrack(`${bone.name}.quaternion`, times, values);
  const at = clip.tracks.findIndex((t) => {
    const dot = t.name.lastIndexOf('.');
    return dot > 0 && t.name.slice(dot + 1) === 'quaternion' && normBoneName(t.name.slice(0, dot)) === key;
  });
  if (at < 0) clip.tracks.push(track);
  else {
    clip.tracks[at] = track;
    for (let i = clip.tracks.length - 1; i > at; i--) {
      const t = clip.tracks[i];
      const dot = t.name.lastIndexOf('.');
      if (dot > 0 && t.name.slice(dot + 1) === 'quaternion' && normBoneName(t.name.slice(0, dot)) === key) {
        clip.tracks.splice(i, 1);
      }
    }
  }
}

/** In-place XZ of the point a share `s` of the way from ankle to ball. */
function pivotAt(tracks: Tracks, leg: (typeof LEGS)[number], f: number, s: number): [number, number] {
  const a = tracks[leg.ankle][f];
  const b = tracks[leg.ball][f];
  return [a[0] + s * (b[0] - a[0]), a[2] + s * (b[2] - a[2])];
}

/**
 * THE LEG PIN of one clip (module docstring): per leg the DOWN and HOLD
 * weights, per held run the held point and its anchor, per frame the IK —
 * written as new UpLeg/Leg/Foot tracks on `times`. `tracks` are the sampled
 * contact points (cm, in place, heights over the rest floor), `rest` their
 * rest heights, `path` the root path in use (cm per frame).
 * Returns whether any frame was moved.
 */
function pinLegs(clip: THREE.AnimationClip, times: readonly number[], legs: LegBones[],
                 legFrames: LegFrame[][], tracks: Tracks, ground: Record<string, number>,
                 rest: Record<string, number>, weights: Record<string, number[]>, path: Array<[number, number]>,
                 fps: number): boolean {
  const n = times.length;
  const keyTimes = Float32Array.from(times);
  let pinned = false;
  LEGS.forEach((leg, s) => {
    const frames = legFrames[s];
    // Only a SOLE-DOWN frame pins (`legPin.soleDown`): the lift compares
    // with the upright stance and means nothing for a foot on its side, its
    // instep or its heel.
    const sole = soleDown(tracks[leg.ankle].map((p) => p[1]), tracks[leg.ball].map((p) => p[1]),
      rest[leg.ankle] - rest[leg.ball]);
    const footWeight = (w: Record<string, number[]>): number[] => Array.from({ length: n },
      (_, f) => (sole[f] ? Math.max(w[leg.ankle]?.[f] ?? 0, w[leg.ball]?.[f] ?? 0) : 0));
    // DOWN: the foot comes down by w · its lift, w from the contacts as
    // sampled.
    const down = pinRuns(footWeight(weights), fps);
    if (!down.some((w) => w > 0)) return;
    const lift = Array.from({ length: n }, (_, f) => {
      const v = Math.min(tracks[leg.ankle][f][1] - ground[leg.ankle],
        tracks[leg.ball][f][1] - ground[leg.ball]);
      return Number.isFinite(v) ? v : 0;
    });
    // HOLD: the horizontal pin follows the contacts of the LOWERED foot — a
    // frame the lift puts on the ground is a planted frame and is held in full
    // (a foot hovering 3 cm up weighs 0.67 before, but stands on the ground
    // after, and a partial hold there is a visible skate).
    const lowered: Tracks = {};
    for (const p of [leg.ankle, leg.ball]) {
      lowered[p] = tracks[p].map((q, f) => [q[0], q[1] - down[f] * lift[f], q[2]] as Vec3);
    }
    const after = contactWeights(lowered, ground, fps);
    const hold = pinRuns(footWeight(after), fps);
    // The point held per run: between ankle (s = 0) and ball (s = 1), weighted
    // by how planted each is over the run's full frames — the middle of a flat
    // foot, the ball of one on its toes. Its anchor is its mean WORLD XZ over
    // those frames; the ankle's target moves it by what that point is off its
    // anchor (the foot keeps its rotation, so it moves as one piece).
    const anchor: Array<[number, number] | null> = new Array(n).fill(null);
    const pivot = new Array<number>(n).fill(0);
    for (let f = 0; f < n;) {
      if (!(hold[f] > 0)) { f++; continue; }
      const a = f;
      while (f + 1 < n && hold[f + 1] > 0) f++;
      const b = f++;
      let ca = 0;
      let cb = 0;
      for (let g = a; g <= b; g++) {
        if (hold[g] < FULL) continue;
        ca += after[leg.ankle][g];
        cb += after[leg.ball][g];
      }
      const sBall = ca + cb > 0 ? cb / (ca + cb) : 0;
      let sx = 0;
      let sz = 0;
      let k = 0;
      for (let g = a; g <= b; g++) {
        pivot[g] = sBall;
        if (hold[g] < FULL) continue;
        const pt = pivotAt(tracks, leg, g, sBall);
        sx += pt[0] + path[g][0];
        sz += pt[1] + path[g][1];
        k++;
      }
      if (k) for (let g = a; g <= b; g++) anchor[g] = [sx / k, sz / k];
    }
    const values = [new Float32Array(n * 4), new Float32Array(n * 4), new Float32Array(n * 4)];
    const prev: Array<THREE.Quaternion | null> = [null, null, null];
    let changed = false;
    for (let g = 0; g < n; g++) {
      const fr = frames[g];
      let local = fr.local;
      const w = anchor[g] ? hold[g] : 0;
      const at = anchor[g] ?? [0, 0];
      if (w > 0 || down[g] > 0) {
        const pt = pivotAt(tracks, leg, g, pivot[g]);
        const target: Vec3 = [
          fr.ankle[0] + w * (at[0] - path[g][0] - pt[0]),
          fr.ankle[1] - down[g] * lift[g],
          fr.ankle[2] + w * (at[1] - path[g][1] - pt[1]),
        ];
        const ik = twoBoneIk(fr.hip, fr.knee, fr.ankle, target, fr.knee);
        const du = toThree(ik.upper);
        const dl = toThree(ik.lower);
        const dul = dl.clone().multiply(du);
        // New world rotations: the thigh turned by du, the shin by dl·du, the
        // foot kept; each back into its (new) parent's frame.
        local = [
          fr.wUpperParent.clone().invert().multiply(du.clone().multiply(fr.wUpper)),
          du.clone().multiply(fr.wLowerParent).invert().multiply(dul.clone().multiply(fr.wLower)),
          dul.clone().multiply(fr.wFootParent).invert().multiply(fr.wFoot),
        ];
        changed = true;
      }
      local.forEach((q, i) => {
        // Keep the keys on one hemisphere: a sign flip is the same rotation,
        // but a track interpolates component-wise between neighbours.
        const out = q.clone();
        if (prev[i] && out.dot(prev[i]!) < 0) out.set(-out.x, -out.y, -out.z, -out.w);
        out.toArray(values[i], g * 4);
        prev[i] = out;
      });
    }
    if (!changed) return;
    pinned = true;
    const bones = legs[s];
    replaceQuatTrack(clip, bones.upper, keyTimes, values[0]);
    replaceQuatTrack(clip, bones.lower, keyTimes, values[1]);
    replaceQuatTrack(clip, bones.foot, keyTimes, values[2]);
  });
  return pinned;
}

/** Clip time of the first sample in which any contact point is in FULL
 *  contact, or `duration` when none is (module docstring, the bridge's
 *  height). */
function firstFullContact(weights: Record<string, number[]>, times: readonly number[],
                          duration: number): number {
  for (let f = 0; f < times.length; f++) {
    if (Object.values(weights).some((w) => w[f] >= FULL)) return times[f];
  }
  return duration;
}

/**
 * Rebuild the travel of every clip that carries one (`clipRootPath`) on
 * `template`'s own skeleton and store it in place of the imported path, then
 * pin the planted feet of that clip on this skeleton, and measure the height
 * the bridge needs (`setClipBridgeLift`) — module docstring.
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
        driftCm: 0, rebuiltDriftCm: 0, importedDriftCm: 0, pinnedCm: 0, liftCm: 0,
        travel: travelEndCm(clipRootPath(clip)!, unitsPerCm) });
    }
    log?.(summaryLine(reports));
    return reports;
  }
  const bones = points as THREE.Object3D[];
  const legs = legBonesOf(byKey);

  // Rest heights, cm: each point's bind-pose height over the lowest foot
  // point of the rest (the four points and the toe ends, as the importer's
  // `_rest_heights` does).
  const v = new THREE.Vector3();
  const restY = bones.map((b) => b.getWorldPosition(v).y);
  const mixer = new THREE.AnimationMixer(probe);
  const floorY = Math.min(...restY,
    ...TOE_ENDS.map((k) => byKey.get(k)).filter((b): b is THREE.Object3D => !!b)
      .map((b) => b.getWorldPosition(v).y));
  const rest: Record<string, number> = {};
  CONTACT_POINTS.forEach((p, i) => { rest[p] = (restY[i] - floorY) / unitsPerCm; });

  // The lowest foot point of a posed probe, template units — the points of
  // the rest floor above.
  const footPoints = [...bones,
    ...TOE_ENDS.map((k) => byKey.get(k)).filter((b): b is THREE.Object3D => !!b)];
  const storeLift = (clip: THREE.AnimationClip, times: readonly number[], firstContactS: number) => {
    let lowest = Infinity;
    sampleOnProbe(mixer, probe, clip, [times[times.length - 1]], () => {
      for (const b of footPoints) lowest = Math.min(lowest, b.getWorldPosition(v).y);
    });
    if (Number.isFinite(lowest)) setClipBridgeLift(clip, { endLift: floorY - lowest, firstContactS });
  };

  const cmOf = (b: THREE.Object3D): Vec3 => {
    b.getWorldPosition(v);
    return [v.x / unitsPerCm, v.y / unitsPerCm, v.z / unitsPerCm];
  };
  const worldQ = (o: THREE.Object3D): THREE.Quaternion => o.getWorldQuaternion(new THREE.Quaternion());
  // The contact tracks' heights are measured from the SAME rest floor as
  // `rest`: the probe's world origin is not at the feet on every rig
  // (Test3_mia is centred on its hips), and `groundHeights` caps a point's
  // ground at its rest height — both have to be in one frame.
  const floorCm = floorY / unitsPerCm;
  const readPoints = (into: Tracks) => {
    bones.forEach((b, i) => {
      const p = cmOf(b);
      into[CONTACT_POINTS[i]].push([p[0], p[1] - floorCm, p[2]]);
    });
  };
  const emptyTracks = (): Tracks => {
    const t: Tracks = {};
    for (const p of CONTACT_POINTS) t[p] = [];
    return t;
  };

  for (const clip of todo) {
    const imported = clipRootPath(clip)!;
    const times = sampleTimes(clip);
    const span = times[times.length - 1] - times[0];
    const fps = span > 0 ? (times.length - 1) / span : FALLBACK_FPS;

    const tracks = emptyTracks();
    const legFrames: LegFrame[][] = LEGS.map(() => []);
    sampleOnProbe(mixer, probe, clip, times, () => {
      readPoints(tracks);
      legs?.forEach((leg, s) => {
        legFrames[s].push({
          hip: cmOf(leg.upper), knee: cmOf(leg.lower), ankle: cmOf(leg.foot),
          wUpperParent: worldQ(leg.upper.parent!), wUpper: worldQ(leg.upper),
          wLowerParent: worldQ(leg.lower.parent!), wLower: worldQ(leg.lower),
          wFootParent: worldQ(leg.foot.parent!), wFoot: worldQ(leg.foot),
          local: [leg.upper.quaternion.clone(), leg.lower.quaternion.clone(), leg.foot.quaternion.clone()],
        });
      });
    });

    const ground = groundHeights(tracks, rest);
    const weights = contactWeights(tracks, ground, fps);
    const importedCm: Array<[number, number]> = times.map((t) => {
      const o = travelAt(imported, t);
      return [o.x / unitsPerCm, o.z / unitsPerCm];
    });
    const anyFull = Object.values(weights).some((w) =>
      w.some((x, f) => f + 1 < w.length && Math.min(x, w[f + 1]) >= FULL));
    if (!anyFull) {
      reports.push({ clip: clip.name, used: 'imported', reason: 'no full contact',
        driftCm: 0, rebuiltDriftCm: 0, importedDriftCm: 0, pinnedCm: 0, liftCm: 0,
        travel: travelEndCm(imported, unitsPerCm) });
      storeLift(clip, times, clip.duration);
      continue;
    }
    const path = footLockPath(tracks, weights);
    const rebuiltDriftCm = maxPlantedDrift(tracks, weights, path);
    const importedDriftCm = maxPlantedDrift(tracks, weights, importedCm);
    // Never worse than the import: measured by the same contacts, a rebuilt
    // path that does not hold the planted points better is not taken.
    const useRig = rebuiltDriftCm < importedDriftCm - RELOCK_MIN_GAIN_CM;
    const inUse = useRig ? path : importedCm;
    let travel: [number, number];
    if (useRig) {
      const xz = new Float32Array(path.length * 2);
      path.forEach(([x, z], i) => { xz[i * 2] = x * unitsPerCm; xz[i * 2 + 1] = z * unitsPerCm; });
      setClipRootPath(clip, { times: Float32Array.from(times), xz });
      const end = path[path.length - 1];
      travel = [end[0], end[1]];
    } else {
      travel = travelEndCm(imported, unitsPerCm);
    }

    // The leg pin on the path in use, then the drift of the clip as it now
    // plays: a fresh sampling of the baked tracks, judged on the same contacts.
    let driftCm = useRig ? rebuiltDriftCm : importedDriftCm;
    let pinnedCm = 0;
    let liftCm = 0;
    if (legs && pinLegs(clip, times, legs, legFrames, tracks, ground, rest, weights, inUse, fps)) {
      const after = emptyTracks();
      sampleOnProbe(mixer, probe, clip, times, () => readPoints(after));
      driftCm = maxPlantedDrift(after, weights, inUse);
      for (const leg of LEGS) {
        after[leg.ankle].forEach((p, f) => {
          const o = tracks[leg.ankle][f];
          pinnedCm = Math.max(pinnedCm, Math.hypot(p[0] - o[0], p[2] - o[2]));
          liftCm = Math.max(liftCm, Math.abs(p[1] - o[1]));
        });
      }
    }
    // The bridge's height on the clip as it now plays (the pin moved feet).
    storeLift(clip, times, firstFullContact(weights, times, clip.duration));
    reports.push({
      clip: clip.name, used: useRig ? 'rig' : 'imported',
      ...(useRig ? {} : { reason: IMPORTED_BETTER }),
      ...(legs ? {} : { pinReason: 'no leg bones' }),
      driftCm, rebuiltDriftCm, importedDriftCm, pinnedCm, liftCm, travel,
    });
  }
  log?.(summaryLine(reports));
  return reports;
}
