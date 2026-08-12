// Bundle entry for the MapTab auto-fit check. Paths are relative to this file
// (scripts/), so the bundler resolves them no matter where the repo lives.
import React from '../node_modules/react/index.js'
import { createRoot } from '../node_modules/react-dom/client.js'
import { I18nProvider } from '../frontend/src/i18n/I18nProvider.tsx'
import { ToastProvider } from '../frontend/src/lib/Toast.tsx'
import { MapTab } from '../frontend/src/tabs/map/MapTab.tsx'

globalThis.__mountMapTab = (el) => {
  const root = createRoot(el)
  root.render(
    React.createElement(I18nProvider, null,
      React.createElement(ToastProvider, null,
        React.createElement(MapTab, null))))
  return root
}
