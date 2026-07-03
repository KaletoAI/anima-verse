import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPut } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { Field } from '../../components/Field'
import { useHelp } from '../../help/HelpContext'
import { collectTokens, type TmplSectionRaw } from './TemplateTab'

/**
 * Per-character image-generation overrides (Characters → Image):
 *  - Backend match: a glob over image-backend names (e.g. "Flux*"). The server
 *    resolves it to a concrete backend at render time, picking among matches by
 *    availability — independent of the global fallback. A model picker is
 *    intentionally absent (the model comes from the backend).
 *  - LoRA override: LoRAs always applied for this character.
 * Backed by /characters/{name}/outfit-imagegen (GET/PUT) plus the backend
 * list (/world/imagegen-options) and available LoRAs (/outfit-lora-options).
 */

interface Lora {
  name: string
  strength: number
}

interface SlotEntry {
  prompt: string
  lora: { name: string; strength: number }
}

// Body slots in editor order; the second column starts at 'underwear_top'.
const SLOT_ORDER = [
  'head',
  'neck',
  'outer',
  'top',
  'underwear_top',
  'bottom',
  'underwear_bottom',
  'legs',
  'feet',
] as const
const SLOT_LABELS: Record<string, string> = {
  head: 'Head',
  neck: 'Neck',
  outer: 'Outerwear',
  top: 'Top',
  underwear_top: 'Underwear (top)',
  bottom: 'Bottom',
  underwear_bottom: 'Underwear (bottom)',
  legs: 'Legs',
  feet: 'Feet',
}

