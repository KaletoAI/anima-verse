/**
 * The pure text helpers of the character area's 3D-preview corners (Ruling UI3):
 * `stampLabel` formats a SYSTEM stamp for the "Built …" caption (BuiltAtCaption)
 * and the freshness badge; `freshnessText` composes the badge text and its
 * tooltip (FreshnessBadge). Kept out of the component files so those export
 * components only.
 */
import { clockSettings, formatDate, formatTime, sameZoneDay } from '../../lib/clockFormat'
import type { Freshness } from './FreshnessBadge'

/** A SYSTEM stamp as the 3D previews and their freshness badges show it: the time of day when it is today,
 *  else day, short month and time. "" for an unusable value. */
export function stampLabel(value: string | null | undefined, now: Date = new Date()): string {
  if (!value) return ''
  const clock = clockSettings()
  const time = formatTime(value, clock)
  if (!time) return ''
  if (sameZoneDay(value, now, clock)) return time
  return `${formatDate(value, clock, { day: 'numeric', month: 'short' })} ${time}`
}

/** The badge text parts and its tooltip lines of a freshness (pure but for `t`). */
export function freshnessText(freshness: Freshness, t: (s: string) => string): { text: string; title: string } {
  const changed = freshness.changed_views || []
  const parts = (freshness.reason || '').split(' · ').filter(Boolean).map((part) => {
    const at = stampLabel(changed.find((c) => c.reason === part)?.at)
    return at ? `${t(part)} · ${at}` : t(part)
  })
  const reason = parts.join(' · ')
  const action = freshness.action ? ` — ${t(freshness.action)}` : ''
  const text = freshness.state === 'current' ? t('current')
    : freshness.state === 'stale' ? (reason ? `${t('outdated')}: ${reason}${action}` : t('outdated'))
    : t('no data')
  const lines = [freshness.state === 'missing' && reason ? `${text} · ${reason}` : text]
  const built = stampLabel(freshness.built_at)
  if (built) lines.push(`${t('Model built')}: ${built}`)
  for (const c of changed) {
    const at = stampLabel(c.at)
    if (at) lines.push(`${t(c.reason)}: ${at}`)
  }
  return { text, title: lines.join('\n') }
}
