/**
 * ChatGalleryPicker — modal grid that lets the avatar attach an existing
 * character-library image to a chat message (feature #6). Reads
 * GET /chat/{user}/image-library (user segment is ignored server-side) and
 * groups thumbnails per character. Picking one hands its display URL back to
 * the composer, which attaches it as `image_url` on the next send.
 *
 * Rendered via a portal — the composer lives inside react-grid-layout's
 * transform context, where a position:fixed modal would otherwise be clipped.
 */
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet } from '../lib/api'

interface LibImage {
  filename: string
  url: string
}

export function ChatGalleryPicker({
  onPick,
  onClose,
}: {
  onPick: (url: string) => void
  onClose: () => void
}) {
  const { t } = useI18n()
  const [lib, setLib] = useState<Record<string, LibImage[]> | null>(null)

  useEffect(() => {
    apiGet<{ characters?: Record<string, LibImage[]> }>('/chat/me/image-library')
      .then((d) => setLib(d.characters || {}))
      .catch(() => setLib({}))
  }, [])

  const names = lib ? Object.keys(lib).filter((n) => (lib[n] || []).length) : []

  return createPortal(
    <div className="ga-modal-backdrop" onMouseDown={onClose}>
      <div
        className="ga-modal"
        style={{ maxWidth: 720 }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="ga-modal-header">
          <span>{t('Pick an image')}</span>
          <button className="ga-modal-close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="ga-modal-body">
          {lib == null ? (
            <div className="ga-loading">{t('Loading…')}</div>
          ) : names.length === 0 ? (
            <div className="ga-placeholder">{t('No images available.')}</div>
          ) : (
            names.map((name) => (
              <div key={name} style={{ marginBottom: 12 }}>
                <div
                  style={{
                    fontSize: '0.8em',
                    textTransform: 'uppercase',
                    letterSpacing: 0.4,
                    opacity: 0.7,
                    marginBottom: 6,
                  }}
                >
                  {name}
                </div>
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fill, minmax(96px, 1fr))',
                    gap: 8,
                  }}
                >
                  {(lib![name] || []).map((img) => (
                    <button
                      key={img.filename}
                      type="button"
                      onClick={() => onPick(img.url)}
                      title={img.filename}
                      style={{
                        padding: 0,
                        border: '1px solid var(--border, #30363d)',
                        borderRadius: 6,
                        overflow: 'hidden',
                        cursor: 'pointer',
                        background: 'none',
                        aspectRatio: '1 / 1',
                      }}
                    >
                      <img
                        src={img.url}
                        alt={img.filename}
                        style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
                      />
                    </button>
                  ))}
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}
