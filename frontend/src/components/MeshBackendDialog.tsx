import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../i18n/I18nProvider'
// The budget arithmetic is shared with the variant strip — one rule, so the
// number a field shows and the number a run starts on cannot drift apart.
import { faceFor, LOD_STAGE_DEFAULT, type FaceTargets } from './faceBudget'
import { DEFAULT_MODEL_TIER, MODEL_TIERS, type ModelTier } from './ModelGallery'

export type { FaceTargets }

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

export type MeshView = 'front' | 'back' | 'left' | 'right'

export interface MeshViewChoice {
  view: MeshView
  options: { value: string; label: string }[]
  required?: boolean
}

const VIEW_LABELS: Record<MeshView, string> = {
  front: 'Front', back: 'Back', left: 'Left', right: 'Right',
}

/** Per-run overrides next to the backend pick — empty = backend default. */
export interface MeshGenerateOpts {
  face_num?: number
  texture_size?: number
  /** Resolution slot the result fills (only sent when the caller offers the
   *  tier choice). */
  tier?: ModelTier
  /** Target triangle count of the low stage baked in the same job. THREE
   *  states (ruling V9): absent = this dialog offers no stage control, so the
   *  subject's own low budget may still apply; an EMPTY ARRAY = the control is
   *  there and switched OFF, and nothing is baked; a number = that stage. */
  lod_faces?: number | number[]
  /** Chosen image per view (file name), only views that were picked. */
  views?: Partial<Record<MeshView, string>>
}

const TEXTURE_SIZES = [512, 1024, 2048]

