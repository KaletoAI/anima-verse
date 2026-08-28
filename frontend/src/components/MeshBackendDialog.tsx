import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../i18n/I18nProvider'
import { DEFAULT_MODEL_TIER, MODEL_TIERS, type ModelTier } from './ModelGallery'

export interface MeshBackend {
  name: string
  face_num?: number | null
  /** Hard ceiling of this backend's face count (0/absent = none). Some
   *  backends do not fail above their limit, they hang — so the field caps
   *  the input instead of letting the job run into a timeout. */
  face_num_max?: number | null
  /** This alias can bake reduced LOD stages in the SAME job. Comes from the
   *  alias schema (server side), never from the backend's name. */
  lod_stages?: boolean
}

/** Per-run overrides next to the backend pick — empty = backend default. */
export interface MeshGenerateOpts {
  face_num?: number
  texture_size?: number
  /** Resolution slot the result fills (only sent when the caller offers the
   *  tier choice). */
  tier?: ModelTier
  /** Target triangle count of the low stage baked in the same job (absent =
   *  no stage requested). */
  lod_faces?: number
}

const TEXTURE_SIZES = [512, 1024, 2048]

/** Prefilled target size of the low stage — the alias default of the contract. */
const LOD_STAGE_DEFAULT = 5000

// Low-variant recipe for a run that targets the `low` tier directly — the
// third way next to a baked generation stage and the mesh→mesh reduction: a
// second run with a smaller budget. The numbers are a PREFILL, shown in the
// editable fields — not a hidden rewrite of what the admin asked for.
const LOW_FACE_FRACTION = 0.25
/** Offered when the picked backend declares no face default of its own. */
const LOW_FACE_FALLBACK = 4000
const LOW_TEXTURE_SIZE = 512

/** Face budget prefilled for a tier: what the SUBJECT states for it, else the
 *  backend default for `full` and a quarter of it (rounded to 500) for `low`.
 *  '' = leave it to the backend.
 *
 *  The subject's own targets come first because they are a decision that
 *  outlives the run (props v2 E5): a variant that says what it costs must not
 *  have that overwritten by whatever the picked backend defaults to. */
function faceFor(tier: ModelTier, backendDefault: number,
                 stated: FaceTargets = {}): string {
  if (tier === DEFAULT_MODEL_TIER) {
    if (stated.high) return String(stated.high)
    return backendDefault ? String(backendDefault) : ''
  }
  if (stated.low) return String(stated.low)
  if (!backendDefault) return String(LOW_FACE_FALLBACK)
  return String(Math.max(500, Math.round(backendDefault * LOW_FACE_FRACTION / 500) * 500))
}

/** What the SUBJECT of this run states about its own triangle budgets — the
 *  variant's `target_faces_high` / `target_faces_low` where the caller has
 *  them (props v2 E5). Absent fields fall back to the backend default. */
export interface FaceTargets {
  high?: number | null
  low?: number | null
}

/**
 * Backend picker for a mesh generation — shared by EVERY 3D generate button
 * (character 3D model, building/room models, prop regenerate). ALWAYS a
 * dialog (even with a single backend, which is then preselected); the list is
 * the available mesh backends of the relevant rig. Picking a backend prefills
 * "Face count" with ITS configured default — override it per run. "Texture
 * size" is plumbed the same way and reaches the gateway as soon as its alias
 * declares the parameter. Rendered via createPortal so it also works inside
 * the /play grid.
 *
 * A backend whose alias can bake reduced LOD stages in the same job (server
 * flag `lod_stages`, read from the alias schema) additionally offers the low
 * stage's target size — one run then fills both tiers. The control is absent
 * for every other backend.
 *
 * With `showTier` the dialog also asks WHICH resolution slot the result fills
 * (galleries that hold one mesh per tier). Picking `low` prefills the reduced
 * budget into the very same fields, so the admin sees — and may change — what
 * the run will actually use. The mesh→mesh reduction ("Create low variant")
 * uses the same dialog WITHOUT the tier choice — its result is a low variant
 * by definition — and prefills the shrink alias' own defaults.
 */
