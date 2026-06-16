/**
 * TemplateTab — rendert EINEN Template-Tab (z.B. „General", „Aussehen") generisch
 * als Spalten-Layout. Der Tab besitzt einen Spalten-Bereich (`tab.columns`); jede
 * Section mit `column ∈ tab.columns` landet in der passenden Spalte (sortiert nach
 * column, innerhalb nach row). Kein Hardcoding — alles aus dem Template.
 *
 * Lädt die drei Stores EINMAL (profile/config/status_effects) und speichert jedes
 * Feld in den richtigen (wie TemplateSectionForm, aber für den ganzen Tab).
 *
 * Mehrzeilige Text-Felder mit {tokens} bekommen eine **Live-Vorschau der
 * Ersetzungen** über die Backend-Funktion (POST /characters/{name}/resolve-tokens)
 * — kein Frontend-Nachbau.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { Field } from '../../components/Field'
import { TemplateField, tmplText, type TmplFieldDef, type DynamicData } from './TemplateField'
import type { TmplSection } from './TemplateSectionForm'

const FORCE_READONLY = new Set(['character_name'])

interface TmplTabDef {
  id: string
  label?: string
  label_de?: string
  columns?: number[]
}
interface TmplSectionRaw extends TmplSection {
  special?: unknown
  column?: number
  row?: number
}

function asBoolStore(f: TmplFieldDef) {
  return f.store === 'config' ? 'config' : f.store === 'status_effects' ? 'status_effects' : 'profile'
}

// Mehrzeiliges Text-Feld mit Live-Token-Vorschau (Backend-Resolver).
function PromptField({
  character,
  field,
  value,
  disabled,
  onCommit,
}: {
  character: string
  field: TmplFieldDef
  value: unknown
  disabled?: boolean
  onCommit: (v: string) => void
}) {
  const { t } = useI18n()
  const [local, setLocal] = useState(String(value ?? ''))
  const [resolved, setResolved] = useState('')
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    setLocal(String(value ?? ''))
  }, [value])

  // Debounced Resolve über das Backend, wann immer der Text Tokens enthält.
  useEffect(() => {
    if (timer.current) clearTimeout(timer.current)
    if (!local.includes('{')) {
      setResolved('')
      return
    }
    timer.current = setTimeout(async () => {
      try {
        const r = await apiPost<{ resolved: string }>(
          `/characters/${encodeURIComponent(character)}/resolve-tokens`,
          { text: local, target_key: field.key },
        )
        setResolved(r.resolved && r.resolved !== local ? r.resolved : '')
      } catch {
        setResolved('')
      }
    }, 400)
    return () => {
      if (timer.current) clearTimeout(timer.current)
    }
  }, [local, character, field.key])

  return (
    <>
      <textarea
        className="ga-input"
        rows={4}
        value={local}
        disabled={disabled}
        onChange={(e) => setLocal(e.target.value)}
        onBlur={() => {
          if (local !== String(value ?? '')) onCommit(local)
        }}
      />
      {resolved ? (
        <div className="tpl-token-preview">
          <span className="tpl-token-preview-label">{t('Preview (resolved)')}</span>
          {resolved}
        </div>
      ) : null}
    </>
  )
}

export function TemplateTab({
  character,
  tab,
  sections,
  dynamicData,
  specialSlots,
}: {
  character: string
  tab: TmplTabDef
  sections: TmplSectionRaw[]
  dynamicData: DynamicData
  /** Render-Node je `section.special` (z.B. "placement" → Platzierungs-UI). */
  specialSlots?: Record<string, React.ReactNode>
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
      const hasStat = sections.some((s) => (s.fields || []).some((f) => f.store === 'status_effects'))
      if (hasStat) {
        try {
          const se = await apiGet<{ status_effects: Record<string, unknown> }>(
            `/characters/${encodeURIComponent(character)}/status-effects`,
          )
          setStatus(se.status_effects || {})
        } catch {
          setStatus({})
        }
      }
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setLoaded(true)
    }
  }, [character, sections, t, toast])

  useEffect(() => {
    load()
  }, [load])

  const lookup = (key: string): unknown =>
    key in config ? config[key] : key in status ? status[key] : profile[key]

  const getVal = (f: TmplFieldDef): unknown => {
    const s = asBoolStore(f)
    let v = s === 'config' ? config[f.key] : s === 'status_effects' ? status[f.key] : profile[f.key]
    if ((v === '' || v === null || v === undefined) && f.default !== undefined) v = f.default
    return v ?? ''
  }

  const visible = (vw?: { field: string; values: unknown[] }): boolean => {
    if (!vw || !vw.field) return true
    return (vw.values || []).map(String).includes(String(lookup(vw.field) ?? ''))
  }

  const commit = useCallback(
    async (f: TmplFieldDef, raw: string) => {
      const s = asBoolStore(f)
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

  const editableFields = (s: TmplSectionRaw): TmplFieldDef[] =>
    (s.fields || []).filter((f) => f.editor_visible !== false && !f.source_file && visible(f.visible_when))

  if (!loaded) return <div className="ga-loading">{t('Loading…')}</div>

  const cols = (tab.columns || []).slice().sort((a, b) => a - b)

  const renderField = (f: TmplFieldDef) => {
    const ro = !!f.readonly || FORCE_READONLY.has(f.key)
    const label = (tmplText(f, 'label', lang) || f.key) + (f.required ? ' *' : '')
    const hint = tmplText(f, 'hint', lang)
    const isPrompt = f.type === 'text' && f.multiline
    return (
      <Field key={f.key} label={label} hint={hint || undefined}>
        {isPrompt ? (
          <PromptField
            character={character}
            field={f}
            value={getVal(f)}
            disabled={ro || savingKey === f.key}
            onCommit={(v) => commit(f, v)}
          />
        ) : (
          <TemplateField
            field={f}
            value={getVal(f)}
            dynamicData={dynamicData}
            disabled={ro || savingKey === f.key}
            lang={lang}
            onCommit={(v) => commit(f, v)}
          />
        )}
      </Field>
    )
  }

  return (
    <div className="ga-form tpl-tab-cols">
      {cols.map((col) => {
        const colSections = sections
          .filter((s) => (s.column || 1) === col)
          .filter((s) =>
            s.special ? !!(specialSlots && specialSlots[String(s.special)]) : editableFields(s).length > 0,
          )
          .sort((a, b) => (a.row ?? 0) - (b.row ?? 0))
        return (
          <div key={col} className="tpl-tab-col">
            {colSections.map((s) => (
              <div key={s.id} className="tpl-tab-section">
                <div className="ga-fieldset-title">{tmplText(s, 'label', lang) || s.id}</div>
                {s.special
                  ? specialSlots?.[String(s.special)]
                  : editableFields(s).map(renderField)}
              </div>
            ))}
          </div>
        )
      })}
    </div>
  )
}
