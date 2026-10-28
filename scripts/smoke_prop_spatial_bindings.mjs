/** Spatial authoring consumer regressions; intentionally run by the controller. */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile, mkdtemp, writeFile, rm } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const ts = require('typescript');
const dir = await mkdtemp(join(tmpdir(), 'prop-spatial-'));
try {
  const canonicalSource = await readFile(new URL('../packages/scene-render/src/placeTransform.ts', import.meta.url), 'utf8');
  const canonicalFile = join(dir, 'placeTransform.mjs');
  const transpile = source => ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } }).outputText;
  await writeFile(canonicalFile, transpile(canonicalSource));
  const source = await readFile(new URL('../frontend/src/tabs/props/accessGeometry.ts', import.meta.url), 'utf8');
  const file = join(dir, 'spatial.mjs');
  await writeFile(file, transpile(source).replace('../../../../packages/scene-render/src/placeTransform', './placeTransform.mjs'));
  const { accessWorldPoint, accessLocalPoint, propMetresPerUnit } = await import(`file://${file}`);
  const { placeTransform } = await import(`file://${canonicalFile}`);
  const near = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-10, `${actual} != ${expected}`);
  const dimensions = { width_m: 2, depth_m: 1.5, height_m: 1 };
  const cases = [
    { bbox: [4, 4, 4], rotation: { y: 45 }, expected: .5 },
    { bbox: [4, 2, 1], rotation: { y: 45 }, expected: .5 },
    { bbox: [4, 2, 1], rotation: { x: 36, y: 127, z: -58 }, expected: .5 },
    { bbox: [4, 2, 1], rotation: { x: -45, y: -135, z: -223 }, expected: .5 },
    { bbox: [4, 2, 1], rotation: { x: 91, y: -271, z: 179 }, expected: .5 },
  ];
  for (const { bbox, rotation, expected } of cases) {
    const scale = propMetresPerUnit(bbox, dimensions, rotation);
    near(scale, expected);
    const placement = placeTransform({ role: 'prop', id: 'regression', variants: {}, level: 0,
      fix_euler: { x: 0, y: 0, z: 0, ...rotation }, yaw_deg: 0, measure: 'xyz',
      max_m: 2, anchor: [0, 0], bottom_y: 0 }, [{ min: [0, 0, 0], max: bbox }]);
    near(scale, placement.outerScale);
    const frame = { centreX: 4, centreZ: -3, groundY: -2, unitsPerMetre: 1 / scale };
    const access = { x: -4, z: 5, yaw: 90 };
    const rendered = accessWorldPoint(access, frame);
    near((rendered[0] - frame.centreX) * placement.outerScale, access.x);
    near((rendered[2] - frame.centreZ) * placement.outerScale, access.z);
    assert.equal(rendered[1], frame.groundY);
    assert.deepEqual(accessLocalPoint(rendered, frame), { x: access.x, z: access.z });
    // Slots and a reference figure use metres / scale in the raw-unit viewer.
    near((.6 / scale) * placement.outerScale, .6);
    near((1.75 / scale) * placement.outerScale, 1.75);
    // Raw marker readback remains a raw-box fraction, not an exact-rotation AABB fraction.
    near(.75 * bbox[0] * scale, .75 * bbox[0] * placement.outerScale);
  }
  near(propMetresPerUnit([4, 4, 4], dimensions, { y: 45 }), .5);
  assert.ok(Math.abs(propMetresPerUnit([4, 4, 4], dimensions, { y: 45 }) - .5 / Math.sqrt(2)) > .1);
  const marker = id => ({ id, group: 'seat', at: [.5, 0, .5], capacity: 2 });
  const binding = { action_id: 'pair', variant_uid: 'v', supported: true, marker_ids: ['a', 'b'], validation: 'local_valid' };
  const frame = { centreX: 4, centreZ: -3, groundY: -2, unitsPerMetre: 2 };
  // Outside-box access is preserved, ground is fixed, and inverse picking agrees.
  assert.deepEqual(accessWorldPoint({ x: -4, z: 5, yaw: 90 }, frame), [-4, -2, 7]);
  assert.deepEqual(accessLocalPoint([-4, -2, 7], frame), { x: -4, z: 5 });
  // The preview renders every server-provided marker/slot/role, preserving numbers.
  // These arbitrary points deliberately cannot be inferred from body marker geometry.
  const previewSource = await readFile(new URL('../frontend/src/tabs/props/PropPreview.tsx', import.meta.url), 'utf8');
  const module = { exports: {} };
  const jsx = (type, props) => ({ type, props });
  const Viewer = () => null;
  runInNewContext(ts.transpileModule(previewSource, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText,
    { module, exports: module.exports, require: id => {
      if (id === 'react') return { useMemo: fn => fn(), useState: initial => [initial, () => {}] };
      if (id === 'react/jsx-runtime') return { jsx, jsxs: jsx };
      if (id === '@anima/scene-render') return { FIGURE_HEIGHT_M: 1.70 };
      if (id.includes('Model3DViewer')) return { Model3DViewer: Viewer };
      if (id.includes('placeTypes')) return { previewEntry: () => undefined };
      if (id.includes('usePropWorkspace')) return { saveScaleFigure() {} };
      if (id.includes('accessGeometry')) return { propMetresPerUnit };
      if (id.includes('propActionAuthoring')) return { actionPreviewPose: () => 'sit' };
      throw new Error(id);
    } });
  const points = { a: { 0: { actor: { x: -1.2, z: 3.4, yaw: 7, source: 'auto' } },
    1: { actor: { x: -.6, z: 3.4, yaw: 7, source: 'auto' } },
    2: { actor: { x: 0, z: 3.4, yaw: 7, source: 'auto' } } },
    b: { 0: { actor: { x: 9, z: -8, yaw: 270, source: 'override' } } } };
  const tree = module.exports.PropPreview({ workspace: {
    t: text => text, actions: [{ id: 'sit', participants: 1 }], selectedActionId: 'sit',
    shownVariant: { uid: 'v' }, derivedBindings: { v: [binding] },
    accessPreviews: { sit: { v: points } }, area: 'places', markers: [],
    poseCatalog: { entries: [] }, groups: {}, shownDims: dimensions, prop: {},
    variants: [], shownHasMesh: true, accessPlacing: null, waterController: {},
  } });
  function findViewer(node) {
    if (!node || typeof node !== 'object') return undefined;
    if (Array.isArray(node)) return node.map(findViewer).find(Boolean);
    return node.type === Viewer ? node : findViewer(node.props?.children);
  }
  const rings = findViewer(tree).props.actionAccessPoints;
  assert.equal(rings.length, 4);
  assert.deepEqual(Array.from(rings, point => [point.x, point.z, point.yaw]), [[-1.2, 3.4, 7], [-.6, 3.4, 7], [0, 3.4, 7], [9, -8, 270]]);
  assert(rings[0].label.includes('Automatic access'));
  assert(rings[3].label.includes('Access override'));
  console.log('PASS: derived binding preview, ground coordinates and all server access rings');
} finally { await rm(dir, { recursive: true, force: true }); }
