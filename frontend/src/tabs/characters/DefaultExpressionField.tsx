/** The default image is displayed independently of an explicit render attempt. */
import { useEffect, useState } from 'react'
import { useExpressionAttempt } from '@anima/player-ui'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'
import { openLightbox } from '../../components/Lightbox'

export function DefaultExpressionField({ character }: { character: string }) {
  const { t } = useI18n()
  const generation = useExpressionAttempt(character)
  const [ready, setReady] = useState<boolean | null>(null)
  const [version, setVersion] = useState(() => String(Date.now()))
  const enc = encodeURIComponent(character)
  const src = `/characters/${enc}/outfit-expression?override=1&v=${encodeURIComponent(generation.contentVersion || version)}`
  useEffect(() => { setReady(null); setVersion(String(Date.now())) }, [character])
  // A queued NPC finishing job may publish later; observe it without triggering.
  useEffect(() => {
    if (ready !== false || generation.busy || generation.error) return
    let alive = true
    let timer: ReturnType<typeof setTimeout>
    let polls = 0
    const poll = async () => {
      try {
        const status = await apiGet<{ state: string; content_version: string }>(`/characters/${enc}/expression-status?override=1`)
        if (!alive) return
        if (status.content_version) { setVersion(status.content_version); return }
      } catch { /* A deleted character or interrupted server leaves the empty state. */ }
      if (alive && ++polls < 225) timer = setTimeout(() => { void poll() }, 4000)
    }
    timer = setTimeout(() => { void poll() }, 4000)
    return () => { alive = false; clearTimeout(timer) }
  }, [ready, generation.busy, generation.error, enc])
  return <div style={{ display: 'flex', flexDirection: 'column', gap: 8, height: '100%', minHeight: 0 }}>
    <p className="ga-field-hint">{t('The default expression follows the selected set and outfit, not the current activity.')}</p>
    <div style={{ position: 'relative', flex: 1, minHeight: 320, border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
      <img src={src} alt={t('Default expression')} onLoad={() => setReady(true)} onError={() => setReady(false)}
        onClick={() => { if (ready) openLightbox({ src, alt: t('Default expression') }) }}
        style={{ width: '100%', height: '100%', objectFit: 'contain', display: ready ? 'block' : 'none', cursor: 'zoom-in' }} />
      {generation.busy && <span role="status" className="ga-tag" style={{ position: 'absolute', top: 8, left: 8 }}>{t('Rendering…')}</span>}
      {ready === false && <p className="ga-placeholder">{t('No default expression yet')}</p>}
    </div>
    {generation.error && <p role="alert" style={{ color: 'var(--error)' }}>{generation.error}</p>}
    <button type="button" className="ga-btn ga-btn-sm" disabled={generation.busy}
      onClick={() => void generation.start({ override: true, pieces: {}, items: [], force: true })}>
      {generation.busy ? t('Rendering…') : t('Re-render default expression')}
    </button>
  </div>
}
