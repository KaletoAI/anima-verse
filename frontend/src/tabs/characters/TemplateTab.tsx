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
import { useHelp } from '../../help/HelpContext'
import { useToast } from '../../lib/Toast'
import { Field } from '../../components/Field'
import { TemplateField, tmplText, type TmplFieldDef, type DynamicData } from './TemplateField'
import type { TmplSection } from './TemplateSectionForm'
import { FieldImage } from './FieldImage'

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

interface TokenChip {
  token: string
  label: string
}

// Sammelt die {token}-Platzhalter, die laut Template auf `targetKey` zielen
// (replacement.target == targetKey, string oder Liste) — quer über ALLE
// Sektionen, da z.B. {gender} aus einer anderen Spalte stammt.
function collectTokens(sections: TmplSectionRaw[], targetKey: string, lang: string): TokenChip[] {
  const out: TokenChip[] = []
  const seen = new Set<string>()
  for (const s of sections) {
    for (const f of s.fields || []) {
      const r = f.replacement as { token?: string; target?: string | string[] } | undefined
      if (!r) continue
      const targets = Array.isArray(r.target) ? r.target : r.target ? [r.target] : []
      if (!targets.includes(targetKey)) continue
      const tok = String(r.token || f.key)
      if (!tok || seen.has(tok)) continue
      seen.add(tok)
      out.push({ token: tok, label: tmplText(f, 'label', lang) || tok })
    }
  }
  return out
}

// Mehrzeiliges Text-Feld mit Live-Token-Vorschau (Backend-Resolver) und
// klickbaren Token-Chips, die {placeholder} an der Cursor-Position einfügen.
function PromptField({
  character,
  field,
  value,
  disabled,
  tokens,
  onCommit,
}: {
  character: string
  field: TmplFieldDef
  value: unknown
  disabled?: boolean
  tokens: TokenChip[]
  onCommit: (v: string) => void
}) {
  const { t } = useI18n()
  const { setHelp } = useHelp()
  const [local, setLocal] = useState(String(value ?? ''))
  const [resolved, setResolved] = useState('')
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const taRef = useRef<HTMLTextAreaElement>(null)
  useEffect(() => {
    setLocal(String(value ?? ''))
  }, [value])

  // Text an der aktuellen Cursor-Position einfügen. Liest den LIVE-Wert aus dem
  // DOM (ta.value) statt aus dem state-`local` — so funktioniert der Aufruf aus
  // dem Help-Panel auch nach dem Tippen korrekt (kein stale-Closure).
  const insertText = (ins: string) => {
    const ta = taRef.current
    if (!ta) {
      setLocal((v) => v + ins)
      return
    }
    const cur = ta.value
    const s = ta.selectionStart ?? cur.length
    const e = ta.selectionEnd ?? cur.length
    const next = cur.slice(0, s) + ins + cur.slice(e)
    setLocal(next)
    requestAnimationFrame(() => {
      const el = taRef.current
      if (!el) return
      el.focus()
      const pos = s + ins.length
      el.setSelectionRange(pos, pos)
    })
  }

  // Tokens + Insert-Funktion ans Help-Panel melden (beim Fokus). Topic kommt aus
  // dem Template-help-Key (z.B. image_prompt fuer appearance), sonst kein Topic.
  const announceHelp = () => setHelp(
    typeof field.help === 'string' ? field.help : null,
    {
      items: tokens.map((tk) => ({ code: `{${tk.token}}`, text: tk.label, insert: `{${tk.token}}` })),
      insert: insertText,
    },
  )

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
      {/* Insert-Tokens sind ins Help-Panel verlagert (Fokus → Panel zeigt sie
          mit Cursor-Insert). Der Textarea bekommt dafuer den vollen Platz. */}
      <textarea
        ref={taRef}
        className="ga-input"
        rows={12}
        value={local}
        disabled={disabled}
        onFocus={announceHelp}
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
  excludeKeys,
  imageBeside,
}: {
  character: string
  tab: TmplTabDef
  sections: TmplSectionRaw[]
  dynamicData: DynamicData
  /** Render-Node je `section.special` (z.B. "placement" → Platzierungs-UI). */
  specialSlots?: Record<string, React.ReactNode>
  /** Policy-Ausschluss einzelner Felder (z.B. Social-Zahlen im /play). */
  excludeKeys?: string[]
  /** Prompt-Felder mit Bild zweispaltig rendern (Prompt links, Bild rechts)
   *  statt Bild unter dem Prompt — genutzt vom /play-Avatar-Panel. */
  imageBeside?: boolean
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

  const ex = new Set(excludeKeys || [])
  const editableFields = (s: TmplSectionRaw): TmplFieldDef[] =>
    (s.fields || []).filter(
      (f) => f.editor_visible !== false && !f.source_file && !ex.has(f.key) && visible(f.visible_when),
    )

  if (!loaded) return <div className="ga-loading">{t('Loading…')}</div>

  const cols = (tab.columns || []).slice().sort((a, b) => a - b)

  const renderField = (f: TmplFieldDef) => {
    const ro = !!f.readonly || FORCE_READONLY.has(f.key)
    const label = (tmplText(f, 'label', lang) || f.key) + (f.required ? ' *' : '')
    const hint = tmplText(f, 'hint', lang)
    const isPrompt = f.type === 'text' && f.multiline
    const imagePreview = typeof f.image_preview === 'string' ? f.image_preview : ''
    const input = isPrompt ? (
      <PromptField
        character={character}
        field={f}
        value={getVal(f)}
        disabled={ro || savingKey === f.key}
        tokens={collectTokens(sections, f.key, lang)}
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
    )
    // Side-by-side (Avatar-Panel): Prompt + Chips + Preview links, Bild rechts.
    if (imageBeside && isPrompt && imagePreview) {
      return (
        <div key={f.key} className="tpl-prompt-beside">
          <div className="tpl-prompt-beside-text">
            <Field label={label} hint={hint || undefined} help={typeof f.help === 'string' ? f.help : undefined}>
              {input}
            </Field>
          </div>
          <div className="tpl-prompt-beside-image">
            <FieldImage character={character} kind={imagePreview} />
          </div>
        </div>
      )
    }
    return (
      <div key={f.key}>
        <Field label={label} hint={hint || undefined} help={typeof f.help === 'string' ? f.help : undefined}>
          {input}
        </Field>
        {imagePreview ? <FieldImage character={character} kind={imagePreview} /> : null}
      </div>
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
