/**
 * SurfaceKindDetail — every stored version of ONE texture kind: thumbnail,
 * provenance, physical edge length, the ⭐ activation (what the 3D client
 * gets) and the armed two-step delete. The generator for a new version is
 * slotted in by the container (`generateForm`).
 */
import type { ReactNode } from 'react'
import { DetailToolbar } from '../../components/DetailToolbar'
import { useI18n } from '../../i18n/I18nProvider'
import { dateShort, madeWith } from './surfaceTypes'
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
  generateForm: ReactNode
}

export function SurfaceKindDetail({
  group, pending, cacheBump, armedDel, onSize, onSelect, onRemove, onZoom,
  onUpload, generateForm,
}: SurfaceKindDetailProps) {
  const { t } = useI18n()

  return (
    <>
      <DetailToolbar
        title={group.kind}
        extra={
          <button type="button" className="ga-btn ga-btn-sm" onClick={onUpload}
            title={t('Upload a new version for this kind (JPEG/PNG/WebP, seamless, top-down)')}>
            ⬆ {t('Upload version')}
          </button>
        }
      />
      <div className="ga-form">
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
      {generateForm}
    </>
  )
}
