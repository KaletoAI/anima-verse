/** Shared E3 vector adapters. See shared/test-vectors/README.md for their JSON contract. */
import { build } from 'esbuild';
import { vectorArgs, vectorValue } from './e3VectorSupport.mjs';
const paths = {
  lod: 'client3d/src/scene/terrainLod.ts', height: 'packages/scene-render/src/worldHeight.ts',
  tiles: 'client3d/src/scene/heightTiles.ts', layer: 'packages/scene-render/src/layerCut.ts',
  natural: 'client3d/src/scene/naturalGroundMath.ts', raster: 'client3d/src/scene/waterRaster.ts',
  shade: 'client3d/src/scene/waterShade.ts', plane: 'client3d/src/scene/waterPlaneMath.ts',
  fall: 'packages/scene-render/src/waterfall.ts', curtain: 'client3d/src/scene/waterfall.ts',
  sky: 'client3d/src/scene/skyLight.ts', fog: 'client3d/src/scene/fogConstants.ts',
  shadow: 'client3d/src/scene/shadowSnap.ts', backdrop: 'client3d/src/scene/backdropProfile.ts',
  veil: 'client3d/src/scene/fogVeilMath.ts', wave: 'packages/scene-render/src/materials.ts',
  ambience: 'client3d/src/scene/ambience.ts',
};
export async function e3Dispatch() {
  const built = await build({ stdin: { contents: Object.entries(paths).map(([name, path]) =>
    `export * as ${name} from './${path}';`).join('\n'), resolveDir: process.cwd(), loader: 'ts' },
    bundle: true, platform: 'node', format: 'esm', write: false });
  const modules = await import(`data:text/javascript;base64,${Buffer.from(built.outputFiles[0].text).toString('base64')}`);
  const functions = Object.assign({}, ...Object.values(modules));
  function decode(value) {
    if (Array.isArray(value)) return value.map(decode);
    if (!value || typeof value !== 'object') return value;
    if ('$grid' in value) return (x, z) => functions.sampleWorldHeight(value.$grid, x, z);
    if ('$plane' in value) {
      const [a, b, c] = value.$plane;
      return (x, z) => a * x + b * z + c;
    }
    if ('$pyramid' in value) return functions.buildPyramid(...decode(value.$pyramid));
    if ('$capGrid' in value) return functions.buildLodCapGrid(...decode(value.$capGrid));
    if ('$layerWindow' in value) return functions.packLayerWindow(...decode(value.$layerWindow));
    if ('$raster' in value) {
      const { tileM, tiles } = value.$raster;
      return { tileM, tiles: new Map(tiles.map(([key, args]) => [key, functions.waterTileFrom(...args)])) };
    }
    if ('$rng' in value) {
      let i = 0;
      return () => {
        if (i >= value.$rng.length) throw new Error('Hand-derived random stream exhausted');
        return value.$rng[i++];
      };
    }
    if ('$select' in value) {
      const { bounds, ...opts } = value.$select;
      return { ...opts, boundsOf: () => ({ ...bounds }) };
    }
    if ('$number' in value) {
      if (value.$number === 'NaN') return NaN;
      throw new Error(`Unknown non-finite input ${value.$number}`);
    }
    const decoded = Object.fromEntries(Object.entries(value).map(([k, v]) => [k, decode(v)]));
    return vectorArgs(decoded);
  }
  function plain(value) {
    if (typeof value === 'number' && !Number.isFinite(value)) return null;
    if (value instanceof Map) return [...value].map(([k, v]) => [k, plain(v)]);
    if (ArrayBuffer.isView(value) || Array.isArray(value)) return Array.from(value, plain);
    if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, plain(v)]));
    return value;
  }
  const dispatch = {};
  for (const [name, fn] of Object.entries(functions)) {
    if (typeof fn !== 'function') continue;
    const invoke = (...args) => {
      if (name === 'latticeSample') {
        const [rows, ...rest] = args;
        return fn((i, j) => rows[j]?.[i] ?? 0, ...rest);
      }
      const result = fn(...decode(args));
      if (name === 'gameHourLights') return { ...result, sun: result.sun.getHex(), sky: result.sky.getHex() };
      return result;
    };
    dispatch[name] = (...args) => plain(invoke(...args));
    dispatch[`${name}Value`] = (args, path) => plain(vectorValue(invoke(...args), path));
  }
  dispatch.e3Constants = () => Object.fromEntries(Object.entries(functions).filter(([k, v]) =>
    /^[A-Z][A-Z_0-9]+$/.test(k) && (typeof v === 'number' || typeof v === 'string')));
  return dispatch;
}
