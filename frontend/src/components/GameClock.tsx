import { useCallback, useEffect, useRef, useState } from 'react'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet, apiPost } from '../lib/api'

/**
 * Header clock: shows SYSTEM time and GAME time side by side.
 *
 * The game clock runs on the WORLD CALENDAR (seasons and days, no real
 * dates — plan-game-calendar). The server hands over the instant fully
 * rendered plus the calendar definition; this component keeps
 * `total_seconds` + `factor` + the fetch moment and derives the display
 * locally (game seconds = base + elapsed_real × factor; a frozen clock
 * stands still), so there is no per-second polling and no date parsing.
 *
 * Clicking the game clock opens an in-app popover to set the game time
 * (season / day / time / year) and the tick factor (admin only).
 */
interface CalendarSeason {
  key: string
  name: string
  days: number
  sunrise: string
  sunset: string
}

interface CalendarInfo {
  seasons: CalendarSeason[]
  year_days: number
  week_days: string[]
  year_label: string
}

interface GameInstant {
  canonical: string
  total_seconds: number
  year: number
  day_of_year: number
  season: string
  season_name: string
  day_of_season: number
  hour: number
  minute: number
  label: string
}

interface ClockInfo {
  system_now: string
  game: GameInstant
  anchor_real: string
  anchor_game: string
  factor: number
  frozen: boolean
  calendar: CalendarInfo
}

const DAY_SECONDS = 24 * 60 * 60

interface GameParts {
  year: number
  dayOfYear: number
  seasonIndex: number
  dayOfSeason: number
  hour: number
  minute: number
  weekday: number | null
}

/**
 * Split whole GAME seconds into calendar parts — the client-side twin of
 * `GameTime.parts()` on the server, and the ONLY arithmetic this component
 * does. Year and day are 1-based, exactly like the payload.
 */
function gameParts(totalSeconds: number, cal: CalendarInfo): GameParts {
  const secs = Math.max(0, Math.floor(totalSeconds))
  const dayIndex = Math.floor(secs / DAY_SECONDS)
  const secOfDay = secs - dayIndex * DAY_SECONDS
  const yearDays = cal.year_days > 0 ? cal.year_days : 1
  const dayOfYear0 = dayIndex % yearDays
  let seasonIndex = 0
  let start = 0
  for (let i = 0; i < cal.seasons.length; i++) {
    if (dayOfYear0 >= start) { seasonIndex = i } else { break }
    start += cal.seasons[i].days
  }
  const seasonStart = cal.seasons
    .slice(0, seasonIndex)
    .reduce((acc, s) => acc + s.days, 0)
  return {
    year: Math.floor(dayIndex / yearDays) + 1,
    dayOfYear: dayOfYear0 + 1,
    seasonIndex,
    dayOfSeason: dayOfYear0 - seasonStart + 1,
    hour: Math.floor(secOfDay / 3600),
    minute: Math.floor((secOfDay % 3600) / 60),
    weekday: cal.week_days.length ? dayIndex % cal.week_days.length : null,
  }
}

function two(n: number): string {
  return n < 10 ? `0${n}` : String(n)
}

function fmtClock(d: Date): string {
  return `${two(d.getHours())}:${two(d.getMinutes())}`
}

/** Same shape as `GameTime.label()` on the server: `<Weekday, >Season, day N ·
 *  HH:MM · Year n`. The season names arrive localized, "day" goes through t(). */
function fmtGameLabel(p: GameParts, cal: CalendarInfo, dayWord: string): string {
  const season = cal.seasons[p.seasonIndex]?.name || ''
  let head = season ? `${season}, ${dayWord} ${p.dayOfSeason}` : `${dayWord} ${p.dayOfSeason}`
  if (p.weekday !== null) head = `${cal.week_days[p.weekday]}, ${head}`
  const chunks = [head, `${two(p.hour)}:${two(p.minute)}`]
  if (cal.year_label) chunks.push(cal.year_label.replace('{n}', String(p.year)))
  return chunks.join(' · ')
}

