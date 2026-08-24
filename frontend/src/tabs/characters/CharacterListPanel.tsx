import { useMemo } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { ImportButton } from '../../components/ImportExport'
import type { CharacterRef } from '../../lib/refs'

/**
 * Left-hand character list: header + New/Import actions + the selectable
 * character rows. `characters` is expected pre-sorted by the parent.
 *
 * Temporary NPCs ride in the same list payload and are split off into their
 * own group here — the split is by the `temporary` flag the backend derives
 * from the character's TEMPLATE, never by a name pattern. A second kind of
 * NPC is another template with the same flag and lands in this group too.
 */
export function CharacterListPanel({
  characters,
  selected,
  onSelect,
  onNew,
  onNewNpc,
  onImported,
}: {
  characters: CharacterRef[]
  selected: string
  onSelect: (name: string) => void
  onNew: () => void
  onNewNpc: () => void
  onImported: () => void
}) {
  const { t } = useI18n()
  const regular = useMemo(() => characters.filter((c) => !c.temporary), [characters])
  const npcs = useMemo(() => characters.filter((c) => c.temporary), [characters])

  const row = (c: CharacterRef, marker?: string) => {
    const isActive = c.name === selected
    return (
      <li key={c.name}>
        <button
          type="button"
          className={`ga-list-row${isActive ? ' is-active' : ''}`}
          onClick={() => onSelect(c.name)}
        >
          <span className="ga-list-row-main">
            <strong>{marker ? `${marker} ` : ''}{c.display_name || c.name}</strong>
          </span>
        </button>
      </li>
    )
  }

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
        {regular.length === 0 ? (
          <li className="ga-list-empty">{t('No characters')}</li>
        ) : (
          regular.map((c) => row(c))
        )}
      </ul>
      <div className="ga-twocol-header" style={{ marginTop: 12 }}>
        <h3>{t('Temporary NPCs')}</h3>
        <div className="ga-twocol-header-actions">
          <button type="button" className="ga-btn" onClick={onNewNpc}>
            {t('New NPC')}
          </button>
        </div>
      </div>
      <ul className="ga-list">
        {npcs.length === 0 ? (
          <li className="ga-list-empty">{t('No temporary NPCs')}</li>
        ) : (
          npcs.map((c) => row(c, '✦'))
        )}
      </ul>
    </aside>
  )
}
