/**
 * ModelGallery — the shared list UI of a 3D model store.
 *
 * Buildings, rooms (`BuildingModelPanel`) and props (`PropModelPanel`) keep
 * their meshes in the SAME gallery (app/core/model_store.py): several stored
 * files, one active per resolution tier, a "render nothing" entry. The rows,
 * the tier badges and the per-tier select buttons are therefore one component
 * instead of three copies. Everything AROUND the list (viewer, placement
 * dials, upload target) stays with the panel that owns it — this is plain
 * admin UI, not geometry (nothing here belongs in @anima/scene-render).
 */
import { useCallback, useState } from 'react'
import { useI18n } from '../i18n/I18nProvider'
import { apiPost } from '../lib/api'
import { useToast } from '../lib/Toast'

/** The named resolution tiers, in fallback order (app/core/model_store.TIERS).
 *  `full` is the modelled quality and the default for everything that exists,
 *  `low` the overview/distance mesh. */
export const MODEL_TIERS = ['full', 'low'] as const
export type ModelTier = (typeof MODEL_TIERS)[number]
export const DEFAULT_MODEL_TIER: ModelTier = 'full'

/** WHERE a stored file came from, grouped as the props gallery publishes it
 *  (`app/core/props.list_models`, v2 E4). The building/room galleries send
 *  none — the row then labels itself from `source` alone. */
export interface GalleryLabelParts {
  /** `upload` | `generated` | `areas` | `variant-copy` | `lod` | `shrink` | … */
  source?: string
  /** Splits only: `auto` | `manual` | `rename` | `delete`. */
  areas_mode?: string
  /** The ONE area a rename or a delete was about ('' for a detection). */
  areas_area?: string
  /** The areas this file names, in mesh order. */
  area_ids?: string[]
  /** A split names the ORIGIN it was cut from, not its predecessor. */
  source_file?: string
  /** A variant copy names the file and the VARIANT it was taken from. */
  copied_from?: { file?: string; variant?: number }
  /** A distance mesh names the full file it inherits its areas from. */
  inherits_from?: string
}

/** One stored model file as every gallery route reports it. */
export interface GalleryModel {
  filename: string
  format?: string
  created_at?: string
  backend?: string
  source?: string
  /** Building/room only: the gallery image the mesh was generated from. */
  source_image?: string
  /** Low variants: the stored model file this one was reduced FROM. */
  source_file?: string
  /** The tier the file was MADE for (sidecar; default `full`). */
  tier?: string
  /** The tiers the file currently SERVES (the selection). */
  selected_for?: string[]
  face_num?: number
  /** Why the file has fewer faces than its variant asked for ('' = it got
   *  what was asked). Written when the target was over the backend's own
   *  ceiling and the job ran clamped (props v2 E5). */
  face_target_note?: string
  texture_size?: number
  /** Whether a mesh→mesh reduction of THIS file can work at all (server-side
   *  capability probe): a mesh without UVs/texture has nothing to re-bake. */
  shrinkable?: boolean
  /** Why not — a short server sentence, empty when it is shrinkable. */
  shrink_reason?: string
  /** What the CPU reduction left of this file (0 = not a reduced mesh). */
  tris?: number
  /** The target fraction it was reduced to (0 = not a reduced mesh). */
  lod_ratio?: number
  /** The file a client without a tier request gets. */
  active?: boolean
  /** What the second line says about the file's origin (props gallery). */
  label_parts?: GalleryLabelParts
}

/** The state of the Blender refinement runner, as every model status reports
 *  it (`app/blender/runner.status()`). Only `usable` decides here: without a
 *  working Blender the CPU reduction cannot run at all. */
export interface BlenderStatus {
  enabled?: boolean
  executable?: string
  version?: string
  usable?: boolean
}

/**
 * "Build distance mesh" — reduces the subject's FULL mesh on the CPU (Blender
 * Decimate) and stores the result as the gallery's `low` model.
 *
 * The same button for props, buildings and room dioramas: only the endpoint
 * differs, and it is exactly the character twin's action (FieldModel3D). The
 * call BLOCKS — a CPU reduction takes seconds, so the triangle counts come
 * back in the answer instead of being polled for. Hidden without a usable
 * Blender: an action that can only fail is worse than no action.
 */
