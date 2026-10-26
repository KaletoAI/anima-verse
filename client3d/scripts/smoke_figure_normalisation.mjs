#!/usr/bin/env node
/** Hand-derived figure normalisation vectors (no model, config or server).
 * Usage: timeout 300 node client3d/scripts/smoke_figure_normalisation.mjs
 *
 * [N] anchorFigureBind owns pivot position/scale: reset both, measure bind
 * bbox, k = height/(size.y || 1), position = (-cx*k,-minY*k,-cz*k).
 * Offset box min (2,-2,4), max (6,2,8): centre (4,0,6), height 4;
 * desired 2 -> k=.5, position (-2,1,-3), final min (-1,0,-1),
 * max (1,2,1). Initial position (9,8,7), scale 3 are discarded.
 * Centred min (-1,0,-1), max (1,2,1), desired 2: k=1, position zero,
 * same final box (feet already at zero).
 * Flat min (2,3,4), max (4,3,8): height 0 -> denominator 1,
 * desired 2 -> k=2, centre (3,3,6), position (-6,-6,-12),
 * final min (-2,0,-4), max (2,0,4).
 * Negative min (-6,-4,-8), max (-2,0,-4): height=4, desired=4,
 * k=1, centre (-4,-2,-6), position (4,4,6), final min (-2,0,-2),
 * max (2,4,2). Initial position (3,2,1), scale 2 are discarded.
 *
 * figures.ts Figure constructor independently centres XZ and grounds Y
 * after applying model scale. These vectors exercise the existing shared
 * scene-render bind helper; no extraction from either implementation needed.
 */
import { runPairVectors } from './pairVectorDispatch.mjs';
const { passed, failed } = await runPairVectors('figure_normalisation');
console.log(`\n${passed} ok, ${failed} failed`);
process.exitCode = failed ? 1 : 0;
