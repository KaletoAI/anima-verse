/**
 * ViewRenderTile — one view of a "views in one row" strip (Ruling A90: the Base body tab's four views side by side):
 * the view's light and name, its state in one word under it in the light's colour, the picture small (RefImage — a
 * click enlarges it, the freshness badge comes with its `meta`, the server decides it), then the view's own button
 * with its cost in short form ("↻ 1 image + 4 hub") — the long sentence (what it renders, what it makes stale) is its
 * mouse-over. Under it, each in one line with the whole on mouse-over: the reason of a yellow or red light, the run
 * state, why the button waits, the failure and the kept warning. A `note` dims the picture and says what it really
 * is (a picture that is not the current view it stands for).
 *
 * The caller decides everything (what the button starts and says, why it is disabled); the tile only renders.
 */
import type { ReactNode } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { RefImage } from './RefImage'
import type { ImageTileMeta } from './RefImage'
import { LIGHT_COLOR } from './stepStyle'

const ONE_LINE = 'ga-hint ga-one-line'

export function ViewRenderTile({ label, state, stateColor, reason, lead, url, meta, height, running, status, failed,
  error, warning, disabled, disabledTitle, disabledReason, note, actionLabel, actionTitle, onRender }: {
  /** The view's name. */
  label: string
  /** Its state in one word, written under the name in `stateColor`. */
  state?: string
  stateColor?: string
  /** The reason of a yellow or red light (one line, the whole on mouse-over); "" for none. */
  reason?: string
  /** Before the name, e.g. the view's step light. */
  lead?: ReactNode
  url: string | null
  meta?: ImageTileMeta | null
  height: number
  /** The view renders now. */
  running: boolean
  /** An extra block under the tile (e.g. the front's skin detail step). */
  status?: ReactNode
  /** The view's last render failed (shown while it does not run), with its error. */
  failed?: boolean
  error?: string | null
  /** The kept image's warning (shown while it does not run). */
  warning?: string | null
  disabled: boolean
  /** Why the button is disabled (its tooltip then). */
  disabledTitle?: string
  /** Why the button is disabled, shown as a line under the tile (and as its tooltip). */
  disabledReason?: string
  /** The image is not the current view it stands for: shown dimmed with this line under it. */
  note?: string
  /** The button's words with the cost in short form; without one "Regenerate" / "Generate". */
  actionLabel?: string
  /** The button's tooltip otherwise: the whole sentence with its cost and what it makes stale. */
  actionTitle?: string
  onRender: () => void
}) {
  const { t } = useI18n()
  const action = url ? t('Regenerate') : t('Generate')
  // The failure and the warning are said in their own lines below; the reason line is for the rest (a stale view).
  const shownReason = reason && reason !== error && reason !== warning ? reason : ''
  return (
    <div className="ga-view-tile">
      <div className="ga-view-head">
        {lead}<strong className="ga-one-line" title={label}>{label}</strong>
      </div>
      {state ? <div className={ONE_LINE} style={{ color: stateColor }} title={state}>{state}</div> : null}
      {url ? (
        <div style={note ? { opacity: 0.45 } : undefined}>
          <RefImage key={url} src={url} height={height} label={label} meta={meta} compact />
        </div>
      ) : (
        <div className="ga-hint ga-ref-empty" style={{ height }}>
          {running ? t('Generating…') : t('No render yet')}
        </div>
      )}
      <button
        type="button"
        className="ga-btn ga-btn-sm ga-view-action"
        disabled={disabled || running}
        title={(disabled && (disabledReason || disabledTitle)) || actionTitle || undefined}
        onClick={onRender}
        aria-label={`${action} · ${label}`}
      >
        {actionLabel || action}
      </button>
      {shownReason && !running ? (
        <div className={ONE_LINE} style={{ color: stateColor }} title={shownReason}>{shownReason}</div>
      ) : null}
      {url && running ? <div className={ONE_LINE}>{t('Generating…')}</div> : null}
      {url && note ? <div className={ONE_LINE} style={{ color: LIGHT_COLOR.yellow }} title={note}>{note}</div> : null}
      {disabled && !running && disabledReason ? (
        <div className={ONE_LINE} style={{ fontStyle: 'italic' }} title={disabledReason}>{disabledReason}</div>
      ) : null}
      {failed && !running ? (
        <div className={ONE_LINE} style={{ color: LIGHT_COLOR.red }} title={error || ''}>
          {t('Failed')}{error ? `: ${error}` : ''}
        </div>
      ) : null}
      {url && warning && !running ? (
        <div className={ONE_LINE} style={{ color: LIGHT_COLOR.yellow }} title={warning}>{warning}</div>
      ) : null}
      {status}
    </div>
  )
}
