import { useI18n } from '../../i18n/I18nProvider'
import { ImportButton } from '../../components/ImportExport'
import type { CharacterRef } from '../../lib/refs'

/**
 * Left-hand character list: header + New/Import actions + the selectable
 * character rows. `characters` is expected pre-sorted by the parent.
 */
export function CharacterListPanel({
  characters,
  selected,
  onSelect,
  onNew,
  onImported,
}: {
  characters: CharacterRef[]
  selected: string
  onSelect: (name: string) => void
  onNew: () => void
  onImported: () => void
}) {
  const { t } = useI18n()
  return (
    <aside className="ga-twocol-left">
      <div className="ga-twocol-header">
        <h3>{t('Characters')}</h3>
        <div className="ga-twocol-header-actions">
          <button type="button" className="ga-btn ga-btn-primary" onClick={onNew}>
            {t('New character')}
          </button>
          <ImportButton
            endpoint="/characters/import"
            overwriteSupported
            onImported={onImported}
          />
        </div>
      </div>
      <ul className="ga-list">
        {characters.length === 0 ? (
          <li className="ga-list-empty">{t('No characters')}</li>
        ) : (
          characters.map((c) => {
            const isActive = c.name === selected
            return (
              <li key={c.name}>
                <button
                  type="button"
                  className={`ga-list-row${isActive ? ' is-active' : ''}`}
                  onClick={() => onSelect(c.name)}
                >
                  <span className="ga-list-row-main">
                    <strong>{c.display_name || c.name}</strong>
                  </span>
                </button>
              </li>
            )
          })
        )}
      </ul>
    </aside>
  )
}