export function GameClock({ readOnly = false, showSystem = true }: {
  /** true = display only (player UI) — no set popover; setting the game
   *  time/speed happens in the Game-Admin header. */
  readOnly?: boolean
  /** false = hide the system clock (compact player header). */
  showSystem?: boolean
} = {}) {
  const { t, lang } = useI18n()
  const [info, setInfo] = useState<ClockInfo | null>(null)
  const fetchedAt = useRef<number>(0)
  const [, setTick] = useState(0)
  const [open, setOpen] = useState(false)
  const [editSeason, setEditSeason] = useState('')
  const [editDay, setEditDay] = useState('')
  const [editClock, setEditClock] = useState('')
  const [editYear, setEditYear] = useState('')
  const [editFactor, setEditFactor] = useState('')
  const [busy, setBusy] = useState(false)
  const rootRef = useRef<HTMLDivElement | null>(null)

  const load = useCallback(async () => {
    try {
      const d = await apiGet<ClockInfo>(`/world/game-time?lang=${encodeURIComponent(lang)}`)
      fetchedAt.current = Date.now()
      setInfo(d)
    } catch {
      setInfo(null)
    }
  }, [lang])

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

  const cal = info.calendar
  const elapsedMs = Date.now() - fetchedAt.current
  const gameSeconds = info.frozen
    ? info.game.total_seconds
    : info.game.total_seconds + (elapsedMs / 1000) * info.factor
  const parts = gameParts(gameSeconds, cal)
  const gameLabel = fmtGameLabel(parts, cal, t('day'))
  const sysNow = new Date(new Date(info.system_now).getTime() + elapsedMs)
  const seasonKey = editSeason || cal.seasons[parts.seasonIndex]?.key || ''
  const seasonDays = cal.seasons.find((s) => s.key === seasonKey)?.days ?? 30

  const openEditor = () => {
    setEditSeason(cal.seasons[parts.seasonIndex]?.key || '')
    setEditDay(String(parts.dayOfSeason))
    setEditClock(`${two(parts.hour)}:${two(parts.minute)}`)
    setEditYear(String(parts.year))
    setEditFactor(String(info.factor))
    setOpen(true)
  }

  const save = async () => {
    if (busy) return
    setBusy(true)
    try {
      const body: Record<string, unknown> = {}
      const day = parseInt(editDay, 10)
      const year = parseInt(editYear, 10)
      const [hh, mm] = (editClock || '').split(':')
      if (seasonKey && Number.isFinite(day) && Number.isFinite(year)) {
        body.game_time = {
          year,
          season: seasonKey,
          day,
          hour: parseInt(hh, 10) || 0,
          minute: parseInt(mm, 10) || 0,
        }
      }
      const f = parseFloat(editFactor)
      if (Number.isFinite(f) && f >= 0 && f !== info.factor) body.factor = f
      const d = await apiPost<ClockInfo>(
        `/world/game-time?lang=${encodeURIComponent(lang)}`, body)
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
      🕰 {gameLabel}
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
            <span style={{ opacity: 0.7 }}>{t('Season')}</span>
            <select
              className="ga-input"
              value={seasonKey}
              onChange={(e) => setEditSeason(e.target.value)}
            >
              {cal.seasons.map((s) => (
                <option key={s.key} value={s.key}>{s.name}</option>
              ))}
            </select>
          </label>
          <div style={{ display: 'flex', gap: 8 }}>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1 }}>
              <span style={{ opacity: 0.7 }}>{t('Day of season')}</span>
              <input
                className="ga-input"
                type="number"
                min={1}
                max={seasonDays}
                step={1}
                value={editDay}
                onChange={(e) => setEditDay(e.target.value)}
              />
            </label>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1 }}>
              <span style={{ opacity: 0.7 }}>{t('Year')}</span>
              <input
                className="ga-input"
                type="number"
                min={1}
                step={1}
                value={editYear}
                onChange={(e) => setEditYear(e.target.value)}
              />
            </label>
          </div>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span style={{ opacity: 0.7 }}>{t('Time of day')}</span>
            <input
              className="ga-input"
              type="time"
              value={editClock}
              onChange={(e) => setEditClock(e.target.value)}
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
