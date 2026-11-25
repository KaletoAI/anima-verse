import { useI18n } from '@anima/player-ui';
import type { InfoPanelData } from '../game/infoPanel';
import type { TravelPick } from '../game/travelPick';
import { gameActions } from './bus';

/** The scene owns both the information and the detail-view button state. */
export function InfoPanel({ info, onPick }: { info: InfoPanelData; onPick: (pick: TravelPick) => void }) {
  const { t } = useI18n();
  const kind = !info.view?.openable ? 'zoom' : info.view.open ? 'closeView' : 'lookInside';
  return <div className="info-panel">
    <button className="panel-close" title={t('Close')} onClick={() => gameActions.closeInfo?.()}>✕</button>
    <h2>{info.name}</h2>
    {info.travel && <button className="panel-zoom" onClick={() => onPick({
      id: info.id, name: info.name, distanceM: info.travel!.distanceM,
    })}>{t('Travel here')}</button>}
    {info.description && <p className="desc">{info.description}</p>}
    {!!info.rooms.length && <><h3>{t('Rooms')}</h3><ul>{info.rooms.map((room, i) =>
      <li key={i}>{room.name}{!!room.who.length && <span className="who"> · {room.who.join(', ')}</span>}</li>)}</ul></>}
    {!!info.present.length && <><h3>{t('Present')}</h3><ul>{info.present.map((char, i) =>
      <li key={i}>{char.name}{char.activity && <span className="who"> · {char.activity}</span>}
        {char.mood && <span className="who"> · {char.mood}</span>}
        {char.travelTo && <span className="who">🚶 → {char.travelTo}{char.eta && ` · ${char.eta}`}</span>}</li>)}</ul></>}
    {!!info.events.length && <><h3>{t('Events')}</h3><ul>{info.events.map((event, i) =>
      <li key={i}>{event.danger ? '🔥' : '❗'} {event.text}</li>)}</ul></>}
    <button className="panel-zoom" onClick={() => gameActions.infoAction?.(info.id, kind)}>
      {kind === 'zoom' ? `🔍 ${t('Zoom in')}` : kind === 'closeView' ? `✕ ${t('Close view')}` : `🔍 ${t('Look inside')}`}
    </button>
  </div>;
}
