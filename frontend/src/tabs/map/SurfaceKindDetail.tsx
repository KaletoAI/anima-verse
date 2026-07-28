/**
 * SurfaceKindDetail — every stored version of ONE texture kind: thumbnail,
 * provenance, physical edge length, the ⭐ activation (what the 3D client
 * gets) and the armed two-step delete.
 *
 * The generator (backend + prompts + actions) is slotted in by the container
 * (`generateForm`) and sits WITH the properties, not as an island below the
 * versions: the selected entry shows its own prompts and starts a run there.
 */
import type { ReactNode } from 'react'
import { DetailToolbar } from '../../components/DetailToolbar'
import { Field } from '../../components/Field'
import { SurfaceMaterialPreview } from './SurfaceMaterialPreview'
import { useI18n } from '../../i18n/I18nProvider'
import { SURFACE_PROMPT_CONTEXT, WATER_DEFAULTS, WATER_DIALS, dateShort,
  madeWith } from './surfaceTypes'
import type { TexGroup, TexVersion } from './surfaceTypes'

interface SurfaceKindDetailProps {
  group: TexGroup
  /** A generation for this kind is running. */
  pending: boolean
  /** Cache buster for the thumbnails — bumped after a generation/upload. */
  cacheBump: number
  /** Filename armed for deletion ('' = none). */
  armedDel: string
  onSize: (filename: string, raw: string) => void
  onSelect: (filename: string) => void
  onRemove: (filename: string) => void
  onZoom: (version: TexVersion) => void
  onUpload: () => void
  /** Persist name / description / material class. The ID is not editable. */
  onMeta: (meta: { name?: string; description?: string
                   material?: Record<string, unknown> }) => void
  generateForm: ReactNode
}

