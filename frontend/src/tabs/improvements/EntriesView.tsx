/**
 * The standing orders behind the queue: what should be improved, in which
 * order, and how far each one has got.
 *
 * The ORDER is the point of this view — the engine works the entries top
 * down, so dragging a row is the one control that decides what happens next.
 * The reorder is optimistic (the list jumps immediately, then PATCHes); a
 * failing PATCH refetches, so the screen never keeps an order the server
 * refused.
 *
 * No polling here: the Queue view is the live one. This list refetches after
 * every mutation, which is when its numbers actually change by our doing.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { useToast } from '../../lib/Toast'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { SortableList } from '../../components/SortableList'
import { NewImprovementDialog } from './NewImprovementDialog'
import { EntryDetail } from './EntryDetail'
import {
  deleteImprovement, fetchImprovements, fetchTypes, pauseImprovement,
  rescanImprovement, resumeImprovement, runNow, setOrder,
} from './api'
import { STEP_STATUS_LABELS } from './types'
import type { Improvement, ImprovementType } from './types'

/** The ENTRY statuses (not the step ones) — 'open' is a state, not a verb. */
const ENTRY_STATUS_LABELS: Record<string, string> = {
  open: 'Open',
  paused: 'Paused',
  done: 'Done',
}

/** A system stamp (technical, not game time) rendered as a wall clock. */
function clockTime(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString()
}

