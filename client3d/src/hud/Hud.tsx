/**
 * HUD v1 of the 3D client (plan-3d-game stage 2, tasks 5 + 6). hud.css carries
 * the structure, theme-fantasy.css the look (variables redefined under #hud).
 *
 * Layout: a right-edge rail of toggle buttons, the chat as a docked panel
 * bottom-left, everything else as a right-side dock column. The root never
 * catches the pointer — only rail and panels do (hud.css), so camera dragging
 * on the canvas keeps working everywhere else.
 *
 * Stage 6 added the remaining /play panels (inventory, mind, phone, news,
 * tasks) to that rail. They are the identical components out of
 * `@anima/player-ui` and poll themselves, so the frame is all this file adds;
 * `requires` on a rail entry hides the button when the bound skill package is
 * gone, the same gating /play does.
 *
 * This container owns the ONE `/play/scene` poll (same contract as PlayerApp
 * in /play): ScenePanel receives data + refresh as props and never polls
 * itself. The `photoDialog` slot is filled with `PlayerPhotoDialog` (stage 6),
 * the package's slim player-side dialog — the big game-admin `ImageGenDialog`
 * that /play slots in stays where it is. Gallery/instagram still depend on
 * that admin dialog and remain open.
 *
 * The CHAT panel additionally runs in an auto mode (E3 acceptance) — it shows
 * itself when something is said and withdraws when the room stays silent; see
 * the block around CHAT_IDLE_MS below. Self/Others stay purely manual.
 */
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import {
  apiGet, apiPost, usePoll, useI18n, useToast, Icon, ErrorBoundary,
  ScenePanel, SelfPanel, OthersPanel, PartyStrip,
  BelongingsPanel, MindPanel, PhonePanel, NewsPanel, TaskPanel, QuestsPanel,
  PlayerPhotoDialog,
  type SceneData, type SceneLine, type IconName,
} from '@anima/player-ui';
import { CharacterPlaque } from './CharacterPlaque';
import { GameMenu } from './GameMenu';
import { Minimap } from './Minimap';
import { PerfOverlay } from './PerfOverlay';
import { ttsSpeak, ttsStatus } from '../api';
import { elevatorOptions } from '../game/elevator';
import { getAudio } from '../game/audio';
import { loadPrefs, savePrefs, PREFS_KEY, type Prefs } from '../game/prefs';
import { SHOW_ALL_KEY } from '../game/fog';
import { MINIMAP_PREF_KEY } from '../game/minimap';
import {
  afterOwnLine, createVoiceover, newSceneLines, roomChanged, sceneStampOf,
  speakableLines, type SceneSnapshot, type Voiceover,
} from '../game/voiceover';
import { isTypingTarget } from '../scene/engine';
import { gameActions, getGameState, setGameState, setPerfEnabled, subscribeGameState, uiActions } from './bus';
import '@anima/player-ui/panels.css';
import './hud.css';
// Load order matters: the fantasy theme redefines the custom properties and
// overrides the plain rules of hud.css, so it must come last.
import './theme-fantasy.css';

type PanelId = 'chat' | 'self' | 'others' | 'menu'
  | 'belongings' | 'mind' | 'phone' | 'news' | 'tasks' | 'quests';

/** `requires` = the skill id the panel is bound to, exactly as in /play's
 *  PANEL_META: without the skill package the button is gone, so removing a
 *  package degrades the HUD by itself instead of leaving a dead button. */
const PANELS: Array<{ id: PanelId; icon: IconName; title: string; requires?: string }> = [
  { id: 'chat', icon: 'chat', title: 'Chat' },
  { id: 'self', icon: 'self', title: 'Self' },
  { id: 'others', icon: 'others', title: 'Others' },
  { id: 'belongings', icon: 'backpack', title: 'Inventory' },
  { id: 'mind', icon: 'brain', title: 'Mind' },
  { id: 'phone', icon: 'phone', title: 'Phone', requires: 'send_message' },
  { id: 'news', icon: 'news', title: 'News' },
  { id: 'quests', icon: 'scroll', title: 'Quests' },
  { id: 'tasks', icon: 'tasks', title: 'Tasks' },
  // The package's gear (`settings`) — no icon of our own was added for this.
  { id: 'menu', icon: 'settings', title: 'Menu' },
];

