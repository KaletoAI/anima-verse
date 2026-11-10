import * as THREE from 'three';
import * as SkeletonUtils from 'three/addons/utils/SkeletonUtils.js';
import { measureClipGround } from '@anima/scene-render';
import type { FootPose } from '@anima/scene-render';

/**
 * WHERE A CLIP PUTS THE BODY over the ground — the client's call into the ONE
 * measurement of `@anima/scene-render` (`clipGround.ts` there: the bare rule
 * of the swim finding, acceptance round 2026-08-13, finding 3, and the shod
 * rule of the footwear strand). The rule, its constants and the pure
 * arithmetic (`groundOffsetOf`, `soleGroundOffsetOf`) live in the package;
 * this module only clones the template so the measurement is side-effect
 * free (the mixer poses a skeleton, and the template is what every figure of
 * this model is cloned from — a posed template would hand the last sampled
 * frame to the next `Figure`).
 *
 * What the number is good for is decided in `figures.Figure.play`, and only
 * while a TERRAIN MOVE clip runs — a sleeper on a bed floats on purpose.
 */
export { GROUND_SAMPLE_FRAMES, GROUND_SAMPLE_VERTICES, SOLE_LEVEL_M, clipGroundOffset,
  groundOffsetOf, soleGroundOffsetOf } from '@anima/scene-render';

/**
 * Measure `groundOffset` for every clip, on a CLONE of the target rig.
 * `footPose` + `rootY` select the shod rule (the package docstring): the
 * sole contacts of a matching foot pose are sampled and the figure's
 * standing lift enters the arithmetic. Without them: the bare rule, as before.
 */
export function measureGroundOffsets(clips: readonly THREE.AnimationClip[],
                                     target: THREE.Object3D,
                                     footPose?: FootPose | null,
                                     rootY = 0): void {
  if (!clips.length) return;
  const probe = SkeletonUtils.clone(target);
  probe.updateMatrixWorld(true);
  measureClipGround(THREE, clips, probe, { footPose, rootY });
}