export function EntriesView() {
  const { t } = useI18n()
  const { toast } = useToast()
  const [entries, setEntries] = useState<Improvement[] | null>(null)
  const [types, setTypes] = useState<ImprovementType[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [creating, setCreating] = useState(false)
  const [pendingDelete, setPendingDelete] = useState<Improvement | null>(null)
  const [busyId, setBusyId] = useState('')
  const [loadError, setLoadError] = useState('')

  // A failing load keeps the last good list on screen and says so — wiping it
  // to [] would render "No entries yet", which is a LIE about the world: the
  // entries are there, the request is not.
  const load = useCallback(async () => {
    try {
      setEntries(await fetchImprovements())
      setLoadError('')
    } catch (e) {
      setLoadError((e as Error).message)
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [t, toast])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    fetchTypes().then(setTypes).catch(() => setTypes([]))
  }, [])

  const typeLabel = useCallback((typeId: string) => {
    const found = types.find((x) => x.id === typeId)
    return found ? found.label : typeId
  }, [types])

  const statusLabel = useCallback((value: string) => (
    STEP_STATUS_LABELS[value] ? t(STEP_STATUS_LABELS[value]) : value
  ), [t])

  const entryStatusLabel = useCallback((value: string) => (
    ENTRY_STATUS_LABELS[value] ? t(ENTRY_STATUS_LABELS[value]) : value
  ), [t])

  /** One mutation, one refetch — every action funnels through here. */
  const act = useCallback(async (
    id: string, run: () => Promise<unknown>,
  ) => {
    setBusyId(id)
    try {
      await run()
      await load()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusyId('')
    }
  }, [load, t, toast])

  const reorder = useCallback(async (ids: string[]) => {
    const previous = entries || []
    // Optimistic: the dragged row stays where it was dropped while the PATCH
    // travels — a list that snaps back for half a second reads as a bug.
    setEntries(ids
      .map((id) => previous.find((e) => e.id === id))
      .filter((e): e is Improvement => !!e))
    try {
      await setOrder(ids)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
    await load()
  }, [entries, load, t, toast])

  const rescan = useCallback((entry: Improvement) => act(entry.id, async () => {
    const r = await rescanImprovement(entry.id)
    toast(t('{a} added, {c} closed')
      .replace('{a}', String(r.added)).replace('{c}', String(r.closed)))
  }), [act, t, toast])

  const confirmDelete = useCallback(async () => {
    const entry = pendingDelete
    setPendingDelete(null)
    if (!entry) return
    if (selectedId === entry.id) setSelectedId('')
    await act(entry.id, () => deleteImprovement(entry.id))
  }, [act, pendingDelete, selectedId])

  /** The step log is a drawer: clicking the open row closes it again. */
  const toggleSelected = useCallback((id: string) => {
    setSelectedId((current) => (current === id ? '' : id))
  }, [])

  const selected = useMemo(
    () => (entries || []).find((e) => e.id === selectedId) || null,
    [entries, selectedId])

  const created = useCallback(() => {
    setCreating(false)
    load()
  }, [load])

  return (
    <div className="ga-page-scroll">
      <div className="ga-imp-head">
        <button type="button" className="ga-btn ga-btn-sm ga-btn-primary"
          onClick={() => setCreating(true)}>
          {t('New improvement')}
        </button>
        <span className="ga-form-hint">
          {t('The engine works these top down — drag to reorder.')}
        </span>
      </div>

      {/* A standing notice, not a toast that scrolls away while the list
          shows numbers from before the failure. */}
      {loadError ? (
        <div className="ga-imp-error">{t('Error')}: {loadError}</div>
      ) : null}

      {entries === null ? (
        loadError ? null : <div className="ga-loading">{t('Loading…')}</div>
      ) : entries.length === 0 ? (
        <ul className="ga-list">
          <li className="ga-list-empty">{t('No entries yet')}</li>
        </ul>
      ) : (
        <SortableList
          items={entries}
          getKey={(entry) => entry.id}
          onReorder={reorder}
          rowClassName={(entry) => (
            entry.id === selectedId ? 'is-active' : '')}
          render={(entry) => (
            <>
              <span className="ga-list-row-main" role="button" tabIndex={0}
                aria-expanded={entry.id === selectedId}
                onClick={() => toggleSelected(entry.id)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    toggleSelected(entry.id)
                  }
                }}>
                <span>{entry.label || typeLabel(entry.type_id)}</span>
                <span className="ga-list-row-sub">
                  {typeLabel(entry.type_id)}
                </span>
                <span className="ga-list-row-sub">
                  {entry.mode === 'standing' ? t('Standing') : t('One-shot')}
                </span>
                <span className={entry.status === 'open'
                  ? 'ga-status-ok' : 'ga-status-paused'}>
                  {entryStatusLabel(entry.status)}
                </span>
                <span className="ga-list-row-sub">
                  {entry.done}/{entry.done + entry.pending + entry.running}
                  {entry.skipped
                    ? ` · ${entry.skipped} ${statusLabel('skipped')}` : ''}
                  {entry.failed
                    ? ` · ${entry.failed} ${statusLabel('failed')}` : ''}
                </span>
                <span className="ga-list-row-sub">
                  {t('Last scan')} {clockTime(entry.last_scan_at) || t('Never')}
                </span>
              </span>
              <span className="ga-imp-actions">
                <button type="button" className="ga-btn ga-btn-sm"
                  disabled={busyId === entry.id}
                  onClick={() => act(entry.id, () => (
                    entry.status === 'paused'
                      ? resumeImprovement(entry.id)
                      : pauseImprovement(entry.id)))}>
                  {entry.status === 'paused' ? t('Resume') : t('Pause')}
                </button>
                <button type="button" className="ga-btn ga-btn-sm"
                  disabled={busyId === entry.id}
                  onClick={() => act(entry.id, () => runNow(entry.id))}>
                  {t('Run now')}
                </button>
                <button type="button" className="ga-btn ga-btn-sm"
                  disabled={busyId === entry.id}
                  onClick={() => rescan(entry)}>
                  {t('Rescan')}
                </button>
                <button type="button" className="ga-btn ga-btn-sm ga-btn-danger"
                  disabled={busyId === entry.id}
                  onClick={() => setPendingDelete(entry)}>
                  {t('Delete')}
                </button>
              </span>
            </>
          )}
        />
      )}

      {selected ? (
        <EntryDetail improvement={selected} statusLabel={statusLabel}
          onClose={() => setSelectedId('')} onChanged={load} />
      ) : null}

      <NewImprovementDialog open={creating} types={types}
        onCreated={created} onClose={() => setCreating(false)} />

      <ConfirmDialog
        open={!!pendingDelete}
        title={t('Delete improvement')}
        message={t('The entry and all its steps are removed, and a step of it that is running right now is cancelled.')}
        confirmLabel={t('Delete')}
        danger
        onConfirm={confirmDelete}
        onClose={() => setPendingDelete(null)}
      />
    </div>
  )
}
