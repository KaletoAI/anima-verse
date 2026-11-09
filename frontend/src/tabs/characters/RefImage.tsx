/**
 * RefImage — the ONE image tile of the character tabs (Base body, Pose with
 * the dressed outfit views, T-pose and extra views, Hair): the picture plus
 * two corner badges, and a click that opens it in the shared Lightbox.
 *
 * Lower left: when the image was made (`createdAt` — the sidecar's stamp,
 * else the file's mtime, both supplied by the server), formatted with the
 * shared clock settings. Lower right: "<model> · <W>×<H>" — the model from
 * the image's sidecar (`model`, else `service`; older images without one show
 * the size alone), the size read off the loaded bitmap itself
 * (naturalWidth/Height), i.e. what the file actually is, not what the config
 * asked for. When the two do not fit side by side, the time moves up a line.
 *
 * Backend payloads that carry `model` / `created_at`:
 * `model_refs.image_tile_meta` (model-refs info, base_info.image_meta,
 * garment_info image steps and their attempts).
 */
import { useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { useEnlarge } from '../../components/ZoomButton'
import { clockSettings, formatDateTime, useClockSettings } from '../../lib/clockFormat'

/** The tile meta the server hands along with an image URL. */
export interface ImageTileMeta {
  model?: string | null
  created_at?: string | null
}

const BADGE_STYLE: CSSProperties = {
  maxWidth: '100%',
  padding: '1px 5px',
  borderRadius: 4,
  background: 'rgba(0, 0, 0, 0.55)',
  color: '#fff',
  fontSize: 11,
  lineHeight: '16px',
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap',
  boxSizing: 'border-box',
}

/** Badge overrides for small tiles. */
const COMPACT_BADGE: CSSProperties = { padding: '0 3px', fontSize: 10, lineHeight: '14px' }

export function RefImage({
  src,
  height,
  width = '100%',
  radius = 6,
  label,
  meta,
  action,
  compact = false,
}: {
  src: string
  height: number
  width?: number | string
  radius?: number
  /** Lightbox alt text (which image this is). */
  label?: string
  /** Model and creation time of the image (server payload). */
  meta?: ImageTileMeta | null
  /** Control in the upper right corner (e.g. the regenerate button). */
  action?: ReactNode
  /** Small tile: smaller badges and insets. */
  compact?: boolean
}) {
  // Re-render once the server-configured clock format and timezone arrive.
  useClockSettings()
  const [size, setSize] = useState('')
  const [hidden, setHidden] = useState(false)
  const enlarge = useEnlarge()
  const zoom = enlarge({ src, alt: label || '' })
  const inset = compact ? 3 : 6
  const badge = compact ? { ...BADGE_STYLE, ...COMPACT_BADGE } : BADGE_STYLE
  const time = meta?.created_at ? formatDateTime(meta.created_at, clockSettings()) : ''
  const model = (meta?.model || '').trim()
  const right = [model, size].filter(Boolean).join(' · ')
  return (
    <div style={{ position: 'relative', width, flex: typeof width === 'number' ? 'none' : undefined }}>
      <img
        src={src}
        alt=""
        {...zoom}
        style={{
          ...zoom.style,
          display: 'block',
          width: '100%',
          height,
          objectFit: 'contain',
          borderRadius: radius,
          border: '1px solid var(--border, #30363d)',
          background: 'rgba(255, 255, 255, 0.04)',
          visibility: hidden ? 'hidden' : undefined,
        }}
        onLoad={(e) => {
          const im = e.target as HTMLImageElement
          setSize(`${im.naturalWidth}×${im.naturalHeight}`)
        }}
        onError={() => setHidden(true)}
      />
      {!hidden && (time || right) ? (
        <div
          style={{
            position: 'absolute',
            left: inset,
            right: inset,
            bottom: inset,
            display: 'flex',
            flexWrap: 'wrap',
            alignItems: 'flex-end',
            gap: 2,
            pointerEvents: 'none',
          }}
        >
          {time ? <span style={badge}>{time}</span> : null}
          {right ? <span style={{ ...badge, marginLeft: 'auto' }}>{right}</span> : null}
        </div>
      ) : null}
      {action ? (
        <div style={{ position: 'absolute', top: inset, right: inset }}>{action}</div>
      ) : null}
    </div>
  )
}