export function SurfaceKindDetail({
  group, pending, cacheBump, armedDel, onSize, onSelect, onRemove, onZoom,
  onUpload, onMeta, generateForm,
}: SurfaceKindDetailProps) {
  const { t } = useI18n()
  const mat = (group.material || {}) as Record<string, unknown>
  // The version the 3D client gets — the preview must show THAT one.
  const active = group.versions.find((v) => v.active) || group.versions[0]
  const cls = (group.material?.class as string) || 'matte'
  /** Patch ONE dial — the whole declaration travels, the server clamps it. */
  const setMat = (key: string, value: unknown) => onMeta({
    material: { class: 'water', ...WATER_DEFAULTS, ...mat, [key]: value },
  })

  return (
    <>
      <DetailToolbar
        title={group.name || group.kind}
        extra={
          <button type="button" className="ga-btn ga-btn-sm" onClick={onUpload}
            title={t('Upload a new version for this kind (JPEG/PNG/WebP, seamless, top-down)')}>
            ⬆ {t('Upload version')}
          </button>
        }
      />
      <div className="ga-form">
        <div className="ga-form-section-label">{t('Properties')}</div>
        <div className="ga-form-row">
          <Field label={t('Name')}
            hint={t('Free text, spaces welcome — this is what every picker shows. Rename it whenever you like.')}>
            <input
              key={`name-${group.kind}-${group.name || ''}`}
              className="ga-input"
              defaultValue={group.name || ''}
              placeholder={group.kind}
              onBlur={(e) => {
                if (e.target.value.trim() !== (group.name || ''))
                  onMeta({ name: e.target.value })
              }}
              onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
            />
          </Field>
          <Field label={t('ID')} compact
            hint={t('Fixed — it sits in file names and in world data.')}>
            <input
              className="ga-input"
              style={{ width: 130 }}
              value={group.kind}
              readOnly
              title={t('The id the terrain field, the level/room floor kinds and the blends point at. Changing it would be a data migration, so it stays — and it never reaches a prompt.')}
            />
          </Field>
        </div>
        <Field label={t('Description')} help="surface_prompt"
          promptContext={SURFACE_PROMPT_CONTEXT}
          hint={t('The one text that goes into the prompt of new versions.')}>
          <textarea
            key={`desc-${group.kind}-${group.description || ''}`}
            className="ga-textarea"
            rows={2}
            defaultValue={group.description || ''}
            placeholder={t('What the texture shows, e.g. "seamless rubber flooring with a fine round-stud pattern"')}
            onBlur={(e) => {
              if (e.target.value.trim() !== (group.description || ''))
                onMeta({ description: e.target.value })
            }}
          />
        </Field>
        {/* How the kind is LIT. A water surface is not recognised by its
            colour but by what it reflects and how it moves — the class says
            so once, and BOTH renderers build the same material from it. */}
        <Field label={t('Material')}
          hint={cls === 'water'
            ? t('Moving ripples, low roughness and a sky reflection — the texture stays the base colour.')
            : t('Matte, like every other ground surface.')}>
          <select
            className="ga-input"
            style={{ maxWidth: 200 }}
            value={cls}
            onChange={(e) => onMeta({
              material: e.target.value === 'water'
                ? { class: 'water', ...WATER_DEFAULTS, ...(group.material || {}) }
                : { class: 'matte' },
            })}
          >
            <option value="matte">{t('Matte (default)')}</option>
            <option value="water">{t('Water')}</option>
          </select>
        </Field>
        {cls === 'water' ? (
          <div style={{ display: 'flex', gap: 14, alignItems: 'flex-start',
            flexWrap: 'wrap' }}>
            {/* The dials on the left, what they DO on the right — `wave_m` is
                a metre value and unusable without something to measure it
                against (the 1.70 m figure on a stated 10 m patch). */}
            <div style={{ flex: '1 1 260px', minWidth: 0 }}>
          <div className="ga-form-row" style={{ flexWrap: 'wrap' }}>
            <Field label={t('Tint')} compact
              hint={t('Base colour the texture is mixed against.')}>
              <input
                className="ga-input"
                type="color"
                style={{ width: 56, padding: 2 }}
                value={(mat.tint as string) || WATER_DEFAULTS.tint}
                onChange={(e) => setMat('tint', e.target.value)}
              />
            </Field>
            {WATER_DIALS.map(([key, label, min, max, step]) => (
              <Field key={key} label={t(label)} compact
                hint={key === 'wave_m'
                  ? t('Distance between wave crests — 1.6 m is a lake, 6 m an open sea.')
                  : undefined}>
                <input
                  className="ga-input"
                  type="number"
                  min={min}
                  max={max}
                  step={step}
                  style={{ width: 84 }}
                  value={(mat[key] as number | undefined) ?? WATER_DEFAULTS[key]}
                  onChange={(e) => {
                    const n = parseFloat(e.target.value)
                    if (Number.isFinite(n)) setMat(key, n)
                  }}
                />
              </Field>
            ))}
          </div>
            </div>
            <SurfaceMaterialPreview
              material={group.material}
              textureUrl={active?.url}
              sizeM={active?.size_m}
            />
          </div>
        ) : null}
        {/* HOW it is made sits with WHAT it is — one entry, one place. */}
        {generateForm}
        <div className="ga-form-section-label">{t('Versions')}</div>
        {pending ? (
          <span className="ga-hint">{t('Generating…')}</span>
        ) : null}
        <span className="ga-hint">
          {t('The ⭐ active version is what the 3D client gets; click a thumbnail to enlarge.')}
        </span>
        <div className="ga-tex-versions">
          {group.versions.map((v) => (
            <div key={v.filename} className={`ga-tex-card${v.active ? ' is-active' : ''}`}>
              <img
                src={`${v.url}?v=${cacheBump}`}
                alt={`${group.kind} ${v.filename}`}
                title={t('Click to enlarge')}
                onClick={() => onZoom(v)}
              />
              <span className="ga-hint ga-tex-card-meta" title={v.prompt || undefined}>
                {madeWith(v, t)}
                {dateShort(v.created_at) ? ` · ${dateShort(v.created_at)}` : ''}
              </span>
              <div className="ga-tex-card-row">
                <input
                  className="ga-input"
                  type="number"
                  min={0.1}
                  step={0.5}
                  style={{ width: 52 }}
                  defaultValue={v.size_m}
                  title={t('Physical edge length in metres — the client tiles in world scale (10 m cell = 10/size repetitions).')}
                  onBlur={(e) => onSize(v.filename, e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
                />
                {v.active ? (
                  <span title={t('Active — this version is what the 3D client gets.')}>⭐</span>
                ) : (
                  <button
                    type="button"
                    className="ga-btn ga-btn-sm"
                    onClick={() => onSelect(v.filename)}
                    title={t('Make this version the active one (what the 3D client gets)')}
                  >
                    {t('Select')}
                  </button>
                )}
                <button
                  type="button"
                  className="ga-btn ga-btn-sm ga-btn-danger"
                  style={{ marginLeft: 'auto' }}
                  onClick={() => onRemove(v.filename)}
                >
                  {armedDel === v.filename ? t('Really delete?') : '🗑'}
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  )
}
