/**
 * The entry editor (create/edit/order/steps) — the second half of the tab.
 * Placeholder until it is built; the segment switch already leads here so the
 * seam is visible instead of hidden behind a disabled button.
 */
import { useI18n } from '../../i18n/I18nProvider'

export function EntriesView() {
  const { t } = useI18n()
  return <div className="ga-placeholder">{t('Entries')}</div>
}