/** The panels that are a full reading surface rather than a status strip.
 *  At most ONE of them is open: the dock is one column of fixed height, and
 *  six 120px minimums plus self/others/menu do not fit on any screen — they
 *  would silently spill past the bottom edge. Opening one therefore closes
 *  the other five; self/others/menu keep stacking freely as before. */
const CONTENT_PANELS = new Set<PanelId>([
  'belongings', 'mind', 'phone', 'news', 'tasks', 'quests']);

/** Panels that need more than the dock's 320px (user finding, acceptance of
 *  stage 6 part 1): the inventory is a table of item rows, and MindPanel puts
 *  a navigation column NEXT to its content and folds that column down to bare
 *  icons below 340px — in a 320px dock it was never anything else. Widening
 *  the dock to 480 (half again) is what makes both readable; only one content
 *  panel is ever open, so the column can follow the one that is. The quest
 *  book joins them: a beat row is a timestamp column NEXT to its text, and in
 *  320px the text side is down to a couple of words per line. */
const WIDE_PANELS = new Set<PanelId>(['belongings', 'mind', 'quests']);

/** The prefs fields that are a volume. Each is named exactly like the audio
 *  bus it drives, so applying one is a lookup and not a mapping table. */
const VOLUME_FIELDS = ['master', 'music', 'ambient', 'tts'] as const;

/** Quiet time after which an unpinned chat panel withdraws. Long enough to
 *  read the line that brought it up and start typing, short enough that a
 *  silent room clears the view without anyone reaching for the rail. Roughly
 *  four poll intervals (5 s), so a late answer still counts as "the
 *  conversation goes on" and not as a fresh interruption. */
const CHAT_IDLE_MS = 20000;
/** Storage key of the performance readout — separate from the audio prefs on
 *  purpose, see the block that reads it. */
const PERF_KEY = 'av3d.perf.v1';
/** The idle timeout ran out while the panel was still in use (focus inside it,
 *  or one of its picker modals open) — look again after this. */
const CHAT_BUSY_RECHECK_MS = 5000;

