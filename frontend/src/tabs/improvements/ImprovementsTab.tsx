/**
 * Game-Admin "Improvements" tab — the idle-time worker's queue.
 *
 * Two views over the same data: the QUEUE is what will run next and whether
 * the engine may run it at all; the ENTRIES are the standing orders that
 * produce those steps. The queue is the default because it answers the
 * question the tab is opened with: is anything happening.
 */
import { useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { QueueView } from './QueueView'
import { EntriesView } from './EntriesView'

type View = 'queue' | 'entries'

export function ImprovementsTab() {
  const { t } = useI18n()
  const [view, setView] = useState<View>('queue')

  return (
    <>
      <div className="ga-imp-segments">
        <button type="button" onClick={() => setView('queue')}
          className={'ga-btn ga-btn-sm'
            + (view === 'queue' ? ' ga-btn-primary' : '')}>
          {t('Queue')}
        </button>
        <button type="button" onClick={() => setView('entries')}
          className={'ga-btn ga-btn-sm'
            + (view === 'entries' ? ' ga-btn-primary' : '')}>
          {t('Entries')}
        </button>
      </div>
      {view === 'queue' ? <QueueView /> : <EntriesView />}
    </>
  )
}
