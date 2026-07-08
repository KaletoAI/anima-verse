import { useCallback, useEffect, useMemo, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPut } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { Field } from '../../components/Field'

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
  const { t } = useI18n()
  const { toast } = useToast()
  const [pattern, setPattern] = useState('')
  const [loras, setLoras] = useState<Lora[]>([])
  const [backends, setBackends] = useState<string[]>([])  // image-backend names (match target)
  const [outfitDefault, setOutfitDefault] = useState('')  // global outfit default (match spec)
  const [availableLoras, setAvailableLoras] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [addName, setAddName] = useState('')

  // The server resolves the LoRA list from the SAVED match pattern (backend
  // lora_filter + library, endpoint-filtered) — so the "Add LoRA" choices
  // must be refetched after every pattern save, not loaded just once.
  const refreshLoraOptions = useCallback(async () => {
    try {
      const loraOpts = await apiGet<{ loras?: string[] }>(
        `/characters/outfit-lora-options?character_name=${encodeURIComponent(character)}`,
      )
      setAvailableLoras((loraOpts.loras || []).filter((l) => l && l !== 'None'))
    } catch { /* keep the previous list */ }
  }, [character])

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
        // A changed match may resolve to another backend → reload the
        // available LoRAs for the Add-LoRA select.
        void refreshLoraOptions()
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      } finally {
        setSaving(false)
      }
    },
    [character, t, toast, refreshLoraOptions],
  )

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    ;(async () => {
      try {
        const [ovr, opts, loraOpts] = await Promise.all([
          apiGet<{ workflow?: string; loras?: Lora[] }>(
            `/characters/${encodeURIComponent(character)}/outfit-imagegen`,
          ),
          apiGet<{ options?: Array<{ name?: string; category?: string }>; outfit_imagegen_default?: string }>('/world/imagegen-options'),
          apiGet<{ loras?: string[] }>(
            `/characters/outfit-lora-options?character_name=${encodeURIComponent(character)}`,
          )
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

  // Beim Fokus eines Slot-Fragments: Topic + Appearance-Tokens (mit Insert) ans
  // Help-Panel melden — Parität zum Appearance-Prompt.

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

    </div>
  )
}
