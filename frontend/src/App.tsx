import { useCallback, useEffect, useState } from 'react'
import { useI18n } from './i18n/I18nProvider'
import { TABS, isTabId, type TabId } from './tabs/registry'
import { ErrorBoundary } from './components/ErrorBoundary'
import { useAuth } from './lib/AuthGate'

function readHashTab(): TabId {
  const raw = window.location.hash.replace(/^#\/?/, '').toLowerCase()
  return isTabId(raw) ? raw : 'characters'
}

export default function App() {
  const { t } = useI18n()
  const { user, logout } = useAuth()
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
    <div className="ga-shell">
      <header className="ga-header">
        <a className="ga-back" href="/" title={t('Back to chat')}>
          ← {t('Back to chat')}
        </a>
        <h1>{t('Game Admin')}</h1>
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 10 }}>
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
    </div>
  )
}
