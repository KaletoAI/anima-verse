import { useCallback, useEffect, useRef, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { PromptPreview } from './PromptPreview'

/** Generic body-slot editor — renders whatever the character's species
 * package declares (attributes + options).
 * Invisible without species packages (no slots -> renders nothing).
 * Lives on the Appearance tab (template section special "body_editor").
 *
 * Given `queueBody`, an edited attribute is REMEMBERED for the container's one
 * Save instead of being POSTed on the spot — the character sheet in the
 * Game-Admin owns a change buffer. Without it every change is its own request,
 * which is what the /play avatar panel still wants: it has no Save button to
 * collect into. */

export interface BodySlotAttr {
  key: string
  type: string
  options: string[]
  allow_custom: boolean
  label: string
  value: string
  // lora_select only: companion strength value (<key>_strength)
  strength?: number
}
export interface BodySlot {
  id: string
  package_id: string
  covered_by: string[]
  exposed: boolean
  attributes: BodySlotAttr[]
  // Slots with an exposed prompt: per-character override + the package
  // default (shown greyed as placeholder, never materialized).
  exposed_prompt?: string
  exposed_default?: string
  // Emit the exposed text even when attribute values are empty
  // (empty placeholders vanish: 'exposed {size} breasts' -> 'exposed breasts').
  exposed_always?: boolean
}

/** One attribute written into a slot — the same mapping for an optimistic
 *  update and for laying the container's draft over what the GET returned. */
function withValue(s: BodySlot, key: string, value: string): BodySlot {
  if (key === 'exposed_prompt') return { ...s, exposed_prompt: value }
  if (key === 'exposed_always') return { ...s, exposed_always: value === 'true' }
  return {
    ...s,
    attributes: s.attributes.map((a) =>
      a.key === key ? { ...a, value }
      : key === `${a.key}_strength` ? { ...a, strength: parseFloat(value) || 1 }
      : a),
  }
}

export function BodyEditor({ character, queueBody, draftFor, discardSignal }: {
  character: string
  /** Remember one slot's values instead of POSTing them. */
  queueBody?: (slotId: string, patch: Record<string, unknown>) => void
  /** What the container has buffered for a slot, laid over the loaded values
   *  so re-opening the tab shows the unsaved edits. */
  draftFor?: (slotId: string) => Record<string, unknown>
  /** Bumped by the container's Discard — the slots are re-read. */
  discardSignal?: number
}) {
  const { t } = useI18n()
  const [slots, setSlots] = useState<BodySlot[]>([])
  // LoRA names for lora_select attributes — resolved against the character's
  // "Backend match (glob)" (same source as the outfit/variant LoRA picker).
  const [loras, setLoras] = useState<string[]>([])
  const [previewKey, setPreviewKey] = useState(0)
  const enc = encodeURIComponent(character)
  /** Read while loading without making the loader depend on the draft. */
  const draftRef = useRef(draftFor)
  draftRef.current = draftFor

  const load = useCallback(async () => {
    try {
      const d = await apiGet<{ slots?: BodySlot[] }>(`/characters/${enc}/body-slots`)
      const df = draftRef.current
      setSlots((d.slots || []).map((s) => {
        let out = s
        for (const [k, v] of Object.entries(df ? df(s.id) : {})) out = withValue(out, k, String(v))
        return out
      }))
      if ((d.slots || []).some((s) => s.attributes.some((a) => a.type === 'lora_select'))) {
        try {
          const lr = await apiGet<{ loras?: Array<{ name: string } | string> }>(
            `/characters/outfit-lora-options?character_name=${enc}`,
          )
          setLoras((lr.loras || []).map((l) => (typeof l === 'string' ? l : l.name)).filter(Boolean))
        } catch { setLoras([]) }
      }
    } catch { setSlots([]) }
  }, [enc])
  // Runs once on mount and again on every Discard — by which time the buffer
  // is empty, so the reload lands on the stored values.
  useEffect(() => { load() }, [load, discardSignal])

  const commit = useCallback((slotId: string, key: string, value: string) => {
    setSlots((prev) => prev.map((s) => (s.id === slotId ? withValue(s, key, value) : s)))
    if (queueBody) {
      // The prompt preview stays on the stored truth until the Save; it is
      // rendered by the server, which has not seen this value yet.
      queueBody(slotId, { [key]: value })
      return
    }
    void (async () => {
      try {
        await apiPost(`/characters/${enc}/body-slots/${encodeURIComponent(slotId)}`,
          { values: { [key]: value } })
        setPreviewKey((k) => k + 1)
      } catch { load() }
    })()
  }, [enc, load, queueBody])

  if (!slots.length) return null
  return (
    <div className="ga-form" style={{ gap: 6 }}>
      {slots.map((s) => (
        <div key={s.id} style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.82em', minWidth: 80, opacity: 0.75 }}
            title={s.covered_by.length ? `${t('Covered by')}: ${s.covered_by.join(', ')}` : undefined}>
            {s.id.replace(/_/g, ' ')}
          </span>
          {s.attributes.map((a) => {
            if (a.type === 'lora_select') {
              return (
                <span key={a.key} style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
                  <select className="ga-input" value={a.value} title={a.label}
                    style={{ fontSize: '0.82em', padding: '2px 6px', minWidth: 120 }}
                    onChange={(e) => commit(s.id, a.key, e.target.value)}>
                    <option value="">{a.label}…</option>
                    {loras.map((n) => <option key={n} value={n}>{n}</option>)}
                    {a.value && !loras.includes(a.value) && (
                      <option value={a.value}>{a.value}</option>
                    )}
                  </select>
                  <input className="ga-input" type="number" step="0.05" min="-2" max="2"
                    title={`${a.label} — ${t('strength')}`}
                    style={{ fontSize: '0.82em', padding: '2px 4px', width: 58 }}
                    value={a.strength ?? 1}
                    onChange={(e) => commit(s.id, `${a.key}_strength`, e.target.value)} />
                </span>
              )
            }
            if (a.options.length > 0 && !a.allow_custom) {
              return (
                <select key={a.key} className="ga-input" value={a.value} title={a.label}
                  style={{ fontSize: '0.82em', padding: '2px 6px', minWidth: 100 }}
                  onChange={(e) => commit(s.id, a.key, e.target.value)}>
                  <option value="">{a.label}…</option>
                  {a.options.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
              )
            }
            return (
              <input key={a.key} className="ga-input" value={a.value} title={a.label}
                placeholder={a.label} list={a.options.length ? `body-${s.id}-${a.key}` : undefined}
                style={{ fontSize: '0.82em', padding: '2px 6px', width: 120 }}
                onChange={(e) => commit(s.id, a.key, e.target.value)} />
            )
          })}
          {s.exposed_default !== undefined && (
            <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center', flex: '1 1 150px', minWidth: 140 }}>
              <input className="ga-input" value={s.exposed_prompt || ''}
                placeholder={s.exposed_default}
                title={t('Exposed prompt override — empty = package default (grey)')}
                style={{ fontSize: '0.82em', padding: '2px 6px', flex: 1, minWidth: 0 }}
                onChange={(e) => commit(s.id, 'exposed_prompt', e.target.value)} />
              <input type="checkbox" checked={!!s.exposed_always}
                title={t('Also emit without attribute values (empty placeholders vanish)')}
                onChange={(e) => commit(s.id, 'exposed_always', String(e.target.checked))} />
            </span>
          )}
          {s.attributes.map((a) => a.options.length > 0 && a.allow_custom && a.type !== 'lora_select' ? (
            <datalist key={`dl-${a.key}`} id={`body-${s.id}-${a.key}`}>
              {a.options.map((o) => <option key={o} value={o} />)}
            </datalist>
          ) : null)}
        </div>
      ))}
      <div style={{ marginTop: 8, borderTop: '1px solid rgba(255,255,255,0.12)', paddingTop: 8 }}>
        <PromptPreview character={character} refreshKey={String(previewKey)} />
      </div>
    </div>
  )
}
