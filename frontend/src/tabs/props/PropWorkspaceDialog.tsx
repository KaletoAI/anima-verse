import { useEffect, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

/** The existing admin modal surface, with focus contained until the decision. */
export function PropWorkspaceDialog({ title, children, onCancel }: {
  title: string; children: ReactNode; onCancel: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const cancel = useRef(onCancel)
  cancel.current = onCancel
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const node = ref.current
    const focusable = () => Array.from(node?.querySelectorAll<HTMLElement>(
      'button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], [tabindex="0"]') || [])
    focusable()[0]?.focus()
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        event.stopPropagation()
        cancel.current()
      } else if (event.key === 'Tab') {
        const items = focusable()
        const first = items[0], last = items[items.length - 1]
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault(); last?.focus()
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault(); first?.focus()
        }
      }
    }
    node?.addEventListener('keydown', key)
    return () => { node?.removeEventListener('keydown', key); previous?.focus() }
  }, [])
  return createPortal(<div className="ga-modal-backdrop" role="presentation" style={{ zIndex: 1200 }}>
    <div ref={ref} className="ga-modal prop-workspace-dialog" role="dialog"
      aria-modal="true" aria-label={title}>
      <div className="ga-modal-header"><h3>{title}</h3></div>
      {children}
    </div>
  </div>, document.body)
}
