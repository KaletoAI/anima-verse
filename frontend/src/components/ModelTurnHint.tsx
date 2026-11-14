import type { CSSProperties } from 'react'
import { useI18n } from '../i18n/I18nProvider'

/**
 * The one-line hint under every model viewer (T-U4, `lib/modelTurn.ts`): what the mouse does there, and — once the
 * drag has turned the model — the "Reset pose" button that stands it upright again (`onReset`; a double-click does
 * the same). `subject` names what turns: a figure (characters, clips) or a model (props, buildings, garments).
 * `locked`: the view is held straight on (a front view), so a drag moves the view instead.
 */
export function ModelTurnHint({ subject = 'model', locked = false, turned = false, onReset, style }: {
  subject?: 'figure' | 'model'; locked?: boolean; turned?: boolean; onReset?: () => void; style?: CSSProperties
}) {
  const { t } = useI18n()
  const text = locked
    ? t('Front view: drag moves the view · Wheel: zoom')
    : subject === 'figure'
      ? t('Drag: turn the figure · Shift+drag: move the view · Wheel: zoom · Double-click: upright')
      : t('Drag: turn the model · Shift+drag: move the view · Wheel: zoom · Double-click: upright')
  return (
    <div className="ga-hint" style={{ fontSize: 11, marginTop: 2, display: 'flex', gap: 6, alignItems: 'center',
      flexWrap: 'wrap', ...style }}>
      <span title={t('Up/down tilts it forward and back (up to 90°), left/right turns it. Touch: one finger turns, two fingers move and zoom.')}>
        {text}</span>
      {turned && onReset && !locked ? (
        <button type="button" className="ga-btn ga-btn-sm" style={{ padding: '0 6px', fontSize: 11 }}
          onClick={onReset} title={t('Stand it upright again, facing front')}>{t('Reset pose')}</button>
      ) : null}
    </div>
  )
}
