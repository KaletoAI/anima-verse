import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'

type ToastKind = 'info' | 'error' | 'success'

interface ToastState {
  msg: string
  kind: ToastKind
  nonce: number
}

interface ToastValue {
  toast: (msg: string, kind?: ToastKind) => void
}

const ToastContext = createContext<ToastValue | null>(null)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<ToastState | null>(null)

  const toast = useCallback((msg: string, kind: ToastKind = 'info') => {
    setState({ msg, kind, nonce: Date.now() })
  }, [])

  useEffect(() => {
    if (!state) return
    const id = window.setTimeout(() => setState(null), 2200)
    return () => window.clearTimeout(id)
  }, [state])

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      {state ? (
        <div className={`ga-toast ga-toast-${state.kind}`} role="status">
          {state.msg}
        </div>
      ) : null}
    </ToastContext.Provider>
  )
}

export function useToast(): ToastValue {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used inside <ToastProvider>')
  return ctx
}
