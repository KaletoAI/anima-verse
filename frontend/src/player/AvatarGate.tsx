/**
 * AvatarGate — Avatar-Auswahl für die Player-UI (nach Login). Prüft den aktiven
 * Avatar (GET /account/characters): ist keiner gesetzt und gibt es mehrere
 * spielbare Characters, erscheint eine Auswahl (Karten mit Profilbild + Name);
 * bei genau einem wird automatisch gewählt. Mit gesetztem Avatar (oder gar
 * keinem verfügbaren) rendert es direkt die App.
 *
 * Wrappt PlayerApp INNERHALB des AuthGate (player/main.tsx). Stellt über
 * useAvatarSwitch() ein chooseAvatar() bereit, damit die Toolbar den Avatar
 * auch im Spiel wechseln kann.
 */
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet, apiPost } from '../lib/api'

interface AvatarSwitchValue { chooseAvatar: () => void }
const AvatarSwitchContext = createContext<AvatarSwitchValue | null>(null)
export function useAvatarSwitch(): AvatarSwitchValue {
  return useContext(AvatarSwitchContext) || { chooseAvatar: () => {} }
}

type Status = 'loading' | 'choosing' | 'ready'

export function AvatarGate({ children }: { children: ReactNode }) {
  const { t } = useI18n()
  const [status, setStatus] = useState<Status>('loading')
  const [characters, setCharacters] = useState<string[]>([])
  const [active, setActive] = useState<string>('')
  const [busy, setBusy] = useState('')

  const load = useCallback(async (forceChoose = false) => {
    try {
      const r = await apiGet<{ characters: string[]; active_character: string }>('/account/characters')
      const chars = r.characters || []
      setCharacters(chars)
      setActive(r.active_character || '')
      if (forceChoose) { setStatus(chars.length ? 'choosing' : 'ready'); return }
      if (r.active_character) { setStatus('ready'); return }
      if (chars.length === 1) { await pick(chars[0]); return }
      setStatus(chars.length ? 'choosing' : 'ready')
    } catch {
      setStatus('ready') // auth handled elsewhere; let the app render its own empty state
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const pick = useCallback(async (name: string) => {
    setBusy(name)
    try {
      await apiPost('/account/switch-character', { character_name: name })
      setActive(name)
      setStatus('ready')
    } catch { /* stay on chooser */ } finally { setBusy('') }
  }, [])

  useEffect(() => { load() }, [load])

  const value: AvatarSwitchValue = { chooseAvatar: () => load(true) }

  if (status === 'loading') {
    return <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', opacity: 0.6 }}>{t('Loading…')}</div>
  }
  if (status === 'choosing') {
    return (
      <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', padding: 24,
        background: 'var(--bg, #0d1117)', color: 'var(--text, #e6edf3)' }}>
        <div style={{ width: 'min(720px, 94vw)' }}>
          <div style={{ fontSize: '1.2em', fontWeight: 700, marginBottom: 14 }}>{t('Choose your avatar')}</div>
          {characters.length === 0 ? (
            <div style={{ opacity: 0.7 }}>{t('No playable characters available.')}</div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 12 }}>
              {characters.map((name) => (
                <button key={name} onClick={() => pick(name)} disabled={!!busy} title={name}
                  style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8, padding: 12,
                    borderRadius: 12, cursor: 'pointer', color: 'inherit',
                    border: name === active ? '2px solid var(--accent,#2f81f7)' : '1px solid var(--border,#30363d)',
                    background: 'var(--bg-container,#161b22)', opacity: busy && busy !== name ? 0.5 : 1 }}>
                  <img src={`/characters/${encodeURIComponent(name)}/images/profile`} alt=""
                    onError={(e) => { (e.currentTarget as HTMLImageElement).style.visibility = 'hidden' }}
                    style={{ width: 96, height: 96, borderRadius: '50%', objectFit: 'cover',
                      background: 'rgba(255,255,255,0.05)' }} />
                  <span style={{ fontWeight: 600, fontSize: '0.9em', textAlign: 'center' }}>
                    {busy === name ? '…' : name}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    )
  }
  return <AvatarSwitchContext.Provider value={value}>{children}</AvatarSwitchContext.Provider>
}
