/**
 * Which collision payload a garment check measures with (Ruling B11i) — shared by
 * `check_garment_collision.mjs` and its smoke `smoke_check_collision_payload.mjs`.
 *
 * Order, per model:
 *  1. `--collision PAYLOAD.json` (one model only): exactly that file;
 *  2. the SERVED record: the `collision` of the sidecar `<MODEL>.json` beside the GLB — what
 *     `GET /characters/{name}/model3d` hands the client (extension capsules and the character's
 *     region scales included);
 *  3. `--fitted` only: `collision.py::fit_capsules` on the GLB alone — no extension capsules, no
 *     character scales, so NOT the set the client pushes with; the caller prints that.
 * Without any of them the check refuses instead of measuring a set no client uses.
 *
 * Pure apart from the two injected file functions (`exists`, `readJson`).
 */
import * as path from 'path'

/** The sidecar beside a model GLB: `<dir>/<name>.json`. */
export function sidecarPath(modelPath) {
  return path.join(path.dirname(modelPath), path.basename(modelPath).replace(/\.glb$/i, '') + '.json')
}

/** A stored collision record: an object with a capsule list. */
function isRecord(value) {
  return !!value && typeof value === 'object' && Array.isArray(value.capsules)
}

export const FITTED_NOTE = 'FITTED from the GLB alone (no extension capsules, no character scales) — NOT the set the client gets'

/**
 * `{kind: 'file' | 'served' | 'fitted', file, payload, note}` for one model. `payload` is null for
 * `fitted` (the caller fits). Throws when nothing applies or `--collision` names more than one model.
 */
export function resolvePayloadSource(modelPath, opts, io) {
  const { collision = null, fitted = false, modelCount = 1 } = opts
  if (collision) {
    if (modelCount !== 1) throw new Error('--collision needs exactly one model')
    return { kind: 'file', file: collision, payload: io.readJson(collision), note: `payload from ${collision}` }
  }
  const sidecar = sidecarPath(modelPath)
  let reason = `no sidecar ${path.basename(sidecar)} beside the model`
  if (io.exists(sidecar)) {
    const meta = io.readJson(sidecar)
    if (isRecord(meta?.collision)) {
      const rec = meta.collision
      return { kind: 'served', file: sidecar, payload: rec,
        note: `payload = served record of ${path.basename(sidecar)} (version ${rec.version ?? '?'}, ${rec.capsules.length} capsules, source ${rec.source ?? '?'})` }
    }
    reason = `the sidecar ${path.basename(sidecar)} carries no collision record`
  }
  if (fitted) return { kind: 'fitted', file: null, payload: null, note: `payload ${FITTED_NOTE} (${reason})` }
  throw new Error(`${path.basename(modelPath)}: ${reason} — pass --collision PAYLOAD.json, or --fitted for the `
    + 'GLB-only fit (not what the client gets)')
}