export function BuildDistanceMeshButton({
  url, hasLow, blender, disabled = false, targetFaces = 0, onDone,
}: {
  /** POST endpoint of this subject's build (…/lod). */
  url: string
  /** A low model already exists — the button rebuilds instead of building. */
  hasLow: boolean
  /** From the panel's status payload; missing/unusable hides the button. */
  blender?: BlenderStatus
  /** Another job of this subject is running. */
  disabled?: boolean
  /** The triangle count this subject STATES for its distance mesh (props v2
   *  E5; 0 = none, and the configured fraction decides). Named on the button,
   *  because "Build distance mesh" otherwise says nothing about how small. */
  targetFaces?: number
  /** Reload the gallery — the build added a file and moved the selection. */
  onDone: () => void | Promise<unknown>
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [busy, setBusy] = useState(false)
  const build = useCallback(async () => {
    setBusy(true)
    try {
      const d = await apiPost<{ tris?: number; tris_before?: number }>(url, {})
      // The counts come from the Blender stage and may be absent (an older
      // stage reported none) — then the message says the build happened and
      // stays quiet about numbers instead of printing "undefined".
      const counts = d.tris_before && d.tris
        ? `: ${d.tris_before.toLocaleString()} → ${d.tris.toLocaleString()} ${t('tris')}`
        : ''
      toast(`${t('Distance mesh built')}${counts}`)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
      return
    } finally {
      setBusy(false)
    }
    // Outside the try: the build SUCCEEDED, and a failing gallery reload must
    // not be reported as a failed build (the list is one reload away).
    try {
      await onDone()
    } catch { /* the mesh is stored either way */ }
  }, [url, onDone, t, toast])
  if (!blender?.usable) return null
  return (
    <button
      type="button"
      className="ga-btn ga-btn-sm"
      disabled={busy || disabled}
      onClick={() => { void build() }}
      title={t('Builds a reduced copy of this mesh for viewing at a distance. The full model is untouched — the client picks whichever fits the camera distance.')}
    >
      {hasLow ? t('Rebuild distance mesh') : t('Build distance mesh')}
      {targetFaces ? ` → ${targetFaces.toLocaleString()} ${t('faces')}` : ''}
    </button>
  )
}

/** Which tiers a subject has + the "low missing" hint. A missing tier is not
 *  an error — the clients fall back to the best available one — but nothing
 *  else would ever tell the admin that the low mesh was never built.
 *
 *  `showLabel={false}` drops the leading caption for a caller whose SECTION is
 *  already named after these tiers (the prop detail since 2026-08-29) — the
 *  word twice above one another says nothing twice. */
export function TierSummary({ tiers, showLabel = true }:
  { tiers?: string[]; showLabel?: boolean }) {
  const { t } = useI18n()
  const have = new Set(tiers || [])
  return (
    <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
      {showLabel ? <span className="ga-hint">{t('Resolution tiers')}</span> : null}
      {MODEL_TIERS.map((tier) => (
        <span
          key={tier}
          className={`ga-tag ${have.has(tier) ? 'ga-tag-tier' : 'ga-tag-missing'}`}
          title={have.has(tier)
            ? t('A model is selected for this tier.')
            : t('No model is selected for this tier — the clients fall back to the next available one.')}
        >
          {have.has(tier) ? `✓ ${tier}` : `${tier} — ${t('missing')}`}
        </span>
      ))}
      {!have.has('low') && have.size > 0 ? (
        <span className="ga-hint">
          {t('No low variant: the distance view renders the full mesh. Generate one with target tier “low” or upload it.')}
        </span>
      ) : null}
    </div>
  )
}

/** WHAT this file is, in one phrase — the answer to the measured symptom of
 *  a gallery full of identically named GLBs (befunde 2026-08-28 § 8: eight
 *  files of one variant in ten minutes, each row showing only a minute and a
 *  backend). Empty when the file records no origin worth a word (a plain
 *  generation says its backend two parts later). */
function originLabel(m: GalleryModel, t: (s: string) => string): string {
  const lp = m.label_parts || {}
  const source = lp.source || m.source || ''
  const ids = (lp.area_ids || []).join(', ')
  if (source === 'areas') {
    // The four things a run can do to a mesh — the mode says which, and the
    // areas say what came out of it.
    switch (lp.areas_mode) {
      case 'auto':
        return [t('Split'), t('auto'), ids].filter(Boolean).join(' · ')
      case 'manual':
        return [t('Drawn'), ids].filter(Boolean).join(' · ')
      case 'rename':
        return `${t('Renamed →')} ${lp.areas_area || ids}`.trim()
      case 'delete':
        // The dissolved id is the only thing that tells two removals apart.
        return lp.areas_area ? `${t('Removed →')} ${lp.areas_area}` : t('Area removed')
      case 'adopt':
        // The modeller NAMED these surfaces (E6); nothing was detected.
        return [t('Adopted'), ids].filter(Boolean).join(' · ')
      default:
        return [t('Split'), ids].filter(Boolean).join(' · ')
    }
  }
  if (source === 'variant-copy') {
    const from = lp.copied_from || {}
    // A picture variant carries a COPY of the frame — saying which variant it
    // was taken from is what makes a stale copy findable.
    if (typeof from.variant === 'number' && from.variant >= 0) {
      return `${t('Copy of variant')} ${from.variant + 1}`
    }
    return from.file ? `${t('Copy of')} ${from.file}` : t('Variant copy')
  }
  // NOT `Upload`: that source string is the button label, and its German is
  // the imperative „Hochladen“ — a row states what the file IS.
  if (source === 'upload') return t('Uploaded')
  // A reduction is not a generation: naming the mesh→mesh step is what
  // separates a real low mesh from a second full run at a low budget.
  if (source === 'shrink') return t('reduced')
  // A stage came out of the SAME job as its full mesh (baked from the same
  // views), which is why it names a source_file without being a reduction.
  if (source === 'lod') return t('Distance mesh')
  return ''
}

/** Per-run facts of one stored file, as one line (origin, backend, faces,
 *  texture, source) — empty when the file carries no record. */
function runHint(m: GalleryModel, t: (s: string) => string): string {
  const parts: string[] = []
  const origin = originLabel(m, t)
  if (origin) parts.push(origin)
  if (m.backend) parts.push(m.backend)
  if (m.face_num) parts.push(`${m.face_num.toLocaleString()} ${t('faces')}`)
  // A budget the backend cut: the row would otherwise show a face count the
  // file does not have, and nobody would find the ceiling again.
  if (m.face_target_note) parts.push(m.face_target_note)
  if (m.texture_size) parts.push(`${m.texture_size}²`)
  if (m.source_image) parts.push(`${t('from')} ${m.source_image}`)
  // A variant copy already NAMED its source above; every other file that
  // records one gets it here (a split names its origin, a low mesh its full).
  if (m.source_file && (m.label_parts?.source || m.source) !== 'variant-copy') {
    parts.push(`${t('from')} ${m.source_file}`)
  }
  // What the CPU reduction actually achieved — the only place these numbers
  // are visible, and the answer to "is this low mesh worth serving".
  if (m.tris) parts.push(`${m.tris.toLocaleString()} ${t('tris')}`)
  if (m.lod_ratio) parts.push(`${Math.round(m.lod_ratio * 100)} %`)
  return parts.join(' · ')
}

/** The "render nothing" row (the `__none__` sentinel of the default tier) —
 *  distinct from "no files stored". */
export function NoModelRow({ noneSelected, onSelect }: {
  noneSelected: boolean
  onSelect: () => void
}) {
  const { t } = useI18n()
  return (
    <div
      style={{
        display: 'flex', gap: 8, alignItems: 'center',
        padding: '3px 6px', borderRadius: 6,
        border: '1px solid var(--border, #30363d)',
      }}
    >
      <span title={noneSelected ? t('No model is rendered.') : undefined}
        style={{ width: '1.2em', textAlign: 'center' }}>
        {noneSelected ? '⭐' : ''}
      </span>
      <span style={{ fontSize: '0.82em' }}>{t('No model')}</span>
      <span className="ga-hint">{t('render nothing')}</span>
      <span style={{ marginLeft: 'auto', display: 'inline-flex', gap: 6 }}>
        {!noneSelected ? (
          <button
            type="button"
            className="ga-btn ga-btn-sm"
            onClick={onSelect}
            title={t('Render no 3D model — until another one is selected or generated.')}
          >
            {t('Select')}
          </button>
        ) : null}
      </span>
    </div>
  )
}

/**
 * One gallery row: click previews the file, the tier buttons make it the
 * active model of that tier, ⤵ reduces it to a low variant, × deletes it
 * (armed two-step, no window.confirm).
 */
export function ModelGalleryRow({
  model, shown, armedDelete, onPreview, onSelect, onArmDelete, onDelete,
  onShrink, shrinkAvailable = false, shrinkPending = false,
}: {
  model: GalleryModel
  /** The file the viewer currently shows. */
  shown: boolean
  armedDelete: boolean
  onPreview: () => void
  onSelect: (tier: ModelTier) => void
  /** null disarms. */
  onArmDelete: (filename: string | null) => void
  onDelete: () => void
  /** Reduce THIS file to a low variant (mesh→mesh). Omitted = no such action
   *  in this gallery. */
  onShrink?: () => void
  /** A mesh2mesh backend is configured — without one the action stays visible
   *  but disabled, so the missing configuration is what the admin sees. */
  shrinkAvailable?: boolean
  /** A job of this gallery is running — no second one on top. */
  shrinkPending?: boolean
}) {
  const { t } = useI18n()
  const selectedFor = model.selected_for || []
  const madeFor = model.tier || DEFAULT_MODEL_TIER
  const hint = runHint(model, t)
  // Two independent reasons can block the reduction — a missing backend (the
  // world's configuration) and a source mesh that cannot be re-baked (this
  // file). Both must stay readable, so the tooltip lists what applies.
  const canShrink = model.shrinkable !== false
  const shrinkBlocked: string[] = []
  if (!shrinkAvailable) {
    shrinkBlocked.push(t('No mesh→mesh backend configured — add one with api_type openai_mesh and category mesh2mesh (alias “mesh-shrink”) in Media Generation.'))
  }
  if (!canShrink) {
    shrinkBlocked.push(
      `${t('This mesh cannot be reduced')}: ${model.shrink_reason || t('the mesh brings no UVs/texture to re-bake.')}`)
  }
  return (
    <div
      onClick={onPreview}
      style={{
        display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap',
        padding: '3px 6px', borderRadius: 6, cursor: 'pointer',
        border: `1px solid ${shown ? 'var(--accent, #58a6ff)' : 'var(--border, #30363d)'}`,
        background: shown ? 'rgba(88,166,255,0.08)' : 'transparent',
      }}
    >
      <span
        title={selectedFor.length
          ? t('Active for: ') + selectedFor.join(', ')
          : undefined}
        style={{ width: '1.2em', textAlign: 'center' }}
      >
        {selectedFor.length ? '⭐' : ''}
      </span>
      <span style={{ fontSize: '0.82em' }}>
        {(model.created_at || '').replace('T', ' ').slice(0, 16) || model.filename}
      </span>
      <span className="ga-tag ga-tag-tier"
        title={t('The tier this file was generated or uploaded for.')}>
        {madeFor}
      </span>
      {hint ? <span className="ga-hint">{hint}</span> : null}
      <span style={{ marginLeft: 'auto', display: 'inline-flex', gap: 6 }}>
        {MODEL_TIERS.map((tier) => {
          const on = selectedFor.includes(tier)
          return (
            <button
              key={tier}
              type="button"
              className={`ga-btn ga-btn-sm${on ? ' ga-btn-primary' : ''}`}
              disabled={on}
              onClick={(e) => { e.stopPropagation(); onSelect(tier) }}
              title={on
                ? t('This file is the model the clients get for this tier.')
                : t('Make this the model the clients get for this tier.')}
            >
              {on ? '⭐ ' : ''}{tier}
            </button>
          )
        })}
        {onShrink ? (
          <button
            type="button"
            className="ga-btn ga-btn-sm"
            disabled={!shrinkAvailable || !canShrink || shrinkPending}
            onClick={(e) => { e.stopPropagation(); onShrink() }}
            title={shrinkBlocked.length
              ? shrinkBlocked.join(' — ')
              : t('Create a low variant from this file: the mesh itself is reduced (mesh→mesh) and the result becomes the “low” model of this gallery.')}
          >
            ⤵ {t('low variant')}
          </button>
        ) : null}
        {armedDelete ? (
          <>
            <button
              type="button"
              className="ga-btn ga-btn-sm ga-btn-danger"
              onClick={(e) => { e.stopPropagation(); onDelete() }}
            >
              {t('Sure?')}
            </button>
            <button
              type="button"
              className="ga-btn ga-btn-sm"
              onClick={(e) => { e.stopPropagation(); onArmDelete(null) }}
            >
              {t('Cancel')}
            </button>
          </>
        ) : (
          <button
            type="button"
            className="ga-btn ga-btn-sm ga-btn-danger"
            onClick={(e) => { e.stopPropagation(); onArmDelete(model.filename) }}
            title={t('Delete this model')}
          >
            ×
          </button>
        )}
      </span>
    </div>
  )
}

/** Target tier of an UPLOAD — the file is stored as a new gallery entry of
 *  that tier and becomes its active model. */
export function TierPicker({ value, onChange, label }: {
  value: ModelTier
  onChange: (tier: ModelTier) => void
  label?: string
}) {
  const { t } = useI18n()
  return (
    <label style={{ display: 'inline-flex', gap: 4, alignItems: 'center', fontSize: '0.82em' }}
      title={t('Which resolution slot the file fills. The clients take “low” at a distance and fall back to “full” when there is none.')}>
      {label ?? t('as')}
      <select
        className="ga-input"
        style={{ width: 82 }}
        value={value}
        onChange={(e) => onChange(e.target.value as ModelTier)}
      >
        {MODEL_TIERS.map((tier) => <option key={tier} value={tier}>{tier}</option>)}
      </select>
    </label>
  )
}
