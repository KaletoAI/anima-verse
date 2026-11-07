/**
 * The avatar's open plans — a small permanent box at the top right, under the
 * top bar's "Log out", above the minimap (`.hud-corner` stacks the two).
 *
 * `GET /play/intents` decides everything that needs the server: which plans
 * count (owned, or the avatar is a participant), the time label in the world
 * calendar, the order (timed first by game time, then the rest by priority),
 * and whose description may be shown — someone else's plan carries none, so a
 * surprise stays one. This component only lists and folds.
 *
 * Polled every 30 s; the poll key carries the avatar, so a changed avatar
 * starts a fresh answer instead of showing the old one's plans. Nothing is
 * drawn while spectating or while the list is empty. The collapsed state is a
 * local view setting like the minimap switch.
 */
import { useCallback, useState } from 'react';
import { Icon, useI18n, usePoll } from '@anima/player-ui';
import { getPlayIntents, type PlayIntent } from '../api';

const COLLAPSED_KEY = 'av3d.intentsCollapsed';
const POLL = { intervalMs: 30000, pushedIntervalMs: 30000, minSpacingMs: 30000 };

export function IntentsBox({ avatar }: { avatar: string }) {
  const { t } = useI18n();
  const { data } = usePoll<{ avatar: string; intents: PlayIntent[] }>(
    `play-intents:${avatar}`, getPlayIntents, { ...POLL, enabled: !!avatar });
  const [collapsed, setCollapsedState] = useState(
    () => localStorage.getItem(COLLAPSED_KEY) === '1');
  const setCollapsed = useCallback((on: boolean) => {
    localStorage.setItem(COLLAPSED_KEY, on ? '1' : '0');
    setCollapsedState(on);
  }, []);
  const [expanded, setExpanded] = useState<string | null>(null);

  const intents = data?.intents || [];
  if (!avatar || !intents.length) return null;
  return (
    <section className="hud-intents" aria-label={t('Plans')}>
      <button type="button" className="hud-intents-head" aria-expanded={!collapsed}
        onClick={() => setCollapsed(!collapsed)}
        title={collapsed ? t('Show plans') : t('Hide plans')}>
        <Icon name="tasks" size={13} />
        <span className="hud-intents-title">{t('Plans')}</span>
        <span className="hud-intents-count">{intents.length}</span>
        <span className="hud-intents-fold" aria-hidden="true">{collapsed ? '▸' : '▾'}</span>
      </button>
      {!collapsed && (
        <ul className="hud-intents-list">
          {intents.map((it) => {
            const canOpen = it.own && !!it.description;
            const isOpen = canOpen && expanded === it.id;
            return (
              <li key={it.id} className={'hud-intent' + (it.own ? ' own' : '')}>
                <button type="button" className="hud-intent-row" disabled={!canOpen}
                  aria-expanded={canOpen ? isOpen : undefined}
                  onClick={() => setExpanded(isOpen ? null : it.id)}>
                  {it.when && <span className="hud-intent-when">{it.when}</span>}
                  <span className="hud-intent-title">{it.title}</span>
                  <span className="hud-intent-owner">{it.own ? t('you') : it.owner}</span>
                </button>
                {isOpen && <p className="hud-intent-desc">{it.description}</p>}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