const LOW_TEXTURE_SIZE = 512

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
  views,
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
  /** The VIEWS a multi-view alias may take (design 2026-09-02): per view the
   *  candidate images. 0 options -> not rendered (a required one blocks
   *  Generate), 1 option -> a checkbox (on by default), more -> a select with
   *  "- none -" for optional views and the first entry preselected. */
  views?: MeshViewChoice[]
  onGenerate: (backend: string, opts: MeshGenerateOpts) => void
  onClose: () => void
}) {
  const { t } = useI18n()
  const [picked, setPicked] = useState(defaultBackend)
  const [faceDraft, setFaceDraft] = useState('')
  // What the face field was PREFILLED with. Kept because "untouched" is the
  // only thing that may mean "decide for me" — comparing against the backend
  // default instead would swallow a typed number the moment the subject's own
  // budget happens to differ from it (review finding 2).
  const [facePrefill, setFacePrefill] = useState('')
  const [texSize, setTexSize] = useState('')
  const [tier, setTier] = useState<ModelTier>(DEFAULT_MODEL_TIER)
  // Low stage baked alongside the main result — only for backends whose alias
  // declares it. On by default (it costs seconds and fills the low tier), but
  // switchable off: some subjects only ever get looked at from up close.
  const [lodOn, setLodOn] = useState(true)
  const [lodDraft, setLodDraft] = useState(String(LOD_STAGE_DEFAULT))
  const [viewPick, setViewPick] = useState<Partial<Record<MeshView, string>>>({})
  // Reset the selection to the default each time the dialog opens (the
  // backends and default may have loaded/changed between opens). Keyed on
  // the backends' CONTENT, not the array identity — the callers refresh
  // their lists on every job poll, and a fresh (but identical) array must
  // not wipe a selection the admin just made.
  const backendsKey = backends.map((b) => `${b.name}:${b.face_num || 0}`).join('|')
  const viewsKey = (views || [])
    .map((v) => `${v.view}:${v.options.map((o) => o.value).join(',')}`)
    .join('|')
  const statedHigh = faceTargets.high || 0
  const statedLow = faceTargets.low || 0
  /** Fill the face field AND remember what it was filled with — the two are
   *  one act, and a prefill nobody recorded cannot be told from a typed
   *  number later. */
  const prefillFaces = (value: string) => {
    setFaceDraft(value)
    setFacePrefill(value)
  }
  useEffect(() => {
    if (!open) return
    setPicked(defaultBackend)
    const b = backends.find((x) => x.name === defaultBackend)
    prefillFaces(faceFor(DEFAULT_MODEL_TIER, b?.face_num || 0, faceTargets))
    setTexSize(defaultTextureSize ? String(defaultTextureSize) : '')
    setTier(DEFAULT_MODEL_TIER)
    setLodOn(true)
    setLodDraft(String(statedLow || LOD_STAGE_DEFAULT))
    const initial: Partial<Record<MeshView, string>> = {}
    for (const v of views || []) {
      if (v.options.length) initial[v.view] = v.options[0].value
    }
    setViewPick(initial)
    // The view seeding must re-run when the CANDIDATE IMAGES change, not just
    // on open — a caller that fills `views` after opening would otherwise keep
    // an empty pick. Keyed on the views' CONTENT for the same reason as
    // `backendsKey`: the callers rebuild the array on every job poll, and a
    // fresh (but identical) array must not wipe a pick the admin just made.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, defaultBackend, defaultTextureSize, backendsKey, viewsKey, statedHigh, statedLow])

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
  // A view the caller marked required but has NO candidate image for cannot be
  // filled by this dialog — the run would silently lose it, so Generate stops.
  const missingRequired = (views || []).filter((v) => v.required && !v.options.length)
  const viewBlocked = missingRequired.length > 0

  const pick = (name: string) => {
    setPicked(name)
    // The face field always shows what THIS run would use: the newly picked
    // backend's configured default (reduced when the target tier is low),
    // ready to be overridden.
    const b = backends.find((x) => x.name === name)
    prefillFaces(faceFor(tier, b?.face_num || 0, faceTargets))
  }

  const pickTier = (next: ModelTier) => {
    setTier(next)
    const b = backends.find((x) => x.name === picked)
    prefillFaces(faceFor(next, b?.face_num || 0, faceTargets))
    setTexSize(next === DEFAULT_MODEL_TIER ? '' : String(LOW_TEXTURE_SIZE))
  }

  const start = () => {
    const opts: MeshGenerateOpts = {}
    let f = parseInt(faceDraft, 10)
    const selected = backends.find((x) => x.name === picked)
    const max = selected?.face_num_max || 0
    if (Number.isFinite(f) && max > 0 && f > max) f = max
    // Send the face count only when it was CHANGED from what the field was
    // prefilled with. An untouched field keeps meaning "decide for me" — the
    // server then uses the subject's stated budget (props v2 E5), or the
    // backend default where it states none, which is exactly what the field
    // was showing. Compared against the PREFILL and not against the backend
    // default: with a budget the prefill is the budget, and a run that means
    // to use the backend's own number types it in — that must reach the
    // server rather than fall back to the budget it was typed over.
    if (Number.isFinite(f) && f > 0 && String(f) !== facePrefill) {
      opts.face_num = f
    }
    const tex = parseInt(texSize, 10)
    if (Number.isFinite(tex) && tex > 0) opts.texture_size = tex
    if (showTier) opts.tier = tier
    if (canLod) {
      // OFF IS A STATEMENT (ruling V9): an empty list switches the stage off
      // at the server, which would otherwise fall back to the subject's own
      // low budget and bake one anyway. Sending nothing is reserved for "this
      // dialog has no stage control at all".
      const lod = parseInt(lodDraft, 10)
      opts.lod_faces = lodOn && Number.isFinite(lod) && lod > 0 ? lod : []
    }
    if (views && views.length) {
      const chosen: Partial<Record<MeshView, string>> = {}
      for (const v of views) {
        const val = viewPick[v.view]
        if (val) chosen[v.view] = val
      }
      // Sent AS-IS even when empty: `{}` means "views were offered, nothing
      // picked", which the server treats like an absent key — the callers map
      // it (props: `views: []`, locations: no `view_images`).
      opts.views = chosen
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
              {views && views.length ? (
                <>
                  <label className="ga-hint">{t('Views')}</label>
                  {views.map((v) => {
                    if (!v.options.length) return null
                    const label = t(VIEW_LABELS[v.view])
                    if (v.options.length === 1) {
                      const only = v.options[0]
                      return (
                        <label key={v.view} className="ga-check-row">
                          <input type="checkbox"
                            checked={!!viewPick[v.view]}
                            disabled={!!v.required}
                            onChange={(e) => setViewPick((p) => ({
                              ...p, [v.view]: e.target.checked ? only.value : '' }))} />
                          <span>{label} · {only.label}</span>
                        </label>
                      )
                    }
                    return (
                      <label key={v.view} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                        <span className="ga-hint">{label}{v.required ? '' : ` (${t('optional')})`}</span>
                        <select className="ga-input" value={viewPick[v.view] || ''}
                          onChange={(e) => setViewPick((p) => ({ ...p, [v.view]: e.target.value }))}>
                          {!v.required ? <option value="">{t('— none —')}</option> : null}
                          {v.options.map((o) => (
                            <option key={o.value} value={o.value}>{o.label}</option>
                          ))}
                        </select>
                      </label>
                    )
                  })}
                  {viewBlocked ? (
                    <div className="ga-hint" style={{ color: 'var(--danger, #f85149)' }}>
                      {t('No image for the required view(s): {views}').replace('{views}',
                        missingRequired.map((v) => t(VIEW_LABELS[v.view])).join(', '))}
                    </div>
                  ) : (
                    <div className="ga-hint">
                      {t('A single-slot alias uses the front only; a multi-view alias takes every view picked here.')}
                    </div>
                  )}
                </>
              ) : null}
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
            disabled={none || viewBlocked}
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
