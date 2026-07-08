import { useCallback, useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { PromptPreview } from './PromptPreview'

/** Generic body-slot editor — renders whatever the character's species
 * package declares (attributes + options); saves per attribute on change.
 * Invisible without species packages (no slots -> renders nothing).
 * Lives on the Appearance tab (template section special "body_editor"). */

export interface BodySlotAttr {
  key: string
  type: string
  options: string[]
  allow_custom: boolean
  label: string
  value: string
}
export interface BodySlot {
  id: string
  package_id: string
  covered_by: string[]
  exposed: boolean
  attributes: BodySlotAttr[]
}

export function BodyEditor({ character }: { character: string }) {
  const { t } = useI18n()
  const [slots, setSlots] = useState<BodySlot[]>([])
  // LoRA names for lora_select attributes — resolved against the character's
  // "Backend match (glob)" (same source as the outfit/variant LoRA picker).
  const [loras, setLoras] = useState<string[]>([])
  const [previewKey, setPreviewKey] = useState(0)
  const enc = encodeURIComponent(character)

  const load = useCallback(async () => {
    try {
      const d = await apiGet<{ slots?: BodySlot[] }>(`/characters/${enc}/body-slots`)
      setSlots(d.slots || [])
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
  useEffect(() => { load() }, [load])

  const save = useCallback(async (slotId: string, key: string, value: string) => {
    setSlots((prev) => prev.map((s) => s.id === slotId
      ? { ...s, attributes: s.attributes.map((a) => a.key === key ? { ...a, value } : a) }
      : s))
    try {
      await apiPost(`/characters/${enc}/body-slots/${encodeURIComponent(slotId)}`,
        { values: { [key]: value } })
      setPreviewKey((k) => k + 1)
    } catch { load() }
  }, [enc, load])

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
                <select key={a.key} className="ga-input" value={a.value} title={a.label}
                  style={{ fontSize: '0.82em', padding: '2px 6px', minWidth: 120 }}
                  onChange={(e) => save(s.id, a.key, e.target.value)}>
                  <option value="">{a.label}…</option>
                  {loras.map((n) => <option key={n} value={n}>{n}</option>)}
                  {a.value && !loras.includes(a.value) && (
                    <option value={a.value}>{a.value}</option>
                  )}
                </select>
              )
            }
            if (a.options.length > 0 && !a.allow_custom) {
              return (
                <select key={a.key} className="ga-input" value={a.value} title={a.label}
                  style={{ fontSize: '0.82em', padding: '2px 6px', minWidth: 100 }}
                  onChange={(e) => save(s.id, a.key, e.target.value)}>
                  <option value="">{a.label}…</option>
                  {a.options.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
              )
            }
            return (
              <input key={a.key} className="ga-input" value={a.value} title={a.label}
                placeholder={a.label} list={a.options.length ? `body-${s.id}-${a.key}` : undefined}
                style={{ fontSize: '0.82em', padding: '2px 6px', width: 120 }}
                onChange={(e) => save(s.id, a.key, e.target.value)} />
            )
          })}
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
