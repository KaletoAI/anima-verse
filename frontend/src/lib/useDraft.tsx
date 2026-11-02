import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ConfirmDialog } from '@anima/player-ui'
import { useI18n } from '../i18n/I18nProvider'
import { setUnsavedGuard } from './unsavedGuard'

/**
 * A detail form's draft together with the state it was opened in, so the tab
 * can tell "edited but not saved" (`dirty`) without a hand-written comparison.
 *
 *   const { draft, setDraft, load, dirty } = useDraft<MyDraft>()
 *   load(asDraft(row))           // open / after save: the new baseline
 *   setDraft(d => ({...d, x}))   // an edit: dirty from now on
 *
 * The comparison is structural (JSON), so editing a value and editing it back
 * is clean again.
 */
export function useDraft<T>() {
  const [draft, setDraft] = useState<T | null>(null)
  const [base, setBase] = useState('null')
  const load = useCallback((next: T | null) => {
    setDraft(next)
    setBase(JSON.stringify(next))
  }, [])
  const dirty = useMemo(() => draft !== null && JSON.stringify(draft) !== base, [draft, base])
  return { draft, setDraft, load, dirty }
}

/**
 * The question "discard the unsaved changes?" before something replaces the
 * open draft — another row, a new entry, or another tab.
 *
 *   const { guard, dialog } = useDiscardGuard(dirty)
 *   <button onClick={() => guard(() => editRow(r))}>…</button>
 *   {dialog}
 *
 * `guard(fn)` runs `fn` at once while nothing is unsaved, otherwise after the
 * user confirmed. The tab switch asks through `lib/unsavedGuard` — so only a
 * tab that registers no guard of its own may use this hook.
 */
export function useDiscardGuard(dirty: boolean) {
  const { t } = useI18n()
  const dirtyRef = useRef(dirty)
  dirtyRef.current = dirty
  const [pending, setPending] = useState<(() => void) | null>(null)
  useEffect(() => {
    setUnsavedGuard(() => dirtyRef.current)
    return () => setUnsavedGuard(null)
  }, [])
  const guard = useCallback((fn: () => void) => {
    if (dirtyRef.current) setPending(() => fn)
    else fn()
  }, [])
  const dialog = (
    <ConfirmDialog open={pending !== null} title={t('Discard unsaved changes?')}
      message={t('The open entry has changes that were never saved. Continuing discards them.')}
      confirmLabel={t('Discard')} danger
      onConfirm={() => { const fn = pending; setPending(null); fn?.() }}
      onClose={() => setPending(null)} />
  )
  return { guard, dialog }
}