export function MeshBackendDialog({
  open,
  title,
  backends,
  defaultBackend = '',
  defaultTextureSize = 0,
  generateLabel,
  showTier = false,
  hint = '',
  faceTargets = {},
  onGenerate,
  onClose,
}: {
  open: boolean
  title: string
  backends: MeshBackend[]
  /** Preselected backend (e.g. the admin default when rig-compatible). */
  defaultBackend?: string
  /** Preselected texture size (0 = "backend default"). The alias defaults are
   *  not readable from here, so a caller that knows them states them. */
  defaultTextureSize?: number
  generateLabel?: string
  /** Offer the target resolution tier — for the model galleries; the
   *  character model has no tiers. */
  showTier?: boolean
  /** One line above the fields explaining what this particular run does. */
  hint?: string
  /** What the subject STATES it should cost — prefilled over the backend
   *  default, and editable per run like everything else here. */
  faceTargets?: FaceTargets
  onGenerate: (backend: string, opts: MeshGenerateOpts) => void
  onClose: () => void
}) {
  const { t } = useI18n()
  const [picked, setPicked] = useState(defaultBackend)
  const [faceDraft, setFaceDraft] = useState('')
  const [texSize, setTexSize] = useState('')
  const [tier, setTier] = useState<ModelTier>(DEFAULT_MODEL_TIER)
  // Low stage baked alongside the main result — only for backends whose alias
  // declares it. On by default (it costs seconds and fills the low tier), but
  // switchable off: some subjects only ever get looked at from up close.
  const [lodOn, setLodOn] = useState(true)
  const [lodDraft, setLodDraft] = useState(String(LOD_STAGE_DEFAULT))
  // Reset the selection to the default each time the dialog opens (the
  // backends and default may have loaded/changed between opens). Keyed on
  // the backends' CONTENT, not the array identity — the callers refresh
  // their lists on every job poll, and a fresh (but identical) array must
  // not wipe a selection the admin just made.
  const backendsKey = backends.map((b) => `${b.name}:${b.face_num || 0}`).join('|')
  const statedHigh = faceTargets.high || 0
  const statedLow = faceTargets.low || 0
  useEffect(() => {
    if (!open) return
    setPicked(defaultBackend)
    const b = backends.find((x) => x.name === defaultBackend)
    setFaceDraft(faceFor(DEFAULT_MODEL_TIER, b?.face_num || 0, faceTargets))
    setTexSize(defaultTextureSize ? String(defaultTextureSize) : '')
    setTier(DEFAULT_MODEL_TIER)
    setLodOn(true)
    setLodDraft(String(statedLow || LOD_STAGE_DEFAULT))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, defaultBackend, defaultTextureSize, backendsKey, statedHigh, statedLow])

  if (!open) return null
  const none = backends.length === 0
  const selectedBackend = backends.find((x) => x.name === picked)
  // 0 = no cap. Above its cap such a backend does not fail, it HANGS — so the
  // field stops the value here (the server clamps too, and logs it).
  const faceMax = selectedBackend?.face_num_max || 0
  // The stage control only exists where the alias can bake one, and only for a
  // run that fills the FULL tier — a low run IS the reduced mesh already.
  const canLod = !!selectedBackend?.lod_stages
    && (!showTier || tier === DEFAULT_MODEL_TIER)

  const pick = (name: string) => {
    setPicked(name)
    // The face field always shows what THIS run would use: the newly picked
    // backend's configured default (reduced when the target tier is low),
    // ready to be overridden.
    const b = backends.find((x) => x.name === name)
    setFaceDraft(faceFor(tier, b?.face_num || 0, faceTargets))
  }

  const pickTier = (next: ModelTier) => {
    setTier(next)
    const b = backends.find((x) => x.name === picked)
    setFaceDraft(faceFor(next, b?.face_num || 0, faceTargets))
    setTexSize(next === DEFAULT_MODEL_TIER ? '' : String(LOW_TEXTURE_SIZE))
  }

  const start = () => {
    const opts: MeshGenerateOpts = {}
    let f = parseInt(faceDraft, 10)
    const selected = backends.find((x) => x.name === picked)
    const max = selected?.face_num_max || 0
    if (Number.isFinite(f) && max > 0 && f > max) f = max
    // Send the face count only when it differs from the backend default —
    // an untouched prefill keeps meaning "backend default", and the server
    // then falls back to the subject's own stated budget (props v2 E5), which
    // is the very number this field was prefilled with.
    if (Number.isFinite(f) && f > 0 && f !== (selected?.face_num || 0)) {
      opts.face_num = f
    }
    const tex = parseInt(texSize, 10)
    if (Number.isFinite(tex) && tex > 0) opts.texture_size = tex
    if (showTier) opts.tier = tier
    if (canLod && lodOn) {
      const lod = parseInt(lodDraft, 10)
      if (Number.isFinite(lod) && lod > 0) opts.lod_faces = lod
    }
    onGenerate(picked, opts)
  }

  return createPortal(
    <div className="ga-modal-backdrop" onClick={onClose}>
      <div
        className="ga-modal"
        role="dialog"
        aria-label={title}
        style={{ maxWidth: 460 }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="ga-modal-header">
          <span>{title}</span>
          <button type="button" className="ga-modal-close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="ga-modal-body">
          {none ? (
            <div className="ga-hint">
              {t('No mesh backend available — configure one (api_type openai_mesh) in Media Generation.')}
            </div>
          ) : (
            <div className="ga-form">
              {hint ? <div className="ga-hint">{hint}</div> : null}
              {showTier ? (
                <>
                  <label className="ga-hint">{t('Target resolution tier')}</label>
                  <select
                    className="ga-input"
                    value={tier}
                    onChange={(e) => pickTier(e.target.value as ModelTier)}
                  >
                    {MODEL_TIERS.map((v) => (
                      <option key={v} value={v}>{v}</option>
                    ))}
                  </select>
                  <div className="ga-hint">
                    {tier === DEFAULT_MODEL_TIER
                      ? t('The modelled quality — what the clients render up close.')
                      : t('The distance mesh. This run is a second, smaller one: face count and texture below are prefilled accordingly — change them freely. A low mesh can also come from a generation stage or from “⤵ low variant”.')}
                  </div>
                </>
              ) : null}
              <label className="ga-hint">{t('Backend')}</label>
              <select
                className="ga-input"
                value={picked}
                onChange={(e) => pick(e.target.value)}
              >
                <option value="">{t('— default (cheapest available) —')}</option>
                {backends.map((b) => (
                  <option key={b.name} value={b.name}>
                    {b.name}
                    {b.face_num ? ` · ${b.face_num.toLocaleString()} ${t('faces')}` : ''}
                  </option>
                ))}
              </select>
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 2, flex: 1, minWidth: 140 }}
                  title={t('Target triangle count for THIS run. Prefilled with the picked backend\'s default — small deco needs far fewer faces than a character (2,000–20,000).')}>
                  <span className="ga-hint">{t('Face count')}</span>
                  <input
                    className="ga-input"
                    type="number"
                    min={500}
                    max={faceMax || 100000}
                    step={500}
                    value={faceDraft}
                    placeholder={t('backend default')}
                    onChange={(e) => setFaceDraft(e.target.value)}
                  />
                  {faceMax ? (
                    <span className="ga-hint">
                      {t('Max')} {faceMax.toLocaleString()} — {t('this backend hangs above its limit')}
                    </span>
                  ) : null}
                </label>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 2, flex: 1, minWidth: 140 }}
                  title={t('Texture resolution for THIS run — sent as "input_texture_resolution" whenever the alias declares it. Small props rarely need more than 1024.')}>
                  <span className="ga-hint">{t('Texture size')}</span>
                  <select
                    className="ga-input"
                    value={texSize}
                    onChange={(e) => setTexSize(e.target.value)}
                  >
                    <option value="">{t('— backend default —')}</option>
                    {TEXTURE_SIZES.map((v) => (
                      <option key={v} value={String(v)}>{v} × {v}</option>
                    ))}
                  </select>
                </label>
              </div>
              {canLod ? (
                <>
                  <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    <input
                      type="checkbox"
                      checked={lodOn}
                      onChange={(e) => setLodOn(e.target.checked)}
                    />
                    <span className="ga-hint">{t('Also bake a low stage')}</span>
                    <input
                      className="ga-input"
                      type="number"
                      min={500}
                      max={faceMax || 100000}
                      step={500}
                      style={{ width: 110 }}
                      disabled={!lodOn}
                      value={lodDraft}
                      onChange={(e) => setLodDraft(e.target.value)}
                    />
                    <span className="ga-hint">{t('faces')}</span>
                  </label>
                  <div className="ga-hint">
                    {t('The stage is baked from the same views in the same job, while “⤵ low variant” reduces an already stored mesh.')}
                  </div>
                </>
              ) : null}
              <div className="ga-hint">
                {t('Higher face counts mean more detail, bigger files and a slower run.')}
              </div>
            </div>
          )}
        </div>
        <div className="ga-modal-footer" style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
          <button type="button" className="ga-btn ga-btn-sm" onClick={onClose}>
            {t('Cancel')}
          </button>
          <button
            type="button"
            className="ga-btn ga-btn-sm ga-btn-primary"
            disabled={none}
            onClick={start}
          >
            {generateLabel || t('Generate')}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
