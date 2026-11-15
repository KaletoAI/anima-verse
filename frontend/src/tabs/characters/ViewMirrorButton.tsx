/**
 * ViewMirrorButton — the small "⇋" beside a side view's own button (Ruling A91; Base body → Views, Figure → Dressed
 * views): it mirrors the stored view left-right on the CPU (no image job), a second click turns it back. Pressed while
 * the view is mirrored. Its mouse-over says the whole before the click (viewFacingModel.mirrorButton: what becomes
 * due with its hub jobs, one-sided details swap sides); disabled with its reason for a copy of the body's view.
 */
import { useI18n } from '../../i18n/I18nProvider'
import { mirrorButton } from './viewFacingModel'
import type { FacingTile, MirrorFollowup, Side } from './viewFacingModel'

export function ViewMirrorButton({ facing, followup, view, outfit, label, busy, busyReason, onMirror }: {
  facing: FacingTile | null | undefined
  followup: MirrorFollowup | null | undefined
  view: Side
  /** A dressed view (Figure tab) rather than a base view. */
  outfit: boolean
  /** The view's name, for the accessible label. */
  label: string
  /** A click is in flight or the view renders. */
  busy: boolean
  /** Why it waits while busy (its mouse-over then). */
  busyReason?: string
  onMirror: () => void
}) {
  const { t } = useI18n()
  const b = mirrorButton(facing, followup, view, outfit, t)
  const disabled = busy || !!b.disabled
  return (
    <button type="button" className="ga-btn ga-btn-sm ga-view-mirror" aria-pressed={b.on} disabled={disabled}
      title={b.disabled || (busy && busyReason) || b.title} onClick={onMirror}
      aria-label={`${b.on ? t('Turn back') : t('Mirror')} · ${label}`}>
      {b.label}
    </button>
  )
}
