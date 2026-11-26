import { useCallback, useEffect, useRef, useState } from 'react'
import { ConfirmDialog } from '@anima/player-ui'
import { useI18n } from '../../i18n/I18nProvider'
import { useToast } from '../../lib/Toast'
import { DetailToolbar } from '../../components/DetailToolbar'
import { ListHeader } from '../../components/ListHeader'
import { ListPane } from '../../components/ListPane'
import { useDiscardGuard, useDraft } from '../../lib/useDraft'
import { StartRunDialog } from './StartRunDialog'
import { TemplateForm } from './TemplateForm'
import {
  createTemplate, deleteTemplate, fetchCatalog, fetchTemplate, fetchTemplates, questError, updateTemplate,
} from './api'
import type { TemplateListRow, TemplateRow } from './api'
import { canSave, clientIssues, draftToRow, emptyDraft, questErrorText, rowToDraft } from './questsModel'
import type { Catalog, Issue, TemplateDraft } from './questsModel'

/** The guard of the open pane: run `fn` now, or after the admin agreed to drop unsaved edits. */
export type PaneGuard = (fn: () => void) => void

/**
 * The template editor: the list of quest templates on the left, the open one on the right. A template that has
 * no id yet is new (created by Save). Save sends `base_revision`; a 409 `stale` offers Reload, a 422 `invalid`
 * shows the issue list — the way out of it is to save the template as a draft (the state select on Basics).
 */
