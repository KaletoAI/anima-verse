import { useCallback, useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPut } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { Field } from '../../components/Field'
import { DetailToolbar } from '../../components/DetailToolbar'

/**
 * Game-Admin "Setup" tab — the world briefing (description) under the Save
 * button in the DetailToolbar above.
 *
 * - description: free-form world briefing, injected into LLM templates
 *   via the world_setup variable
 *
 * Temperature and weather used to live here as world-wide values; they are a
 * property of the SEASON now and are edited in Admin settings.
 */
export function SetupTab() {
  const { t } = useI18n()
  const { toast } = useToast()
  const [description, setDescription] = useState('')
  const [origDescription, setOrigDescription] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const d = await apiGet<{ description?: string }>('/admin/world-setup')
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
      await apiPut('/admin/world-setup', { description })
      setOrigDescription(description)
      toast(t('Saved'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setSaving(false)
    }
  }, [description, t, toast])

  const revert = useCallback(() => {
    setDescription(origDescription)
  }, [origDescription])

  if (loading) return <div className="ga-loading">{t('Loading…')}</div>

  const dirty = description !== origDescription

  return (
    <div className="ga-page-scroll">
      <DetailToolbar
        title={dirty ? t('Setup (unsaved)') : t('Setup')}
        onSave={save}
        onCancel={dirty ? revert : undefined}
        disabled={saving}
        cancelLabel={t('Revert')}
      />
      <div className="ga-form" style={{ maxWidth: 1100 }}>
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
      </div>

      <div className="ga-form" style={{ maxWidth: 1100, marginTop: 32 }}>
        <h3>{t('World atmosphere')}</h3>
        <div className="ga-form-hint">
          {t('Temperature and weather are configured per season in ')}
          <a href="/admin/settings" target="_blank" rel="noreferrer">
            /admin/settings → Game calendar — seasons
          </a>
          .
        </div>
      </div>
    </div>
  )
}
