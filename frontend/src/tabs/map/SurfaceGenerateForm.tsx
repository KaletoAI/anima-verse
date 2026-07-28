/**
 * SurfaceGenerateForm — HOW a surface texture is rendered: image backend, the
 * COMPLETE final prompt (final-prompt rule: what is shown is what is sent),
 * the negative, and the two actions.
 *
 * It no longer carries identity. Name / ID / Description belong to the ENTRY
 * and are rendered by whoever owns it — the detail view for an existing kind,
 * the create view for a new one — so both surfaces read the same top-down:
 * what it is called, what it is, then how it is made. There is no separate
 * "generate a new version" island any more: the selected entry shows its own
 * prompts and starts a run from there, like every other generated thing in
 * the game.
 */
import { Field } from '../../components/Field'
import { useI18n } from '../../i18n/I18nProvider'
import { SURFACE_PROMPT_CONTEXT } from './surfaceTypes'
import type { BackendInfo } from './surfaceTypes'

interface SurfaceGenerateFormProps {
  /** Everything needed to start a run is present (a name, or an existing id). */
  ready: boolean
  /** Label of the primary action — creating vs. adding a version. */
  generateLabel: string
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
  ready, generateLabel, backends, backendName, onBackend, prompt,
  onPrompt, negative, onNegative, onGenerate, onUpload,
}: SurfaceGenerateFormProps) {
  const { t } = useI18n()

  return (
    <>
      <div className="ga-form-row">
        <Field label={t('Image backend')}>
          <select
            className="ga-input"
            value={backendName}
            onChange={(e) => onBackend(e.target.value)}
          >
            {backends.map((b) => <option key={b.name} value={b.name}>{b.name}</option>)}
          </select>
        </Field>
        <Field label=" " compact>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              type="button"
              className="ga-btn ga-btn-primary"
              disabled={!ready || !backends.length}
              onClick={onGenerate}
            >
              {generateLabel}
            </button>
            <button
              type="button"
              className="ga-btn"
              disabled={!ready}
              onClick={onUpload}
              title={t('Upload an image instead of generating one (JPEG/PNG/WebP, seamless, top-down)')}
            >
              ⬆ {t('Upload')}
            </button>
          </div>
        </Field>
      </div>
      <Field label={t('Final prompt')} help="surface_prompt"
        promptContext={SURFACE_PROMPT_CONTEXT}
        hint={t('Style of the use case plus the description — complete. Edit it and exactly this is sent; the description stays as it is.')}>
        <textarea
          className="ga-textarea"
          rows={3}
          value={prompt}
          onChange={(e) => onPrompt(e.target.value)}
        />
      </Field>
      <Field label={t('Negative prompt')} help="surface_prompt"
        promptContext={SURFACE_PROMPT_CONTEXT}>
        <textarea
          className="ga-textarea"
          rows={2}
          value={negative}
          onChange={(e) => onNegative(e.target.value)}
        />
      </Field>
    </>
  )
}
