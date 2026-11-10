/**
 * ViewRenderTile — one view image of the Base body and Outfit body tabs with
 * its own render action: the view's name and a Generate / Regenerate button
 * above the tile (RefImage — the freshness badge comes with its `meta`, the
 * server decides it), below it the run state ("Generating…", a caller's
 * status line such as the queue place with Cancel), the failure and the
 * kept warning of the view.
 *
 * The caller decides everything (what the button starts, why it is
 * disabled); the tile only renders.
 */
import type { CSSProperties, ReactNode } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { RefImage } from './RefImage'
import type { ImageTileMeta } from './RefImage'

const ERROR_STYLE: CSSProperties = { color: 'var(--danger, #f85149)', overflowWrap: 'anywhere' }
const WARNING_STYLE: CSSProperties = { color: 'var(--warning, #d29922)', overflowWrap: 'anywhere' }

function emptyTile(height: number): CSSProperties {
  return {
    width: '100%',
    height,
    borderRadius: 6,
    border: '1px solid var(--border, #30363d)',
    background: 'rgba(255, 255, 255, 0.04)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    textAlign: 'center',
    padding: 6,
    boxSizing: 'border-box',
  }
}

export function ViewRenderTile({ label, url, meta, height, running, status, failed, error, warning, disabled,
  disabledTitle, actionTitle, onRender }: {
  label: string
  url: string | null
  meta?: ImageTileMeta | null
  height: number
  /** The view renders now. */
  running: boolean
  /** An extra line under the tile (e.g. the queue place with Cancel). */
  status?: ReactNode
  /** The view's last render failed (shown while it does not run), with its error. */
  failed?: boolean
  error?: string | null
  /** The kept image's warning (shown while it does not run). */
  warning?: string | null
  disabled: boolean
  /** Why the button is disabled (its tooltip then). */
  disabledTitle?: string
  /** The button's tooltip otherwise. */
  actionTitle?: string
  onRender: () => void
}) {
  const { t } = useI18n()
  const action = url ? t('Regenerate') : t('Generate')
  return (
    <div style={{ minWidth: 0 }}>
      <div className="ga-face-actions-row" style={{ justifyContent: 'space-between', marginBottom: 2 }}>
        <span className="ga-hint">{label}</span>
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          disabled={disabled || running}
          title={(disabled && disabledTitle) || actionTitle || undefined}
          onClick={onRender}
          aria-label={`${action} · ${label}`}
        >
          {action}
        </button>
      </div>
      {url ? (
        <RefImage key={url} src={url} height={height} label={label} meta={meta} compact />
      ) : (
        <div className="ga-hint" style={emptyTile(height)}>
          {running ? t('Generating…') : t('No render yet')}
        </div>
      )}
      {url && running ? <div className="ga-hint">{t('Generating…')}</div> : null}
      {status}
      {failed && !running ? (
        <div className="ga-hint" style={ERROR_STYLE} title={error || ''}>
          {t('Failed')}{error ? `: ${error}` : ''}
        </div>
      ) : null}
      {url && warning && !running ? (
        <div className="ga-hint" style={WARNING_STYLE} title={warning}>{warning}</div>
      ) : null}
    </div>
  )
}