export function TemplatesView({ onGuard, onStarted }: {
  onGuard?: (guard: PaneGuard | null) => void
  /** Called after a run was started from the open template (the tab switches to Runs). */
  onStarted?: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [rows, setRows] = useState<TemplateListRow[] | null>(null)
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const { draft, setDraft, load: loadDraft, dirty } = useDraft<TemplateDraft>()
  const { guard, dialog: discardDialog } = useDiscardGuard(dirty)
  const [issues, setIssues] = useState<Issue[]>([])
  const [error, setError] = useState('')
  const [stale, setStale] = useState(false)
  const [saving, setSaving] = useState(false)
  // The list, "+ New" and Copy stay clickable while a save is in flight; they do nothing until it ends, so the
  // save's answer never replaces a template the admin opened meanwhile (a ref: the callbacks are memoised).
  const savingRef = useRef(false)
  const [pendingDelete, setPendingDelete] = useState(false)
  const [starting, setStarting] = useState(false)
  const invalidMessage = t('A ready template must have no issues. Fix them, or set the state to Draft and save.')

  useEffect(() => {
    onGuard?.(guard)
    return () => onGuard?.(null)
  }, [guard, onGuard])

  const reload = useCallback(async () => {
    try {
      setRows(await fetchTemplates())
    } catch (e) {
      toast(t('Failed to load') + ': ' + (e as Error).message, 'error')
      setRows((prev) => prev || [])
    }
  }, [t, toast])

  useEffect(() => { reload() }, [reload])
  useEffect(() => {
    fetchCatalog().then(setCatalog).catch((e) => {
      toast(t('Failed to load') + ': ' + (e as Error).message, 'error')
      setCatalog({ conditions: [], prerequisites: [], effects: [], role_kinds: [] })
    })
  }, [t, toast])

  const show = useCallback((row: TemplateRow) => {
    loadDraft(rowToDraft(row))
    setIssues(Array.isArray(row.issues) ? row.issues : [])
    setError('')
    setStale(false)
  }, [loadDraft])

  const open = useCallback(async (id: string) => {
    try {
      show(await fetchTemplate(id))
    } catch (e) {
      toast(t('Error') + ': ' + questErrorText(questError(e), t), 'error')
    }
  }, [show, t, toast])

  const newTemplate = useCallback(() => guard(() => {
    if (savingRef.current) return
    loadDraft(emptyDraft())
    setIssues([])
    setError('')
    setStale(false)
  }), [guard, loadDraft])

  const editTemplate = useCallback((row: TemplateListRow) => guard(() => {
    if (!savingRef.current) void open(row.id)
  }), [guard, open])

  const copyTemplate = useCallback(() => {
    if (savingRef.current) return
    setDraft((prev) => (prev ? { ...prev, id: '', revision: 0, state: 'draft', title: `${prev.title} (copy)`.trim() } : prev))
    setIssues([])
    setStale(false)
    setError('')
  }, [setDraft])

  const fail = useCallback((e: unknown) => {
    const err = questError(e)
    if (err.code === 'stale') {
      setStale(true)
      setError(t('This template was changed elsewhere since you opened it. Reload it to continue; your edits here are lost.'))
    } else if (err.code === 'invalid') {
      setIssues(err.issues)
      setError(invalidMessage)
    } else {
      setError(questErrorText(err, t))
    }
    toast(t('Error') + ': ' + questErrorText(err, t), 'error')
  }, [invalidMessage, t, toast])

  const save = useCallback(async () => {
    if (!draft) return
    if (!draft.title.trim()) {
      setError(t('The quest needs a title'))
      return
    }
    setSaving(true)
    savingRef.current = true
    setError('')
    setStale(false)
    const body = draftToRow(draft)
    try {
      let saved: TemplateRow
      if (!draft.id) {
        // A new template is always created as a draft; "ready" is a second save against the new revision.
        const { state, ...createBody } = body
        saved = await createTemplate(createBody)
        if (state === 'ready') {
          show(saved)
          await reload()
          try {
            saved = await updateTemplate(saved.id, { state: 'ready' }, saved.revision)
          } catch (e) {
            // The template IS stored now, as a draft: say so, and keep the admin's "Ready" as an unsaved edit so
            // the next Save (after fixing the issues) sets it ready.
            const err = questError(e)
            setDraft((prev) => (prev ? { ...prev, state: 'ready' } : prev))
            const reason = err.code === 'invalid'
              ? t('{n} issue(s), listed below').replace('{n}', String(err.issues.length))
              : questErrorText(err, t)
            if (err.code === 'invalid') setIssues(err.issues)
            const text = t('Saved as a draft — not ready yet: {reason}').replace('{reason}', reason)
            setError(text)
            toast(text, 'error')
            return
          }
        }
      } else {
        saved = await updateTemplate(draft.id, body, draft.revision)
      }
      show(saved)
      toast(t('Saved'))
      await reload()
    } catch (e) {
      fail(e)
    } finally {
      setSaving(false)
      savingRef.current = false
    }
  }, [draft, fail, reload, setDraft, show, t, toast])

  const reloadOpen = useCallback(() => {
    if (draft?.id) void open(draft.id)
  }, [draft, open])

  const doDelete = useCallback(async () => {
    setPendingDelete(false)
    if (!draft?.id) return
    try {
      await deleteTemplate(draft.id)
      toast(t('Deleted'))
      loadDraft(null)
      setIssues([])
      await reload()
    } catch (e) {
      const text = questErrorText(questError(e), t)
      setError(text)
      toast(t('Error') + ': ' + text, 'error')
    }
  }, [draft, loadDraft, reload, t, toast])

  if (rows === null || catalog === null) return <div className="ga-loading">{t('Loading…')}</div>

  const serverIssuePaths = new Set(issues.map((i) => i.path))
  const allIssues = draft
    ? [...issues, ...clientIssues(draft, catalog.effects).filter((i) => !serverIssuePaths.has(i.path))]
    : issues

  return (
    <div className="ga-twocol">
      <ListPane id="quest-templates" label={t('Quest templates')}>
        <ListHeader title={t('Quest templates')} onNew={newTemplate} onCopy={copyTemplate}
          copyDisabled={!draft || !draft.id} />
        <ul className="ga-list">
          {rows.length === 0 ? (
            <li className="ga-list-empty">{t('No quest templates yet')}</li>
          ) : rows.map((row) => {
            const active = !!draft && draft.id === row.id
            return (
              <li key={row.id}>
                <button type="button" className={`ga-list-row${active ? ' is-active' : ''}`}
                  onClick={() => editTemplate(row)}>
                  <span className="ga-list-row-main">
                    <strong>{row.title || row.id}</strong>
                    {row.open_runs ? (
                      <span className="ga-list-row-sub">— {t('{n} open').replace('{n}', String(row.open_runs))}</span>
                    ) : null}
                  </span>
                  <span className={`ga-tag${row.state === 'ready' ? ' ga-status-ok' : ''}`}>
                    {row.state === 'ready' ? t('Ready') : t('Draft')}
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      </ListPane>

      <section className="ga-twocol-right">
        {draft ? (
          <>
            <DetailToolbar
              title={draft.id ? draft.title || draft.id : t('New quest template')}
              onSave={save}
              onCancel={() => {
                if (draft.id) void open(draft.id)
                else { loadDraft(null); setIssues([]); setError('') }
              }}
              onDelete={draft.id ? () => setPendingDelete(true) : undefined}
              disabled={saving}
              saveDisabled={!canSave(draft, dirty)}
              dirty={dirty}
              extra={
                <button type="button" className="ga-btn ga-btn-sm"
                  disabled={!draft.id || dirty || draft.state !== 'ready' || saving}
                  title={draft.id && !dirty && draft.state === 'ready' ? undefined : t('Save the template as ready first')}
                  onClick={() => setStarting(true)}>
                  {t('Start run')}
                </button>
              }
            />
            {error || (!stale && allIssues.length) ? (
              <div className="ga-hint ga-quest-error" role="alert">
                {error ? <p>{error}</p> : null}
                {stale ? (
                  <button type="button" className="ga-btn ga-btn-sm" onClick={reloadOpen}>{t('Reload')}</button>
                ) : null}
                {!stale && allIssues.length ? (
                  <ul>{allIssues.map((i, n) => <li key={n}><code>{i.path || '—'}</code> {t(i.message)}</li>)}</ul>
                ) : null}
              </div>
            ) : null}
            <TemplateForm draft={draft} catalog={catalog} issues={allIssues}
              onChange={(next) => setDraft(next)} onStructureChange={() => {
                setIssues([])
                setError((e) => (e === invalidMessage ? '' : e))
              }} />
          </>
        ) : (
          <div className="ga-placeholder">{t('Click a quest template or create a new one.')}</div>
        )}
      </section>

      <ConfirmDialog
        open={pendingDelete}
        title={t('Delete quest template')}
        message={t('Quest template "{name}" is deleted. Runs that already ended keep their own copy.')
          .replace('{name}', draft ? draft.title || draft.id : '')}
        confirmLabel={t('Delete')}
        danger
        onConfirm={() => { void doDelete() }}
        onClose={() => setPendingDelete(false)}
      />
      {draft && draft.id ? (
        <StartRunDialog open={starting} templateId={draft.id} title={draft.title || draft.id} roles={draft.roles}
          onClose={() => setStarting(false)}
          onStarted={() => {
            setStarting(false)
            toast(t('Run started'))
            void reload()
            onStarted?.()
          }} />
      ) : null}
      {discardDialog}
    </div>
  )
}
