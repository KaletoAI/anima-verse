import { useCallback, useEffect, useMemo, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { Field } from '../../components/Field'
import { DetailToolbar } from '../../components/DetailToolbar'
import { ListHeader } from '../../components/ListHeader'
import { IconPicker } from '../../components/IconPicker'
import { ExportButton, ImportButton, PublishButton } from '../../components/ImportExport'

interface PromptFilter {
  id: string
  label?: string
  icon?: string
  condition?: string
  drop_blocks?: string[]
  prompt_modifier?: string
  image_modifier?: string
  enabled?: boolean
  source?: string
  warnings?: string[]
  /** Fields the shared baseline fills and this world override leaves empty —
   *  the overlay replaces by id, so those shared values are hidden. */
  masked_fields?: string[]
}

interface FiltersData {
  filters: PromptFilter[]
  block_keys: string[]
  condition_hint?: string
}

interface DraftState extends Required<Omit<PromptFilter, 'source' | 'warnings' | 'masked_fields'>> {
  originalId: string
  source: string
  maskedFields: string[]
  isNew: boolean
}

const EMPTY_DRAFT: DraftState = {
  id: '',
  label: '',
  icon: '',
  condition: '',
  drop_blocks: [],
  prompt_modifier: '',
  image_modifier: '',
  enabled: true,
  originalId: '',
  source: '',
  maskedFields: [],
  isNew: true,
}

function asDraft(f: PromptFilter): DraftState {
  return {
    id: f.id,
    label: f.label || '',
    icon: f.icon || '',
    condition: f.condition || '',
    drop_blocks: [...(f.drop_blocks || [])],
    prompt_modifier: f.prompt_modifier || '',
    image_modifier: f.image_modifier || '',
    enabled: f.enabled !== false,
    originalId: f.id,
    source: f.source || '',
    maskedFields: [...(f.masked_fields || [])],
    isNew: false,
  }
}

/** A world row that carries the same id as a shared state REPLACES it whole
 *  (no deep merge — project rule). So an override that lacks the icon hides
 *  the shared icon, and the only repair is to drop the world row. */
const OVERRIDE = 'world override'

export function StatesTab() {
  const { t } = useI18n()
  const { toast } = useToast()
  const [data, setData] = useState<FiltersData | null>(null)
  const [draft, setDraft] = useState<DraftState | null>(null)
  const [loading, setLoading] = useState(true)
  // In-app confirmation for the two destructive actions (no window.confirm).
  const [confirmAction, setConfirmAction] = useState<'delete' | 'reset' | null>(null)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const next = await apiGet<FiltersData>('/admin/prompt-filters/data')
      setData(next)
    } catch (e) {
      toast(t('Failed to load') + ': ' + (e as Error).message, 'error')
    } finally {
      setLoading(false)
    }
  }, [t, toast])

  useEffect(() => {
    reload()
  }, [reload])

  const sortedFilters = useMemo(() => {
    if (!data) return []
    return [...data.filters].sort((a, b) => a.id.localeCompare(b.id))
  }, [data])

  const newFilter = useCallback(() => {
    setConfirmAction(null)
    setDraft({ ...EMPTY_DRAFT })
  }, [])

  const editFilter = useCallback((f: PromptFilter) => {
    setConfirmAction(null)
    setDraft(asDraft(f))
  }, [])

  const copyFilter = useCallback(() => {
    setConfirmAction(null)
    setDraft((prev) => (prev
      ? { ...prev, id: '', isNew: true, source: '', originalId: '', maskedFields: [] }
      : prev))
  }, [])

  const updateDraft = useCallback(<K extends keyof DraftState>(key: K, value: DraftState[K]) => {
    setDraft((prev) => (prev ? { ...prev, [key]: value } : prev))
  }, [])

  const toggleBlock = useCallback((block: string) => {
    setDraft((prev) => {
      if (!prev) return prev
      const set = new Set(prev.drop_blocks)
      if (set.has(block)) set.delete(block)
      else set.add(block)
      return { ...prev, drop_blocks: Array.from(set) }
    })
  }, [])

  const save = useCallback(async () => {
    if (!draft) return
    const id = draft.id.trim()
    if (!id) {
      toast(t('id required'), 'error')
      return
    }
    try {
      await apiPost('/admin/prompt-filters/save', {
        id,
        label: draft.label.trim(),
        icon: draft.icon.trim(),
        condition: draft.condition.trim(),
        drop_blocks: draft.drop_blocks,
        prompt_modifier: draft.prompt_modifier,
        image_modifier: draft.image_modifier,
        enabled: draft.enabled,
      })
      toast(t('Saved'))
      // Re-fetch and re-pin the just-saved filter so the detail panel
      // stays open. The save endpoint only echoes {status,id}, so look
      // the persisted row up from the reloaded list.
      const next = await apiGet<FiltersData>('/admin/prompt-filters/data')
      setData(next)
      const saved = next.filters.find((f) => f.id === id)
      if (saved) setDraft(asDraft(saved))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [draft, reload, t, toast])

  /** Both actions send the SAME request — DELETE drops the world row. What
   *  differs is what that means: for a world-only state it removes the state,
   *  for an override it uncovers the shared entry again. */
  const applyRemoval = useCallback(async () => {
    if (!draft || draft.isNew) return
    const wasReset = confirmAction === 'reset'
    try {
      await apiDelete(`/admin/prompt-filters/${encodeURIComponent(draft.originalId)}`)
      toast(wasReset ? t('Reset to the shared state') : t('Deleted'))
      await reload()
      setConfirmAction(null)
      setDraft(null)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [confirmAction, draft, reload, t, toast])

  const move = useCallback(
    async (target: 'world' | 'shared') => {
      if (!draft || draft.isNew) return
      setConfirmAction(null)
      try {
        await apiPost(`/admin/prompt-filters/${encodeURIComponent(draft.originalId)}/move`, { target })
        toast(target === 'shared' ? t('Moved to shared') : t('Moved to world'))
        await reload()
        setDraft(null)
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
    },
    [draft, reload, t, toast],
  )

  if (loading || !data) return <div className="ga-loading">{t('Loading…')}</div>

  return (
    <div className="ga-twocol">
      <aside className="ga-twocol-left">
        <ListHeader
          title={t('States')}
          onNew={newFilter}
          onCopy={copyFilter}
          copyDisabled={!draft || draft.isNew}
          extra={
            <>
              <ExportButton
                endpoint="/admin/prompt-filters/export"
                filename="states.zip"
                label={t('Export all')}
                title={t('Download all world-level states as a ZIP')}
              />
              <ImportButton
                endpoint="/admin/prompt-filters/import"
                onImported={() => reload()}
                title={t('Upload a states ZIP (merges by id)')}
              />
              <PublishButton packType="states" defaultName="States block" />
            </>
          }
        />
        <p className="ga-sched-muted">
          {t(
            'On match, the selected blocks are removed from the thought prompt, the modifier appears under effects_block, the icon shows in the character header and the image modifier is appended to the image prompt.',
          )}
          <br />
          {t('Sources: shared baseline + world overlay (world overrides shared by id).')}
        </p>
        <ul className="ga-list">
          {sortedFilters.length === 0 ? (
            <li className="ga-list-empty">{t('No states yet')}</li>
          ) : (
            sortedFilters.map((f) => {
              const isActive = draft && !draft.isNew && draft.originalId === f.id
              return (
                <li key={f.id}>
                  <button
                    type="button"
                    className={`ga-list-row${isActive ? ' is-active' : ''}`}
                    onClick={() => editFilter(f)}
                  >
                    <span className="ga-list-row-main">
                      {f.icon ? <span style={{ marginRight: 6 }}>{f.icon}</span> : null}
                      <code>{f.id}</code>
                      {f.label ? <span className="ga-list-row-sub">— {f.label}</span> : null}
                      {f.warnings && f.warnings.length > 0 ? (
                        <span style={{ marginLeft: 6, color: '#f85149' }}
                          title={f.warnings.join('\n')}>⚠</span>
                      ) : null}
                      {f.source === OVERRIDE && (f.masked_fields || []).length > 0 ? (
                        <span
                          style={{ marginLeft: 6, color: '#d29922' }}
                          title={t('Hides the shared values for: {fields}')
                            .replace('{fields}', (f.masked_fields || []).join(', '))}
                        >↺</span>
                      ) : null}
                    </span>
                    <span
                      className={`ga-source ga-source-${(f.source || 'shared').replace(' ', '-')}`}
                      title={f.source === OVERRIDE
                        ? t('A world entry with this id replaces the shared state completely.')
                        : undefined}
                    >
                      {f.source || 'shared'}
                    </span>
                  </button>
                </li>
              )
            })
          )}
        </ul>
      </aside>
      <section className="ga-twocol-right">
        {draft ? (
          <>
            <DetailToolbar
              title={draft.id || t('New state')}
              onSave={save}
              onCancel={() => { setConfirmAction(null); setDraft(null) }}
              onDelete={draft.isNew
                ? undefined
                : () => setConfirmAction(draft.source === OVERRIDE ? 'reset' : 'delete')}
              deleteLabel={draft.source === OVERRIDE ? t('Reset to shared') : undefined}
              onMove={draft.isNew ? undefined : move}
              storage={
                draft.source === 'shared'
                  ? 'shared'
                  : draft.source === OVERRIDE
                    ? 'world override'
                    : 'world'
              }
            />
            {confirmAction ? (
              <div
                style={{
                  display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
                  margin: '8px 0', padding: '8px 10px', borderRadius: 6,
                  border: '1px solid #d29922', background: 'rgba(210, 153, 34, 0.12)',
                }}
              >
                <span style={{ flex: '1 1 240px' }}>
                  {confirmAction === 'reset'
                    ? t('Drop the world entry "{id}" so the shared state applies again?')
                      .replace('{id}', draft.originalId)
                    : t('Delete state "{id}"?').replace('{id}', draft.originalId)}
                </span>
                <button className="ga-btn ga-btn-danger ga-btn-sm" onClick={applyRemoval}>
                  {confirmAction === 'reset' ? t('Reset to shared') : t('Delete')}
                </button>
                <button className="ga-btn ga-btn-sm" onClick={() => setConfirmAction(null)}>
                  {t('Cancel')}
                </button>
              </div>
            ) : null}
            {draft.source === OVERRIDE ? (
              <p className="ga-sched-muted">
                {draft.maskedFields.length > 0
                  ? t('This world entry replaces the shared state of the same id and hides its {fields}. "Reset to shared" removes the world entry, and the shared state applies again.')
                    .replace('{fields}', draft.maskedFields.join(', '))
                  : t('This world entry replaces the shared state of the same id. "Reset to shared" removes the world entry, and the shared state applies again.')}
              </p>
            ) : null}
            <DraftForm
              draft={draft}
              blockKeys={data.block_keys || []}
              onUpdate={updateDraft}
              onToggleBlock={toggleBlock}
            />
          </>
        ) : (
          <div className="ga-placeholder">{t('Click a state or create a new one.')}</div>
        )}
      </section>
    </div>
  )
}

interface DraftFormProps {
  draft: DraftState
  blockKeys: string[]
  onUpdate: <K extends keyof DraftState>(key: K, value: DraftState[K]) => void
  onToggleBlock: (block: string) => void
}

function DraftForm({ draft, blockKeys, onUpdate, onToggleBlock }: DraftFormProps) {
  const { t } = useI18n()
  const selectedBlocks = useMemo(() => new Set(draft.drop_blocks), [draft.drop_blocks])

  // Live-Validierung der Condition über den Server — EXAKT dieselbe Funktion wie
  // die Laufzeit-Prüfung (validate_condition_references), kein eigener Regex.
  const [condWarnings, setCondWarnings] = useState<string[]>([])
  useEffect(() => {
    const cond = (draft.condition || '').trim()
    if (!cond) { setCondWarnings([]); return }
    let cancelled = false
    const h = setTimeout(() => {
      apiGet<{ warnings?: string[] }>(`/admin/prompt-filters/validate?condition=${encodeURIComponent(cond)}`)
        .then((d) => { if (!cancelled) setCondWarnings(d.warnings || []) })
        .catch(() => { if (!cancelled) setCondWarnings([]) })
    }, 350)
    return () => { cancelled = true; clearTimeout(h) }
  }, [draft.condition])

  return (
    <div className="ga-form">
      <Field label={t('Enabled')} inline compact>
        <input
          type="checkbox"
          checked={draft.enabled}
          onChange={(e) => onUpdate('enabled', e.target.checked)}
        />
      </Field>

      <div className="ga-form-row">
        <Field label={t('Filter ID')} hint={t('a-z0-9_ — used as the profile tag that triggers the filter')}>
          <input
            className="ga-input"
            style={{ fontFamily: 'monospace' }}
            value={draft.id}
            placeholder="filter-id"
            onChange={(e) => onUpdate('id', e.target.value)}
          />
        </Field>
        <Field label={t('Label')}>
          <input
            className="ga-input"
            value={draft.label}
            placeholder={t("e.g. 'Drunk — clouded memory'")}
            onChange={(e) => onUpdate('label', e.target.value)}
          />
        </Field>
      </div>

      <div className="ga-form-row">
        <Field label={t('Icon')} compact>
          <div style={{ width: 110 }}>
            <IconPicker value={draft.icon} onChange={(v) => onUpdate('icon', v)} />
          </div>
        </Field>
        <Field
          label={t('Additional condition')}
          help="condition"
          hint={t('Optional. Filter triggers via the id-tag; this expression triggers it additionally (e.g. stamina<10).')}
        >
          <input
            className="ga-input"
            value={draft.condition}
            placeholder="stamina<10"
            onChange={(e) => onUpdate('condition', e.target.value)}
          />
          {condWarnings.length > 0 ? (
            <div style={{ color: '#f85149', fontSize: '0.8em', marginTop: 4 }}>
              {condWarnings.map((w, i) => <div key={i}>⚠ {w}</div>)}
            </div>
          ) : null}
        </Field>
      </div>

      <Field label={t('Drop blocks')} hint={t('Click to toggle which prompt blocks are removed when this filter matches.')}>
        <div className="ga-block-picker">
          {blockKeys.length === 0 ? (
            <span className="ga-form-hint">{t('No block keys provided.')}</span>
          ) : (
            blockKeys.map((b) => {
              const on = selectedBlocks.has(b)
              return (
                <button
                  key={b}
                  type="button"
                  className={`ga-block${on ? ' is-on' : ''}`}
                  onClick={() => onToggleBlock(b)}
                >
                  {b}
                </button>
              )
            })
          )}
        </div>
      </Field>

      <Field
        label={t('Prompt modifier')}
        help="prompt_modifier"
        hint={t('Text appended to effects_block. Placeholders {avatar} / {giver} — see the help panel.')}
      >
        <textarea
          className="ga-textarea"
          rows={3}
          value={draft.prompt_modifier}
          placeholder="You are drunk. Recent conversations feel fuzzy …"
          onChange={(e) => onUpdate('prompt_modifier', e.target.value)}
        />
      </Field>

      <Field
        label={t('Image modifier')}
        help="image_modifier"
        hint={t("One directive per line. Plain text is appended to the person description; 'A -> B' replaces a matching fragment (e.g. neat hair -> messy tousled hair). Applies to every image type while the state is active.")}
      >
        <textarea
          className="ga-textarea"
          rows={2}
          value={draft.image_modifier}
          placeholder="flushed cheeks, glassy eyes"
          onChange={(e) => onUpdate('image_modifier', e.target.value)}
        />
      </Field>

    </div>
  )
}
