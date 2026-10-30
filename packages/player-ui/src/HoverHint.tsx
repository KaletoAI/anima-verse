import { useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

/** A mouse-over hint drawn by the page itself. A `title` tooltip is drawn by the
 *  browser, and the native client's embedded browser draws none; a disabled button
 *  gets no mouse events either, so the hint listens on a wrapper and the caller sets
 *  `pointer-events: none` on a disabled child. The bubble is portalled to the body so
 *  no scrolling panel clips it. Without text the children render unwrapped. */
export function HoverHint({ text, children }: { text?: string; children: ReactNode }) {
  const [at, setAt] = useState<{ left: number; top: number; bottom: number } | null>(null)
  if (!text) return <>{children}</>
  const below = !!at && at.top < 40
  return <span className="player-hover-hint" data-hint={text}
    onMouseEnter={event => {
      const rect = event.currentTarget.getBoundingClientRect()
      setAt({ left: rect.left, top: rect.top, bottom: rect.bottom })
    }}
    onMouseLeave={() => setAt(null)}>
    {children}
    {at && createPortal(<div role="tooltip" className="player-hover-hint-bubble"
      style={below ? { left: at.left, top: at.bottom + 4 }
        : { left: at.left, top: at.top - 4, transform: 'translateY(-100%)' }}>{text}</div>, document.body)}
  </span>
}
