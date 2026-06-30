/**
 * TemplateSectionForm — rendert EINE Template-Sektion generisch als Formular.
 *
 * Lädt die drei Speicher des Characters und schreibt jedes Feld in den richtigen:
 *   - `store` fehlt        → profile_json            (GET/POST /characters/{n}/profile)
 *   - `store: config`      → config_json             (GET/POST /characters/{n}/config)
 *   - `store: status_effects` → profile.status_effects (GET /status-effects, POST /profile)
 *
 * Sichtbarkeit (`visible_when`) wird live über alle Speicher ausgewertet.
 * Soul-Felder (`source_file`) und unsichtbare Felder (`editor_visible:false`)
 * werden übersprungen. Kein Hardcoding — alles aus der Template-Definition.
 */
import { useCallback, useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { Field } from '../../components/Field'
import { TemplateField, tmplText, type TmplFieldDef, type DynamicData } from './TemplateField'

// Identitäts-Schlüssel: nie editierbar (Rename würde den DB-Key brechen).
const FORCE_READONLY = new Set(['character_name'])

export interface TmplSection {
  [k: string]: unknown
  id: string
  label?: string
  label_de?: string
  fields?: TmplFieldDef[]
  visible_when?: { field: string; values: unknown[] }
}

export function TemplateSectionForm({
  character,
  section,
  dynamicData,
  excludeKeys,
}: {
  character: string
  section: TmplSection
  dynamicData: DynamicData
  /** Policy-Ausschluss einzelner Felder (z.B. Social-Zahlen im /play). */
  excludeKeys?: string[]
}) {
  const { t, lang } = useI18n()
  const { toast } = useToast()
  const [profile, setProfile] = useState<Record<string, unknown>>({})
  const [config, setConfig] = useState<Record<string, unknown>>({})
  const [status, setStatus] = useState<Record<string, unknown>>({})
  const [savingKey, setSavingKey] = useState('')
  const [loaded, setLoaded] = useState(false)

  const load = useCallback(async () => {
    if (!character) return
    setLoaded(false)
    try {
      const [pr, cf] = await Promise.all([
        apiGet<{ profile: Record<string, unknown> }>(`/characters/${encodeURIComponent(character)}/profile`),
        apiGet<{ config: Record<string, unknown> }>(`/characters/${encodeURIComponent(character)}/config`),
      ])
      setProfile(pr.profile || {})
      setConfig(cf.config || {})
      // status_effects nur laden, wenn die Sektion solche Felder hat.
      const hasStat = (section.fields || []).some((f) => f.store === 'status_effects')
      if (hasStat) {
        try {
          const se = await apiGet<{ status_effects: Record<string, unknown> }>(
            `/characters/${encodeURIComponent(character)}/status-effects`,
          )
          setStatus(se.status_effects || {})
        } catch {
          setStatus({})
        }
      } else {
        setStatus({})
      }
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setLoaded(true)
    }
  }, [character, section, t, toast])

  useEffect(() => {
    load()
  }, [load])

  const storeOf = (f: TmplFieldDef) => f.store || 'profile'

  // Rohwert aus dem richtigen Speicher (für visible_when-Lookups über alle Keys).
  const lookup = (key: string): unknown => {
    if (key in config) return config[key]
    if (key in status) return status[key]
    return profile[key]
  }

  const getVal = (f: TmplFieldDef): unknown => {
    const s = storeOf(f)
    let v = s === 'config' ? config[f.key] : s === 'status_effects' ? status[f.key] : profile[f.key]
    if ((v === '' || v === null || v === undefined) && f.default !== undefined) v = f.default
    return v ?? ''
  }

  const visible = (vw?: { field: string; values: unknown[] }): boolean => {
    if (!vw || !vw.field) return true
    const dv = lookup(vw.field)
    return (vw.values || []).map(String).includes(String(dv ?? ''))
  }

  const commit = useCallback(
    async (f: TmplFieldDef, raw: string) => {
      const s = storeOf(f)
      const value: unknown = f.type === 'number' ? (raw === '' ? '' : Number(raw)) : raw
      setSavingKey(f.key)
      try {
        if (s === 'config') {
          await apiPost(`/characters/${encodeURIComponent(character)}/config`, { fields: { [f.key]: value } })
          setConfig((c) => ({ ...c, [f.key]: value }))
        } else if (s === 'status_effects') {
          const merged = { ...status, [f.key]: value }
          await apiPost(`/characters/${encodeURIComponent(character)}/profile`, {
            fields: { status_effects: merged },
          })
          setStatus(merged)
        } else {
          await apiPost(`/characters/${encodeURIComponent(character)}/profile`, { fields: { [f.key]: value } })
          setProfile((p) => ({ ...p, [f.key]: value }))
        }
        toast(t('Saved'))
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
        load()
      } finally {
        setSavingKey('')
      }
    },
    [character, status, t, toast, load],
  )

  if (!loaded) {
    return <div className="ga-loading">{t('Loading…')}</div>
  }

  // Editierbare, sichtbare Felder (Soul + unsichtbare + Policy-Ausschlüsse raus).
  const ex = new Set(excludeKeys || [])
  const fields = (section.fields || []).filter(
    (f) => f.editor_visible !== false && !f.source_file && !ex.has(f.key) && visible(f.visible_when),
  )
  if (fields.length === 0) {
    return <div className="ga-placeholder">{t('No editable fields in this section.')}</div>
  }

  return (
    <div className="ga-form">
      <div className="ga-form-row ga-form-row-wrap-tpl">
        {fields.map((f) => {
          const ro = !!f.readonly || FORCE_READONLY.has(f.key)
          const hint = tmplText(f, 'hint', lang)
          const label = tmplText(f, 'label', lang) || f.key
          const wide = f.type === 'text' && f.multiline
          return (
            <div key={f.key} className={wide ? 'tpl-field-wide' : 'tpl-field'}>
              <Field label={label + (f.required ? ' *' : '')} hint={hint || undefined} help={f.help}>
                <TemplateField
                  field={f}
                  value={getVal(f)}
                  dynamicData={dynamicData}
                  disabled={ro || savingKey === f.key}
                  lang={lang}
                  onCommit={(v) => commit(f, v)}
                />
              </Field>
            </div>
          )
        })}
      </div>
    </div>
  )
}
