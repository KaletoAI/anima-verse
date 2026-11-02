import { useI18n } from '@anima/player-ui';
import type { PhotoHintState } from '../game/photoMode';

export function PhotoModeHint({ state, taken }: { state: PhotoHintState; taken: boolean }) {
  const { t } = useI18n();
  if (!state.active) return taken
    ? <div className="photo-mode-hint" role="status">{t('Shot taken')}</div> : null;
  if (state.capturing) return null;
  return <div className="photo-mode-hint" role="status">
    {t('Photo mode')} · {t('Speed')}: {state.speed.toFixed(1)} m/s<br />
    {t('WASD move · Q/E down/up · Drag to look · Wheel speed · Shift faster')}<br />
    {t('Space: take photo · F2 / Esc: leave')}
  </div>;
}

