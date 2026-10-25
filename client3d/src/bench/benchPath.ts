/** Portable path parsing and piecewise linear interpolation; no engine dependencies. */
export type Vec3 = [number, number, number];
export interface CameraPath {
  version: 1;
  space: 'anchor-relative metres, y up';
  duration: number;
  warmup: number;
  keyframes: Array<{t: number; pos: Vec3; target: Vec3}>;
}

export function loadPath(raw: unknown): CameraPath {
  const p = raw as CameraPath;
  const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
  const vector = (v: unknown) => Array.isArray(v) && v.length === 3 && v.every(finite);
  if (!p || p.version !== 1 || p.space !== 'anchor-relative metres, y up'
      || !finite(p.duration) || p.duration <= 0 || !finite(p.warmup) || p.warmup < 0
      || !Array.isArray(p.keyframes) || p.keyframes.length < 2
      || p.keyframes.some((k, i) => !k || !finite(k.t) || !vector(k.pos) || !vector(k.target)
        || (i > 0 && k.t <= p.keyframes[i - 1].t))
      || p.keyframes[0].t !== 0 || p.keyframes.at(-1)!.t !== p.duration) {
    throw new Error('Invalid camera path v1');
  }
  return p;
}

export function samplePath(path: CameraPath, t: number): {pos: Vec3; target: Vec3} {
  if (!Number.isFinite(t)) throw new Error('Path time must be finite');
  const keys = path.keyframes;
  const end = keys.at(-1)!;
  if (t <= keys[0].t) return {pos: [...keys[0].pos], target: [...keys[0].target]};
  if (t >= end.t) return {pos: [...end.pos], target: [...end.target]};
  const hi = keys.findIndex(k => k.t >= t);
  const a = keys[hi - 1], b = keys[hi], u = (t - a.t) / (b.t - a.t);
  const lerp = (x: Vec3, y: Vec3): Vec3 => x.map((v,i) => v + (y[i] - v) * u) as Vec3;
  return {pos: lerp(a.pos,b.pos), target: lerp(a.target,b.target)};
}
