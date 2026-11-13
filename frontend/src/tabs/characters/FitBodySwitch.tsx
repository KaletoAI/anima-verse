/**
 * The Details preview's body switch (Ruling A31): one button per body the piece has a fit attempt on — "Plain
 * body" and every "Body shape (<what is in it>)" — each with its status light and, under the buttons, the selected
 * body's verdict in plain words (the measured reasons on hover). The viewer beside shows that body WITH the piece
 * as last fitted there, a refused fit included, the region the refusing check measured marked in colour (legend
 * below the buttons; the server grafts the marks, the client only shows them).
 *
 * A refused fit can be accepted ("Accept this fit") — admin-only, it spends no job; the figure is then due for a
 * re-assembly on the CPU (the server's estimate is shown before the click and after it). "Accepted by you" (green)
 * holds until the fit, its body or the fit version changes; "Undo accept" brings the refusal back. Server:
 * `fit_attempts.bodies` (GET …/garments/{item} `bodies`), POST …/garments/{item}/fits/{body}/accept | unaccept.
 */
import { useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { StepLight } from './FieldHairstyles'
import { ACCEPTED_BY_YOU, bodyWords } from './figureModel'
import type { FitBody } from './figureModel'
import type { Light } from './hairstylesModel'

/** The follow-up the server estimates after an acceptance or its undo (`figure_build.cost`). */
interface FollowUp { hub_jobs: number | null; steps: Array<{ name: string; label: string; jobs: number | null }> }

const LIGHT: Record<FitBody['status'], Light> = {
  accepted: 'green', user_accepted: 'green', refused: 'red', stale: 'yellow', missing: 'grey',
}
const STATUS_TEXT: Record<FitBody['status'], string> = {
  accepted: 'accepted', user_accepted: ACCEPTED_BY_YOU, refused: 'refused', stale: 'out of date',
  missing: 'not fitted yet',
}
const ROW: CSSProperties = { display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }
const ACCEPTED: CSSProperties = { color: 'var(--success, #3fb950)' }
const REFUSED: CSSProperties = { color: 'var(--danger, #f85149)', overflowWrap: 'anywhere' }

/** "Plain body: accepted" / "Body shape (t-shirt): refused — the left trouser leg stands off the thigh". */
function bodyVerdict(b: FitBody, t: (s: string) => string): string {
  const head = `${bodyWords(b.label, t)}: ${t(STATUS_TEXT[b.status])}`
  return b.reason && b.status !== 'accepted' ? `${head} — ${b.reason}` : head
}

/** The CPU follow-up in words: "re-assembly of the figure (CPU only)", or the steps with their hub jobs. */
function followUpWords(f: FollowUp | null | undefined, t: (s: string) => string): string {
  if (!f || !f.steps.length) return t('nothing is due')
  if (f.hub_jobs === 0 && f.steps.every((s) => s.name === 'assemble')) return t('re-assembly of the figure (CPU only)')
  const jobs = f.hub_jobs === null ? t('cost unknown') : t('{n} hub jobs').replace('{n}', String(f.hub_jobs))
  return `${f.steps.map((s) => s.label).join(', ')} (${jobs})`
}

export function FitBodySwitch({ character, itemId, bodies, selected, onSelect, onChanged }: {
  character: string
  itemId: string
  bodies: FitBody[]
  /** The key of the body shown. */
  selected: string
  onSelect: (key: string) => void
  /** After an accept / undo: poll the panel again. */
  onChanged: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [busy, setBusy] = useState(false)
  const [after, setAfter] = useState<{ key: string; text: string } | null>(null)
  const shown = bodies.find((b) => b.key === selected) || bodies[0]
  if (!shown) return null

  const call = async (action: 'accept' | 'unaccept') => {
    setBusy(true)
    try {
      const res = await apiPost<{ follow_up?: FollowUp }>(
        `/characters/${encodeURIComponent(character)}/garments/${encodeURIComponent(itemId)}/fits/${
          encodeURIComponent(shown.key)}/${action}`, {})
      const due = followUpWords(res?.follow_up, t)
      const text = (action === 'accept' ? t('Accepted — nothing spent. Due now: {due}.')
        : t('Acceptance undone — the fit counts as refused again. Due now: {due}.')).replace('{due}', due)
      setAfter({ key: shown.key, text })
      toast(text)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
      onChanged()
    }
  }

  const legend: ReactNode = shown.marks.length ? (
    <div style={ROW} aria-label={t('Marked in the preview')}>
      <span className="ga-hint">{t('Marked in the preview')}:</span>
      {shown.marks.map((m) => (
        <span key={m.kind} style={{ ...ROW, gap: 4 }} className="ga-hint"
          title={t('{n} points the check counted').replace('{n}', String(m.count))}>
          <span aria-hidden style={{ width: 10, height: 10, borderRadius: 2, background: m.colour, display: 'inline-block' }} />
          {t(m.label)} ({m.count})
        </span>
      ))}
    </div>
  ) : null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={ROW} role="group" aria-label={t('Body shown')}>
        {bodies.map((b) => (
          <button key={b.key} type="button" aria-pressed={b.key === shown.key}
            className={`ga-btn ga-btn-sm${b.key === shown.key ? ' ga-btn-primary' : ''}`}
            title={[bodyVerdict(b, t), b.reason_detail, b.current ? t('The figure stands on this body now') : '']
              .filter(Boolean).join('\n')}
            onClick={() => onSelect(b.key)}>
            <span style={{ ...ROW, gap: 6, flexWrap: 'nowrap' }}>
              <StepLight light={LIGHT[b.status]} />
              {bodyWords(b.label, t)}
              {b.status === 'user_accepted'
                ? <span style={b.key === shown.key ? undefined : ACCEPTED}>· {t(ACCEPTED_BY_YOU)}</span> : null}
            </span>
          </button>
        ))}
      </div>
      {bodies.map((b) => (
        <div key={b.key} className="ga-hint"
          style={b.status === 'refused' ? REFUSED : b.status === 'user_accepted' ? ACCEPTED : undefined}
          title={b.reason_detail || undefined}>
          {b.key === shown.key ? '▸ ' : ''}{bodyVerdict(b, t)}
        </div>
      ))}
      {legend}
      {shown.status === 'refused' ? (
        <div style={ROW}>
          <button type="button" className="ga-btn ga-btn-sm" disabled={busy || !shown.can_accept}
            title={shown.can_accept
              ? t('Counts this fit as accepted everywhere until it, its body or the fit version changes. Spends no jobs; then due: re-assembly of the figure (CPU only).')
              : t(shown.accept_block)}
            onClick={() => { void call('accept') }}>
            {t('Accept this fit')}
          </button>
          <span className="ga-hint">
            {shown.can_accept ? t('No jobs. Then due: re-assembly of the figure (CPU only).') : t(shown.accept_block)}
          </span>
        </div>
      ) : null}
      {shown.status === 'user_accepted' ? (
        <div style={ROW}>
          <button type="button" className="ga-btn ga-btn-sm" disabled={busy}
            title={t('The fit counts as refused again. Spends no jobs; then due: re-assembly of the figure (CPU only).')}
            onClick={() => { void call('unaccept') }}>
            {t('Undo accept')}
          </button>
          <span className="ga-hint">{t('No jobs. Then due: re-assembly of the figure (CPU only).')}</span>
        </div>
      ) : null}
      {after && after.key === shown.key ? (
        <div className="ga-hint">
          {after.text} {t('The Figure tab shows it as due.')}
        </div>
      ) : null}
    </div>
  )
}
