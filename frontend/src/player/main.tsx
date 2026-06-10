import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { PlayerApp } from './PlayerApp.tsx'
import { ErrorBoundary } from './ErrorBoundary.tsx'
import { I18nProvider } from '../i18n/I18nProvider.tsx'
import { ToastProvider } from '../lib/Toast.tsx'
import '../styles/game-admin.css'
import 'react-grid-layout/css/styles.css'
import 'react-resizable/css/styles.css'
import './player.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <I18nProvider>
      <ToastProvider>
        <ErrorBoundary>
          <PlayerApp />
        </ErrorBoundary>
      </ToastProvider>
    </I18nProvider>
  </StrictMode>,
)
