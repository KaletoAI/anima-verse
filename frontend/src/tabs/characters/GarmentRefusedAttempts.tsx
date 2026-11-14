/**
 * GarmentRefusedAttempts — "Refused images" at the top of an own-mesh piece's dialog (Ruling A79; the Wardrobe's
 * "Mesh steps" and the Figure tab's Details open it). A view whose every attempt its checks refused holds the piece
 * up; the step grid below shows those attempts as tiny tiles, this panel puts them where the failure is read:
 *
 * - per refused view a block with its light (red: nothing accepted) and its name; per stored attempt a small
 *   thumbnail (a click enlarges it), its refusal reasons one line each in plain words (the measured numbers on
 *   mouse-over) and "Use this attempt" with its cost — no hub job for the click, then the hub jobs of what
 *   becomes due after it (the server's estimate, `use_runs`), the fit on the CPU. A refused attempt taken this way
 *   is "Accepted by you" (Ruling A37: voided when an image it was made from changes);
 * - the last "Use this" of the piece (`use_undo`): its light (yellow), what was taken, and "Undo — 0 hub jobs",
 *   which puts back the images, the mesh and the refusal of before (POST …/garments/{item}/images/undo-use); the
 *   lines under it say what comes back. When the image was replaced since, the reason stands instead of the button.
 *
 * Shown only when there is something to decide; the click goes through the dialog (`onUse` — the same call as
 * the grid's "Use this"; `onUndo`).
 */
import type { CSSProperties } from 'react'
import { useEnlarge } from '../../components/ZoomButton'
import { useI18n } from '../../i18n/I18nProvider'
import { clockSettings, formatDateTime } from '../../lib/clockFormat'
import { StepLight } from './StepRows'
import type { AttemptUsePlans, GarmentInfo, GarmentView } from './useGarment'
import {
  REFUSED_LIGHT, reasonWords, refusedViews, undoHeadline, undoLabel, undoLight, undoLines, attemptUseLabel,
  viewName,
} from './refusedAttemptsModel'
import type { UseUndoState } from './refusedAttemptsModel'

const BOX: CSSProperties = {
  display: 'flex', flexDirection: 'column', gap: 6, padding: '6px 8px', borderRadius: 6,
  border: '1px solid var(--border, #30363d)',
}
const HEAD: CSSProperties = { display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }
const GRID: CSSProperties = { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(230px, 1fr))', gap: 8 }
const TILE: CSSProperties = { display: 'flex', gap: 8, alignItems: 'flex-start' }
const THUMB: CSSProperties = { width: 64, height: 84, objectFit: 'cover', borderRadius: 4,
  border: '1px solid var(--danger, #f85149)', flex: '0 0 auto' }
const LINES: CSSProperties = { margin: 0, paddingLeft: 16, fontSize: '0.8em' }

export function GarmentRefusedAttempts({ garment, useRuns, useUndo, busy, onUse, onUndo }: {
  garment: GarmentInfo | null
  useRuns: AttemptUsePlans | null | undefined
  useUndo: UseUndoState | null | undefined
  busy: boolean
  onUse: (step: string, view: GarmentView, attempt: number) => void
  onUndo: () => void
}) {
  const { t } = useI18n()
  const enlarge = useEnlarge()
  const views = refusedViews(garment, useRuns)
  if (!views.length && !useUndo) return null
  return (
    <div style={BOX} role="region" aria-label={t('Refused images')}>
      {views.length ? (
        <span style={{ fontWeight: 600 }}>{t('Refused images')}</span>
      ) : null}
      {views.map((v) => {
        const name = viewName(v.step, v.view, t)
        return (
          <div key={`${v.step}:${v.view}`} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <div style={HEAD}>
              <StepLight light={REFUSED_LIGHT}
                title={t('Every attempt of this view was refused by its checks — nothing is accepted, the steps after it wait')} />
              <span>{name}</span>
              <span className="ga-hint">
                · {t('every attempt refused — use one by hand if it looks right to you')}
              </span>
            </div>
            <div style={GRID}>
              {v.attempts.map((a) => {
                const alt = `${name} · ${t('Attempt')} ${a.attempt}`
                const zoom = enlarge({ src: a.url, alt })
                const plan = a.plan
                const label = attemptUseLabel(plan, t)
                const tip = [
                  label,
                  t('The click itself spends no hub job.'),
                  t('Its checks refused it: you accept it ("Accepted by you"). Any change of an image it was made from voids that.'),
                  plan?.follow_up ? `${t('Then due')}: ${plan.follow_up.note}` : '',
                  t('Undo puts back what was there before.'),
                ].filter(Boolean).join('\n')
                return (
                  <div key={a.attempt} style={TILE}>
                    <img src={a.url} alt={alt} {...zoom} title={`${alt}\n${t('Click to enlarge')}`}
                      style={{ ...zoom.style, ...THUMB }} />
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0 }}>
                      <span className="ga-hint">
                        {t('Attempt')} {a.attempt}
                        {a.created_at ? ` · ${t('Rendered')} ${formatDateTime(a.created_at, clockSettings())}` : ''}
                      </span>
                      <ul style={LINES}>
                        {(a.reasons.length ? a.reasons : [t('Refused')]).map((r) => {
                          const w = reasonWords(r, t)
                          return <li key={r} title={w.detail}>{w.text}</li>
                        })}
                      </ul>
                      {plan?.in_use ? (
                        <span className="ga-hint">{t('In use')}</span>
                      ) : (
                        <button type="button" className="ga-btn ga-btn-sm" disabled={busy || !plan || !!plan.block}
                          title={plan?.block ? t(plan.block) : tip} onClick={() => onUse(v.step, v.view, a.attempt)}>
                          {label}
                        </button>
                      )}
                      {plan?.block ? <span className="ga-hint">{t(plan.block)}</span> : null}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )
      })}
      {useUndo ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div style={HEAD}>
            <StepLight light={undoLight(useUndo)}
              title={useUndo.available ? t('Taken by hand — the steps after it are due') : t(useUndo.why_not)} />
            <span>{undoHeadline(useUndo, t)}</span>
            {useUndo.at ? (
              <span className="ga-hint">· {formatDateTime(useUndo.at, clockSettings())}</span>
            ) : null}
            {useUndo.available ? (
              <button type="button" className="ga-btn ga-btn-sm" disabled={busy}
                title={[t('Puts back what was there before this “Use this”:'), ...undoLines(useUndo, t)].join('\n')}
                onClick={onUndo}>
                {undoLabel(t)}
              </button>
            ) : (
              <span className="ga-hint">{t(useUndo.why_not)}</span>
            )}
          </div>
          {useUndo.available ? (
            <ul style={LINES} className="ga-hint" aria-label={t('What Undo puts back')}>
              {undoLines(useUndo, t).map((line) => <li key={line}>{line}</li>)}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