// Convert a shell-style glob (only '*' wildcard) to a case-insensitive regex.
function globToRegex(glob: string): RegExp {
  const escaped = glob.replace(/[.+?^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*')
  return new RegExp('^' + escaped + '$', 'i')
}

// Make a match spec readable: "backend:LocalAI-Flux" -> "LocalAI-Flux".
function formatMatchSpec(spec: string): string {
  const s = (spec || '').trim()
  if (s.startsWith('backend:')) return s.slice(8)
  return s
}

export function ImageOverrides({ character }: { character: string }) {
  const { t, lang } = useI18n()
  const { toast } = useToast()
  const { setHelp } = useHelp()
  // Appearance-{token}-Platzhalter (wie im Appearance-Prompt) + zuletzt
  // fokussiertes Slot-Input, damit das Help-Panel an die Cursor-Position einfügt.
  const [appearanceTokens, setAppearanceTokens] = useState<{ token: string; label: string }[]>([])
  const slotElRef = useRef<{ slot: string; el: HTMLInputElement } | null>(null)
  const [pattern, setPattern] = useState('')
  const [loras, setLoras] = useState<Lora[]>([])
  const [backends, setBackends] = useState<string[]>([])  // image-backend names (match target)
  const [outfitDefault, setOutfitDefault] = useState('')  // global outfit default (match spec)
  const [availableLoras, setAvailableLoras] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [addName, setAddName] = useState('')
  // Per-slot prompt + LoRA overrides (Image Appearance).
  const [slots, setSlots] = useState<Record<string, SlotEntry>>({})
  const [slotsSaving, setSlotsSaving] = useState(false)

  // Persist the full override ({backend match pattern, loras}); model is dropped.
  // The server field for the match pattern is still named "workflow".
  const persist = useCallback(
    async (next: { pattern: string; loras: Lora[] }) => {
      setSaving(true)
      try {
        await apiPut(`/characters/${encodeURIComponent(character)}/outfit-imagegen`, {
          workflow: next.pattern.trim(),
          loras: next.loras,
        })
        toast(t('Saved'))
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      } finally {
        setSaving(false)
      }
    },
    [character, t, toast],
  )

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    ;(async () => {
      try {
        const [ovr, opts, loraOpts, slotResp] = await Promise.all([
          apiGet<{ workflow?: string; loras?: Lora[] }>(
            `/characters/${encodeURIComponent(character)}/outfit-imagegen`,
          ),
          apiGet<{ options?: Array<{ name?: string; category?: string }>; outfit_imagegen_default?: string }>('/world/imagegen-options'),
          apiGet<{ loras?: string[] }>(
            `/characters/outfit-lora-options?character_name=${encodeURIComponent(character)}`,
          ),
          apiGet<{ slots?: Record<string, SlotEntry> }>(
            `/characters/${encodeURIComponent(character)}/slot-overrides`,
          ),
        ])
        if (cancelled) return
        setPattern(ovr.workflow || '')
        setLoras(Array.isArray(ovr.loras) ? ovr.loras : [])
        // Inpaint targets (category=inpaint) are only for Map-Fit/Match-Edges,
        // not for a character's normal render matching.
        setBackends(
          (opts.options || [])
            .filter((o) => o.name && o.category !== 'inpaint')
            .map((o) => o.name as string),
        )
        setOutfitDefault(opts.outfit_imagegen_default || '')
        setAvailableLoras((loraOpts.loras || []).filter((l) => l && l !== 'None'))
        setSlots(slotResp.slots || {})
      } catch (e) {
        if (!cancelled) toast(t('Failed to load') + ': ' + (e as Error).message, 'error')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [character, t, toast])

  // Appearance-Tokens des Characters laden (Template → replacement.target ==
  // character_appearance), damit die Slot-Fragmente dieselben {…}-Platzhalter
  // anbieten wie der Appearance-Prompt. Rein optional (Bequemlichkeit).
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const pr = await apiGet<{ profile?: { template?: string } }>(
          `/characters/${encodeURIComponent(character)}/profile`,
        )
        const tmplId = String(pr.profile?.template || '')
        if (!tmplId) return
        const tmpl = await apiGet<{ sections?: TmplSectionRaw[] }>(`/templates/${encodeURIComponent(tmplId)}`)
        if (cancelled) return
        setAppearanceTokens(collectTokens(tmpl.sections || [], 'character_appearance', lang))
      } catch {
        /* tokens are a convenience — ignore load errors */
      }
    })()
    return () => {
      cancelled = true
    }
  }, [character, lang])

  const matching = useMemo(() => {
    const p = pattern.trim()
    if (!p) return []
    // Glob over image-backend names (an optional "backend:" prefix is allowed) —
    // same resolution as resolve_imagegen_target on the server.
    const re = globToRegex(p.replace(/^backend:/i, '').trim())
    return backends.filter((b) => re.test(b))
  }, [pattern, backends])

  const setLorasAndSave = useCallback(
    (next: Lora[]) => {
      setLoras(next)
      persist({ pattern, loras: next })
    },
    [pattern, persist],
  )

  const updateSlot = useCallback((slot: string, patch: Partial<SlotEntry>) => {
    setSlots((prev) => {
      const cur = prev[slot] || { prompt: '', lora: { name: '', strength: 1 } }
      return { ...prev, [slot]: { ...cur, ...patch } }
    })
  }, [])

  const updateSlotLora = useCallback((slot: string, patch: Partial<SlotEntry['lora']>) => {
    setSlots((prev) => {
      const cur = prev[slot] || { prompt: '', lora: { name: '', strength: 1 } }
      return { ...prev, [slot]: { ...cur, lora: { ...cur.lora, ...patch } } }
    })
  }, [])

  // {token} an der Cursor-Position des zuletzt fokussierten Slot-Inputs einfügen.
  // Liest den LIVE-Wert/Caret aus dem DOM (Selektion bleibt nach Blur erhalten),
  // damit der Klick auf den „+"-Button im Help-Panel trotzdem korrekt einfügt.
  const insertIntoFocusedSlot = useCallback((ins: string) => {
    const cur = slotElRef.current
    if (!cur) return
    const { slot, el } = cur
    const v = el.value
    const s = el.selectionStart ?? v.length
    const e = el.selectionEnd ?? v.length
    const next = v.slice(0, s) + ins + v.slice(e)
    updateSlot(slot, { prompt: next })
    requestAnimationFrame(() => {
      el.focus()
      const pos = s + ins.length
      el.setSelectionRange(pos, pos)
    })
  }, [updateSlot])

  // Beim Fokus eines Slot-Fragments: Topic + Appearance-Tokens (mit Insert) ans
  // Help-Panel melden — Parität zum Appearance-Prompt.
  const announceSlotHelp = useCallback((slot: string, el: HTMLInputElement) => {
    slotElRef.current = { slot, el }
    setHelp('image_prompt', {
      items: appearanceTokens.map((tk) => ({ code: `{${tk.token}}`, text: tk.label, insert: `{${tk.token}}` })),
      insert: insertIntoFocusedSlot,
    })
  }, [appearanceTokens, setHelp, insertIntoFocusedSlot])

  const saveSlots = useCallback(async () => {
    setSlotsSaving(true)
    try {
      await apiPut(`/characters/${encodeURIComponent(character)}/slot-overrides`, { slots })
      toast(t('Saved'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setSlotsSaving(false)
    }
  }, [character, slots, t, toast])


  if (loading) return <div className="ga-loading">{t('Loading…')}</div>

  return (
    <div className="ga-form">
      <div className="ga-fieldset">
        <div className="ga-fieldset-title">{t('Render match')}</div>
        <div className="ga-form-row">
          <Field
            label={t('Backend match (glob)')}
            help="imagegen_target"
            hint={t('e.g. "Flux*" or an exact backend name. Matched against image-backend names; the server picks an available match at render time. Empty = global default.')}
          >
            <input
              className="ga-input"
              value={pattern}
              placeholder="Flux*"
              disabled={saving}
              onChange={(e) => setPattern(e.target.value)}
              onBlur={() => persist({ pattern, loras })}
            />
          </Field>
          <Field label={t('Currently matches')} hint={t('Backends matching the pattern right now.')}>
            <div className="ga-img-matches">
              {pattern.trim() === '' ? (
                <span className="ga-sched-muted">
                  {t('— global default —')}
                  {outfitDefault ? (
                    <span className="ga-img-match-chip" style={{ marginLeft: 6 }}>{formatMatchSpec(outfitDefault)}</span>
                  ) : null}
                </span>
              ) : matching.length === 0 ? (
                <span className="ga-img-nomatch">{t('no match')}</span>
              ) : (
                matching.map((w) => (
                  <span key={w} className="ga-img-match-chip">
                    {w}
                  </span>
                ))
              )}
            </div>
          </Field>
        </div>
        {backends.length > 0 ? (
          <p className="ga-sched-muted" style={{ margin: '2px 0 0' }}>
            {t('Available targets:')} {backends.join(', ')}
          </p>
        ) : null}
      </div>

      <div className="ga-fieldset">
        <div className="ga-fieldset-title">{t('LoRA override')}</div>
        {loras.length === 0 ? (
          <div className="ga-placeholder">{t('No LoRAs forced for this character.')}</div>
        ) : (
          loras.map((l, i) => (
            <div className="ga-form-row" key={i}>
              <Field label={i === 0 ? t('LoRA') : ''}>
                <input className="ga-input" value={l.name} disabled readOnly />
              </Field>
              <Field label={i === 0 ? t('Strength') : ''} compact>
                <input
                  className="ga-input"
                  type="number"
                  step="0.05"
                  style={{ width: 90 }}
                  value={l.strength}
                  onChange={(e) => {
                    const strength = parseFloat(e.target.value)
                    setLoras((prev) =>
                      prev.map((x, j) => (j === i ? { ...x, strength: isNaN(strength) ? 1 : strength } : x)),
                    )
                  }}
                  onBlur={() => persist({ pattern, loras })}
                />
              </Field>
              <Field label={i === 0 ? '' : ''} compact>
                <button
                  type="button"
                  className="ga-btn ga-btn-sm ga-btn-danger"
                  onClick={() => setLorasAndSave(loras.filter((_, j) => j !== i))}
                >
                  {t('Remove')}
                </button>
              </Field>
            </div>
          ))
        )}
        <div className="ga-form-row" style={{ marginTop: 6, gap: 8 }}>
          <Field label={t('Add LoRA')}>
            <select className="ga-input" value={addName} onChange={(e) => setAddName(e.target.value)}>
              <option value="">— {t('pick a LoRA')} —</option>
              {availableLoras
                .filter((l) => !loras.some((x) => x.name === l))
                .map((l) => (
                  <option key={l} value={l}>
                    {l}
                  </option>
                ))}
            </select>
          </Field>
          <div style={{ display: 'flex', alignItems: 'flex-end' }}>
            <button
              type="button"
              className="ga-btn ga-btn-sm"
              disabled={!addName}
              onClick={() => {
                if (!addName) return
                setLorasAndSave([...loras, { name: addName, strength: 1 }])
                setAddName('')
              }}
            >
              {t('Add')}
            </button>
          </div>
        </div>
      </div>

      <div className="ga-fieldset">
        <div className="ga-fieldset-title">{t('Image Appearance (slot overrides)')}</div>
        <p className="ga-sched-muted" style={{ margin: '0 0 8px' }}>
          {t('Per slot: the prompt is added to the image prompt when that slot is empty and uncovered; the LoRA is merged into a free LoRA slot.')}
        </p>
        <div className="ga-img-slotgrid">
          {[SLOT_ORDER.slice(0, 4), SLOT_ORDER.slice(4)].map((col, ci) => (
            <div key={ci}>
              {col.map((slot) => {
                const entry = slots[slot] || { prompt: '', lora: { name: '', strength: 1 } }
                const loraName = entry.lora?.name || ''
                return (
                  <div key={slot} className="ga-img-slotrow">
                    <div className="ga-img-slotlabel">{t(SLOT_LABELS[slot])}</div>
                    <input
                      className="ga-input"
                      placeholder={t('Prompt fragment (e.g. "bare feet")')}
                      value={entry.prompt || ''}
                      onFocus={(e) => announceSlotHelp(slot, e.currentTarget)}
                      onChange={(e) => updateSlot(slot, { prompt: e.target.value })}
                    />
                    <div className="ga-img-slotlora">
                      <span className="ga-sched-muted">LoRA</span>
                      <select
                        className="ga-input"
                        value={loraName}
                        onChange={(e) => updateSlotLora(slot, { name: e.target.value })}
                      >
                        <option value="">— {t('none')} —</option>
                        {loraName && !availableLoras.includes(loraName) ? (
                          <option value={loraName}>
                            {loraName} ({t('unavailable')})
                          </option>
                        ) : null}
                        {availableLoras.map((l) => (
                          <option key={l} value={l}>
                            {l}
                          </option>
                        ))}
                      </select>
                      <input
                        className="ga-input"
                        type="number"
                        step="0.05"
                        min="-2"
                        max="2"
                        style={{ width: 64 }}
                        value={entry.lora?.strength ?? 1}
                        onChange={(e) =>
                          updateSlotLora(slot, { strength: parseFloat(e.target.value) || 1 })
                        }
                      />
                    </div>
                  </div>
                )
              })}
            </div>
          ))}
        </div>
        <div className="ga-form-row" style={{ marginTop: 8 }}>
          <button
            type="button"
            className="ga-btn ga-btn-sm ga-btn-primary"
            disabled={slotsSaving}
            onClick={saveSlots}
          >
            {slotsSaving ? t('Saving…') : t('Save appearance')}
          </button>
        </div>
      </div>
    </div>
  )
}
