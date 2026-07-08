import { useCallback, useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'

/** Effective prompt preview for the admin: how the person description,
 * face prompt and outfit line render RIGHT NOW — body-slot fragments
 * included, coverage applied (a covered slot suppresses its exposed
 * fragment). Refetches whenever `refreshKey` changes (body edits,
 * outfit changes). */
export function PromptPreview({ character, refreshKey = '' }:
    { character: string; refreshKey?: string }) {
  const { t } = useI18n()
  const [data, setData] = useState<{ scene?: string; face?: string; outfit?: string }>({})

  const load = useCallback(async () => {
    try {
      setData(await apiGet(`/characters/${encodeURIComponent(character)}/prompt-preview`))
    } catch { setData({}) }
  }, [character])
  useEffect(() => { load() }, [load, refreshKey])

  const rows: Array<[string, string]> = [
    [t('Scene prompt'), data.scene || ''],
    [t('Face prompt'), data.face || ''],
    [t('Outfit'), data.outfit || ''],
  ]
  if (!rows.some(([, v]) => v)) return null
  return (
    <div style={{ display: 'grid', gap: 4, fontSize: '0.8em', opacity: 0.85 }}>
      {rows.map(([label, value]) => value ? (
        <div key={label} style={{ borderLeft: '2px solid var(--border, #30363d)', paddingLeft: 8 }}>
          <div style={{ fontWeight: 600, opacity: 0.7 }}>{label}</div>
          <div style={{ lineHeight: 1.35 }}>{value}</div>
        </div>
      ) : null)}
    </div>
  )
}
