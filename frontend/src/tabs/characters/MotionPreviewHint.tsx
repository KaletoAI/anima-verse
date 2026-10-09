import { useI18n } from '../../i18n/I18nProvider'
import { previewHint } from './motionFieldPreview'

export function MotionPreviewHint({ field }: { field: string }) {
  const { t } = useI18n()
  const { category, hint } = previewHint(field, t)
  const labels = { live: t('Live'), motion: t('Motion'), tilt: t('Tilt'), rebuild: t('Rebuild') }
  return <small className="ga-hint" title={hint} style={{ marginLeft: 6, padding: '1px 4px', border: '1px solid var(--border)', borderRadius: 4 }}>{labels[category]}</small>
}
