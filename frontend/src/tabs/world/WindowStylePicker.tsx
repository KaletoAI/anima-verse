/** Window styles for room openings and the location default.
 * The shipped library, including thumbnails, is shared once per admin page.
 * An empty opening selection inherits; geometry is resolved by the server.
 */
import { useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'

interface WindowStyle {
  id: string
  name: string
  description: string
  thumbnail_url?: string
}

let styleLibrary: Promise<WindowStyle[]> | undefined
function useWindowStyles(): WindowStyle[] {
  const [styles, setStyles] = useState<WindowStyle[]>([])
  useEffect(() => {
    let stale = false
    styleLibrary ??= apiGet<{ styles: WindowStyle[] }>('/world/window-styles')
      .then((data) => data.styles).catch(() => [])
    void styleLibrary.then((data) => { if (!stale) setStyles(data) })
    return () => { stale = true }
  }, [])
  return styles
}

export function WindowStyleSelect({ value, defaultStyle, onChange }: {
  value: string
  defaultStyle?: string
  onChange: (id: string) => void
}) {
  const { t } = useI18n()
  const styles = useWindowStyles()
  const chosen = styles.find((s) => s.id === value)
  const defaultName = styles.find((s) => s.id === defaultStyle)?.name || defaultStyle
  return <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
    <select className="ga-input" value={value} aria-label={t('Window')}
      title={chosen?.description} onChange={(e) => onChange(e.target.value)}>
      <option value="">{defaultName ? `${t('Building default')} (${defaultName})` : t('Building default')}</option>
      {value && !chosen ? <option value={value}>{value} {t('(missing)')}</option> : null}
      {styles.map((style) => <option key={style.id} value={style.id}>{style.name}</option>)}
    </select>
    {chosen?.thumbnail_url ? <img src={chosen.thumbnail_url} alt={chosen.name}
      loading="lazy" width={48} height={48} style={{ objectFit: 'contain' }} /> : null}
  </span>
}

export function OpeningWindowStyle({ opening, defaultStyle, onPatch }: {
  opening: { window_style?: string }
  defaultStyle?: string
  onPatch: (patch: { window_style?: string }) => void
}) {
  const { t } = useI18n()
  return <label style={{ display: 'inline-flex', gap: 4, alignItems: 'center', fontSize: '0.82em' }}>
    {t('Window')}
    <WindowStyleSelect value={opening.window_style || ''} defaultStyle={defaultStyle}
      onChange={(id) => onPatch({ window_style: id || undefined })} />
  </label>
}

export function LocationWindowDefault({ styleId, onChange }: {
  styleId: string
  onChange: (id: string) => void
}) {
  const { t } = useI18n()
  return <label style={{ display: 'inline-flex', gap: 5, alignItems: 'center', fontSize: '0.82em' }}
    title={t('Window style used by every window of this place that names none.')}>
    {t('Default window')}
    <WindowStyleSelect value={styleId} onChange={onChange} />
  </label>
}
