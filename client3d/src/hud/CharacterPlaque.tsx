/**
 * Plaque of the selected figure (plan-3d-game stage 3, task 1).
 *
 * Reads the selection straight off the HUD bus — the vanilla app publishes it
 * on every figure click and refreshes it on every worldmap poll, so activity,
 * mood and travel target stay live while the plaque is open. Renders `null`
 * without a selection, which is why `Hud.tsx` can mount it unconditionally.
 *
 * The action row is the anchor for the rest of the stage: `Zoom to` and `Take
 * control` (task 2) today, talk (task 5) lands next to them. Everything it
 * triggers goes through `gameActions`; the only state this component writes is
 * clearing the selection.
 *
 * Room is deliberately NOT shown: the worldmap sends `room_id`, an opaque id,
 * and the bus carries no room-name map to resolve it against.
 */
import { useSyncExternalStore } from 'react';
import { useI18n, Icon } from '@anima/player-ui';
import { gameActions, getGameState, setGameState, subscribeGameState } from './bus';

export function CharacterPlaque() {
  const { t } = useI18n();
  const state = useSyncExternalStore(subscribeGameState, getGameState);
  const sel = state.selected;
  if (!sel) return null;

  const char = sel.char;
  const travelTo = char.movement_target_name || '';

  return (
    <div className="hud-plaque">
      <div className="hud-plaque-portrait">
        {char.avatar_url
          ? <img src={char.avatar_url} alt="" />
          : <span>{char.name.slice(0, 1).toUpperCase()}</span>}
      </div>

      <div className="hud-plaque-body">
        <div className="hud-plaque-name">
          {char.name}
          {sel.isAvatar && <span className="hud-plaque-badge">{t('Your avatar')}</span>}
        </div>
        {char.activity && (
          <div className="hud-plaque-row">
            <span className="hud-plaque-key">{t('Activity')}</span>
            <span>{char.activity}</span>
          </div>
        )}
        {char.mood && (
          <div className="hud-plaque-row">
            <span className="hud-plaque-key">{t('Mood')}</span>
            <span>{char.mood}</span>
          </div>
        )}
        {travelTo && (
          <div className="hud-plaque-row">
            <span className="hud-plaque-key">{t('Travelling to')}</span>
            <span>{travelTo}</span>
          </div>
        )}
        <div className="hud-plaque-actions">
          <button className="player-chip" onClick={() => gameActions.zoomTo?.(char.name)}>
            {t('Zoom to')}
          </button>
          {/* Taking control is offered on the avatar only, and only while the
              overview is up — leaving again is the HUD's mode chip / Esc. */}
          {sel.isAvatar && state.mode === 'overview' && (
            <button className="player-chip" onClick={() => gameActions.enterEmbodied?.()}>
              {t('Take control')}
            </button>
          )}
        </div>
      </div>

      <button className="hud-plaque-close" onClick={() => setGameState({ selected: null })}
        title={t('Close')} aria-label={t('Close')}>
        <Icon name="close" size={14} />
      </button>
    </div>
  );
}
