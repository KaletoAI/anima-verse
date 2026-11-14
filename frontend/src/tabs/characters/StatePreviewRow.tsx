/**
 * StatePreviewRow — the state preview beside the Base body tab's viewer (Ruling A66; it sat under the 3D tab's viewer
 * until then): "Preview state" with None (at rest) and each state whose bone pose moves one of the base model's
 * extension groups (`statePicker`), and the line beside it — "Preview only — nothing is saved, nothing runs.", why
 * there is nothing to pick, "Loading…" while the picked state's motion is fetched, or the error. Only renders: the
 * owner (FieldBaseBody) holds the pick, fetches the motion with a GET and hands it to the viewer.
 */
import { useI18n } from '../../i18n/I18nProvider'
import type { statePicker } from './baseBodyModel'

export function StatePreviewRow({ picker, value, loading, error, onChange }: {
  picker: ReturnType<typeof statePicker>
  value: string
  loading: boolean
  error: string
  onChange: (state: string) => void
}) {
  const { t } = useI18n()
  return (
    <div className="ga-face-actions-row ga-base-state-preview" style={{ alignItems: 'center', gap: 6 }}>
      <span className="ga-hint" style={{ whiteSpace: 'nowrap' }}>{t('Preview state')}</span>
      {picker.options.length ? (
        <select className="ga-input" style={{ width: 'auto', maxWidth: 260 }} value={value}
          title={t('Shows the extension bones as this state moves them. Rest angle and size show at once; gravity and spring when you drag the figure or play a clip.')}
          onChange={(event) => onChange(event.target.value)}>
          {picker.options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
      ) : null}
      <span className="ga-hint" role="status" style={error ? { color: 'var(--danger, #f85149)', overflowWrap: 'anywhere' } : undefined}>
        {error ? `${t('Error')}: ${error}` : loading ? t('Loading…') : picker.note}
      </span>
    </div>
  )
}
