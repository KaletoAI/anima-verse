/** JSON adapter shared with the later native consumer (schema in the smoke header).
 * Only input poses are assembled here; expectations always come from JSON.
 */
export function retargetVectorDispatch(THREE, api) {
  const rotation = (turns = []) => {
    const q = new THREE.Quaternion();
    for (const [axis, degrees] of turns) {
      const v = new THREE.Vector3(axis === 'x' ? 1 : 0, axis === 'y' ? 1 : 0, axis === 'z' ? 1 : 0);
      q.multiply(new THREE.Quaternion().setFromAxisAngle(v, degrees * Math.PI / 180));
    }
    return q;
  };
  const pose = (data) => {
    const out = { world: new Map(), parent: new Map(), parentBone: new Map(), position: new Map(), soles: new Map() };
    const matrices = new Map();
    const armature = rotation(data.armature);
    for (const [key, parent, turns = [], xyz = [0, 0, 0]] of data.bones) {
      const above = parent === null ? armature : out.world.get(parent);
      const matrix = (parent === null ? new THREE.Matrix4().makeRotationFromQuaternion(armature) : matrices.get(parent)).clone()
        .multiply(new THREE.Matrix4().compose(new THREE.Vector3(...xyz), rotation(turns), new THREE.Vector3(1, 1, 1)));
      matrices.set(key, matrix);
      out.world.set(key, above.clone().multiply(rotation(turns)));
      out.parent.set(key, above.clone()); out.parentBone.set(key, parent);
      out.position.set(key, new THREE.Vector3().setFromMatrixPosition(matrix));
    }
    const root = [...out.parentBone].find(([, parent]) => parent === null)?.[0];
    const inverse = out.world.get(root)?.clone().invert();
    for (const [side, points] of Object.entries(data.soles ?? {})) {
      const matrix = matrices.get(side + 'foot');
      const point = (xyz) => {
        const v = new THREE.Vector3(...xyz).applyMatrix4(matrix);
        return inverse ? v.applyQuaternion(inverse) : v;
      };
      out.soles.set(side, { heel: point(points.heel), toe: point(points.toe) });
    }
    for (const key of data.omitPositions ?? []) out.position.delete(key);
    return out;
  };
  const corrections = (donor, target) => api.restCorrections(THREE, pose(donor), pose(target));
  const factors = (map) => Object.fromEntries([...map].map(([key, k]) => [key, { left: k.left.toArray(), right: k.right.toArray() }]));
  const drive = (k, q) => k ? q.premultiply(k.left).multiply(k.right) : q;
  return {
    retargetFactors: (donor, target) => factors(corrections(donor, target)),
    retargetConstantDeformations: (donor, target, animated) => {
      const d = pose(donor), t = pose(target), map = corrections(donor, target);
      const dw = new Map(), tw = new Map(), out = {};
      for (const [key, parent] of target.bones) {
        const dq = (parent === null ? rotation(donor.armature) : dw.get(parent)).clone().multiply(rotation(animated[key]));
        const tq = (parent === null ? rotation(target.armature) : tw.get(parent)).clone().multiply(drive(map.get(key), rotation(animated[key])));
        dw.set(key, dq); tw.set(key, tq);
        const donorDeformation = dq.clone().multiply(d.world.get(key).clone().invert());
        const targetDeformation = tq.clone().multiply(t.world.get(key).clone().invert());
        out[key] = donorDeformation.invert().multiply(targetDeformation).toArray();
      }
      return out;
    },
    retargetHas: (donor, target, key) => corrections(donor, target).has(key),
    retargetDeformation: (donor, target, key, turns) => {
      const q = drive(corrections(donor, target).get(key), rotation(turns));
      return q.multiply(pose(target).world.get(key).clone().invert()).toArray();
    },
    retargetWorld: (donor, target, animated) => {
      const map = corrections(donor, target), world = new Map();
      for (const [key, parent] of target.bones) {
        const above = parent === null ? rotation(target.armature) : world.get(parent);
        world.set(key, above.clone().multiply(drive(map.get(key), rotation(animated[key]))));
      }
      return Object.fromEntries([...world].map(([key, q]) => [key, q.toArray()]));
    },
    bindRelativeClipSummary: (donor, target, key, turns, positions) => {
      const q = rotation(turns).toArray();
      const pt = new THREE.VectorKeyframeTrack('hips.position', [0, 1], positions);
      const clip = new THREE.AnimationClip('idle', 1, [
        new THREE.QuaternionKeyframeTrack(key + '.quaternion', [0, 1], [...q, ...q]), pt]);
      const out = api.bindRelativeClip(THREE, clip, corrections(donor, target));
      return { sameClip: out === clip, samePosition: out.tracks[1] === pt,
        positions: Array.from(out.tracks[1].values), quaternion: Array.from(out.tracks[0].values).slice(0, 4) };
    },
    retargetKeys: (donor, target) => [...corrections(donor, target).keys()],
    retargetDrive: (donor, target, key, turns) => drive(corrections(donor, target).get(key), rotation(turns)).toArray(),
    retargetPositions: (donor, target, animated = {}) => {
      const map = corrections(donor, target), matrices = new Map(), out = {};
      for (const [key, parent, , xyz = [0, 0, 0]] of target.bones) {
        const above = parent === null ? new THREE.Matrix4().makeRotationFromQuaternion(rotation(target.armature)) : matrices.get(parent);
        const matrix = above.clone().multiply(new THREE.Matrix4().compose(new THREE.Vector3(...xyz),
          drive(map.get(key), rotation(animated[key])), new THREE.Vector3(1, 1, 1)));
        matrices.set(key, matrix); out[key] = new THREE.Vector3().setFromMatrixPosition(matrix).toArray();
      }
      return out;
    },
    retargetSoleDeltas: (donor, target) => {
      const map = corrections(donor, target);
      const rest = pose(target);
      const root = [...rest.parentBone].find(([, parent]) => parent === null)?.[0];
      const rootQ = rest.world.get(root) ?? new THREE.Quaternion();
      return ['left', 'right'].map(side => {
        const key = side + 'foot', sole = rest.soles.get(side);
        // Deformation at an identity clip is S in the root rest frame.
        const q = rootQ.clone().invert().multiply(rest.world.get(key));
        const k = map.get(key)?.right ?? new THREE.Quaternion();
        const delta = sole.heel.clone().sub(sole.toe).applyQuaternion(q.invert()).applyQuaternion(k);
        return delta.y;
      });
    },
    bindRelativeValues: (donor, target, key, turns) => {
      const q = rotation(turns);
      const values = api.bindRelativeValues(THREE, q.toArray(), corrections(donor, target).get(key));
      return values ? Array.from(values) : null;
    },
    retargetCounterProbe: (kind) => {
      const ry = d => rotation([['y', d]]), rx = d => rotation([['x', d]]);
      const q = kind === 'order'
        ? rx(40).invert().multiply(ry(50)).multiply(rx(40)).multiply(ry(-50))
        : ry(20).multiply(rx(40)).multiply(ry(-20)).multiply(rx(-40));
      return 2 * Math.acos(Math.min(1, Math.abs(q.w))) * 180 / Math.PI;
    },
  };
}
