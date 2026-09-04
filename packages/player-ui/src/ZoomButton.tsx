/**
 * ZoomButton / useEnlarge — the two ways an image gets its "enlarge" affordance.
 *
 * - `useEnlarge()` returns a props factory for images that are PURELY
 *   presentational: spread `enlarge({ src, alt })` onto the `<img>` and it
 *   becomes a keyboard-operable zoom-in control that opens the shared Lightbox.
 * - `<ZoomButton item={…} />` is the small magnifier for images that sit
 *   inside a control whose click does something else (select, toggle, arm…):
 *   an absolutely positioned corner button that opens the Lightbox WITHOUT
 *   reaching the tile's own handler. The tile needs `position: relative`.
 *   It renders as `role="button"` on a span so it is valid inside a real
 *   `<button>` tile too (button-in-button is invalid HTML).
 *
 * Styles live in Lightbox.css so they travel with the Lightbox itself.
 */
import type { CSSProperties, KeyboardEvent, MouseEvent, PointerEvent, SyntheticEvent } from 'react'
import { Icon } from './icons'
import { useI18n } from './I18nProvider'
import { openLightbox, type LightboxItem } from './Lightbox'

/** Props for a purely presentational image: click / Enter / Space enlarge it. */
export function useEnlarge() {
  const { t } = useI18n()
  return (item: LightboxItem, extraStyle?: CSSProperties) => ({
    role: 'button' as const,
    tabIndex: 0,
    title: t('Click to enlarge'),
    style: { cursor: 'zoom-in', ...extraStyle },
    onClick: (e: MouseEvent) => { e.preventDefault(); e.stopPropagation(); openLightbox(item) },
    onKeyDown: (e: KeyboardEvent) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); openLightbox(item) }
    },
  })
}

export function ZoomButton({
  item,
  size = 14,
  className,
  style,
}: {
  /** What to open — a value or a getter (for tiles whose URL is computed). */
  item: LightboxItem | (() => LightboxItem)
  size?: number
  className?: string
  style?: CSSProperties
}) {
  const { t } = useI18n()
  const open = (e: SyntheticEvent) => {
    e.preventDefault()
    e.stopPropagation()
    openLightbox(typeof item === 'function' ? item() : item)
  }
  // The tile may start a drag or arm itself on pointer/mouse down — the
  // magnifier swallows those too, so it never counts as a tile interaction.
  const swallow = (e: PointerEvent | MouseEvent) => e.stopPropagation()
  return (
    <span
      role="button"
      tabIndex={0}
      className={`lb-zoom-corner${className ? ` ${className}` : ''}`}
      style={style}
      title={t('Click to enlarge')}
      aria-label={t('Enlarge')}
      onClick={open}
      onPointerDown={swallow}
      onMouseDown={swallow}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') open(e) }}
    >
      <Icon name="zoomIn" size={size} />
    </span>
  )
}
