import { useCallback, useEffect, useRef, useState } from 'react'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet, apiPost } from '../lib/api'

/**
 * Header clock: shows SYSTEM time and GAME time side by side. The game clock
 * is anchored server-side (world_kv) — the component fetches the anchors once
 * and ticks locally (game = anchor_game + elapsed_real × factor; frozen clock
 * stands still), so no per-second polling. Clicking the game clock opens an
 * in-app popover to set the game time and the tick factor (admin).
 */
interface ClockInfo {
  system_now: string
  game_now: string
  anchor_real: string
  anchor_game: string
  factor: number
  frozen: boolean
}

function two(n: number): string {
  return n < 10 ? `0${n}` : String(n)
}

function fmtClock(d: Date): string {
  return `${two(d.getHours())}:${two(d.getMinutes())}`
}

function fmtGame(d: Date): string {
  return `${two(d.getDate())}.${two(d.getMonth() + 1)}.${d.getFullYear()} ${two(d.getHours())}:${two(d.getMinutes())}`
}

/** For <input type="datetime-local"> — local-naive ISO without seconds. */
function toLocalInput(d: Date): string {
  return `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())}T${two(d.getHours())}:${two(d.getMinutes())}`
}

export function GameClock({ readOnly = false, showSystem = true }: {
  /** true = display only (player UI) — no set popover; setting the game
   *  time/speed happens in the Game-Admin header. */
  readOnly?: boolean
  /** false = hide the system clock (compact player header). */
  showSystem?: boolean
} = {}) {
  const { t } = useI18n()
  const [info, setInfo] = useState<ClockInfo | null>(null)
  const fetchedAt = useRef<number>(0)
  const [, setTick] = useState(0)
  const [open, setOpen] = useState(false)
  const [editTime, setEditTime] = useState('')
  const [editFactor, setEditFactor] = useState('')
  const [busy, setBusy] = useState(false)
  const rootRef = useRef<HTMLDivElement | null>(null)

  const load = useCallback(async () => {
    try {
      const d = await apiGet<ClockInfo>('/world/game-time')
      fetchedAt.current = Date.now()
      setInfo(d)
    } catch {
      setInfo(null)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  // Re-render every 10s (minute-precision display) + refetch on focus and
  // every 5 min (picks up freeze/factor changes made elsewhere).
  useEffect(() => {
    const tick = setInterval(() => setTick((n) => n + 1), 10_000)
    const refetch = setInterval(() => { void load() }, 300_000)
    const onFocus = () => { void load() }
    window.addEventListener('focus', onFocus)
    return () => { clearInterval(tick); clearInterval(refetch); window.removeEventListener('focus', onFocus) }
  }, [load])

  // Close the popover on outside click.
  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  if (!info) return null

  const elapsedMs = Date.now() - fetchedAt.current
  const gameBase = new Date(info.game_now).getTime()
  const gameNow = new Date(info.frozen ? gameBase : gameBase + elapsedMs * info.factor)
  const sysNow = new Date(new Date(info.system_now).getTime() + elapsedMs)

  const openEditor = () => {
    setEditTime(toLocalInput(gameNow))
    setEditFactor(String(info.factor))
    setOpen(true)
  }

  const save = async () => {
    if (busy) return
    setBusy(true)
    try {
      const body: Record<string, unknown> = {}
      if (editTime) body.game_time = new Date(editTime).toISOString()
      const f = parseFloat(editFactor)
      if (Number.isFinite(f) && f >= 0 && f !== info.factor) body.factor = f
      const d = await apiPost<ClockInfo>('/world/game-time', body)
      fetchedAt.current = Date.now()
      setInfo(d)
      setOpen(false)
    } catch {
      // keep the popover open so the user can retry
    } finally {
      setBusy(false)
    }
  }

  const clockBody = (
    <>
      🕰 {fmtGame(gameNow)}
      {info.factor !== 1 ? <span style={{ opacity: 0.7, marginLeft: 4 }}>×{info.factor}</span> : null}
      {info.frozen ? <span style={{ marginLeft: 4 }}>❄</span> : null}
    </>
  )

  return (
    <div ref={rootRef} style={{ position: 'relative', display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.85em' }}>
      {showSystem && (
        <span style={{ opacity: 0.6 }} title={t('System time')}>
          🖥 {fmtClock(sysNow)}
        </span>
      )}
      {readOnly ? (
        <span title={t('Game time')} style={{ fontVariantNumeric: 'tabular-nums', opacity: 0.85 }}>
          {clockBody}
        </span>
      ) : (
      <button
        className="ga-btn ga-btn-sm"
        onClick={openEditor}
        title={info.frozen
          ? t('Game time (frozen — the world freeze stops the game clock). Click to set time & speed.')
          : t('Game time. Click to set time & speed.')}
        style={{ fontVariantNumeric: 'tabular-nums' }}
      >
        {clockBody}
      </button>
      )}
      {open && (
        <div style={{
          position: 'absolute', top: '100%', right: 0, zIndex: 60, marginTop: 4,
          background: 'var(--panel, #161b22)', border: '1px solid var(--border, #30363d)',
          borderRadius: 6, boxShadow: '0 6px 20px rgba(0,0,0,0.4)', padding: 12,
          display: 'flex', flexDirection: 'column', gap: 8, minWidth: 260,
        }}>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span style={{ opacity: 0.7 }}>{t('Game time')}</span>
            <input
              className="ga-input"
              type="datetime-local"
              value={editTime}
              onChange={(e) => setEditTime(e.target.value)}
            />
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span style={{ opacity: 0.7 }}>{t('Speed (× system time)')}</span>
            <input
              className="ga-input"
              type="number"
              min={0}
              step={0.5}
              value={editFactor}
              onChange={(e) => setEditFactor(e.target.value)}
            />
          </label>
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            <button className="ga-btn ga-btn-sm" onClick={() => setOpen(false)} disabled={busy}>
              {t('Cancel')}
            </button>
            <button className="ga-btn ga-btn-sm ga-btn-primary" onClick={() => { void save() }} disabled={busy}>
              {t('Save')}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
