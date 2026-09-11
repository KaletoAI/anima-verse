/**
 * TemplateField — renders ONE character field generically from its template
 * definition (`type`/`options`/`source`/`allow_custom`/`multiline`/`readonly`).
 * No hardcoding: every property comes from the template field.
 *
 * The value is handed back via `onCommit(value)` — immediately for selects,
 * onBlur for text/number. `allow_custom` shows a "Custom…" entry that switches
 * to a free-text field (like the old UI).
 */
import { useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'

export interface TmplFieldDef {
  [k: string]: unknown
  key: string
  type?: string
  options?: Array<string | { value?: string; id?: string; label?: string }>
  source?: string
  allow_custom?: boolean
  multiline?: boolean
  readonly?: boolean
  required?: boolean
  placeholder?: string
  placeholder_de?: string
  label?: string
  label_de?: string
  hint?: string
  hint_de?: string
  help?: string  // topic key for the context-sensitive help panel
  default?: unknown
  store?: string
  source_file?: string
  editor_visible?: boolean
  visible_when?: { field: string; values: unknown[] }
  /** This field is an INPUT the server derives other fields from, so saving it
   *  changes keys the form never sent (the temp-NPC lifetime recomputes
   *  `expires_at`). The renderers re-read the stores after such a save, or the
   *  readonly display right next to the control keeps showing the old value. */
  reload_after_save?: boolean
}

/** An option source. `days` is only filled where the source carries a length
 *  per entry — the world calendar's seasons do, and a `season_day` field takes
 *  the day maximum from it. */
export interface DynamicOption {
  value: string
  label: string
  days?: number
}

export type DynamicData = Record<string, DynamicOption[]>

function normOpts(
  raw: Array<string | { value?: string; id?: string; label?: string }> | undefined,
): Array<{ value: string; label: string }> {
  return (raw || []).map((o) =>
    typeof o === 'string'
      ? { value: o, label: o }
      : { value: String(o.value ?? o.id ?? ''), label: String(o.label ?? o.value ?? o.id ?? '') },
  )
}

export function tmplText(
  field: { [k: string]: unknown },
  key: 'label' | 'hint' | 'placeholder',
  lang: string,
): string {
  const de = field[`${key}_de`]
  if (lang === 'de' && typeof de === 'string' && de) return de
  const base = field[key]
  return typeof base === 'string' ? base : ''
}


/** Split a stored `"<season_key>:<day>"`. The DAY is the last segment, so a
 *  season key containing a colon survives — the same split the backend's
 *  `parse_season_day` does. A value without a colon is kept as the season half
 *  so an imported oddity stays visible instead of vanishing from the form. */
function splitSeasonDay(raw: string): { season: string; day: string } {
  const text = raw.trim()
  const cut = text.lastIndexOf(':')
  if (cut < 0) return { season: text, day: '' }
  return { season: text.slice(0, cut).trim(), day: text.slice(cut + 1).trim() }
}

/**
 * A day of the WORLD calendar without a year — a season plus the day within it,
 * stored as one string `"<season_key>:<day>"`. The season list comes from the
 * field's option source (`dynamicData`), so the control never knows a season
 * name or a season length itself.
 *
 * Only a complete pair is a calendar day: half an entry commits `""`, never a
 * broken value. A season key the calendar does not (or no longer) know is kept
 * as its own option — the backend ignores such a value when reading, it never
 * discards it, so the form must not silently drop it either.
 */
function SeasonDayField({
  value,
  seasons,
  disabled,
  onCommit,
}: {
  value: string
  seasons: DynamicOption[]
  disabled?: boolean
  onCommit: (value: string) => void
}) {
  const { t } = useI18n()
  const [season, setSeason] = useState(() => splitSeasonDay(value).season)
  const [day, setDay] = useState(() => splitSeasonDay(value).day)
  useEffect(() => {
    const parts = splitSeasonDay(value)
    setSeason(parts.season)
    setDay(parts.day)
  }, [value])

  const picked = seasons.find((s) => s.value === season)
  // Without a season (or with one the calendar does not know) the longest
  // season is the only honest ceiling; an empty list leaves the day open.
  const maxDay = picked?.days ?? seasons.reduce((m, s) => Math.max(m, s.days ?? 0), 0)
  const seasonKnown = !season || seasons.some((s) => s.value === season)

  const commit = (nextSeason: string, nextDay: string) => {
    const n = parseInt(nextDay, 10)
    const limit = seasons.find((s) => s.value === nextSeason)?.days ?? 0
    const bounded = Number.isFinite(n) && n >= 1 ? (limit > 0 ? Math.min(n, limit) : n) : 0
    const next = nextSeason && bounded ? `${nextSeason}:${bounded}` : ''
    if (next !== value) onCommit(next)
  }

  return (
    <div style={{ display: 'flex', gap: 6 }}>
      <select
        className="ga-input"
        aria-label={t('Season')}
        title={t('Season')}
        value={season}
        disabled={disabled}
        style={{ flex: 1, minWidth: 0 }}
        onChange={(e) => {
          const next = e.target.value
          // A day beyond the new season's length does not exist there.
          const limit = seasons.find((s) => s.value === next)?.days ?? 0
          const n = parseInt(day, 10)
          const nextDay = limit > 0 && Number.isFinite(n) && n > limit ? String(limit) : day
          setSeason(next)
          setDay(nextDay)
          commit(next, nextDay)
        }}
      >
        <option value="">— {t('Season')} —</option>
        {/* Keep an imported value the calendar does not know */}
        {seasonKnown ? null : <option value={season}>{season}</option>}
        {seasons.map((s) => (
          <option key={s.value} value={s.value}>
            {s.label}
          </option>
        ))}
      </select>
      <input
        className="ga-input"
        type="number"
        min={1}
        max={maxDay || undefined}
        aria-label={t('Day')}
        title={t('Day')}
        placeholder={t('Day')}
        value={day}
        disabled={disabled}
        style={{ width: 90, flex: '0 0 auto' }}
        onChange={(e) => setDay(e.target.value)}
        onBlur={() => commit(season, day)}
      />
    </div>
  )
}

export function TemplateField({
  field,
  value,
  dynamicData,
  disabled,
  lang,
  onCommit,
}: {
  field: TmplFieldDef
  value: unknown
  dynamicData: DynamicData
  disabled?: boolean
  lang: string
  onCommit: (value: string) => void
}) {
  const [local, setLocal] = useState(String(value ?? ''))
  useEffect(() => {
    setLocal(String(value ?? ''))
  }, [value])

  const type = field.type || 'text'
  const placeholder = tmplText(field, 'placeholder', lang)

  // Option source: dynamic (source) or static (options).
  const opts =
    type === 'character_select'
      ? dynamicData.characters || []
      : field.source
        ? dynamicData[field.source] || []
        : normOpts(field.options)
  const inOpts = opts.some((o) => o.value === local)
  // An option source may bring its OWN empty entry when "not set" needs a
  // label (e.g. "Automatic (female)"). Then the built-in placeholder below
  // would render a second, unlabelled empty row.
  const hasEmptyOpt = opts.some((o) => o.value === '')

  // Custom mode: free text active for allow_custom (value not among options).
  const [custom, setCustom] = useState<boolean>(!!field.allow_custom && local !== '' && !inOpts)
  useEffect(() => {
    if (field.allow_custom && local !== '' && !opts.some((o) => o.value === local)) setCustom(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value])

  // ---- Text (multiline) ----
  if (type === 'text' && field.multiline) {
    return (
      <textarea
        className="ga-input"
        rows={Number(field.rows) > 0 ? Number(field.rows) : 3}
        value={local}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(e) => setLocal(e.target.value)}
        onBlur={() => {
          if (local !== String(value ?? '')) onCommit(local)
        }}
      />
    )
  }

  // ---- Number ----
  if (type === 'number') {
    return (
      <input
        className="ga-input"
        type="number"
        value={local}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(e) => setLocal(e.target.value)}
        onBlur={() => {
          if (local !== String(value ?? '')) onCommit(local)
        }}
      />
    )
  }

  // ---- Season + day of the world calendar ----
  if (type === 'season_day') {
    return (
      <SeasonDayField
        value={local}
        seasons={dynamicData[field.source || 'seasons'] || []}
        disabled={disabled}
        onCommit={onCommit}
      />
    )
  }

  // ---- Select / character_select ----
  if (type === 'select' || type === 'character_select') {
    if (field.allow_custom && custom) {
      return (
        <div style={{ display: 'flex', gap: 6 }}>
          <input
            className="ga-input"
            type="text"
            value={local}
            placeholder={placeholder}
            disabled={disabled}
            style={{ flex: 1, minWidth: 0 }}
            onChange={(e) => setLocal(e.target.value)}
            onBlur={() => {
              if (local !== String(value ?? '')) onCommit(local)
            }}
          />
          <button
            type="button"
            className="ga-btn"
            title="Back to list"
            disabled={disabled}
            onClick={() => {
              setCustom(false)
              setLocal('')
              if (value) onCommit('')
            }}
          >
            ↩
          </button>
        </div>
      )
    }
    return (
      <select
        className="ga-input"
        value={local}
        disabled={disabled}
        onChange={(e) => {
          const v = e.target.value
          if (v === '__custom__') {
            setCustom(true)
            setLocal('')
            return
          }
          setLocal(v)
          onCommit(v)
        }}
      >
        {hasEmptyOpt ? null : <option value="">— —</option>}
        {/* Keep an imported value that is not among the options */}
        {local && !inOpts ? <option value={local}>{local}</option> : null}
        {opts.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
        {field.allow_custom ? <option value="__custom__">✏ Custom…</option> : null}
      </select>
    )
  }

  // ---- Text (single line, default) ----
  return (
    <input
      className="ga-input"
      type="text"
      value={local}
      placeholder={placeholder}
      disabled={disabled}
      onChange={(e) => setLocal(e.target.value)}
      onBlur={() => {
        if (local !== String(value ?? '')) onCommit(local)
      }}
    />
  )
}
