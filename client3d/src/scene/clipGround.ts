import * as THREE from 'three';
import * as SkeletonUtils from 'three/addons/utils/SkeletonUtils.js';

/**
 * WHERE A CLIP PUTS THE BODY over the ground — the measurement half of the
 * swim finding (acceptance round 2026-08-13, finding 3).
 *
 * A figure is anchored ONCE, in its BIND pose: `Figure`'s constructor drops the
 * instance by `box.min.y`, so the soles stand on y = 0 while the rig is in the
 * pose the mesh was authored in. Every clip is played against that one anchor,
 * which is right for everything authored on the floor and wrong for everything
 * authored on a line of its own: `swim.fbx` is animated on a WATER LINE (hip
 * median 78.4 against the standing reference of 110.1 Mixamo units, the body
 * 74° prone), so the lowest body point of the posed figure sits +0.26 … +0.32 m
 * over the anchor and the swimmer floats over the lake it should be in.
 *
 * The rule here is generic and carries no clip name: MEASURE the lowest body
 * point of every adapted clip once, store it as the clip's `groundOffset`, and
 * let the caller decide when the ground is the reference (`figures.Figure`
 * applies it while a TERRAIN MOVE clip plays, and nowhere else — a sleeper on
 * a bed floats on purpose).
 *
 * THE MEASUREMENT IS THE SKINNING, not the skeleton: bones sit inside the body,
 * and what touches the water is the mesh. Vertices are sampled through
 * `SkinnedMesh.getVertexPosition` (bone transform + morph targets) over
 * `GROUND_SAMPLE_FRAMES` frames — exactly the headless diagnosis run, and
 * `client3d/scripts/smoke_clip_ground.mjs` repeats it against real assets.
 *
 * The unit is the TEMPLATE's metre: the measurement runs on the unscaled model
 * template, so a consumer that scales its instance (`Figure.baseScale`) scales
 * the offset with it.
 */

/** Frames a clip is sampled at, evenly over its whole duration (start and end
 *  both included, so it is this many + 1 poses). 24 is the rate the retarget
 *  path already samples at — a swimming stroke has no detail under 1/24 s. */
export const GROUND_SAMPLE_FRAMES = 24;

/** Vertex budget per pose, spread over ALL skinned meshes of the model with one
 *  stride. A full mesh is 20 000 vertices and 20 clips are 500 poses: sampling
 *  every vertex would be ten million skinning evaluations on a load path, for a
 *  number whose consumer is a centimetre-scale drop. The stride costs at most
 *  the local mesh resolution (millimetres to a centimetre on a body). */
export const GROUND_SAMPLE_VERTICES = 1024;

/**
 * The drop a clip needs so its lowest body point reaches the ground, from the
 * two measured heights — the pure half of the rule, hand-checked in
 * `client3d/scripts/smoke_clip_ground.mjs`.
 *
 * NEVER NEGATIVE. A clip whose body dips BELOW the bind pose (a crouch, a lunge
 * that plants a knee under the sole plane) is authored on the floor already and
 * is not lifted out of it: raising a figure is not what this exists for, and a
 * lift would show as feet over the ground on every step of a walk cycle.
 * Non-finite readings (a clip with no vertices sampled, an empty mesh) are no
 * measurement and answer 0 — the unchanged behaviour of before.
 */
export function groundOffsetOf(clipMinY: number, bindMinY: number): number {
  const drop = clipMinY - bindMinY;
  return Number.isFinite(drop) && drop > 0 ? drop : 0;
}

/** The offset a clip carries, in template metres — 0 for every clip that was
 *  never measured (a model's own embedded clips, a retargeted borrow). */
export function clipGroundOffset(clip: THREE.AnimationClip): number {
  const raw = clip.userData?.groundOffset;
  return typeof raw === 'number' && Number.isFinite(raw) ? raw : 0;
}

/**
 * Measure `groundOffset` for every clip, on a CLONE of the target rig.
 *
 * The clone is what makes this side-effect free: the mixer poses a skeleton,
 * and the template is what every figure of this model is cloned from — a posed
 * template would hand the last sampled frame to the next `Figure`.
 *
 * Rigs without a skinned mesh (static props, the animal rigs that walk
 * procedurally) are left alone: there is no body to measure, and their clips
 * keep the 0 they started with.
 */
export function measureGroundOffsets(clips: readonly THREE.AnimationClip[],
                                     target: THREE.Object3D): void {
  if (!clips.length) return;
  const probe = SkeletonUtils.clone(target);
  probe.updateMatrixWorld(true);
  const skins: THREE.SkinnedMesh[] = [];
  probe.traverse((o) => {
    if ((o as THREE.SkinnedMesh).isSkinnedMesh) skins.push(o as THREE.SkinnedMesh);
  });
  if (!skins.length) return;
  // The anchor the consumer uses: `Figure` drops the instance by the BIND-pose
  // box, and `Box3.setFromObject` reads the geometry box for a skinned mesh —
  // the bind pose, whatever the bones are doing. So this is the same y = 0 the
  // figure will stand on, measured in the same space as the samples below.
  const bindMinY = new THREE.Box3().setFromObject(probe).min.y;
  const total = skins.reduce((n, s) => n + s.geometry.attributes.position.count, 0);
  const stride = Math.max(1, Math.ceil(total / GROUND_SAMPLE_VERTICES));
  const mixer = new THREE.AnimationMixer(probe);
  const v = new THREE.Vector3();
  for (const clip of clips) {
    const action = mixer.clipAction(clip);
    action.play();
    let minY = Infinity;
    for (let f = 0; f <= GROUND_SAMPLE_FRAMES; f++) {
      mixer.setTime((clip.duration * f) / GROUND_SAMPLE_FRAMES);
      probe.updateMatrixWorld(true);
      for (const skin of skins) {
        const count = skin.geometry.attributes.position.count;
        for (let i = 0; i < count; i += stride) {
          skin.getVertexPosition(i, v);
          skin.localToWorld(v);
          if (v.y < minY) minY = v.y;
        }
      }
    }
    action.stop();
    mixer.uncacheClip(clip);
    clip.userData.groundOffset = groundOffsetOf(minY, bindMinY);
  }
}
