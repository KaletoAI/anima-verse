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
}

/** Per-run overrides next to the backend pick — empty = backend default. */
export interface MeshGenerateOpts {
  face_num?: number
  texture_size?: number
  /** Resolution slot the result fills (only sent when the caller offers the
   *  tier choice). */
  tier?: ModelTier
}

const TEXTURE_SIZES = [512, 1024, 2048]

// Interim low-variant recipe (plan-3d-lod-und-betreten.md Etappe 2): until
// the ComfyUI mesh→mesh reduction exists (Etappe 4), a low variant is simply
// a second run with a smaller budget. The numbers are a PREFILL, shown in the
// editable fields — not a hidden rewrite of what the admin asked for.
const LOW_FACE_FRACTION = 0.25
/** Offered when the picked backend declares no face default of its own. */
const LOW_FACE_FALLBACK = 4000
const LOW_TEXTURE_SIZE = 512

/** Face budget prefilled for a tier: the backend default for `full`, a
 *  quarter of it (rounded to 500) for `low`. '' = leave it to the backend. */
function faceFor(tier: ModelTier, backendDefault: number): string {
  if (tier === DEFAULT_MODEL_TIER) return backendDefault ? String(backendDefault) : ''
  if (!backendDefault) return String(LOW_FACE_FALLBACK)
  return String(Math.max(500, Math.round(backendDefault * LOW_FACE_FRACTION / 500) * 500))
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
 * With `showTier` the dialog also asks WHICH resolution slot the result fills
 * (galleries that hold one mesh per tier). Picking `low` prefills the reduced
 * budget into the very same fields, so the admin sees — and may change — what
 * the run will actually use.
 */
export function MeshBackendDialog({
  open,
  title,
  backends,
  defaultBackend = '',
  generateLabel,
  showTier = false,
  onGenerate,
  onClose,
}: {
  open: boolean
  title: string
  backends: MeshBackend[]
  /** Preselected backend (e.g. the admin default when rig-compatible). */
  defaultBackend?: string
  generateLabel?: string
  /** Offer the target resolution tier — for the model galleries; the
   *  character model has no tiers. */
  showTier?: boolean
  onGenerate: (backend: string, opts: MeshGenerateOpts) => void
  onClose: () => void
}) {
  const { t } = useI18n()
  const [picked, setPicked] = useState(defaultBackend)
  const [faceDraft, setFaceDraft] = useState('')
  const [texSize, setTexSize] = useState('')
  const [tier, setTier] = useState<ModelTier>(DEFAULT_MODEL_TIER)
  // Reset the selection to the default each time the dialog opens (the
  // backends and default may have loaded/changed between opens). Keyed on
  // the backends' CONTENT, not the array identity — the callers refresh
  // their lists on every job poll, and a fresh (but identical) array must
  // not wipe a selection the admin just made.
  const backendsKey = backends.map((b) => `${b.name}:${b.face_num || 0}`).join('|')
  useEffect(() => {
    if (!open) return
    setPicked(defaultBackend)
    const b = backends.find((x) => x.name === defaultBackend)
    setFaceDraft(faceFor(DEFAULT_MODEL_TIER, b?.face_num || 0))
    setTexSize('')
    setTier(DEFAULT_MODEL_TIER)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, defaultBackend, backendsKey])

  if (!open) return null
  const none = backends.length === 0
  const selectedBackend = backends.find((x) => x.name === picked)
  // 0 = no cap. Above its cap such a backend does not fail, it HANGS — so the
  // field stops the value here (the server clamps too, and logs it).
  const faceMax = selectedBackend?.face_num_max || 0

  const pick = (name: string) => {
    setPicked(name)
    // The face field always shows what THIS run would use: the newly picked
    // backend's configured default (reduced when the target tier is low),
    // ready to be overridden.
    const b = backends.find((x) => x.name === name)
    setFaceDraft(faceFor(tier, b?.face_num || 0))
  }

  const pickTier = (next: ModelTier) => {
    setTier(next)
    const b = backends.find((x) => x.name === picked)
    setFaceDraft(faceFor(next, b?.face_num || 0))
    setTexSize(next === DEFAULT_MODEL_TIER ? '' : String(LOW_TEXTURE_SIZE))
  }

  const start = () => {
    const opts: MeshGenerateOpts = {}
    let f = parseInt(faceDraft, 10)
    const selected = backends.find((x) => x.name === picked)
    const max = selected?.face_num_max || 0
    if (Number.isFinite(f) && max > 0 && f > max) f = max
    // Send the face count only when it differs from the backend default —
    // an untouched prefill keeps meaning "backend default".
    if (Number.isFinite(f) && f > 0 && f !== (selected?.face_num || 0)) {
      opts.face_num = f
    }
    const tex = parseInt(texSize, 10)
    if (Number.isFinite(tex) && tex > 0) opts.texture_size = tex
    if (showTier) opts.tier = tier
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
                      : t('The distance mesh. Until the mesh→mesh reduction exists, a low variant is a second run with a smaller budget: face count and texture below are prefilled accordingly — change them freely.')}
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
