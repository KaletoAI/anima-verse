/**
 * ImagePicker — WHICH picture goes on a key surface of a prop.
 *
 * Two steps and no third: a SOURCE (one of this world's places, or a
 * character) and then a picture out of that gallery, picked from thumbnails.
 * A poster is chosen by looking at it — a file-name dropdown (what the
 * placement editor had) makes an admin open the gallery in another tab to find
 * out what `img_0037.png` is.
 *
 * It builds only the two URL forms the server accepts, both out of
 * `imagePicker.ts` (`locUrl` / `charUrl`) — nothing here knows a route. The
 * stored value IS that URL, so the source reads back off it and needs no state
 * of its own; the one thing that does is "source picked, no picture yet",
 * which is not a storable state (an empty value is no value).
 */
import { useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { loadLocations, type LocationRef } from '../../lib/refs'
import { ZoomButton } from '../../components/ZoomButton'
import { charUrl, fileOf, locUrl, sourceOf, useCharacterImages,
  useCharacterNames, useLocationImages } from './imagePicker'

/** The world's places, once per mounted picker. The character roster has its
 *  own hook next door; a place list has none yet and is small enough to fetch
 *  here rather than to invent a cache for. */
function useLocations(): LocationRef[] {
  const [locations, setLocations] = useState<LocationRef[]>([])
  useEffect(() => {
    let stale = false
    loadLocations()
      .then((ls) => { if (!stale) setLocations(ls) })
      .catch(() => { if (!stale) setLocations([]) })
    return () => { stale = true }
  }, [])
  return locations
}

/** The location id out of a stored gallery URL ('' = not a location URL).
 *  `sourceOf` says WHICH KIND of gallery a URL names; only the location id
 *  itself has to be read back here, because the picker offers every place and
 *  has to reopen on the right one. */
function locationOf(url: string): string {
  const m = /^\/world\/locations\/([^/]+)\/gallery\//.exec(url || '')
  return m ? decodeURIComponent(m[1]) : ''
}

export function ImagePicker({ value, onChange, height = 150 }: {
  /** The stored image URL ('' = nothing picked). */
  value: string
  /** The new URL, or '' when the pick was cleared. */
  onChange: (url: string) => void
  /** Height of the thumbnail strip in pixels. */
  height?: number
}) {
  const { t } = useI18n()
  const locations = useLocations()
  const names = useCharacterNames()
  // "Source picked, no picture yet" cannot be stored — the URL would read back
  // as "nothing chosen" and the select would snap shut the moment it was
  // opened. Same answer as the placement editor's: a local flag, consulted
  // only while nothing is stored.
  const [pending, setPending] = useState('')
  const stored = value || ''
  const kind = sourceOf(stored)
  const source = stored
    ? (kind === 'loc' ? `l:${locationOf(stored)}` : kind)
    : pending
  const character = source.startsWith('c:') ? source.slice(2) : ''
  const location = source.startsWith('l:') ? source.slice(2) : ''
  const locImages = useLocationImages(location)
  const charImages = useCharacterImages(character)
  const files = character ? charImages : locImages
  const picked = fileOf(stored)
  const urlOf = (file: string) => (character
    ? charUrl(character, file)
    : locUrl(location, file))

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <select
        className="ga-input"
        value={source}
        title={t('Where the picture comes from — a place’s gallery or a character’s images.')}
        onChange={(e) => {
          setPending(e.target.value)
          // Another gallery cannot keep the file: the name means a picture in
          // the old one. Staying on the same source keeps the pick.
          if (e.target.value !== source) onChange('')
        }}
      >
        <option value="">{t('— pick a source —')}</option>
        <optgroup label={t('Places')}>
          {locations.map((l) => (
            <option key={l.id} value={`l:${l.id}`}>{l.name || l.id}</option>
          ))}
        </optgroup>
        <optgroup label={t('Characters')}>
          {names.map((n) => <option key={n} value={`c:${n}`}>{n}</option>)}
        </optgroup>
      </select>
      {source ? (
        <div
          style={{
            display: 'flex', gap: 4, overflowX: 'auto', height,
            padding: 2, alignItems: 'flex-start',
            border: '1px solid var(--border, #30363d)', borderRadius: 6,
          }}
        >
          {files.length ? files.map((f) => {
            const on = f === picked
            return (
              <button
                key={f} type="button"
                onClick={() => onChange(on ? '' : urlOf(f))}
                title={f}
                style={{
                  flex: '0 0 auto', padding: 0, cursor: 'pointer',
                  borderRadius: 6, background: 'transparent', position: 'relative',
                  border: on ? '2px solid var(--accent, #58a6ff)'
                    : '2px solid transparent',
                }}
              >
                <img
                  src={urlOf(f)} alt={f}
                  style={{ height: height - 12, width: 'auto', borderRadius: 4,
                    display: 'block', objectFit: 'cover' }}
                />
                <ZoomButton item={{ src: urlOf(f), alt: f }} />
              </button>
            )
          }) : (
            <span className="ga-hint" style={{ padding: 4 }}>
              {t('This gallery has no pictures.')}
            </span>
          )}
        </div>
      ) : null}
      {/* A picked file the gallery does not list any more keeps its place —
          a deleted picture must not silently empty the frame. */}
      {picked && files.length > 0 && !files.includes(picked) ? (
        <span className="ga-hint">{`${picked} ${t('(missing)')}`}</span>
      ) : null}
    </div>
  )
}
