/**
 * @anima/scene-render — die geteilten Renderer-Routinen des Szenen-Vertrags.
 *
 * Konsumenten: `frontend` (Admin-Grundriss-Vorschau + 2D-Untergrund) und
 * `client3d` (3D-Weltkarte). Beide hatten diese Routinen vorher je einmal
 * selbst — der Clip-Shader wurde nachweislich zweimal unabhängig gebaut.
 *
 * BEWUSST NICHT hier: Kamera/LOD/Fades, Culling-Anwendung, Labels,
 * Wegfindung, NPC-Logik, Editor-Overlays. Sicht-Zustand bleibt pro App.
 *
 * three kommt überall als PARAMETER, nie als Import — sonst zöge das Paket
 * die Bibliothek in das Haupt-Bundle des Admins, der sie verzögert nachlädt.
 * Typ-Importe sind davon nicht betroffen (sie verschwinden beim Übersetzen).
 */
export { FIT_BOX_MARGIN, placeModelSpec } from './place'
export type { PlaceOptions } from './place'

export { applyClipOutline, disposeClipMaterials, CLIP_MAX_POINTS } from './clip'

export { SpecVerifier, VERIFY_EPS } from './verify'
export type { PrimitiveTarget, VerifyRow } from './verify'

export type {
  ScenePayload, ScenePlate, SceneWall, SceneExtra, SceneModelSpec,
  SceneMarker, SceneExit, SceneStyle, SceneOpening, SceneRoom,
} from './types'
