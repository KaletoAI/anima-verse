/**
 * HUD v1 of the 3D client (plan-3d-game stage 2, tasks 5 + 6). hud.css carries
 * the structure, theme-fantasy.css the look (variables redefined under #hud).
 *
 * Layout: a right-edge rail with three toggle buttons (chat/self/others), the
 * chat as a docked panel bottom-left, self/others as a right-side dock column.
 * The root never catches the pointer — only rail and panels do (hud.css), so
 * camera dragging on the canvas keeps working everywhere else.
 *
 * This container owns the ONE `/play/scene` poll (same contract as PlayerApp
 * in /play): ScenePanel receives data + refresh as props and never polls
 * itself. The `photoDialog` slot is deliberately NOT set — the 📷 scene-photo
 * button is absent in HUD v1 (the image-gen dialog lives in the game-admin
 * UI); open point for stage 6.
 */
import { useCallback, useEffect, useState, useSyncExternalStore } from 'react';
import {
  apiGet, apiPost, usePoll, useI18n, useToast, Icon,
  ScenePanel, SelfPanel, OthersPanel,
  type SceneData, type IconName,
} from '@anima/player-ui';
import { CharacterPlaque } from './CharacterPlaque';
import { gameActions, getGameState, setGameState, subscribeGameState, uiActions } from './bus';
import '@anima/player-ui/panels.css';
import './hud.css';
// Load order matters: the fantasy theme redefines the custom properties and
// overrides the plain rules of hud.css, so it must come last.
import './theme-fantasy.css';

type PanelId = 'chat' | 'self' | 'others';

const PANELS: Array<{ id: PanelId; icon: IconName; title: string }> = [
  { id: 'chat', icon: 'chat', title: 'Chat' },
  { id: 'self', icon: 'self', title: 'Self' },
  { id: 'others', icon: 'others', title: 'Others' },
];

