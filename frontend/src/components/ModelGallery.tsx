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
import { useI18n } from '../i18n/I18nProvider'

/** The named resolution tiers, in fallback order (app/core/model_store.TIERS).
 *  `full` is the modelled quality and the default for everything that exists,
 *  `low` the overview/distance mesh. */
export const MODEL_TIERS = ['full', 'low'] as const
export type ModelTier = (typeof MODEL_TIERS)[number]
export const DEFAULT_MODEL_TIER: ModelTier = 'full'

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
  texture_size?: number
  /** Whether a mesh→mesh reduction of THIS file can work at all (server-side
   *  capability probe): a mesh without UVs/texture has nothing to re-bake. */
  shrinkable?: boolean
  /** Why not — a short server sentence, empty when it is shrinkable. */
  shrink_reason?: string
  /** The file a client without a tier request gets. */
  active?: boolean
}

/** Which tiers a subject has + the "low missing" hint. A missing tier is not
 *  an error — the clients fall back to the best available one — but nothing
 *  else would ever tell the admin that the low mesh was never built. */
export function TierSummary({ tiers }: { tiers?: string[] }) {
  const { t } = useI18n()
  const have = new Set(tiers || [])
  return (
    <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
      <span className="ga-hint">{t('Resolution tiers')}</span>
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

/** Per-run facts of one stored file, as one line ("upload", backend, faces,
 *  texture, origin) — empty when the file carries no record. */
function runHint(m: GalleryModel, t: (s: string) => string): string {
  const parts: string[] = []
  if (m.source === 'upload') parts.push(t('upload'))
  // A reduction is not a generation: naming the mesh→mesh step is what
  // separates a real low mesh from a second full run at a low budget.
  else if (m.source === 'shrink') parts.push(t('reduced'))
  if (m.backend) parts.push(m.backend)
  if (m.face_num) parts.push(`${m.face_num.toLocaleString()} ${t('faces')}`)
  if (m.texture_size) parts.push(`${m.texture_size}²`)
  if (m.source_image) parts.push(`${t('from')} ${m.source_image}`)
  if (m.source_file) parts.push(`${t('from')} ${m.source_file}`)
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
