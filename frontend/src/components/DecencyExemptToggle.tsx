import { useCallback, useEffect, useState } from 'react'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet, apiPost } from '../lib/api'

// Toggle for the per-character decency_exempt state flag. When set, decency
// rules are overridden (nude_ok) regardless of who is present — the manual
// equivalent to is_intimate. The same flag is also settable via rule set_flags
// and the IgnoreDressCode / FollowDressCode skills (decency_exempt package).
// Backend: GET/POST /characters/{name}/decency-exempt
export function DecencyExemptToggle({ character }: { character: string }) {
  const { t } = useI18n()
  const [exempt, setExempt] = useState<boolean | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!character) return
    apiGet<{ exempt?: boolean }>(`/characters/${encodeURIComponent(character)}/decency-exempt`)
      .then((d) => setExempt(!!d.exempt))
      .catch(() => setExempt(false))
  }, [character])

  const toggle = useCallback(async () => {
    if (exempt === null || busy || !character) return
    setBusy(true)
    try {
      const d = await apiPost<{ exempt?: boolean }>(
        `/characters/${encodeURIComponent(character)}/decency-exempt`,
        { exempt: !exempt },
      )
      setExempt(!!d.exempt)
    } catch {
      // leave state untouched on error
    } finally {
      setBusy(false)
    }
  }, [character, exempt, busy])

  if (exempt === null) return null

  return (
    <button
      className="ga-btn ga-btn-sm"
      onClick={() => { void toggle() }}
      disabled={busy}
      style={exempt
        ? { background: '#a371f7', borderColor: '#a371f7', color: '#fff', fontWeight: 600 }
        : undefined}
      title={exempt
        ? t('Decency override active — may stay undressed regardless of who is present. Click to require normal decency.')
        : t('Override decency — stay undressed/revealing regardless of who is present (same effect as nude_ok).')}
    >
      {exempt ? `🔓 ${t('Decency override: ON')}` : `🔓 ${t('Decency override: off')}`}
    </button>
  )
}
