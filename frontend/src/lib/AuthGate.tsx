/**
 * AuthGate — eigene Login/Logout-Schicht für die neuen React-UIs (Game-Admin +
 * Player). Ersetzt den alten Umweg „bei 401 → zur alten /-UI umleiten": prüft
 * GET /auth/status, zeigt bei fehlender Session ein eigenes Login-Formular und
 * rendert sonst die App. Stellt über useAuth() den User + logout() bereit.
 *
 * api.ts feuert bei 401/403(non-game) ein `auth:required`-Window-Event statt zur
 * alten UI zu springen — der Gate fängt es ab und zeigt das Login.
 */
import { createContext, useCallback, useContext, useEffect, useState, type CSSProperties, type ReactNode } from 'react'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet, apiPost } from './api'

export interface AuthUser {
  id: string
  username: string
  role: string
  allowed_characters?: string[]
}

interface AuthValue {
  user: AuthUser | null
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthValue | null>(null)

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthGate>')
  return ctx
}

type Status = 'loading' | 'in' | 'out'

export function AuthGate({ children }: { children: ReactNode }) {
  const { t } = useI18n()
  const [status, setStatus] = useState<Status>('loading')
  const [user, setUser] = useState<AuthUser | null>(null)

  const check = useCallback(async () => {
    try {
      const r = await apiGet<{ authenticated: boolean; user?: AuthUser }>('/auth/status')
      if (r.authenticated && r.user) { setUser(r.user); setStatus('in') }
      else { setUser(null); setStatus('out') }
    } catch {
      setUser(null); setStatus('out')
    }
  }, [])

  useEffect(() => { check() }, [check])

  // api.ts dispatches this instead of redirecting to the old UI on 401.
  useEffect(() => {
    const onRequired = () => { setUser(null); setStatus('out') }
    window.addEventListener('auth:required', onRequired)
    return () => window.removeEventListener('auth:required', onRequired)
  }, [])

  const logout = useCallback(async () => {
    try { await apiPost('/auth/logout', {}) } catch { /* ignore */ }
    setUser(null); setStatus('out')
  }, [])

  if (status === 'loading') {
    return <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', opacity: 0.6 }}>{t('Loading…')}</div>
  }
  if (status === 'out') {
    return <LoginForm onSuccess={(u) => { setUser(u); setStatus('in') }} />
  }
  return <AuthContext.Provider value={{ user, logout }}>{children}</AuthContext.Provider>
}

function LoginForm({ onSuccess }: { onSuccess: (u: AuthUser) => void }) {
  const { t } = useI18n()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = useCallback(async () => {
    if (!username.trim() || busy) return
    setBusy(true); setError('')
    try {
      const r = await apiPost<{ status: string; user: AuthUser }>('/auth/login', { username: username.trim(), password })
      if (r.user) {
        // Land back where the deep-link pointed (api.ts sets ?return=…), else stay.
        const ret = new URLSearchParams(window.location.search).get('return')
        if (ret && ret !== window.location.pathname) { window.location.href = ret; return }
        onSuccess(r.user)
      }
    } catch (e) {
      const status = (e as { status?: number }).status
      setError(status === 401 ? t('Wrong username or password.') : (e as Error).message)
    } finally {
      setBusy(false)
    }
  }, [username, password, busy, onSuccess, t])

  return (
    <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', padding: 24,
      background: 'var(--bg, #0d1117)', color: 'var(--text, #e6edf3)' }}>
      <form onSubmit={(e) => { e.preventDefault(); submit() }}
        style={{ display: 'flex', flexDirection: 'column', gap: 12, width: 'min(340px, 90vw)',
          background: 'var(--bg-container, #161b22)', border: '1px solid var(--border, #30363d)',
          borderRadius: 12, padding: 24, boxShadow: '0 8px 30px rgba(0,0,0,0.45)' }}>
        <div style={{ fontSize: '1.1em', fontWeight: 700, marginBottom: 4 }}>{t('Sign in')}</div>
        <label style={{ fontSize: '0.82em', opacity: 0.75 }}>{t('Username')}</label>
        <input autoFocus value={username} onChange={(e) => setUsername(e.target.value)} disabled={busy}
          style={inputStyle} />
        <label style={{ fontSize: '0.82em', opacity: 0.75 }}>{t('Password')}</label>
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} disabled={busy}
          style={inputStyle} />
        {error ? <div style={{ color: '#e05656', fontSize: '0.85em' }}>{error}</div> : null}
        <button type="submit" disabled={busy || !username.trim()}
          style={{ marginTop: 6, padding: '8px 12px', borderRadius: 8, border: 'none', cursor: 'pointer',
            background: 'var(--accent, #2f81f7)', color: '#fff', fontWeight: 600,
            opacity: busy || !username.trim() ? 0.6 : 1 }}>
          {busy ? '…' : t('Sign in')}
        </button>
      </form>
    </div>
  )
}

const inputStyle: CSSProperties = {
  background: 'var(--bg, #0d1117)', color: 'var(--text, #e6edf3)',
  border: '1px solid var(--border, #30363d)', borderRadius: 8, padding: '8px 10px', fontSize: '0.95em',
}
