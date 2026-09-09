/**
 * ONE place that turns an instant into a readable time of day.
 *
 * Two settings decide the shape, both configured server-side in
 * `/admin/settings → Server` and both delivered by `GET /world/game-time`
 * (`time_format`, `timezone`):
 *
 * - **format** — `24h` `14:23` · `24h_seconds` `14:23:05` · `12h` `2:23 PM` ·
 *   `12h_seconds` `2:23:05 PM`.
 * - **timeZone** — the IANA zone SYSTEM stamps are shown in. It is NOT the
 *   browser's zone: an admin watching a server in another country should read
 *   the world's clock, not their own.
 *
 * GAME time has no zone at all (a world calendar of seasons and days), so it
 * never travels through a `Date` here — `formatGameTime` takes the hour and
 * minute the caller already derived and only applies the format.
 *
 * The 12h/24h decision is made in this file rather than handed to
 * `Intl.DateTimeFormat`, because Intl's `hour12` output is locale-dependent
 * ("2:23 PM" / "2:23 nachm." / "14:23") — one setting must produce one shape
 * everywhere. Intl is used for what it is unambiguously good at: converting an
 * instant into the wall-clock numbers of a zone.
 */

export type TimeFormat = '24h' | '24h_seconds' | '12h' | '12h_seconds'

export interface ClockSettings {
  /** How a time of day reads. */
  format: TimeFormat
  /** IANA zone for SYSTEM stamps; `'UTC'` when unset or unknown. */
  timeZone: string
}

const FORMATS: readonly TimeFormat[] = ['24h', '24h_seconds', '12h', '12h_seconds']

export const DEFAULT_CLOCK: ClockSettings = { format: '24h', timeZone: 'UTC' }

/** Narrow an arbitrary server value to a known format, else `24h`. */
export function asTimeFormat(value: unknown): TimeFormat {
  return FORMATS.includes(value as TimeFormat) ? (value as TimeFormat) : '24h'
}

const two = (n: number) => String(n).padStart(2, '0')

/**
 * Hour/minute/second → the configured shape. The one function every other
 * formatter in this file ends in.
 *
 * `hour` is 0-23. In the 12h shapes hour 0 reads as 12 AM and hour 12 as
 * 12 PM; the hour itself is NOT zero-padded there (`2:23 PM`, not `02:23 PM`),
 * while 24h always is (`02:23`).
 */
export function formatGameTime(
  hour: number,
  minute: number,
  format: TimeFormat = '24h',
  second = 0,
): string {
  const h = Math.floor(hour)
  const withSeconds = format === '24h_seconds' || format === '12h_seconds'
  const tail = withSeconds ? `:${two(Math.floor(second))}` : ''
  if (format === '12h' || format === '12h_seconds') {
    const suffix = h < 12 ? 'AM' : 'PM'
    const h12 = h % 12 === 0 ? 12 : h % 12
    return `${h12}:${two(Math.floor(minute))}${tail} ${suffix}`
  }
  return `${two(h)}:${two(Math.floor(minute))}${tail}`
}

/** Anything a caller might hold → a `Date`, or `null` when unusable. */
function toDate(value: string | number | Date | null | undefined): Date | null {
  if (value === null || value === undefined || value === '') return null
  const d = value instanceof Date ? value : new Date(value)
  return Number.isNaN(d.getTime()) ? null : d
}

/** The wall-clock numbers an instant has in `timeZone`. */
function zoneParts(d: Date, timeZone: string): { hour: number, minute: number, second: number } {
  let parts: Intl.DateTimeFormatPart[]
  try {
    parts = new Intl.DateTimeFormat('en-US', {
      timeZone, hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit',
    }).formatToParts(d)
  } catch {
    // Unknown zone name (a stale config, an exotic browser): read the instant
    // in UTC rather than silently falling back to the viewer's own zone.
    parts = new Intl.DateTimeFormat('en-US', {
      timeZone: 'UTC', hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit',
    }).formatToParts(d)
  }
  const num = (type: string) => {
    const raw = parts.find((p) => p.type === type)?.value ?? '0'
    const n = parseInt(raw, 10)
    return Number.isFinite(n) ? n : 0
  }
  // `hour12: false` renders midnight as 24 in some engines.
  return { hour: num('hour') % 24, minute: num('minute'), second: num('second') }
}

/**
 * A SYSTEM stamp → time of day only, in the configured zone and format.
 * Returns `''` for an unusable value so call sites can render it as-is.
 */
export function formatTime(
  value: string | number | Date | null | undefined,
  clock: ClockSettings = DEFAULT_CLOCK,
): string {
  const d = toDate(value)
  if (!d) return ''
  const p = zoneParts(d, clock.timeZone)
  return formatGameTime(p.hour, p.minute, clock.format, p.second)
}

/** Date part of a SYSTEM stamp, in the configured zone (viewer's locale). */
export function formatDate(
  value: string | number | Date | null | undefined,
  clock: ClockSettings = DEFAULT_CLOCK,
  options: Intl.DateTimeFormatOptions = { year: 'numeric', month: '2-digit', day: '2-digit' },
): string {
  const d = toDate(value)
  if (!d) return ''
  try {
    return new Intl.DateTimeFormat(undefined, { ...options, timeZone: clock.timeZone }).format(d)
  } catch {
    return new Intl.DateTimeFormat(undefined, { ...options, timeZone: 'UTC' }).format(d)
  }
}

/** Date + time of day of a SYSTEM stamp, in the configured zone and format. */
export function formatDateTime(
  value: string | number | Date | null | undefined,
  clock: ClockSettings = DEFAULT_CLOCK,
  dateOptions?: Intl.DateTimeFormatOptions,
): string {
  const d = toDate(value)
  if (!d) return ''
  return `${formatDate(d, clock, dateOptions)} ${formatTime(d, clock)}`
}

/** True when both stamps fall on the same calendar day of the configured zone. */
export function sameZoneDay(
  a: string | number | Date | null | undefined,
  b: string | number | Date | null | undefined,
  clock: ClockSettings = DEFAULT_CLOCK,
): boolean {
  const key = (v: typeof a) => formatDate(v, clock, {
    year: 'numeric', month: '2-digit', day: '2-digit',
  })
  const ka = key(a)
  return ka !== '' && ka === key(b)
}
