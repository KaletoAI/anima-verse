import { useCallback, useEffect, useMemo, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPut, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { Field } from '../../components/Field'
import { loadCharacters } from '../../lib/refs'

/**
 * Per-character image-generation overrides (Characters → Image):
 *  - Render match: a workflow glob (e.g. "Qwen*"). The backend resolves it to
 *    a concrete workflow at render time, picking among matches by endpoint
 *    availability — independent of the global fallback. A model picker is
 *    intentionally absent (the model comes from the workflow).
 *  - LoRA override: LoRAs always applied for this character.
 * Backed by /characters/{name}/outfit-imagegen (GET/PUT) plus the workflow
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

export function ImageOverrides({ character }: { character: string }) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [pattern, setPattern] = useState('')
  const [loras, setLoras] = useState<Lora[]>([])
  const [workflows, setWorkflows] = useState<string[]>([])
  const [availableLoras, setAvailableLoras] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [addName, setAddName] = useState('')
  // Per-slot prompt + LoRA overrides (Image Appearance).
  const [slots, setSlots] = useState<Record<string, SlotEntry>>({})
  const [slotsSaving, setSlotsSaving] = useState(false)
  // Gallery access: other characters allowed to browse this gallery in /play.
  const [viewers, setViewers] = useState<string[]>([])
  const [roster, setRoster] = useState<string[]>([])
  const [viewersSaving, setViewersSaving] = useState(false)

  // Persist the full override ({workflow pattern, loras}); model is dropped.
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
        const [ovr, opts, loraOpts, slotResp, cfgResp, rosterData] = await Promise.all([
          apiGet<{ workflow?: string; loras?: Lora[] }>(
            `/characters/${encodeURIComponent(character)}/outfit-imagegen`,
          ),
          apiGet<{ options?: Array<{ type?: string; name?: string }> }>('/world/imagegen-options'),
          apiGet<{ loras?: string[] }>(
            `/characters/outfit-lora-options?character_name=${encodeURIComponent(character)}`,
          ),
          apiGet<{ slots?: Record<string, SlotEntry> }>(
            `/characters/${encodeURIComponent(character)}/slot-overrides`,
          ),
          apiGet<{ config?: Record<string, unknown> }>(
            `/characters/${encodeURIComponent(character)}/config`,
          ),
          loadCharacters(),
        ])
        if (cancelled) return
        setPattern(ovr.workflow || '')
        setLoras(Array.isArray(ovr.loras) ? ovr.loras : [])
        setWorkflows(
          (opts.options || [])
            .filter((o) => o.type === 'workflow' && o.name)
            .map((o) => o.name as string),
        )
        setAvailableLoras((loraOpts.loras || []).filter((l) => l && l !== 'None'))
        setSlots(slotResp.slots || {})
        const gv = (cfgResp.config || {}).gallery_allowed_viewers
        setViewers(Array.isArray(gv) ? gv.map((x) => String(x)).filter(Boolean) : [])
        setRoster(rosterData.map((c) => c.name).filter((n) => n && n !== character))
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

  const matching = useMemo(() => {
    const p = pattern.trim()
    if (!p) return []
    const re = globToRegex(p)
    return workflows.filter((w) => re.test(w))
  }, [pattern, workflows])

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

  // Persist the viewer list immediately (config bulk-update).
  const setViewersAndSave = useCallback(
    async (next: string[]) => {
      setViewers(next)
      setViewersSaving(true)
      try {
        await apiPost(`/characters/${encodeURIComponent(character)}/config`, {
          fields: { gallery_allowed_viewers: next },
        })
        toast(t('Saved'))
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      } finally {
        setViewersSaving(false)
      }
    },
    [character, t, toast],
  )


  if (loading) return <div className="ga-loading">{t('Loading…')}</div>

  return (
    <div className="ga-form">
      <div className="ga-fieldset">
        <div className="ga-fieldset-title">{t('Render match')}</div>
        <div className="ga-form-row">
          <Field
            label={t('Workflow pattern (glob)')}
            hint={t('e.g. "Qwen*" — matched against workflow names; the backend picks an available match at render time. Empty = global default.')}
          >
            <input
              className="ga-input"
              value={pattern}
              placeholder="Qwen*"
              disabled={saving}
              onChange={(e) => setPattern(e.target.value)}
              onBlur={() => persist({ pattern, loras })}
            />
          </Field>
          <Field label={t('Currently matches')} hint={t('Loaded workflows matching the pattern right now.')}>
            <div className="ga-img-matches">
              {pattern.trim() === '' ? (
                <span className="ga-sched-muted">{t('— global default —')}</span>
              ) : matching.length === 0 ? (
                <span className="ga-img-nomatch">{t('no workflow matches')}</span>
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
        {workflows.length > 0 ? (
          <p className="ga-sched-muted" style={{ margin: '2px 0 0' }}>
            {t('Available workflows:')} {workflows.join(', ')}
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
          {t('Per slot: the prompt is added to the image prompt when that slot is empty and uncovered; the LoRA is merged into a free workflow slot.')}
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

      <div className="ga-fieldset">
        <div className="ga-fieldset-title">{t('Gallery access')}</div>
        <p className="ga-sched-muted" style={{ margin: '0 0 8px' }}>
          {t('Other characters allowed to browse this character’s gallery in the player UI. None checked = only the character itself.')}
        </p>
        <div className="ga-gallery-access">
          {roster.length === 0 ? (
            <span className="ga-sched-muted">{t('No other characters.')}</span>
          ) : (
            roster.map((name) => {
              const on = viewers.includes(name)
              return (
                <label key={name} className="ga-check-row">
                  <input
                    type="checkbox"
                    checked={on}
                    disabled={viewersSaving}
                    onChange={() =>
                      setViewersAndSave(
                        on ? viewers.filter((x) => x !== name) : [...viewers, name],
                      )
                    }
                  />
                  <span>{name}</span>
                </label>
              )
            })
          )}
          {/* Stored names that are not (any longer) in the roster — keep them
              visible so they can be unchecked instead of silently dropped. */}
          {viewers
            .filter((v) => !roster.includes(v))
            .map((v) => (
              <label key={v} className="ga-check-row">
                <input
                  type="checkbox"
                  checked
                  disabled={viewersSaving}
                  onChange={() => setViewersAndSave(viewers.filter((x) => x !== v))}
                />
                <span>
                  {v} <span className="ga-sched-muted">({t('not in roster')})</span>
                </span>
              </label>
            ))}
        </div>
      </div>
    </div>
  )
}
