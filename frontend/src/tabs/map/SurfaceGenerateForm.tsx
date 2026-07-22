/**
 * SurfaceGenerateForm — the generator for one surface texture: kind, image
 * backend, the COMPLETE final prompt (final-prompt rule: what is shown is
 * what is sent) and the upload alternative. Used twice: standalone for a new
 * kind, and inside a kind's detail with the kind locked ("generate a new
 * version"). All state lives in the container — this is the form only.
 */
import { useI18n } from '../../i18n/I18nProvider'
import { KIND_DATALIST_ID } from './surfaceTypes'
import type { BackendInfo } from './surfaceTypes'

interface SurfaceGenerateFormProps {
  kind: string
  onKind: (kind: string) => void
  /** Detail context: the kind is fixed, only a new version is generated. */
  lockKind?: boolean
  backends: BackendInfo[]
  backendName: string
  onBackend: (name: string) => void
  prompt: string
  onPrompt: (value: string) => void
  negative: string
  onNegative: (value: string) => void
  onGenerate: () => void
  onUpload: () => void
}

export function SurfaceGenerateForm({
  kind, onKind, lockKind = false, backends, backendName, onBackend, prompt,
  onPrompt, negative, onNegative, onGenerate, onUpload,
}: SurfaceGenerateFormProps) {
  const { t } = useI18n()
  const ready = !!kind.trim()

  return (
    <div className="ga-form">
      <div className="ga-form-section-label">
        {lockKind ? t('Generate new version') : t('Generate texture')}
      </div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <input
          className="ga-input"
          list={KIND_DATALIST_ID}
          style={{ width: 130 }}
          placeholder={t('kind (road, …)')}
          value={kind}
          disabled={lockKind}
          onChange={(e) => onKind(e.target.value)}
          title={t('Open vocabulary — must match the terrain field of the tiles it should cover.')}
        />
        <select
          className="ga-input"
          style={{ flex: 1, minWidth: 160 }}
          value={backendName}
          onChange={(e) => onBackend(e.target.value)}
        >
          {backends.map((b) => <option key={b.name} value={b.name}>{b.name}</option>)}
        </select>
        <button
          type="button"
          className="ga-btn ga-btn-primary"
          disabled={!ready || !backends.length}
          onClick={onGenerate}
        >
          {t('Generate')}
        </button>
        <button
          type="button"
          className="ga-btn"
          disabled={!ready}
          onClick={onUpload}
          title={t('Upload an image for this kind instead of generating')}
        >
          ⬆ {t('Upload')}
        </button>
      </div>
      <label className="ga-field">
        <span className="ga-field-caption">{t('Final prompt')}</span>
        <textarea
          className="ga-textarea"
          rows={3}
          value={prompt}
          onChange={(e) => onPrompt(e.target.value)}
        />
      </label>
      <label className="ga-field">
        <span className="ga-field-caption">{t('Negative prompt')}</span>
        <textarea
          className="ga-textarea"
          rows={2}
          value={negative}
          onChange={(e) => onNegative(e.target.value)}
        />
      </label>
    </div>
  )
}
