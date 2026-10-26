/** JSON adapters for the E3 smokes. Maps/sets/typed buffers are input values,
 * not expectations; the tags keep their JS representation out of the contract.
 * A FooValue wrapper returns a property path of Foo's result (for old scalar
 * assertions), without putting a second implementation of Foo in the test.
 */
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';
const files = new Map();
export function vectorArgs(value) {
  if (value instanceof Map || value instanceof Set || ArrayBuffer.isView(value)) return value;
  if (Array.isArray(value)) return value.map(vectorArgs);
  if (!value || typeof value !== 'object') return value;
  if ('$map' in value) return new Map(value.$map.map(([k, v]) => [k, vectorArgs(v)]));
  if ('$set' in value) return new Set(value.$set.map(vectorArgs));
  if ('$typed' in value) {
    const types = { Float32Array, Uint8Array, Uint16Array };
    if (!types[value.$typed]) throw new Error(`Unknown buffer ${value.$typed}`);
    return new types[value.$typed](value.values);
  }
  return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, vectorArgs(v)]));
}
export function vectorValue(value, path) {
  for (const key of path) value = value[key];
  return value;
}
export function vectorCase(area, label, fns) {
  if (!files.has(area)) files.set(area, loadVectors(area));
  const file = files.get(area);
  const cases = file.cases.filter(c => c.label === label);
  if (cases.length !== 1) throw new Error(`${area}: expected exactly one case ${label}`);
  return runVectors({ ...file, cases }, fns);
}
