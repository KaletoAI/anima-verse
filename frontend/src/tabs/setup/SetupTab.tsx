import { useCallback, useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPut } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { Field } from '../../components/Field'
import { DetailToolbar } from '../../components/DetailToolbar'
import { WorldSettingsGroup, type WorldSettings } from './WorldSettingsGroup'
import { UseCaseStyles } from './UseCaseStyles'
import { deleteAt, getAt, originOf, setAt, type Json } from './schemaValues'

/**
 * Game-Admin "Setup" tab: world briefing and schema-driven world settings.
 * The toolbar saves each dirty resource to its own endpoint.
 * Temperature and weather belong to each season, edited in Calendar & seasons.
 */
export function SetupTab() {
  const { t } = useI18n()
  const { toast } = useToast()
  const [ws, setWs] = useState<WorldSettings | null>(null)
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

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const [d, settings] = await Promise.all([
        apiGet<{ description?: string }>('/admin/world-setup'),
        apiGet<WorldSettings>('/admin/world-settings'),
      ])
      setWs(settings)
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
        const settings = await apiPut<WorldSettings>('/admin/world-settings', { values, resets })
        setWs(settings)
        setValues(settings.values)
        setOrigValues(settings.values)
        setOverrides(settings.overrides)
        setResets([])
      }
      toast(t('Saved'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setSaving(false)
    }
  }, [description, origDescription, values, origValues, resets, t, toast])

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
    <div className="ga-page-scroll">
      <DetailToolbar
        title={dirty ? t('Setup (unsaved)') : t('Setup')}
        onSave={save}
        onCancel={dirty ? revert : undefined}
        disabled={saving}
        cancelLabel={t('Revert')}
      />
      <nav className="ga-subtabs" role="tablist">
        {[{ id: 'world_setup', label: t('World setup') }, ...(ws?.groups ?? [])].map(sub =>
          <button type="button" key={sub.id} role="tab" aria-selected={selected === sub.id}
            className={`ga-btn ga-btn-sm${selected === sub.id ? ' ga-btn-primary' : ''}`}
            onClick={() => {
              setActiveSub(sub.id)
              try { localStorage.setItem('ga-setup-subtab', sub.id) } catch { /* Storage can be disabled. */ }
            }}>{sub.label}</button>)}
      </nav>
      <fieldset disabled={saving} style={{ border: 0, padding: 0, margin: 0 }}>
      {selected === 'world_setup' ? <div className="ga-form" style={{ maxWidth: 1100 }}>
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
        : ws && group ? <WorldSettingsGroup group={group} schema={ws.schema} values={values}
          shipped={ws.shipped} overrides={overrides} onChange={change} onReset={reset} /> : null}
      </fieldset>
    </div>
  )
}
