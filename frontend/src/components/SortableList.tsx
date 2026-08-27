import { useState } from 'react'
import type { ReactNode } from 'react'
import { useI18n } from '../i18n/I18nProvider'

/**
 * A list whose ORDER is the data — drag a row onto another one and it MOVES
 * there, landing above the row it was dropped on (exactly where the top-border
 * highlight promised). HTML5 drag and drop, no library: the rows are short,
 * the lists are admin-sized, and a drag layer would be more code than the
 * feature.
 *
 * Only the ⋮⋮ handle is `draggable`. On the whole row it would swallow text
 * selection and turn a press-and-drift on an action button into a drag; the
 * drop side stays on the row, which is the target the pointer is actually
 * over.
 *
 * The component owns nothing but the in-flight drag: it reports the new key
 * order through `onReorder` and re-renders from whatever `items` the caller
 * hands back. That keeps the optimistic local order AND the server round trip
 * in the caller, where the failure case (toast + refetch) belongs.
 */
export function SortableList<T>({
  items,
  getKey,
  render,
  onReorder,
  rowClassName,
}: {
  items: T[]
  /** Stable identity of a row — what `onReorder` reports back. */
  getKey: (item: T) => string
  render: (item: T, index: number) => ReactNode
  /** The full key list in its new order. */
  onReorder: (keys: string[]) => void
  /** Extra classes for one row (e.g. `is-active` for the open one). */
  rowClassName?: (item: T) => string
}) {
  const { t } = useI18n()
  const [dragKey, setDragKey] = useState<string | null>(null)
  const [overKey, setOverKey] = useState<string | null>(null)

  const drop = (targetKey: string) => {
    setOverKey(null)
    const sourceKey = dragKey
    setDragKey(null)
    if (!sourceKey || sourceKey === targetKey) return
    const keys = items.map(getKey)
    const from = keys.indexOf(sourceKey)
    const to = keys.indexOf(targetKey)
    if (from < 0 || to < 0) return
    // Move, not swap: take the dragged key out and put it back in front of
    // the target. Removing it first shifts everything behind it down by one,
    // so a downward move has to aim one slot earlier to land ABOVE the row
    // the highlight marked.
    keys.splice(from, 1)
    keys.splice(from < to ? to - 1 : to, 0, sourceKey)
    onReorder(keys)
  }

  return (
    <ul className="ga-list">
      {items.map((item, index) => {
        const key = getKey(item)
        const extra = rowClassName?.(item) || ''
        return (
          <li
            key={key}
            className={'ga-list-row' + (extra ? ' ' + extra : '')}
            style={{
              opacity: dragKey === key ? 0.5 : undefined,
              // The drop target, marked where the row would land — an inline
              // style because the highlight is a transient view state, not a
              // class the stylesheet should have to know about.
              borderTop: overKey === key && dragKey !== key
                ? '2px solid var(--accent, #1f6feb)' : undefined,
            }}
            onDragOver={(e) => { e.preventDefault(); setOverKey(key) }}
            onDragLeave={() => setOverKey((k) => (k === key ? null : k))}
            onDrop={(e) => { e.preventDefault(); drop(key) }}
          >
            <span
              className="ga-sortable-handle"
              title={t('Drag to reorder')}
              draggable
              onDragStart={() => setDragKey(key)}
              onDragEnd={() => { setDragKey(null); setOverKey(null) }}
            >
              ⋮⋮
            </span>
            {render(item, index)}
          </li>
        )
      })}
    </ul>
  )
}
