import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.tsx'
import { I18nProvider } from './i18n/I18nProvider.tsx'
import { ToastProvider } from './lib/Toast.tsx'
import { AuthGate } from './lib/AuthGate.tsx'
import './styles/game-admin.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <I18nProvider>
      <ToastProvider>
        <AuthGate>
          <App />
        </AuthGate>
      </ToastProvider>
    </I18nProvider>
  </StrictMode>,
)
