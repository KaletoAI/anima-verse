/**
 * Smoke: WHICH mesh a placement shows when a prop has several model variants.
 *
 * Usage: direct node call, self-bundling via esbuild:
 *     node client3d/scripts/smoke_model_variant.mjs
 *
 * The canonical scene-model smoke bundles fresh TypeScript on every run;
 * failed builds and failed checks exit nonzero.
 *
 * Runs headless against the SHARED `pickModelVariant` — the one routine both
 * renderers use to turn a placement spec into a URL (§ B2 addendum,
 * "Nachtrag 2026-08-19"). No three.js, no DOM: this is string arithmetic.
 *
 * The rule, and every expected value below derived by hand from it:
 *
 *   1. Without `model_variants` the answer is character for character the old
 *      `pickVariant(spec.variants, tier)` — a prop with ONE variant must not
 *      notice that the list exists.
 *   2. With `model_variants`, the map at index `variant` is taken FIRST, the
 *      resolution tier out of that map SECOND. Both steps, in that order.
 *   3. `variants` is `model_variants[0]` by contract, so `variant: 0` and a
 *      missing `variant` both answer with the primary variant's URL.
 *   4. The index is MODULO, not clamped, and negative indices wrap forward:
 *      the variant count moves when an admin adds or deletes a mesh, and a
 *      placement must not disappear because of it.
 *   5. The tier fallback of `pickVariant` still applies INSIDE the chosen
 *      variant: a variant without `low` answers with its `full` URL, it never
 *      falls through to another variant's low mesh (that would draw a
 *      different object at distance).
 */

import { runModelVectors } from './smoke_scene_models.mjs';
const { passed, failed } = await runModelVectors(c => c.label.startsWith('[M]'));
console.log(`\n${passed} passed, ${failed} failed`);
process.exitCode = failed ? 1 : 0;
