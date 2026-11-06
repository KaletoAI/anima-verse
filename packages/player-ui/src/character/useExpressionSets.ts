import { useCallback, useEffect, useState } from 'react'
import { apiGet } from '../api'
import { useI18n } from '../I18nProvider'

interface Option { value: string; label: string }
interface SetOption extends Option { lora?: string; lora_strength?: number; lora_on_backend?: boolean | null }
interface OptionsResponse { options: SetOption[]; lora_backend?: string; automatic_set: string; selected_set: string; error?: string }

/** Both generic form hosts use the same player-readable, character-scoped source. */
export function useExpressionSets(character: string, revision = 0) {
  const { t } = useI18n()
  const [options, setOptions] = useState<Option[]>([])
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  const refresh = useCallback(() => setReload(v => v + 1), [])
  useEffect(() => {
    let alive = true
    if (!character) { setOptions([]); setError(''); return }
    setError('')
    apiGet<OptionsResponse>(`/characters/${encodeURIComponent(character)}/expression-options`)
      .then(d => {
        if (!alive) return
        // The set's LoRA is part of the label, so it shows right after the
        // pick — with whether this character's expression backend has it.
        const withLora = (o: SetOption, label: string) => {
          if (!o.lora) return label
          const fit = o.lora_on_backend === true ? ' ✓'
            : o.lora_on_backend === false ? ` ⚠ ${t('not on')} ${d.lora_backend}` : ''
          return `${label} · LoRA ${o.lora} (${o.lora_strength ?? 1})${fit}`
        }
        const auto = d.options.find(o => o.value === d.automatic_set)
        setOptions([
          { value: '', label: withLora(auto || { value: '', label: '' }, `${t('Automatic')} (${d.automatic_set})`) },
          ...d.options.map(o => ({ value: o.value, label: withLora(o, o.label) })),
        ])
        setError(d.error || '')
      })
      .catch(e => { if (alive) { setOptions([]); setError((e as Error).message) } })
    return () => { alive = false }
  }, [character, revision, reload, t])
  return { options, error, refresh }
}