export function Hud({ avatar, username, role }: {
  avatar: string; username: string; role: string;
}) {
  const { t } = useI18n();
  const game = useSyncExternalStore(subscribeGameState, getGameState);
  const [open, setOpen] = useState<Record<PanelId, boolean>>({
    chat: true, self: false, others: false, menu: false,
    belongings: false, mind: false, phone: false, news: false, tasks: false,
    quests: false,
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
    setOpen((o) => {
      const next = { ...o, [id]: !o[id] };
      // Opening a content panel closes its siblings — see CONTENT_PANELS.
      if (!o[id] && CONTENT_PANELS.has(id)) {
        for (const other of CONTENT_PANELS) if (other !== id) next[other] = false;
      }
      return next;
    });
  }, []);

  // --- Game menu (E4-T4) ---------------------------------------------------
  //
  // The menu is a rail panel like the others, so its OPEN state lives here
  // with theirs — one place, one shape. The vanilla side (M, Esc) reaches it
  // through `uiActions`, the same direction the F key already uses for the
  // chat; nothing about the menu goes into the game state, because the game
  // does not care whether a menu is open.
  //
  // `closeMenu` answers whether it actually closed something: that is what
  // lets the Esc chain in main.ts hand the key on to the mode exit when no
  // menu is open, without ever reading React state.
  const menuOpen = useRef(open.menu);
  menuOpen.current = open.menu;
  useEffect(() => {
    uiActions.toggleMenu = () => toggle('menu');
    uiActions.closeMenu = () => {
      if (!menuOpen.current) return false;
      setOpen((o) => ({ ...o, menu: false }));
      return true;
    };
    return () => { uiActions.toggleMenu = undefined; uiActions.closeMenu = undefined; };
  }, [toggle]);

  // The local settings of this browser. Loaded once — `localStorage` has no
  // other writer in this tab — and applied to the audio engine right here, so
  // the stored volumes hold from the first note on and not only after somebody
  // opens the menu.
  const [prefs, setPrefsState] = useState<Prefs>(
    () => loadPrefs(localStorage.getItem(PREFS_KEY)));
  useEffect(() => {
    const audio = getAudio();
    for (const field of VOLUME_FIELDS) audio.setVolume(field, prefs[field]);
    // Mount only: every later change goes through `setPrefs` below, which
    // applies exactly the field that moved instead of re-ramping all four.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  /**
   * THE CONTRACT BEHIND THE MENU, in one function:
   * - a VOLUME acts immediately (`AudioEngine.setVolume`, 50 ms ramp) — a
   *   slider one has to release before hearing anything is unusable;
   * - a SWITCH (musicOn/ambientOn/ttsOn) is only stored. The drivers of tasks
   *   5 and 6 own what is played, and a menu that stopped the music itself
   *   would be a second driver fighting the first;
   * - EVERYTHING is written to `localStorage` at once, not on close. The menu
   *   has no OK button, so "changed" is the only moment there is.
   * `gameActions.applyAudioPrefs` is the seam for those drivers: they register
   * it and hear every change; the state at startup they read themselves with
   * `loadPrefs` (they run before this island mounts).
   */
  const prefsRef = useRef(prefs);
  prefsRef.current = prefs;
  const setPrefs = useCallback((patch: Partial<Prefs>) => {
    // Through the ref, not through a state updater: storing and ramping are
    // side effects, and an updater may be run more than once per change.
    const next = { ...prefsRef.current, ...patch };
    prefsRef.current = next;
    const audio = getAudio();
    for (const field of VOLUME_FIELDS) {
      if (patch[field] !== undefined) audio.setVolume(field, next[field]);
    }
    localStorage.setItem(PREFS_KEY, savePrefs(next));
    gameActions.applyAudioPrefs?.(next);
    setPrefsState(next);
  }, []);

  /**
   * The performance readout (Etappe 5) — a LOCAL view setting like the volumes
   * above, but with its own storage key: `PREFS_KEY` is versioned as the AUDIO
   * prefs (`av3d.audio.v1`), and a display switch has no business in there.
   *
   * One boolean, so no `loadPrefs`-style reader is needed: anything that is
   * not the string "1" means off, which is also what an empty store and a
   * hand-edited value give. `setPerfEnabled` is what actually gates the
   * measuring in `main.ts` — while this is off, nothing is traversed at all.
   */
  const [perfOn, setPerfOn] = useState(() => localStorage.getItem(PERF_KEY) === '1');
  useEffect(() => {
    setPerfEnabled(perfOn);
    localStorage.setItem(PERF_KEY, perfOn ? '1' : '0');
  }, [perfOn]);

  /**
   * The minimap (Etappe 5, task 3) — a local view setting like the readout
   * above, and stored the same way. The DEFAULT IS ON, which is why the reader
   * tests for "0" rather than for "1": a fresh browser has nothing stored, and
   * a map one has to go and switch on is a map nobody finds.
   *
   * There is no `setMinimapEnabled` counterpart to `setPerfEnabled`: the slice
   * is published on its own store, so with the canvas unmounted nothing is
   * subscribed and a publish reaches nobody. `main.ts` gates on the embodied
   * mode, this gates on the switch, and the two together are the condition.
   */
  const [minimapOn, setMinimapOn] = useState(
    () => localStorage.getItem(MINIMAP_PREF_KEY) !== '0');
  useEffect(() => {
    localStorage.setItem(MINIMAP_PREF_KEY, minimapOn ? '1' : '0');
  }, [minimapOn]);

  /**
   * "Show all locations" (Etappe 5) — the administrator's way past the fog of
   * war. A LOCAL switch like the two above, but it decides which VIEW the
   * client fetches (`/play/worldmap?all=1`), and that choice is made once at
   * boot: every tile, the pathfinding grid and the veil are built from it. So
   * it is applied by reloading rather than by unbuilding half the world at
   * runtime — the menu says as much next to the switch.
   *
   * Only offered to role `admin`, and `main.ts` reads the stored value under
   * the same condition: a value left behind in somebody else's browser (a
   * demoted account, a shared machine) must not make the client ask for a view
   * the server answers with 403.
   */
  const showAll = localStorage.getItem(SHOW_ALL_KEY) === '1';
  const setShowAll = useCallback((on: boolean) => {
    localStorage.setItem(SHOW_ALL_KEY, on ? '1' : '0');
    location.reload();
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

  // Leaving the party (Etappe 6): PartyStrip is presentational, so the post
  // and the refresh sit here. No optimistic UI — the strip goes away when the
  // next scene payload says the party is gone. Invitations stay in ScenePanel;
  // answering the same invite from two surfaces would resolve it twice.
  const leaveParty = useCallback(async () => {
    try {
      await apiPost('/play/party/leave', {});
      await refreshScene();
    } catch { /* stale invite/party — the next poll corrects the view */ }
  }, [refreshScene]);

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

  // The ground room of the place the avatar is in. It is a room like any
  // other, but it carries no geometry, so the room walk in the vanilla app
  // cannot derive it from the scene it renders — it is the one room that is
  // recognised by a FLAG instead of by a shape. This poll already has the
  // list, and the id travels the same way the party state does. Empty until
  // the first payload arrives: the walk then simply leaves the room alone.
  const groundRoomId = (data?.rooms || []).find((r) => r.is_ground)?.id || '';
  useEffect(() => {
    setGameState({ groundRoomId });
  }, [groundRoomId]);

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

  // --- Spoken lines (E4-T6) ------------------------------------------------
  //
  // The driver of the voices lives HERE because the poll does: it is the same
  // set of new lines that brings the chat panel up, so both read `voiceover.ts`
  // rather than each deciding for itself what "new" means.
  //
  // The speech queue is NOT registered on `gameActions.applyAudioPrefs`: that
  // slot belongs to the soundtrack driver in main.ts (one field, one owner),
  // and this driver does not need it — the prefs it follows are the React state
  // right above, and the effect below reacts to the ONE derived boolean, so a
  // dragged volume slider (dozens of changes a second) never reaches it.
  const [ttsServer, setTtsServer] = useState(false);
  useEffect(() => {
    let alive = true;
    // ONCE per mount: `config.tts.enabled` does not change while a session
    // runs, and `ttsStatus` never throws (false on any failure).
    void ttsStatus().then((on) => { if (alive) setTtsServer(on); });
    return () => { alive = false; };
  }, []);
  // 'auto' follows the server, 'on' still needs it (nothing can render a voice
  // without the backend), 'off' is off. So: the server AND not switched off.
  const speaking = ttsServer && prefs.ttsOn !== 'off';
  const speakingRef = useRef(speaking);
  speakingRef.current = speaking;
  const voice = useRef<Voiceover | null>(null);
  if (!voice.current) {
    voice.current = createVoiceover({
      synth: (line) => ttsSpeak(line.text, line.speaker, username),
      play: (url) => getAudio().speak(url),
      // SPEECH ONLY — music and the ambience bed keep playing.
      stop: () => getAudio().stopSpeech(),
    });
  }
  useEffect(() => {
    // Switching the voices off silences them at once, and leaving the HUD does
    // too. Both run only on a real change of the flag.
    if (!speaking) voice.current?.clear();
  }, [speaking]);
  useEffect(() => () => voice.current?.clear(), []);

  // Auto SHOW (E3 acceptance): a new line in the room brings the chat up — and
  // (E4-T6) the same lines are what gets read aloud. The detection rides on the
  // ONE poll above (`sceneStampOf` — line count plus the IDENTITY of the last
  // line — as the effect's trigger, and `newSceneLines`, which anchors on that
  // last seen line and takes everything behind it, as the rule) instead of a
  // second subscription.
  //
  // Two cases deliberately do NOT count as new, they only set the baseline:
  // the FIRST payload after mount (otherwise the chat pops open on every page
  // load, which is the opposite of what the auto mode is for) and a room
  // change (walking into a room with an older transcript is not somebody
  // speaking). A room whose transcript then grows is a real line again.
  const seenScene = useRef<SceneSnapshot | null>(null);
  const sceneRoom = data?.room_id || '';
  /** the payload's lines, for the effect that only runs when `sceneStamp`
   *  changed — the array identity is fresh on every poll and says nothing */
  const sceneLines = useRef<SceneLine[]>([]);
  sceneLines.current = data?.scene || [];
  const sceneStamp = data ? sceneStampOf(data.scene) : '';
  useEffect(() => {
    if (!sceneStamp) return;                        // no payload yet
    const prev = seenScene.current;
    const cur: SceneSnapshot = { room: sceneRoom, lines: sceneLines.current };
    seenScene.current = cur;
    // Leaving the room ends its conversation: what is still waiting (and what
    // is sounding) was said WHERE ONE NO LONGER IS. Same interruption as the
    // player's own message below — `newSceneLines` cannot say it, because a
    // room change and silence are both "no new lines" to it.
    if (roomChanged(prev, cur)) voice.current?.clear();
    const fresh = newSceneLines(prev, cur);
    if (!fresh.length) return;
    if (!chatOpen.current) setOpen((o) => ({ ...o, chat: true }));
    // Same one-shot pulse the talk key uses: an appearing panel announces
    // itself once instead of just materialising in the corner.
    setChatHail((n) => n + 1);
    // Speech bubbles (stage 6) over the heads in the scene. Same filter as the
    // voice, so bubble and voice never disagree about who said what: only what
    // a voice in THIS room said, no narration, no notes, and not the player's
    // own words — those are in the composer they were just typed into.
    for (const line of speakableLines(fresh, avatarName)) {
      gameActions.sayBubble?.(line.speaker, line.text);
    }
    // The player's own message is the interruption: it silences the queue, and
    // only what came AFTER it is still worth hearing.
    const rest = afterOwnLine(fresh, avatarName);
    if (rest.length !== fresh.length) voice.current?.clear();
    if (speakingRef.current) {
      voice.current?.push(speakableLines(rest, avatarName));
    }
    // `avatarName` and the refs are deliberately not dependencies: this effect
    // must run exactly once per CHANGED transcript, not whenever the payload
    // object is replaced by an identical one.
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
      {/* Performance readout (Etappe 5): shown while the menu switch is on,
          top-left and read-only — see PerfOverlay.tsx. */}
      {perfOn && <PerfOverlay />}

      {/* Minimap (Etappe 5, task 3): the whole world, north up, top right.
          Only in the embodied mode — in the overview one IS looking at the
          map, and a second small copy of it would say nothing. The switch in
          the game menu is the other half of the condition. */}
      {game.mode === 'embodied' && minimapOn && <Minimap />}

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

      {/* Party strip (Etappe 6): who travels with the avatar, top centre and
          below the mode chip. Fed from THIS container's scene poll — no second
          request — and only present while there is a party at all. */}
      {data?.party && (
        <div className="hud-party">
          <PartyStrip party={data.party} onLeave={leaveParty} />
        </div>
      )}

      <nav className="hud-rail">
        {PANELS.filter((p) => !p.requires || hasCapability(p.requires)).map((p) => (
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
          <ErrorBoundary inline label="Chat">
            <ScenePanel data={data} refreshScene={refreshScene} avatar={avatarName}
              hasCapability={hasCapability} moving={moving} onEnterRoom={handleEnterRoom}
              photoDialog={(ctl) => <PlayerPhotoDialog {...ctl} />} />
          </ErrorBoundary>
        </section>
      )}

      {(open.self || open.others || open.menu || open.belongings || open.mind
        || open.phone || open.news || open.tasks || open.quests) && (
        <div className={'hud-dock'
          + ([...WIDE_PANELS].some((id) => open[id]) ? ' hud-dock-wide' : '')}>
          {/* Esc and M are handled HERE as well, not only in main.ts: the
              global key path ignores anything typed into a form control, and a
              volume slider is one — so after touching a slider the keys would
              be swallowed. The panel holds no text field, so both keys are
              unambiguous inside it.
              And ONLY for those: the global chain listens in the CAPTURE phase
              and has therefore already answered every other press by the time
              this runs — with the storey choice FIRST, which is why closing the
              menu here as well made one Esc close two things (E4-T4 minor). The
              guard is the same predicate main.ts uses, so there is exactly one
              rule about what "typed into a control" means. */}
          {open.menu && (
            <section className="hud-panel hud-menu-panel"
              onKeyDown={(e) => {
                if (e.key !== 'Escape' && e.key.toLowerCase() !== 'm') return;
                if (e.ctrlKey || e.metaKey || e.altKey) return;
                if (!isTypingTarget(e.nativeEvent)) return;
                e.stopPropagation();
                setOpen((o) => ({ ...o, menu: false }));
              }}>
              {panelHead('menu', 'settings', t('Menu'))}
              <div className="hud-panel-body">
                <ErrorBoundary inline label="Menu">
                  <GameMenu prefs={prefs} onChange={setPrefs}
                    perfOn={perfOn} onPerfChange={setPerfOn}
                    minimapOn={minimapOn} onMinimapChange={setMinimapOn}
                    isAdmin={role === 'admin'} showAll={showAll} onShowAllChange={setShowAll}
                    onBackToTitle={() => gameActions.backToTitle?.()} />
                </ErrorBoundary>
              </div>
            </section>
          )}
          {open.self && (
            <section className="hud-panel">
              {panelHead('self', 'self', avatarName || t('Self'))}
              <div className="hud-panel-body">
                <ErrorBoundary inline label="Self"><SelfPanel /></ErrorBoundary>
              </div>
            </section>
          )}
          {open.others && (
            <section className="hud-panel">
              {panelHead('others', 'others', t('Others'))}
              <div className="hud-panel-body">
                <ErrorBoundary inline label="Others"><OthersPanel /></ErrorBoundary>
              </div>
            </section>
          )}
          {/* The content panels (stage 6). They are the SAME components /play
              renders — they poll themselves and take no scene data, so there
              is nothing to wire beyond the frame. Only one of them is ever
              mounted at a time (CONTENT_PANELS), which also keeps their polls
              from all running at once. */}
          {open.belongings && (
            <section className="hud-panel">
              {panelHead('belongings', 'backpack', t('Inventory'))}
              <div className="hud-panel-body">
                <ErrorBoundary inline label="Inventory"><BelongingsPanel /></ErrorBoundary>
              </div>
            </section>
          )}
          {open.mind && (
            <section className="hud-panel">
              {panelHead('mind', 'brain', t('Mind'))}
              <div className="hud-panel-body">
                <ErrorBoundary inline label="Mind"><MindPanel character={avatarName} /></ErrorBoundary>
              </div>
            </section>
          )}
          {open.phone && (
            <section className="hud-panel">
              {panelHead('phone', 'phone', t('Phone'))}
              <div className="hud-panel-body">
                <ErrorBoundary inline label="Phone"><PhonePanel /></ErrorBoundary>
              </div>
            </section>
          )}
          {open.news && (
            <section className="hud-panel">
              {panelHead('news', 'news', t('News'))}
              <div className="hud-panel-body">
                <ErrorBoundary inline label="News"><NewsPanel /></ErrorBoundary>
              </div>
            </section>
          )}
          {open.quests && (
            <section className="hud-panel">
              {panelHead('quests', 'scroll', t('Quests'))}
              <div className="hud-panel-body">
                <ErrorBoundary inline label="Quests"><QuestsPanel /></ErrorBoundary>
              </div>
            </section>
          )}
          {open.tasks && (
            <section className="hud-panel">
              {panelHead('tasks', 'tasks', t('Tasks'))}
              <div className="hud-panel-body">
                <ErrorBoundary inline label="Tasks"><TaskPanel /></ErrorBoundary>
              </div>
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
        {/* Entering an adjacent location (Etappe 3): same prompt shape, and
            deliberately LAST in the priority — talk and elevator win, so one
            F press is never two offers. The vanilla side owns the rule of
            WHEN the offer stands (opening proximity / adjacent cell) and
            performs the real server entry on F. */}
        {!game.talkTarget && !game.elevator && game.enterOffer && (
          <div className="hud-talk">
            {t('Press F to enter {name}').replace('{name}', game.enterOffer.name)}
          </div>
        )}
        {/* Selected figure (E3-T1): always mounted, renders null without a
            selection — the plaque is driven by the bus, not by panel state. */}
        <CharacterPlaque />
      </div>
    </>
  );
}
