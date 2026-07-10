import { useCallback, useEffect, useState } from 'react'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet, apiPost } from '../lib/api'

// Global toggle for the world SLEEP mode: every NPC really falls asleep in
// place — no more NPC LLM chat calls (agent loop, telegram, direct chat).
// Ticks, memory consolidation, scheduler, task queue and the GAME CLOCK keep
// running (unlike Freeze, which also stops the game clock). Waking restores
// only the NPCs the sleep mode put to sleep; natural sleepers sleep on.
// Backend: GET/POST /world/sleep-status|sleep|wake (see plan-game-time.md).
export function SleepToggle() {
  const { t } = useI18n()
  const [sleeping, setSleeping] = useState<boolean | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    apiGet<{ sleeping?: boolean }>('/world/sleep-status')
      .then((d) => setSleeping(!!d.sleeping))
      .catch(() => setSleeping(false))
  }, [])

  const toggle = useCallback(async () => {
    if (sleeping === null || busy) return
    setBusy(true)
    try {
      const d = await apiPost<{ sleeping?: boolean }>(sleeping ? '/world/wake' : '/world/sleep', {})
      setSleeping(!!d.sleeping)
    } catch {
      // leave state untouched on error
    } finally {
      setBusy(false)
    }
  }, [sleeping, busy])

  if (sleeping === null) return null

  return (
    <button
      className="ga-btn ga-btn-sm"
      onClick={() => { void toggle() }}
      disabled={busy}
      style={sleeping
        ? { background: '#6e40c9', borderColor: '#6e40c9', color: '#fff', fontWeight: 600 }
        : undefined}
      title={sleeping
        ? t('World is sleeping — all NPCs are asleep, no NPC LLM chat calls. Ticks, memory consolidation and the game clock keep running. Click to wake.')
        : t('Put the world to sleep — every NPC falls asleep instantly, stopping NPC LLM chat calls. Ticks, memory consolidation and the game clock keep running.')}
    >
      {sleeping ? `😴 ${t('World sleeping — Wake')}` : `😴 ${t('Sleep world')}`}
    </button>
  )
}
