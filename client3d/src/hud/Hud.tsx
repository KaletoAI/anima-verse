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
 *
 * The CHAT panel additionally runs in an auto mode (E3 acceptance) — it shows
 * itself when something is said and withdraws when the room stays silent; see
 * the block around CHAT_IDLE_MS below. Self/Others stay purely manual.
 */
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import {
  apiGet, apiPost, usePoll, useI18n, useToast, Icon,
  ScenePanel, SelfPanel, OthersPanel,
  type SceneData, type IconName,
} from '@anima/player-ui';
import { CharacterPlaque } from './CharacterPlaque';
import { elevatorOptions } from '../game/elevator';
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

/** Quiet time after which an unpinned chat panel withdraws. Long enough to
 *  read the line that brought it up and start typing, short enough that a
 *  silent room clears the view without anyone reaching for the rail. Roughly
 *  four poll intervals (5 s), so a late answer still counts as "the
 *  conversation goes on" and not as a fresh interruption. */
const CHAT_IDLE_MS = 20000;
/** The idle timeout ran out while the panel was still in use (focus inside it,
 *  or one of its picker modals open) — look again after this. */
const CHAT_BUSY_RECHECK_MS = 5000;

export function Hud({ avatar }: { avatar: string }) {
  const { t } = useI18n();
  const game = useSyncExternalStore(subscribeGameState, getGameState);
  const [open, setOpen] = useState<Record<PanelId, boolean>>({
    chat: true, self: false, others: false,
  });
  /** `open.chat` for callbacks that must not re-subscribe on every toggle. */
  const chatOpen = useRef(open.chat);
  chatOpen.current = open.chat;
  /**
   * The chat panel knows two modes, and the rail switches between them:
   * unpinned (the auto mode — shows itself on a new line, withdraws when
   * idle) and pinned open (stays until it is closed again). ONE rail click
   * decides it: opening by hand pins, closing unpins — the auto state is
   * simply discarded, there is no three-click cycle to learn. Closing keeps
   * the auto SHOW alive on purpose: "away for now" is not "never again", and
   * the next spoken line brings the panel back.
   */
  const [chatPinned, setChatPinned] = useState(false);
  /** the rendered chat section — for the focus check of the idle timeout */
  const chatRef = useRef<HTMLElement | null>(null);
  const toggle = useCallback((id: PanelId) => {
    if (id === 'chat') setChatPinned(!chatOpen.current);
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
  // bring the chat panel up. The composer is deliberately NOT focused: a key
  // that both opens a panel and steals the focus takes the keyboard away from
  // walking, and whoever wants to type clicks into the field anyway.
  //
  // But "open it" alone is not an answer. The chat panel starts OPEN, so in
  // the delivered state the very first press would do nothing at all —
  // idempotent, invisible, indistinguishable from a broken key. An already
  // open panel therefore gets a one-shot flash of its edge instead (0.6 s,
  // hud.css/theme-fantasy.css). The press is always answered, never silently
  // swallowed.
  //
  // F does NOT pin the panel: pressing it means "talk to that one", not "keep
  // this window forever". While it matters, `talkTarget` holds the panel open
  // anyway, and typing does too — see the idle block below.
  /** counts hails onto an ALREADY open chat; drives the flash below */
  const [chatHail, setChatHail] = useState(0);
  const [chatFlash, setChatFlash] = useState(false);
  useEffect(() => {
    uiActions.openChat = () => {
      if (chatOpen.current) setChatHail((n) => n + 1);
      else setOpen((o) => ({ ...o, chat: true }));
    };
    return () => { uiActions.openChat = undefined; };
  }, []);
  useEffect(() => {
    if (!chatHail) return;               // nothing pressed yet, no flash on mount
    // Off first, on in the next frame: a CSS animation only restarts when the
    // class actually leaves the element, and pressing F twice in a row has to
    // flash twice.
    setChatFlash(false);
    const raf = requestAnimationFrame(() => setChatFlash(true));
    const off = window.setTimeout(() => setChatFlash(false), 700);
    return () => { cancelAnimationFrame(raf); window.clearTimeout(off); };
  }, [chatHail]);

  // Auto SHOW (E3 acceptance): a new line in the room brings the chat up. The
  // detection rides on the ONE poll above — line count plus the last line's
  // timestamp — instead of a second subscription.
  //
  // Two cases deliberately do NOT count as new, they only set the baseline:
  // the FIRST payload after mount (otherwise the chat pops open on every page
  // load, which is the opposite of what the auto mode is for) and a room
  // change (walking into a room with an older transcript is not somebody
  // speaking). A room whose transcript then grows is a real line again.
  const seenScene = useRef<{ room: string; stamp: string } | null>(null);
  const sceneRoom = data?.room_id || '';
  const lastLine = data?.scene?.length ? data.scene[data.scene.length - 1] : null;
  const sceneStamp = data ? `${data.scene?.length ?? 0}|${lastLine?.ts || ''}` : '';
  useEffect(() => {
    if (!sceneStamp) return;                        // no payload yet
    const prev = seenScene.current;
    seenScene.current = { room: sceneRoom, stamp: sceneStamp };
    if (!prev || prev.room !== sceneRoom) return;   // first load / room change
    if (prev.stamp === sceneStamp) return;          // same transcript, silence
    if (!chatOpen.current) setOpen((o) => ({ ...o, chat: true }));
    // Same one-shot pulse the talk key uses: an appearing panel announces
    // itself once instead of just materialising in the corner.
    setChatHail((n) => n + 1);
  }, [sceneRoom, sceneStamp]);

  // Auto HIDE: after CHAT_IDLE_MS in which nothing happened — and only while
  // nothing points at the chat. Every dependency of this effect restarts the
  // window, which is precisely what "idle" means here: `chatHail` counts every
  // new line and every talk key, `open.chat` the panel coming up, and
  // talkTarget/elevatorOpen are standing offers that must not be answered by a
  // vanishing panel. A pinned panel is not this effect's business at all.
  useEffect(() => {
    if (!open.chat || chatPinned) return;
    if (game.talkTarget || game.elevatorOpen) return;
    let timer = 0;
    function expire() {
      // Still in use? Typing in the composer, or one of its picker modals open
      // (they portal to document.body, and unmounting the panel would tear the
      // open picker down with it). Wait and look again.
      if (chatRef.current?.contains(document.activeElement)
          || document.querySelector('.ga-modal-backdrop')) {
        timer = window.setTimeout(expire, CHAT_BUSY_RECHECK_MS);
        return;
      }
      setOpen((o) => ({ ...o, chat: false }));
    }
    timer = window.setTimeout(expire, CHAT_IDLE_MS);
    return () => window.clearTimeout(timer);
  }, [open.chat, chatPinned, chatHail, game.talkTarget, game.elevatorOpen]);

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
        <section ref={chatRef}
          className={`hud-panel hud-chat${chatFlash ? ' hud-flash' : ''}`}>
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
        {/* Elevator (E3, floors on foot): the same prompt shape as the talk
            chip, and deliberately BEHIND it — a character in range wins, so
            one F press is never two offers at once. Unfolded (F again, or a
            click) the prompt becomes one button per storey; the current one is
            not among them. Unlike the prompt these are operated, so they take
            the pointer back (hud.css). */}
        {!game.talkTarget && game.elevator && (
          game.elevatorOpen ? (
            <div className="hud-elevator">
              <span className="hud-elevator-label">{t('Elevator')}</span>
              {elevatorOptions(game.elevator).map((level) => (
                <button key={level} className="hud-elevator-floor"
                  onClick={() => gameActions.rideElevator?.(level)}>
                  {t('Floor {n}').replace('{n}', String(level))}
                </button>
              ))}
            </div>
          ) : (
            <div className="hud-talk">{t('Press F to use the elevator')}</div>
          )
        )}
        {/* Selected figure (E3-T1): always mounted, renders null without a
            selection — the plaque is driven by the bus, not by panel state. */}
        <CharacterPlaque />
      </div>
    </>
  );
}
