import { useCallback, useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost, apiPut } from '../../lib/api'
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

        <BodySlotMigration />
      </div>
    </div>
  )
}

// Body-slot migration payloads (GET/POST /characters/body-slots/migration)
interface MigrationCharPlan {
  character: string
  copies: Array<{ slot: string; attr: string; field: string; value: string }>
  texts: Record<string, { before: string; after: string; dropped: string[] }>
}
interface MigrationPlan { characters: MigrationCharPlan[]; total: number }

/** World-level body-slot migration (on demand, plan-body-slots.md):
 * dry-run preview first, then apply. Copies template-select values into
 * species-package slot values and cleans the migrated {tokens} out of the
 * appearance texts. */
function BodySlotMigration() {
  const { t } = useI18n()
  const { toast } = useToast()
  const [plan, setPlan] = useState<MigrationPlan | null>(null)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(false)

  const preview = useCallback(async () => {
    setBusy(true)
    setDone(false)
    try {
      setPlan(await apiGet<MigrationPlan>('/characters/body-slots/migration'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }, [t, toast])

  const apply = useCallback(async () => {
    setBusy(true)
    try {
      const r = await apiPost<MigrationPlan>('/characters/body-slots/migration/apply', {})
      setPlan(r)
      setDone(true)
      toast(t('Migration applied'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }, [t, toast])

  return (
    <div>
      <h3 style={{ marginTop: 24 }}>{t('Body-slot migration')}</h3>
      <div className="ga-form-hint" style={{ marginBottom: 8 }}>
        {t('Copies the legacy appearance select values into the species-package body slots and removes the migrated {tokens} from the appearance texts. Per world, on demand — preview first.')}
      </div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
        <button className="ga-btn ga-btn-sm" disabled={busy} onClick={preview}>
          {t('Preview migration')}
        </button>
        {plan && plan.total > 0 && !done && (
          <button className="ga-btn ga-btn-sm ga-btn-primary" disabled={busy} onClick={apply}>
            {t('Apply migration')} ({plan.total})
          </button>
        )}
      </div>
      {plan && plan.total === 0 && (
        <div className="ga-form-hint">{t('Nothing to migrate.')}</div>
      )}
      {plan && plan.characters.map((c) => (
        <div key={c.character} style={{ marginBottom: 8, fontSize: '0.85em',
          border: '1px solid var(--border, #30363d)', borderRadius: 6, padding: '6px 10px' }}>
          <strong>{c.character}</strong>
          {c.copies.length > 0 && (
            <div style={{ opacity: 0.8 }}>
              {c.copies.map((cp) => `${cp.field} → ${cp.slot}.${cp.attr} = "${cp.value}"`).join(' · ')}
            </div>
          )}
          {Object.entries(c.texts).map(([field, info]) => (
            <div key={field} style={{ opacity: 0.65 }}>
              {field}: −{info.dropped.length} {t('segments removed')} → „{info.after.slice(0, 90)}{info.after.length > 90 ? '…' : ''}"
            </div>
          ))}
        </div>
      ))}
      {done && <div className="ga-form-hint">{t('Migration applied')}.</div>}
    </div>
  )
}
