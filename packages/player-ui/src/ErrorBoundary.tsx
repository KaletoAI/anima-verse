/**
 * ErrorBoundary — catches render/runtime errors so ONE broken panel cannot
 * collapse the whole surface into a blank area.
 *
 * Two shapes, because the two hosts fail differently:
 * - `/play` wraps the whole app in the FULL-SCREEN variant (default): there is
 *   nothing left to operate anyway, so the error sheet takes the viewport.
 * - the 3D HUD wraps EACH panel in the `inline` variant: the rail, the chat
 *   and the scene behind them are still perfectly usable, so a failing panel
 *   must report inside its own frame and nowhere else. Without this the HUD
 *   island unmounted entirely on any panel error — every HUD element gone at
 *   once, with nothing on screen naming the cause.
 *
 * Either way the message and the stack are shown verbatim and copyable, plus
 * "Try again" — a re-render is often enough after a transient payload.
 */
import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
  /** render inside the surrounding box instead of over the whole viewport */
  inline?: boolean
  /** shown above the message, e.g. the panel name — so a HUD with several
   *  panels says WHICH one failed */
  label?: string
}
interface State { error: Error | null }

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Into the console as well, so the stack resolves fully via source maps.
    console.error(`${this.props.label || 'Player'} crashed:`, error, info.componentStack)
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children
    const inline = !!this.props.inline
    return (
      <div style={{
        ...(inline
          ? { height: '100%', overflow: 'auto' }
          : { position: 'fixed', inset: 0, zIndex: 9999, overflow: 'auto',
              background: 'var(--bg, #0d1117)' }),
        padding: inline ? 10 : 24,
        color: 'var(--text, #e6edf3)',
        font: '13px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace',
      }}>
        <h2 style={{ color: '#ff7b7b', marginTop: 0, fontSize: inline ? '1em' : undefined }}>
          {this.props.label ? `${this.props.label} crashed` : 'Something crashed'}
        </h2>
        {!inline && (
          <p style={{ opacity: 0.8 }}>
            The player UI hit a render error. The details below pinpoint the cause.
          </p>
        )}
        <pre style={{
          whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: inline ? '0.85em' : undefined,
          background: 'rgba(255,255,255,0.05)', border: '1px solid var(--border, #30363d)',
          borderRadius: 8, padding: inline ? 8 : 12, maxHeight: '60vh', overflow: 'auto',
        }}>
          {String(error?.message || error)}
          {error?.stack ? '\n\n' + error.stack : ''}
        </pre>
        <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
          <button onClick={() => this.setState({ error: null })}
            style={{ padding: '6px 14px', borderRadius: 8, cursor: 'pointer',
              border: '1px solid var(--border, #30363d)', background: 'transparent', color: 'inherit' }}>
            Try again
          </button>
          {!inline && (
            <button onClick={() => window.location.reload()}
              style={{ padding: '6px 14px', borderRadius: 8, cursor: 'pointer',
                border: '1px solid var(--accent, #6aa9ff)', background: 'var(--accent, #6aa9ff)', color: '#fff' }}>
              Reload
            </button>
          )}
        </div>
      </div>
    )
  }
}
