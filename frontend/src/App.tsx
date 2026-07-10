import { useCallback, useEffect, useState } from 'react'
import { useI18n } from './i18n/I18nProvider'
import { TABS, isTabId, type TabId } from './tabs/registry'
import { ErrorBoundary } from './components/ErrorBoundary'
import { GenerationIndicator } from './components/GenerationIndicator'
import { FreezeToggle } from './components/FreezeToggle'
import { SleepToggle } from './components/SleepToggle'
import { GameClock } from './components/GameClock'
import { useAuth } from './lib/AuthGate'
import { HelpProvider } from './help/HelpContext'
import { HelpPanel } from './help/HelpPanel'

function readHashTab(): TabId {
  const raw = window.location.hash.replace(/^#\/?/, '').toLowerCase()
  return isTabId(raw) ? raw : 'characters'
}

// Verfügbare UI-Sprachen (es existiert nur de.json; Englisch = Quelle).
const UI_LANGS = [
  { v: 'de', l: 'Deutsch' },
  { v: 'en', l: 'English' },
]

export default function App() {
  const { t, lang, setLang } = useI18n()
  const { user, logout } = useAuth()
  // Aktuelle Sprache immer als Option zeigen (z.B. Browser-Default 'fr').
  const langOpts = UI_LANGS.some((o) => o.v === lang) ? UI_LANGS : [{ v: lang, l: lang }, ...UI_LANGS]
  const [active, setActive] = useState<TabId>(readHashTab)

  useEffect(() => {
    const onHashChange = () => setActive(readHashTab())
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  const select = useCallback((id: TabId) => {
    window.location.hash = `#/${id}`
    setActive(id)
  }, [])

  const ActiveComponent = TABS.find((tab) => tab.id === active)?.Component

  return (
    <HelpProvider>
    <div className="ga-shell">
      <header className="ga-header">
        <a className="ga-back" href="/" title={t('Back to chat')}>
          ← {t('Back to chat')}
        </a>
        <h1>{t('Game Admin')}</h1>
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 10 }}>
          <GameClock />
          <FreezeToggle />
          <SleepToggle />
          <GenerationIndicator />
          <select
            className="ga-input"
            style={{ width: 'auto', padding: '3px 8px', fontSize: '0.85em' }}
            value={lang}
            onChange={(e) => setLang(e.target.value)}
            title={t('Language')}
            aria-label={t('Language')}
          >
            {langOpts.map((o) => (
              <option key={o.v} value={o.v}>
                {o.l}
              </option>
            ))}
          </select>
          {user ? <span style={{ opacity: 0.7, fontSize: '0.85em' }}>{user.username}</span> : null}
          <button className="ga-btn ga-btn-sm" onClick={() => { void logout() }}>{t('Logout')}</button>
        </div>
      </header>
      <nav className="ga-tabs" role="tablist">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            role="tab"
            aria-selected={active === tab.id}
            className={`ga-tab${active === tab.id ? ' is-active' : ''}`}
            onClick={() => select(tab.id)}
          >
            {t(tab.label)}
          </button>
        ))}
      </nav>
      <main className="ga-body">
        {ActiveComponent ? (
          <ErrorBoundary key={active}>
            <ActiveComponent />
          </ErrorBoundary>
        ) : (
          <div className="ga-placeholder">{t('Unknown tab')}</div>
        )}
      </main>
      <HelpPanel />
    </div>
    </HelpProvider>
  )
}
