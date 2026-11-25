import { useCallback, useRef, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { TemplatesView } from './TemplatesView'
import type { PaneGuard } from './TemplatesView'

type SubTab = 'runs' | 'templates'

const STORAGE_KEY = 'ga-quests-subtab'
const DEFAULT_SUBTAB: SubTab = 'runs'
/** The sub-tabs that exist, in their order. A stored or default id that is not listed falls back to the first. */
const SUBTABS: { id: SubTab; label: string }[] = [
  { id: 'templates', label: 'Templates' },
]

function initialSubtab(): SubTab {
  let stored: string | null = null
  try { stored = localStorage.getItem(STORAGE_KEY) } catch { /* Storage can be disabled. */ }
  const wanted = stored || DEFAULT_SUBTAB
  return SUBTABS.find((s) => s.id === wanted)?.id || SUBTABS[0].id
}

/**
 * The Quests tab: sub-tabs over the quest panes, exactly one pane mounted at a time (each owns its draft and its
 * discard guard). A sub-tab switch asks the open pane's guard first, so a dirty template is not dropped silently.
 */
export function QuestsTab() {
  const { t } = useI18n()
  const [subtab, setSubtab] = useState<SubTab>(initialSubtab)
  const paneGuard = useRef<PaneGuard | null>(null)
  const onGuard = useCallback((guard: PaneGuard | null) => { paneGuard.current = guard }, [])

  const select = (id: SubTab) => {
    if (id === subtab) return
    const go = () => {
      setSubtab(id)
      try { localStorage.setItem(STORAGE_KEY, id) } catch { /* Storage can be disabled. */ }
    }
    if (paneGuard.current) paneGuard.current(go)
    else go()
  }

  return (
    <>
      <nav className="ga-subtabs" aria-label={t('Quests')}>
        {SUBTABS.map((s) => (
          <button key={s.id} type="button" aria-pressed={subtab === s.id}
            className={`ga-btn ga-btn-sm${subtab === s.id ? ' ga-btn-primary' : ''}`}
            onClick={() => select(s.id)}>{t(s.label)}</button>
        ))}
      </nav>
      {subtab === 'templates' ? <TemplatesView onGuard={onGuard} /> : null}
    </>
  )
}
