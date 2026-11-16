/**
 * The character list's open-step badges (Ruling A112): per row, when the
 * Build's plan has open steps, one compact badge for the base (plain) body
 * and one for the outfit — an icon and a count, no words; a hub marker with
 * the job count when the steps cost hub jobs. Red when a step is held (only a
 * manual Build runs it, or it failed for its inputs), yellow when merely due.
 * The mouse-over lists the steps. The SERVER plans and splits
 * (`GET /characters/open-steps` → `figure_build.open_steps`); this file only
 * draws what it answers.
 */
import type { ReactNode } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import type { OpenGroup, OpenSteps } from './useOpenSteps'

const BodyIcon = () => (
  <svg width="11" height="12" viewBox="0 0 11 12" aria-hidden="true">
    <circle cx="5.5" cy="2.2" r="2" fill="currentColor" />
    <path d="M2 5.2h7l-1 3.4H7.2L7 12H4l-.2-3.4H3z" fill="currentColor" />
  </svg>
)
const ShirtIcon = () => (
  <svg width="13" height="12" viewBox="0 0 13 12" aria-hidden="true">
    <path d="M4.3 1 1 3l1.3 2.6 1.4-.7V11h5.6V4.9l1.4.7L12 3 8.7 1c-.3 1-1.1 1.6-2.2 1.6S4.6 2 4.3 1z"
      fill="currentColor" />
  </svg>
)

function Badge({ group, icon, heading }: { group: OpenGroup; icon: ReactNode; heading: string }) {
  const { t } = useI18n()
  if (!group.count) return null
  const jobsText = (n: number | null) => (n === null ? t('hub jobs unknown')
    : t('{n} hub jobs').replace('{n}', String(n)))
  const lines = [
    heading.replace('{n}', String(group.count)) + (group.hub_jobs !== 0 ? ` · ${jobsText(group.hub_jobs)}` : ''),
    ...group.steps.map((s) => `${s.hold ? '■' : '•'} ${s.label}`
      + (s.jobs ? ` (${jobsText(s.jobs)})` : '')
      + (s.hold && s.why ? ` — ${s.why}` : '')),
  ]
  return (
    <span className={`ga-open-badge ${group.hold ? 'is-hold' : 'is-due'}`} title={lines.join('\n')}>
      {icon}{group.count}
      {group.hub_jobs !== 0 ? <span className="ga-open-badge-hub">⚡{group.hub_jobs ?? '?'}</span> : null}
    </span>
  )
}

export function OpenStepsBadges({ info }: { info?: OpenSteps }) {
  const { t } = useI18n()
  if (!info) return null
  return (
    <span className="ga-open-badges">
      {info.building ? <span className="ga-open-badge is-building" title={t('A Build is running')}>⟳</span> : null}
      <Badge group={info.base} icon={<BodyIcon />} heading={t('Base body: {n} open steps')} />
      <Badge group={info.outfit} icon={<ShirtIcon />} heading={t('Outfit: {n} open steps')} />
    </span>
  )
}
