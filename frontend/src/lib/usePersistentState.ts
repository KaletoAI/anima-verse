import { useEffect, useRef, useState } from 'react'

/**
 * sessionStorage-backed React state — survives a component unmount (e.g. the
 * Game-Admin tab switch, which mounts only the active tab) and a page reload
 * within the same browser tab. Values are JSON-serialized; `Set` is supported
 * transparently via a small tag so callers can keep using Sets.
 *
 * Same signature as `useState`, plus a storage `key` (namespace it, e.g.
 * "worlddev.messages"). On a JSON/quota error it silently falls back to the
 * in-memory value so it can never break the UI.
 */
function replacer(_k: string, v: unknown): unknown {
  if (v instanceof Set) return { __set__: Array.from(v) }
  return v
}

function reviver(_k: string, v: unknown): unknown {
  if (v && typeof v === 'object' && Array.isArray((v as { __set__?: unknown }).__set__)) {
    return new Set((v as { __set__: unknown[] }).__set__)
  }
  return v
}

export function usePersistentState<T>(
  key: string, initial: T,
): [T, React.Dispatch<React.SetStateAction<T>>] {
  const [state, setState] = useState<T>(() => {
    try {
      const raw = sessionStorage.getItem(key)
      if (raw != null) return JSON.parse(raw, reviver) as T
    } catch { /* corrupt/unavailable — fall through to initial */ }
    return initial
  })

  const keyRef = useRef(key)
  keyRef.current = key

  useEffect(() => {
    try {
      sessionStorage.setItem(keyRef.current, JSON.stringify(state, replacer))
    } catch { /* quota / serialization — keep the in-memory value */ }
  }, [state])

  return [state, setState]
}
