/** World-space positions and bone-only parent indices, in traversal order.
 * A null parent means the bone's immediate parent is not a bone.
 * Inputs describe a valid acyclic skeleton; names need not be unique.
 */
export interface GaitBone {
  name: string;
  parent: number | null;
  position: { x: number; y: number; z: number };
}
export interface GaitBox {
  min: { x: number; y: number; z: number };
  max: { x: number; y: number; z: number };
}
export interface GaitChain {
  bone: number;
  foot: number;
  /** World-space swing axis; the renderer converts to the parent frame. */
  axis: [number, number, number];
  phaseWalk: number;
  phaseRun: number;
}

/** Detect low, rising, unbranched chains; preserve stable traversal ties. */
export function findLegChains(bones: readonly GaitBone[], box: GaitBox): GaitChain[] {
  if (!bones.length) return [];
  const size = { x: box.max.x - box.min.x, y: box.max.y - box.min.y, z: box.max.z - box.min.z };
  const center = { x: (box.min.x + box.max.x) * 0.5, z: (box.min.z + box.max.z) * 0.5 };
  const height = Math.max(size.y, 1e-3);
  const children = bones.map(() => 0);
  for (const bone of bones) if (bone.parent !== null) children[bone.parent]++;
  const found: { bone: number; foot: number }[] = [];
  for (let leaf = 0; leaf < bones.length; leaf++) {
    if (children[leaf]) continue;
    const foot = bones[leaf].position;
    if (foot.y > box.min.y + height * 0.25) continue;
    let top = leaf;
    while (bones[top].parent !== null && children[bones[top].parent!] === 1) {
      top = bones[top].parent!;
    }
    if (top === leaf) continue;
    if (bones[top].position.y - foot.y < height * 0.12) continue;
    if (!found.some(f => f.bone === top)) found.push({ bone: top, foot: leaf });
  }
  found.sort((a, b) => bones[a.foot].position.y - bones[b.foot].position.y);
  const long = size.x > size.z ? 'x' : 'z';
  const cross = long === 'x' ? 'z' : 'x';
  const chains: GaitChain[] = found.slice(0, 4).map(c => ({
    ...c, axis: long === 'x' ? [0, 0, 1] : [1, 0, 0], phaseWalk: 0, phaseRun: 0,
  }));
  const pos = (c: GaitChain) => bones[c.foot].position;
  if (chains.length === 4) {
    const byLong = [...chains].sort((a, b) => pos(a)[long] - pos(b)[long]);
    const [aL, aR] = byLong.slice(0, 2).sort((a, b) => pos(a)[cross] - pos(b)[cross]);
    const [bL, bR] = byLong.slice(2).sort((a, b) => pos(a)[cross] - pos(b)[cross]);
    aL.phaseWalk = 0; bL.phaseWalk = Math.PI / 2;
    aR.phaseWalk = Math.PI; bR.phaseWalk = Math.PI * 1.5;
    aL.phaseRun = 0; bR.phaseRun = 0;
    aR.phaseRun = Math.PI; bL.phaseRun = Math.PI;
  } else {
    for (const c of chains) {
      const p = pos(c)[cross] >= center[cross] ? 0 : Math.PI;
      c.phaseWalk = p; c.phaseRun = p;
    }
  }
  return chains;
}

/** Unwrapped radians; callers retain the existing random initial phases. */
export function advanceProceduralPhase(phase: number, dt: number, gait: 'walk' | 'run' | null): number {
  return phase + dt * (gait === null ? 1.6 : gait === 'run' ? 11 : 7);
}

/** Swing in radians and vertical bob in the same units as height. */
export function proceduralGaitAmplitudes(phase: number, legPhase: number, height: number): { swing: number; bob: number } {
  return { swing: Math.sin(phase + legPhase) * 0.45, bob: Math.abs(Math.sin(phase)) * height * 0.02 };
}

/** Idle bob in metres and breathing as a relative scale multiplier. */
export function proceduralIdleAmplitudes(phase: number): { bob: number; scale: number } {
  return { bob: Math.sin(phase) * 0.012, scale: 1 + Math.sin(phase * 0.5) * 0.006 };
}
