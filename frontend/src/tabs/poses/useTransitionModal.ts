import { useEffect, useRef } from 'react'

/** Portal dialogs share focus trapping, scroll locking and focus restoration. */
export function useTransitionModal(onClose: () => void, busy: boolean) {
  const box = useRef<HTMLDivElement>(null)
  const state = useRef({ onClose, busy })
  state.current = { onClose, busy }
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    box.current?.querySelector<HTMLElement>('input, select, button')?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !state.current.busy) state.current.onClose()
      if (event.key !== 'Tab') return
      const controls = box.current?.querySelectorAll<HTMLElement>(
        'button:not(:disabled), input:not(:disabled), select:not(:disabled), summary',
      )
      const visible = Array.from(controls || []).filter((el) => el.getClientRects().length)
      const first = visible[0]; const last = visible[visible.length - 1]
      if (!first) { event.preventDefault(); box.current?.focus(); return }
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = overflow
      document.removeEventListener('keydown', onKey)
      previous?.focus()
    }
  }, [])
  return box
}
