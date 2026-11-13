/**
 * BuiltAtCaption — the ONE corner caption of the character area's 3D previews
 * that says when the shown model was built (Ruling UI3 a): "Built 20:31", or
 * "Built 12 Nov 20:31" when that is not today. The stamp is the SYSTEM stamp
 * the payload carries beside the preview URL (the model's `created_at`,
 * `served_built_at`, `preview_built_at`, …), shown in the configured clock
 * zone and format, the date in the viewer's locale.
 *
 * Placed bottom right of a 3D preview (Model3DViewer's `builtAt`); bottom left
 * holds the mesh numbers, top left the freshness badge, top right the controls.
 */
import { useClockSettings } from '../../lib/clockFormat'
import { useI18n } from '../../i18n/I18nProvider'
import { stampLabel } from './freshnessText'

export function BuiltAtCaption({ at, inset = 6 }: { at?: string | null; inset?: number }) {
  const { t } = useI18n()
  useClockSettings()   // re-render when the clock settings change
  const label = stampLabel(at)
  if (!label) return null
  return (
    <span
      title={`${t('Model built')}: ${label}`}
      style={{
        position: 'absolute', right: inset, bottom: inset,
        fontSize: '0.72em', opacity: 0.8, pointerEvents: 'auto',
        background: 'rgba(13,17,23,0.55)', color: '#e6edf3',
        padding: '1px 6px', borderRadius: 4, zIndex: 1,
      }}
    >
      {t('Built')} {label}
    </span>
  )
}
