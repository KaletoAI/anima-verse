import { useCallback, useEffect, useState } from 'react'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet, apiPost } from '../lib/api'

// Global toggle for the persistent World-Freeze. Freezing pauses the autonomous
// simulation (agent loop, hourly ticks, scheduler jobs, telegram polling) so the
// world can be built in peace. Image generation and LLM tools keep working.
// Backend: GET/POST /world/freeze-status|freeze|unfreeze (see plan-world-freeze.md).
export function FreezeToggle() {
  const { t } = useI18n()
  const [frozen, setFrozen] = useState<boolean | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    apiGet<{ frozen?: boolean }>('/world/freeze-status')
      .then((d) => setFrozen(!!d.frozen))
      .catch(() => setFrozen(false))
  }, [])

  const toggle = useCallback(async () => {
    if (frozen === null || busy) return
    setBusy(true)
    try {
      const d = await apiPost<{ frozen?: boolean }>(frozen ? '/world/unfreeze' : '/world/freeze', {})
      setFrozen(!!d.frozen)
    } catch {
      // leave state untouched on error
    } finally {
      setBusy(false)
    }
  }, [frozen, busy])

  if (frozen === null) return null

  return (
    <button
      className="ga-btn ga-btn-sm"
      onClick={() => { void toggle() }}
      disabled={busy}
      style={frozen
        ? { background: '#1f6feb', borderColor: '#1f6feb', color: '#fff', fontWeight: 600 }
        : undefined}
      title={frozen
        ? t('World is frozen — autonomous simulation is paused (image generation & LLM tools still work). Click to resume.')
        : t('Freeze the world — pauses ticks, agent loop, scheduler & telegram while you build. Image generation & LLM tools keep working.')}
    >
      {frozen ? `❄ ${t('World frozen — Resume')}` : `❄ ${t('Freeze world')}`}
    </button>
  )
}
