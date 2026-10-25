# Shared test vectors

Hand-derived inputs and expectations that the browser smokes (JavaScript) and the native
client's C# tests both read. One file per area: `shared/test-vectors/<area>.json`
(lowercase letters, digits, underscores). A vector is the drift guard between the two
implementations: when both pass the same file, they compute the same numbers.

## Rules

- **The derivation stays in the source smoke's docstring.** A vector file carries only inputs,
  expectations and `source`, the repo path of the smoke whose docstring derives every number by
  hand from the spec. Case labels start with the `[n]` of that derivation.
- **A vector is never edited to match an implementation.** When an implementation disagrees with
  a vector, the implementation is fixed. A vector changes only when the spec (and with it the
  hand derivation in the docstring) changes.
- No code-generated values: every number in the file is written out.
- No C# geometry code without a green vector from this directory.

## Format `anima-test-vectors/1`

```json
{ "format": "anima-test-vectors/1",
  "source": "client3d/scripts/smoke_bench_math.mjs",
  "fixtures": { "PATH": { "keys": [] } },
  "cases": [ { "label": "[1] a mid keyframe", "fn": "samplePath",
               "args": [ { "$fixture": "PATH" }, 2.5 ], "expect": { "pos": [0, 24, 40] }, "eps": 1e-9 } ] }
```

| Key | Required | Meaning |
|---|---|---|
| `format` | yes | exactly `"anima-test-vectors/1"` |
| `source` | yes | repo path of the smoke holding the hand derivations |
| `fixtures` | no | object, name → any JSON value, referenced from `args` |
| `cases` | yes | non-empty array of cases |
| `cases[].label` | yes | non-empty string, unique within the file (it is the test's display name) |
| `cases[].fn` | yes | name of the function under test, looked up in the runner's dispatch table |
| `cases[].args` | yes | array; the call is `fn(...args)` after fixture resolution |
| `cases[].expect` | yes | expected return value (`null` is a valid expectation) or `{"$throws": true}` |
| `cases[].eps` | no | absolute tolerance for every number in `expect`, `>= 0`, default `1e-9` |

### Fixtures

`{"$fixture": "NAME"}` anywhere inside `args` (at any depth) is replaced by a fresh deep copy of
`fixtures.NAME`, so a function that mutates its input cannot leak into the next case.
`{"$fixture": "NAME", "$with": {...}}` copies an **object** fixture and overrides its top-level
keys with those of `$with` (shallow: a key in `$with` replaces the fixture's value whole).
`$with` on a non-object fixture, an unknown fixture name, or any other key next to
`$fixture` is an error. References are not resolved inside `fixtures` or `expect`.

### Throws

`"expect": {"$throws": true}` (exactly that object) means the call must throw; the case fails when
it returns. Any other expectation fails when the call throws.

### Comparison

`near(expect, actual, eps)` walks the expectation:

- **number**: `actual` must be a finite number with `|expect - actual| <= eps`. An actual
  `NaN` or `±Infinity` fails against every expectation. Integers are compared as doubles;
  `-0` equals `0`.
- **`null`**: equals only `null` (not `0`, not `false`, not a missing key / `undefined`).
- **string / boolean**: strict equality.
- **array**: `actual` must be an array of the same length; elements compare pairwise.
- **object**: `actual` must be an object (not an array); only the expectation's keys are
  checked, extra keys of `actual` are ignored, a missing key fails.

### Load errors

Loading throws (it never skips) when:

- the file is not valid JSON (this includes literals like `NaN` / `Infinity`);
- any number in the file is non-finite (JSON allows `1e400`, which parses to `Infinity`) —
  `NaN`/`Infinity` are forbidden everywhere in the format;
- `format` is not `anima-test-vectors/1`, `source` is missing, `cases` is empty;
- a case lacks `label`, `fn`, `args` (array) or `expect`, has a duplicate label, a bad `eps`,
  a malformed `$throws`, or a fixture reference that does not resolve.

A case whose `fn` is not in the runner's dispatch table is a failure, never a silent skip
(the JS runner throws before running any case).

## JavaScript

`shared/test-vectors/vectors.mjs` (Node built-ins only):

```js
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';
const { passed, failed } = runVectors(loadVectors('bench_math'), { percentile, summarize });
process.exit(failed ? 1 : 0);
```

- `loadVectors(name)` / `loadVectorFile(path)` / `parseVectors(text)` — load and validate.
- `resolveArgs(args, fixtures)` — fixture resolution.
- `near(expect, actual, eps)` → `{ok, diff}`.
- `runVectors(file, fns, {log}?)` → `{passed, failed}`; prints `  ok   <label>` /
  `  FAIL <label>` with expected, actual and the first difference.

`node shared/test-vectors/smoke_vectors_format.mjs` checks these semantics.

## C#

The native tests (`native/tests/Vectors/`) implement the same rules: `VectorFile.Load(name)`,
`VectorCompare.Near(expect, actual, eps, out diff)`, and each vector test class has a dispatch
table `fn → Func<JsonArray, JsonNode?>` that fails a case whose `fn` it does not know.

## Files

| File | Source smoke | Functions |
|---|---|---|
| `bench_math.json` | `client3d/scripts/smoke_bench_math.mjs` | `percentile`, `summarize` (`client3d/src/bench/benchStats.ts`) |
| `ground_polygons.json` | `client3d/scripts/smoke_ground_math.mjs` | `signedArea`, `polygonArea`, `cleanRing` (`packages/scene-render/src/groundAreas.ts`) |
| `scatter.json` | `client3d/scripts/smoke_scatter_math.mjs` | the C#-ported functions of `packages/scene-render/src/scatter.ts` and `client3d/src/scene/scatterLod.ts` (TS↔C# table in the smoke's header). A sampler's `rng` option is a list of numbers, fed in order; drawing past its end throws |
