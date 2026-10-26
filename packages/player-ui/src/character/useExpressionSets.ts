import { useCallback, useEffect, useState } from 'react'
import { apiGet } from '../api'
import { useI18n } from '../I18nProvider'

interface Option { value: string; label: string }
interface OptionsResponse { options: Option[]; automatic_set: string; selected_set: string; error?: string }

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
        setOptions([{ value: '', label: `${t('Automatic')} (${d.automatic_set})` }, ...d.options])
        setError(d.error || '')
      })
      .catch(e => { if (alive) { setOptions([]); setError((e as Error).message) } })
    return () => { alive = false }
  }, [character, revision, reload, t])
  return { options, error, refresh }
}
