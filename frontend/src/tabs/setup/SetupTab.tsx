import { useCallback, useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { ApiError, apiGet, apiPut } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { ConfirmDialog } from '@anima/player-ui'
import { Field } from '@anima/player-ui'
import { DetailToolbar } from '../../components/DetailToolbar'
import { WorldSettingsGroup, type WorldSettings as WorldSettingsPayload } from './WorldSettingsGroup'
import { UseCaseStyles } from './UseCaseStyles'
import { ExtensionMotion } from './ExtensionMotion'
import { PackagesSetup } from './PackagesSetup'
import { deleteAt, getAt, originOf, setAt, type Json } from './schemaValues'

type WorldSettings = WorldSettingsPayload & { revision: string }

/**
 * Game-Admin "Setup" tab: world briefing and schema-driven world settings.
 * The toolbar saves each dirty resource to its own endpoint.
 * Temperature and weather belong to each season, edited in Calendar & seasons.
 */
export function SetupTab() {
  const { t } = useI18n()
  const { toast } = useToast()
  const [ws, setWs] = useState<WorldSettings | null>(null)
  const [revision, setRevision] = useState<string | null>(null)
  const [stalePaths, setStalePaths] = useState<string[] | null>(null)
  const [values, setValues] = useState<Json>({})
  const [origValues, setOrigValues] = useState<Json>({})
  const [resets, setResets] = useState<string[]>([])
  const [overrides, setOverrides] = useState<string[]>([])
  const [activeSub, setActiveSub] = useState(() => {
    try { return localStorage.getItem('ga-setup-subtab') ?? 'world_setup' } catch { return 'world_setup' }
  })
  const [description, setDescription] = useState('')
  const [origDescription, setOrigDescription] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [dropConfirmation, setDropConfirmation] = useState<{
    paths: string[]
    resolve: (confirmed: boolean) => void
  } | null>(null)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const [d, settings] = await Promise.all([
        apiGet<{ description?: string }>('/admin/world-setup'),
        apiGet<WorldSettings>('/admin/world-settings'),
      ])
      setWs(settings)
      setRevision(settings.revision)
      setValues(settings.values)
      setOrigValues(settings.values)
      setOverrides(settings.overrides)
      setResets([])
      const text = d.description || ''
      setDescription(text)
      setOrigDescription(text)
    } catch (e) {
      toast(t('Failed to load') + ': ' + (e as Error).message, 'error')
    } finally {
      setLoading(false)
    }
  }, [t, toast])

  useEffect(() => {
    reload()
  }, [reload])

  const save = useCallback(async () => {
    setSaving(true)
    try {
      if (description !== origDescription) {
        await apiPut('/admin/world-setup', { description })
        setOrigDescription(description)
      }
      if (JSON.stringify(values) !== JSON.stringify(origValues) || resets.length) {
        let settings: WorldSettings
        try {
          settings = await apiPut<WorldSettings>('/admin/world-settings', { values, resets, base_revision: revision })
        } catch (e) {
          const detail = e instanceof ApiError && e.status === 409
            && e.detail !== null && typeof e.detail === 'object'
            ? e.detail as Record<string, unknown> : null
          if (detail?.code !== 'would_drop' || !Array.isArray(detail.paths)
            || !detail.paths.every((path): path is string => typeof path === 'string')) throw e
          const paths = detail.paths
          const confirmed = await new Promise<boolean>(resolve => {
            setDropConfirmation({ paths, resolve })
          })
          if (!confirmed) return
          // Retry once; the outer handler also handles a stale revision on retry.
          settings = await apiPut<WorldSettings>('/admin/world-settings', { values, resets, base_revision: revision, confirm_drop: paths })
        }
        setWs(settings)
        setRevision(settings.revision)
        setValues(settings.values)
        setOrigValues(settings.values)
        setOverrides(settings.overrides)
        setResets([])
      }
      toast(t('Saved'))
    } catch (e) {
      const detail = e instanceof ApiError && e.detail !== null && typeof e.detail === 'object'
        ? e.detail as Record<string, unknown> : null
      if (e instanceof ApiError && (e.status === 428 || (e.status === 409 && detail?.code === 'stale'))) {
        setStalePaths(Array.isArray(detail?.paths)
          ? detail.paths.filter((path): path is string => typeof path === 'string') : [])
        return
      }
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setSaving(false)
    }
  }, [description, origDescription, values, origValues, resets, revision, t, toast])

  const revert = useCallback(() => {
    setDescription(origDescription)
    setValues(origValues)
    setOverrides(ws?.overrides ?? [])
    setResets([])
  }, [origDescription, origValues, ws])

  // Segment boundaries prevent foo from overlapping foobar.
  const change = (path: string, next: Json) => {
    setValues(next)
    setResets(previous => previous.filter(reset => originOf(path, [reset]) === 'default'))
    setOverrides(previous => [...new Set([...previous, path])])
  }
  const reset = (path: string) => {
    const shipped = getAt(ws!.shipped, path)
    setValues(shipped === undefined ? deleteAt(values, path) : setAt(values, path, shipped))
    setResets(previous => [...new Set([...previous, path])])
    setOverrides(previous => previous.filter(other => other !== path && !other.startsWith(path + '.')))
  }

  if (loading) return <div className="ga-loading">{t('Loading…')}</div>

  const dirty = description !== origDescription || JSON.stringify(values) !== JSON.stringify(origValues) || resets.length > 0
  const selected = ws?.groups.some(group => group.id === activeSub) ? activeSub : 'world_setup'
  const group = ws?.groups.find(group => group.id === selected)

  return (
    <div className="ga-page-scroll ga-setup">
      <ConfirmDialog
        open={dropConfirmation !== null}
        title={t('Remove stored settings?')}
        message={t('This save would remove: {paths}. If this page is stale, cancel and reload instead.')
          .replace('{paths}', dropConfirmation?.paths.join(', ') ?? '')}
        confirmLabel={t('Remove')}
        danger
        onConfirm={() => {
          dropConfirmation?.resolve(true)
          setDropConfirmation(null)
        }}
        onClose={() => {
          dropConfirmation?.resolve(false)
          setDropConfirmation(null)
        }}
      />
      <ConfirmDialog
        open={stalePaths !== null}
        title={t('Settings changed elsewhere')}
        message={t('Reload to see the current settings; your unsaved edits here are lost.')
          + (stalePaths?.length ? ' ' + stalePaths.join(', ') : '')}
        confirmLabel={t('Reload')}
        onConfirm={() => {
          setStalePaths(null)
          void reload()
        }}
        onClose={() => setStalePaths(null)}
      />
      <DetailToolbar
        title={dirty ? t('Setup (unsaved)') : t('Setup')}
        onSave={save}
        onCancel={dirty ? revert : undefined}
        disabled={saving}
        cancelLabel={t('Revert')}
      />
      <nav className="ga-subtabs" aria-label={t('Setup')}>
        {[{ id: 'world_setup', label: t('World setup') }, ...(ws?.groups ?? [])].map(sub =>
          <button type="button" key={sub.id} aria-pressed={selected === sub.id}
            className={`ga-btn ga-btn-sm${selected === sub.id ? ' ga-btn-primary' : ''}`}
            onClick={() => {
              setActiveSub(sub.id)
              try { localStorage.setItem('ga-setup-subtab', sub.id) } catch { /* Storage can be disabled. */ }
            }}>{sub.label}</button>)}
      </nav>
      <fieldset disabled={saving} className="ga-setup-content">
      {selected === 'world_setup' ? <div className="ga-form">
        <Field
          label={t('World setup')}
          hint={t(
            'Free-form description of the world: tone, era, genre, ground rules. The chat and World-Dev LLMs see this as a briefing before any character or location context. Empty = no world briefing.',
          )}
        >
          <textarea
            className="ga-textarea"
            rows={20}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder={t(
              'e.g. "Modern-day Berlin. Adults only. Slice-of-life with occasional supernatural twists. Characters speak everyday German; English fine for slang."',
            )}
            spellCheck
          />
        </Field>
        <div className="ga-form-hint">
          {t('Length: characters')} {description.length.toLocaleString()}
        </div>
      </div> : ws && selected === 'image_styles' ? <UseCaseStyles defaults={ws.use_case_defaults}
        values={values} overrides={overrides} onChange={change} onReset={reset} />
        : ws && selected === 'extension_motion' ? <ExtensionMotion values={values} onChange={change} />
        : ws && selected === 'packages' ? <PackagesSetup values={values} onChange={change} />
        : ws && group ? <WorldSettingsGroup group={group} schema={ws.schema} values={values}
          shipped={ws.shipped} overrides={overrides} onChange={change} onReset={reset} /> : null}
      </fieldset>
    </div>
  )
}
