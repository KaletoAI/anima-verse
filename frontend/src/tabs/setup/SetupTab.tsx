import { useCallback, useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPut } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { Field } from '../../components/Field'
import { DetailToolbar } from '../../components/DetailToolbar'

/**
 * Game-Admin "Setup" tab — World briefing (description) + World/Pose
 * settings under one Save button (in the DetailToolbar above).
 *
 * - description: free-form world briefing, injected into LLM templates
 *   via the world_setup variable
 * - world.temperature / weather: soft LLM hints (Plan §1.2)
 * - pose.*: variant matching config (Plan §6.3)
 */
interface WorldSettings {
  world: { temperature: string; weather: string }
  pose: {
    system_active: boolean
    variant_match_threshold: number
    max_variants_per_char: number
  }
  choices: { temperature: string[]; weather: string[] }
}

export function SetupTab() {
  const { t } = useI18n()
  const { toast } = useToast()
  const [description, setDescription] = useState('')
  const [origDescription, setOrigDescription] = useState('')
  const [settings, setSettings] = useState<WorldSettings | null>(null)
  const [origSettings, setOrigSettings] = useState<WorldSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const [d, s] = await Promise.all([
        apiGet<{ description?: string }>('/admin/world-setup'),
        apiGet<WorldSettings>('/world/settings'),
      ])
      const text = d.description || ''
      setDescription(text)
      setOrigDescription(text)
      setSettings(s)
      setOrigSettings(JSON.parse(JSON.stringify(s)))
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
    if (!settings) return
    setSaving(true)
    try {
      // Beide unabhaengigen Endpunkte parallel speichern — Save oben deckt alles ab.
      await Promise.all([
        apiPut('/admin/world-setup', { description }),
        apiPut('/world/settings', { world: settings.world, pose: settings.pose }),
      ])
      setOrigDescription(description)
      setOrigSettings(JSON.parse(JSON.stringify(settings)))
      toast(t('Saved'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setSaving(false)
    }
  }, [description, settings, t, toast])

  const revert = useCallback(() => {
    setDescription(origDescription)
    if (origSettings) setSettings(JSON.parse(JSON.stringify(origSettings)))
  }, [origDescription, origSettings])

  if (loading || !settings) return <div className="ga-loading">{t('Loading…')}</div>

  const dirty =
    description !== origDescription ||
    JSON.stringify(settings) !== JSON.stringify(origSettings)

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
        <div className="ga-form-hint" style={{ marginBottom: 8 }}>
          {t('Soft hints for the chat-LLM. No code effect — the model can choose how to react.')}
        </div>
        <div className="ga-form-row">
          <Field label={t('Temperature')}>
            <select
              className="ga-input"
              value={settings.world.temperature}
              onChange={(e) =>
                setSettings({ ...settings, world: { ...settings.world, temperature: e.target.value } })
              }
            >
              {settings.choices.temperature.map((v) => (
                <option key={v} value={v}>{v}</option>
              ))}
            </select>
          </Field>
          <Field label={t('Weather')}>
            <select
              className="ga-input"
              value={settings.world.weather}
              onChange={(e) =>
                setSettings({ ...settings, world: { ...settings.world, weather: e.target.value } })
              }
            >
              {settings.choices.weather.map((v) => (
                <option key={v} value={v}>{v}</option>
              ))}
            </select>
          </Field>
        </div>

        <h3 style={{ marginTop: 24 }}>{t('Pose variants')}</h3>
        <div className="ga-form-hint" style={{ marginBottom: 8 }}>
          {t('Free-text pose descriptions are matched against existing variants per character to consolidate image cache. Lower threshold = fewer variants, more reuse.')}
        </div>
        <Field label={t('Pose system active')}>
          <label className="ga-form-check">
            <input
              type="checkbox"
              checked={settings.pose.system_active}
              onChange={(e) =>
                setSettings({ ...settings, pose: { ...settings.pose, system_active: e.target.checked } })
              }
            />
            <span>{t('Use pose variants instead of activity-library classification')}</span>
          </label>
        </Field>
        <div className="ga-form-row">
          <Field label={t('Match threshold')} hint={t('Cosine similarity, 0.0–1.0. Default 0.75.')}>
            <input
              type="number"
              className="ga-input"
              min={0}
              max={1}
              step={0.05}
              value={settings.pose.variant_match_threshold}
              onChange={(e) =>
                setSettings({
                  ...settings,
                  pose: {
                    ...settings.pose,
                    variant_match_threshold: parseFloat(e.target.value) || 0,
                  },
                })
              }
            />
          </Field>
          <Field label={t('Max variants per character')}>
            <input
              type="number"
              className="ga-input"
              min={1}
              max={200}
              value={settings.pose.max_variants_per_char}
              onChange={(e) =>
                setSettings({
                  ...settings,
                  pose: {
                    ...settings.pose,
                    max_variants_per_char: parseInt(e.target.value, 10) || 20,
                  },
                })
              }
            />
          </Field>
        </div>
      </div>
    </div>
  )
}