export function Hud({ avatar }: { avatar: string }) {
  const { t } = useI18n();
  const game = useSyncExternalStore(subscribeGameState, getGameState);
  const [open, setOpen] = useState<Record<PanelId, boolean>>({
    chat: true, self: false, others: false,
  });
  const toggle = useCallback((id: PanelId) => {
    setOpen((o) => ({ ...o, [id]: !o[id] }));
  }, []);

  const { data, refresh: refreshScene } = usePoll<SceneData>(
    'play-scene', () => apiGet<SceneData>('/play/scene'), { intervalMs: 5000 });

  // Capability gating, same derivation as /play: a missing list (initial
  // load) shows everything — no flash-hiding.
  const hasCapability = useCallback((skillId: string) =>
    !data?.capabilities || data.capabilities.includes(skillId), [data]);

  const [moving, setMoving] = useState(false);
  const handleEnterRoom = useCallback(async (roomId: string) => {
    if (moving) return;
    setMoving(true);
    try {
      await apiPost('/play/enter-room', { room_id: roomId });
      await refreshScene();
    } catch { /* blocked by a rule or stale — the next poll corrects the view */ }
    finally { setMoving(false); }
  }, [moving, refreshScene]);

  const present = data?.present || [];
  const avatarName = data?.avatar || avatar;

  // Party follower (E3-T3): SAME derivation as /play (PlayerApp hands
  // `party.role === 'follower'` to the MovePad). The vanilla side reads it off
  // the bus and stops steering; the server refuses the step regardless.
  // The ROLE locks the movement, not the leader's name — a party whose leader
  // the payload leaves empty still carries its followers along, and deriving
  // the lock from the name handed those keys back (E3-T5 fix). The name is
  // only there to say WHOM one is following.
  const isFollower = data?.party?.role === 'follower';
  const partyLeader = isFollower ? data?.party?.leader || '' : '';
  useEffect(() => {
    setGameState({ movementLocked: isFollower, partyLeader });
  }, [isFollower, partyLeader]);

  // Toast bridge (E3-T3): the vanilla app renders no text of its own, so a
  // refused step (403 with the server's reason) is shown through the package
  // toast that already lives inside this island.
  const { toast } = useToast();
  useEffect(() => {
    uiActions.toast = (msg: string) => toast(msg, 'error');
    return () => { uiActions.toast = undefined; };
  }, [toast]);

  // Talking (E3-T5): F next to a character — and the plaque's Talk button —
  // open the chat panel. Opening it is ALL this does; the composer is not
  // focused, deliberately. A key that both opens a panel and steals the focus
  // takes the keyboard away from walking, and the player who wants to type
  // clicks into the field anyway. Focusing it is a v2 decision, not an
  // oversight.
  useEffect(() => {
    uiActions.openChat = () => setOpen((o) => (o.chat ? o : { ...o, chat: true }));
    return () => { uiActions.openChat = undefined; };
  }, []);

  const panelHead = (id: PanelId, icon: IconName, title: string) => (
    <header className="hud-panel-head">
      <Icon name={icon} size={14} />
      <span className="hud-panel-title">{title}</span>
      {id === 'chat' && (
        <span className="hud-panel-sub">
          {present.length ? `· ${present.join(', ')}` : `· ${t('You are alone here.')}`}
        </span>
      )}
      <button className="hud-panel-close" onClick={() => toggle(id)}
        title={t('Close')} aria-label={t('Close')}>
        <Icon name="close" size={14} />
      </button>
    </header>
  );

  return (
    <>
      {/* Mode indicator (E3-T2): the ONLY sign of the embodied mode in the HUD
          chrome — one chip below the vanilla top bar that also leaves again.
          Layout and the pointer exception live in hud.css with every other
          surface (E3-T5 fix: they used to be inline styles under a class the
          stylesheet never defined, which left the pointer rule in hud.css
          describing something that was no longer true). */}
      {game.mode === 'embodied' && (
        <div className="hud-mode">
          <button className="player-chip" onClick={() => gameActions.exitEmbodied?.()}>
            {t('Leave (Esc)')}
          </button>
        </div>
      )}

      <nav className="hud-rail">
        {PANELS.map((p) => (
          <button key={p.id} className={open[p.id] ? 'on' : ''}
            onClick={() => toggle(p.id)} aria-pressed={open[p.id]}
            title={t(p.title)} aria-label={t(p.title)}>
            <Icon name={p.icon} size={20} />
          </button>
        ))}
      </nav>

      {open.chat && (
        <section className="hud-panel hud-chat">
          {panelHead('chat', 'chat', avatarName || '—')}
          <ScenePanel data={data} refreshScene={refreshScene} avatar={avatarName}
            hasCapability={hasCapability} moving={moving} onEnterRoom={handleEnterRoom} />
        </section>
      )}

      {(open.self || open.others) && (
        <div className="hud-dock">
          {open.self && (
            <section className="hud-panel">
              {panelHead('self', 'self', avatarName || t('Self'))}
              <div className="hud-panel-body"><SelfPanel /></div>
            </section>
          )}
          {open.others && (
            <section className="hud-panel">
              {panelHead('others', 'others', t('Others'))}
              <div className="hud-panel-body"><OthersPanel /></div>
            </section>
          )}
        </div>
      )}

      {/* Bottom centre, ONE stack (E3-T5): the talk prompt sits directly above
          the plaque instead of floating over it. Both belong to the figure in
          the scene, not to a panel, so they share the viewport centre — and
          stacking them means a plaque that grows a row can never push the
          prompt out of place. The prompt is read, not operated, so it stays
          pointer-transparent (see the pointer rule in hud.css). */}
      <div className="hud-bottom">
        {game.talkTarget && (
          <div className="hud-talk">
            {t('Press F to talk to {name}').replace('{name}', game.talkTarget)}
          </div>
        )}
        {/* Selected figure (E3-T1): always mounted, renders null without a
            selection — the plaque is driven by the bus, not by panel state. */}
        <CharacterPlaque />
      </div>
    </>
  );
}
