/**
 * ErrorBoundary — fängt Render-/Laufzeitfehler in der Player-App ab, damit ein
 * Crash NICHT die ganze Oberfläche zu einer leeren grauen Fläche kollabieren
 * lässt. Zeigt stattdessen die Fehlermeldung + Stack inline an (kopierbar) und
 * bietet „Try again" / „Reload" — so ist die Ursache sofort sichtbar.
 */
import { Component, type ErrorInfo, type ReactNode } from 'react'

interface State { error: Error | null }

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Auch in die Konsole, damit der Stack mit Sourcemaps voll auflösbar ist.
    console.error('Player crashed:', error, info.componentStack)
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children
    return (
      <div style={{
        position: 'fixed', inset: 0, zIndex: 9999, overflow: 'auto',
        padding: 24, background: 'var(--bg, #0d1117)', color: 'var(--text, #e6edf3)',
        font: '13px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace',
      }}>
        <h2 style={{ color: '#ff7b7b', marginTop: 0 }}>Something crashed</h2>
        <p style={{ opacity: 0.8 }}>
          The player UI hit a render error. The details below pinpoint the cause.
        </p>
        <pre style={{
          whiteSpace: 'pre-wrap', wordBreak: 'break-word',
          background: 'rgba(255,255,255,0.05)', border: '1px solid var(--border, #30363d)',
          borderRadius: 8, padding: 12, maxHeight: '60vh', overflow: 'auto',
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
          <button onClick={() => window.location.reload()}
            style={{ padding: '6px 14px', borderRadius: 8, cursor: 'pointer',
              border: '1px solid var(--accent, #6aa9ff)', background: 'var(--accent, #6aa9ff)', color: '#fff' }}>
            Reload
          </button>
        </div>
      </div>
    )
  }
}
