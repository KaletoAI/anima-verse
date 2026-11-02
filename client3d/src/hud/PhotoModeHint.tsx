import { useI18n } from '@anima/player-ui';
import { useLayoutEffect, useRef, useState } from 'react';
import { photoSelectionRect, type PhotoHintState, type PhotoSelection } from '../game/photoMode';
import type { PhotoRect } from '../game/photoView';

function Selection({ selection }: { selection: PhotoSelection }) {
  const host = useRef<HTMLDivElement>(null);
  const start = useRef<{x: number; y: number; pointer: number} | null>(null);
  const [rect, setRect] = useState<PhotoRect | null>(null);
  const { canvas } = selection;
  useLayoutEffect(() => {
    Object.assign(canvas.style, { width: '100%', height: '100%', position: 'absolute', inset: '0' });
    const node = host.current!;
    node.prepend(canvas);
    return () => canvas.remove();
  }, [canvas]);
  const measure = (x: number, y: number) => photoSelectionRect(start.current!, {x, y},
    host.current!.getBoundingClientRect(), canvas.width, canvas.height);
  return <div ref={host} data-photo-selection style={{position: 'absolute', inset: 0, pointerEvents: 'auto',
    overflow: 'hidden', cursor: 'crosshair', touchAction: 'none'}}
    onPointerDown={e => {
      if (e.button !== 0 || start.current) return;
      e.preventDefault(); e.currentTarget.setPointerCapture(e.pointerId);
      start.current = {x: e.clientX, y: e.clientY, pointer: e.pointerId};
      setRect(measure(e.clientX, e.clientY));
    }}
    onPointerMove={e => { if (start.current?.pointer === e.pointerId) setRect(measure(e.clientX, e.clientY)); }}
    onPointerUp={e => {
      if (e.button !== 0 || start.current?.pointer !== e.pointerId) return;
      const selected = measure(e.clientX, e.clientY); start.current = null;
      selection.choose(selected);
    }}
    onPointerCancel={() => { start.current = null; setRect(null); }}>
    {rect && <div style={{position: 'absolute', pointerEvents: 'none', boxSizing: 'border-box',
      left: `${rect.x / canvas.width * 100}%`, top: `${rect.y / canvas.height * 100}%`,
      width: `${rect.width / canvas.width * 100}%`, height: `${rect.height / canvas.height * 100}%`,
      border: '1px solid #d4af62', boxShadow: '0 0 0 100vmax #0009'}}>
      <span style={{position: 'absolute', top: 4, left: 4, padding: '2px 5px', color: '#fff',
        background: '#111d', whiteSpace: 'nowrap', font: '12px system-ui'}}>{rect.width} × {rect.height} px</span>
    </div>}
  </div>;
}

export function PhotoModeHint({ state, taken }: { state: PhotoHintState; taken: boolean }) {
  const { t } = useI18n();
  if (!state.active) return taken
    ? <div className="photo-mode-hint" role="status">{t('Shot taken')}</div> : null;
  if (state.capturing === true) return null;
  if (typeof state.capturing === 'object') return <>
    <Selection selection={state.capturing} />
    <div className="photo-mode-hint" style={{pointerEvents: 'none'}} role="status">
      {t('Drag to select · Click: whole picture · Esc: back')}
    </div>
  </>;
  return <div className="photo-mode-hint" role="status">
    {t('Photo mode')} · {t('Speed')}: {state.speed.toFixed(1)} m/s<br />
    {t('WASD move · Q/E down/up · Drag to look · Wheel speed · Shift faster')}<br />
    {t('Space: select photo · F2 / Esc: leave')}
  </div>;
}
