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
 * that /play slots in stays where it is. The gallery and Instagram panels
 * followed in stage 6 part 2 WITHOUT their dialog slots: regenerating an image
 * (and animating a post) needs those same admin dialogs, so the HUD simply
 * does not offer the buttons.
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
  GalleryPanel, InstagramPanel,
  PlayerPhotoDialog,
  type SceneData, type SceneLine, type IconName,
} from '@anima/player-ui';
import { CharacterPlaque } from './CharacterPlaque';
import { GameMenu } from './GameMenu';
import { Minimap } from './Minimap';
import { PerfOverlay } from './PerfOverlay';
import { ttsSpeak, ttsStatus } from '../api';
import { elevatorOptions, elevatorSoleOption } from '../game/elevator';
import { nearestOffer } from '../game/offers';
import { getAudio } from '../game/audio';
import { loadPrefs, loadScatterPrefs, savePrefs, saveScatterPrefs, PREFS_KEY,
  SCATTER_PREFS_KEY, type Prefs, type ScatterPrefs } from '../game/prefs';
import { SHOW_ALL_KEY } from '../game/prefs';
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
  | 'belongings' | 'mind' | 'phone' | 'news' | 'tasks' | 'quests' | 'gallery'
  | 'instagram';

/** `requires` = the skill id the panel is bound to, exactly as in /play's
 *  PANEL_META: without the skill package the button is gone, so removing a
 *  package degrades the HUD by itself instead of leaving a dead button. */
const PANELS: Array<{ id: PanelId; icon: IconName; title: string; requires?: string }> = [
  { id: 'chat', icon: 'chat', title: 'Chat' },
  { id: 'self', icon: 'self', title: 'Self' },
  { id: 'others', icon: 'others', title: 'Others' },
  { id: 'belongings', icon: 'backpack', title: 'Inventory' },
  { id: 'mind', icon: 'brain', title: 'Mind' },
  // Like /play's PANEL_META, the gallery carries no `requires`: looking at the
  // avatar's own images is not bound to a skill package.
  { id: 'gallery', icon: 'gallery', title: 'Gallery' },
  // Bound to the instagram skill package, exactly as in /play's PANEL_META:
  // no package, no feed, no button.
  { id: 'instagram', icon: 'instagram', title: 'Instagram', requires: 'instagram' },
  { id: 'phone', icon: 'phone', title: 'Phone', requires: 'send_message' },
  { id: 'news', icon: 'news', title: 'News' },
  { id: 'quests', icon: 'scroll', title: 'Quests' },
  { id: 'tasks', icon: 'tasks', title: 'Tasks' },
  // The package's gear (`settings`) — no icon of our own was added for this.
  { id: 'menu', icon: 'settings', title: 'Menu' },
];

/** The panels that are a full reading surface rather than a status strip.
 *  At most ONE of them is open: the dock is one column of fixed height, and
 *  their 120px minimums plus self/others/menu do not fit on any screen — they
 *  would silently spill past the bottom edge. Opening one therefore closes
 *  all the others; self/others/menu keep stacking freely as before. */
const CONTENT_PANELS = new Set<PanelId>([
  'belongings', 'mind', 'phone', 'news', 'tasks', 'quests', 'gallery',
  'instagram']);

/** Panels that need more than the dock's 320px (user finding, acceptance of
 *  stage 6 part 1): the inventory is a table of item rows, and MindPanel puts
 *  a navigation column NEXT to its content and folds that column down to bare
 *  icons below 340px — in a 320px dock it was never anything else. Widening
 *  the dock to 480 (half again) is what makes both readable; only one content
 *  panel is ever open, so the column can follow the one that is. The quest
 *  book joins them: a beat row is a timestamp column NEXT to its text, and in
 *  320px the text side is down to a couple of words per line. The gallery is
 *  the fourth: its thumbnail grid fills 72px columns, so a 320px dock is three
 *  pictures per row and 480px is five — the same wall, half again as much of
 *  it visible at once. Instagram is the fifth for the plainest reason of all:
 *  a post is a full-width picture, so the dock width IS the picture width. */
const WIDE_PANELS = new Set<PanelId>(['belongings', 'mind', 'quests', 'gallery',
  'instagram']);

/** Storage key of the dock width the user dragged for themselves. Absent =
 *  the widths above decide, which is what every fresh browser starts with. */
const DOCK_WIDTH_KEY = 'av3d.dockWidth';
/** Narrower than this and MindPanel folds its navigation to bare icons again
 *  (the very finding WIDE_PANELS exists for), wider and the dock is most of a
 *  laptop screen with the world reduced to a strip. Both ends are also what a
 *  stored value is checked against: a hand-edited or stale number outside them
 *  is dropped rather than honoured. */
const DOCK_MIN = 280;
const DOCK_MAX = 720;

/** The stored dock width, or null for "let the panels decide". Anything that
 *  is not a number inside the range counts as absent — the column must never
 *  come up unusable because of one bad entry in `localStorage`. */
function readDockWidth(): number | null {
  const raw = Number(localStorage.getItem(DOCK_WIDTH_KEY));
  if (!Number.isFinite(raw) || raw < DOCK_MIN || raw > DOCK_MAX) return null;
  return Math.round(raw);
}

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
    quests: false, gallery: false, instagram: false,
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
   * The scatter detail distances (per-object scatter LOD) — a local view
   * setting like the two above, with a reader of its own because it is three
   * numbers rather than one boolean (`loadScatterPrefs`, which never returns
   * half a setting).
   *
   * `main.ts` reads the store at startup for itself, so nothing here has to
   * run before the world is built; what goes through the action is the CHANGE,
   * and the ground applies it to the standing world at once.
   */
  const [scatterPrefs, setScatterPrefsState] = useState<ScatterPrefs>(
    () => loadScatterPrefs(localStorage.getItem(SCATTER_PREFS_KEY)));
  const setScatterPrefs = useCallback((p: ScatterPrefs) => {
    localStorage.setItem(SCATTER_PREFS_KEY, saveScatterPrefs(p));
    gameActions.applyScatterPrefs?.(p);
    setScatterPrefsState(p);
  }, []);

  /**
   * "Show all locations" (Etappe 5) — the administrator's way past the
   * knowledge filter. A LOCAL switch like the two above, but it decides which VIEW the
   * client fetches (`/play/worldmap?all=1`).
   *
   * It applies LIVE: `main.ts` fetches the other view and reconciles the world
   * against it — the places it adds come in through the reveal path, the ones
   * it takes away are given back. The stored value is only what the NEXT start
   * begins with. It used to reload the page, which threw a built world away
   * for a change of view and dropped the player back on the title gate.
   *
   * Only offered to role `admin`, and `main.ts` reads the stored value under
   * the same condition: a value left behind in somebody else's browser (a
   * demoted account, a shared machine) must not make the client ask for a view
   * the server answers with 403.
   */
  const [showAll, setShowAllState] = useState(
    () => localStorage.getItem(SHOW_ALL_KEY) === '1');
  const setShowAll = useCallback((on: boolean) => {
    localStorage.setItem(SHOW_ALL_KEY, on ? '1' : '0');
    setShowAllState(on);
    gameActions.setShowAll?.(on);
  }, []);

  /**
   * The width of the dock column — the user's, once they have said so.
   *
   * A LOCAL view setting like the readout and the minimap above, but it is
   * dragged rather than switched, so it is written at the END of a gesture and
   * not on every state change: a drag produces a value per frame, and an
   * effect on the state would put a hundred writes into `localStorage` for one
   * pull of the handle. `widthRef` carries the last value alongside the state
   * for exactly that — the pointer-up handler needs the number, not a render.
   *
   * `null` means "nothing stored": the panel-driven widths of WIDE_PANELS
   * apply, which is what a fresh browser and a double-clicked reset both give.
   * A stored width WINS over them, because it is an inline style and the wide
   * class is a class — the person who dragged has said what they want, and a
   * panel must not take it back on opening. `max-width` in the stylesheet
   * still caps it against a narrow window, so no width can push the column
   * off-screen.
   */
  const [dockWidth, setDockWidth] = useState<number | null>(readDockWidth);
  const widthRef = useRef<number | null>(dockWidth);
  const dockRef = useRef<HTMLDivElement | null>(null);
  /** The running drag: where it started, how wide the dock was then, and
   *  whether it has actually moved yet. Null while nothing is being dragged.
   *  `moved` is what keeps a plain click on the handle from storing the
   *  current width — a click is not an adjustment, and the double-click reset
   *  is made of two of them. */
  const dragRef = useRef<{ x: number; w: number; moved: boolean } | null>(null);

  const onGripDown = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    // The MEASURED width, not the stored one: with nothing stored the drag has
    // to continue from whatever the panels are currently giving (320 or 480),
    // or the first pixel of movement would jump the column.
    const w = dockRef.current?.getBoundingClientRect().width ?? DOCK_MIN;
    dragRef.current = { x: e.clientX, w, moved: false };
    e.currentTarget.setPointerCapture(e.pointerId);
    e.preventDefault();
  }, []);

  const onGripMove = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag) return;
    // The dock is anchored on the RIGHT, so dragging the handle left widens
    // it — the delta is inverted on purpose.
    const next = Math.round(Math.min(DOCK_MAX, Math.max(DOCK_MIN,
      drag.w + (drag.x - e.clientX))));
    drag.moved = true;
    widthRef.current = next;
    setDockWidth(next);
  }, []);

  const onGripUp = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    dragRef.current = null;
    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId);
    }
    if (!drag?.moved || widthRef.current == null) return;
    localStorage.setItem(DOCK_WIDTH_KEY, String(widthRef.current));
  }, []);

  /** Double-click on the handle = forget the width. Not "back to 320": with
   *  the entry gone the dock follows the open panel again, which is the
   *  behaviour someone who never touched the handle has. */
  const onGripReset = useCallback(() => {
    dragRef.current = null;
    widthRef.current = null;
    setDockWidth(null);
    localStorage.removeItem(DOCK_WIDTH_KEY);
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

  // What this avatar may NOT walk into (task C2, plan-betreten-und-tueren.md
  // § 3 decision 2). The same poll already carries both verdicts — the rooms
  // of the current place and the four neighbour locations — so the lock state
  // costs no extra request, and it stays OUT of the cached scene payloads: the
  // scene binds it by id when it draws and when the player presses a key.
  //
  // Published only on a real CHANGE, keyed by the serialised maps: `usePoll`
  // hands out a fresh object every five seconds, and pushing that through the
  // bus would re-render the whole HUD island for an unchanged answer.
  // The location travels WITH the room locks: room ids repeat across clones of
  // one template, so the receiver may only bind these locks to the rooms of
  // this very location. Deriving that location from another poll would let the
  // two disagree for a moment; here they are one answer.
  const lockedKey = JSON.stringify([
    (data?.rooms || []).filter((r) => r.enterable === false)
      .map((r) => [r.id, r.reason || '']),
    (['north', 'south', 'east', 'west'] as const)
      .map((d) => data?.neighbors?.[d]).filter((n) => n && n.enterable === false)
      .map((n) => [n!.id, n!.reason || '']),
    data?.location_id || '',
  ]);
  useEffect(() => {
    const [rooms, locations, loc] =
      JSON.parse(lockedKey) as [string[][], string[][], string];
    setGameState({
      lockedRooms: Object.fromEntries(rooms),
      lockedLocations: Object.fromEntries(locations),
      lockedLoc: loc,
    });
  }, [lockedKey]);

  // Toast bridge (E3-T3): the vanilla app renders no text of its own, so a
  // refused step (403 with the server's reason) is shown through the package
  // toast that already lives inside this island.
  const { toast } = useToast();
  useEffect(() => {
    // Only a caller that says so gets translated: a scene finding (§ 4.3) is
    // English source text and its own key, while the server's refusal texts
    // arrive localized already and must not be looked up a second time.
    uiActions.toast = (msg: string, translate?: boolean) =>
      toast(translate ? t(msg) : msg, 'error');
    return () => { uiActions.toast = undefined; };
  }, [toast, t]);

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
      {/* Taking control lives in the panel CHROME, not in the shared SelfPanel
          (/play has no 3D view to fly). Only while one is not embodied — in the
          mode the chip above is the way out. It is the only way back in when the
          avatar sits in a closed room: it is not drawn there, so there is no
          figure to click a plaque out of. */}
      {id === 'self' && game.mode !== 'embodied' && (
        <button className="player-chip" onClick={() => gameActions.takeControl?.()}>
          {t('Take control')}
        </button>
      )}
      <button className="hud-panel-close" onClick={() => toggle(id)}
        title={t('Close')} aria-label={t('Close')}>
        <Icon name="close" size={14} />
      </button>
    </header>
  );

  // Two served storeys leave nothing to choose, so the chip names the one
  // direction F leads and the picker never unfolds (Treppen v2 task 4).
  const soleFloor = game.elevator ? elevatorSoleOption(game.elevator) : null;

  // WHICH offer the bottom row shows: the NEAREST one standing, decided by the
  // same function the F key asks (`game/offers.ts`, bug round 2026-08-30). All
  // four may stand at once and exactly one is drawn — the one the key answers,
  // so the player always sees what F does.
  const offer = nearestOffer(game);

  return (
    <>
      {/* Performance readout (Etappe 5): shown while the menu switch is on,
          top-left and read-only — see PerfOverlay.tsx. */}
      {perfOn && <PerfOverlay />}

      {/* Minimap (Etappe 5, task 3): as far as one can see, north up, top right.
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
            {/* photoDialog `key`: a second prepared payload is a NEW dialog,
                not the old one with new props — without the key the edited
                prompt and the chip selection of the previous 📷 press would
                survive into it. */}
            <ScenePanel data={data} refreshScene={refreshScene} avatar={avatarName}
              hasCapability={hasCapability} moving={moving} onEnterRoom={handleEnterRoom}
              photoDialog={(ctl) => <PlayerPhotoDialog key={ctl.prompt} {...ctl} />} />
          </ErrorBoundary>
        </section>
      )}

      {(open.self || open.others || open.menu || open.belongings || open.mind
        || open.phone || open.news || open.tasks || open.quests || open.gallery
        || open.instagram) && (
        <div ref={dockRef}
          className={'hud-dock'
            + ([...WIDE_PANELS].some((id) => open[id]) ? ' hud-dock-wide' : '')}
          style={dockWidth != null ? { width: dockWidth } : undefined}>
          {/* The width handle sits ON the dock's left edge and is taken out of
              the column's flex flow by `position: absolute` — a flex child
              would eat a share of the height the panels divide between them.
              Pointer events (not mouse) with capture, so the drag survives the
              cursor leaving the 14px strip, which at speed it always does. */}
          <div className="hud-dock-grip" role="separator" aria-orientation="vertical"
            title={t('Drag to resize · double-click to reset')}
            aria-label={t('Drag to resize · double-click to reset')}
            onPointerDown={onGripDown} onPointerMove={onGripMove}
            onPointerUp={onGripUp} onPointerCancel={onGripUp}
            onDoubleClick={onGripReset} />
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
                    scatterPrefs={scatterPrefs} onScatterChange={setScatterPrefs}
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
          {open.gallery && (
            <section className="hud-panel">
              {panelHead('gallery', 'gallery', t('Gallery'))}
              <div className="hud-panel-body">
                {/* No `regenDialog`: the regenerate flow needs the game-admin
                    image dialog, which is not part of the package — without
                    the slot the button is simply not there. Browsing, paging
                    and deleting work in full. */}
                <ErrorBoundary inline label="Gallery"><GalleryPanel /></ErrorBoundary>
              </div>
            </section>
          )}
          {open.instagram && (
            <section className="hud-panel">
              {panelHead('instagram', 'instagram', t('Instagram'))}
              <div className="hud-panel-body">
                {/* Neither `imageGenDialog` nor `animateDialog`: regenerating
                    and animating a post need the game-admin dialogs, which are
                    not part of the package — without the slots those two
                    buttons are simply not there. Reading, liking, commenting
                    and deleting work in full. */}
                <ErrorBoundary inline label="Instagram"><InstagramPanel /></ErrorBoundary>
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
        {offer === 'talk' && game.talkTarget && (
          <div className="hud-talk">
            {t('Press F to talk to {name}').replace('{name}', game.talkTarget.name)}
          </div>
        )}
        {/* Elevator (E3, floors on foot): the same prompt shape as the talk
            chip. Unfolded (F again, or a click) the prompt becomes one button
            per storey; the current one is not among them. Unlike the prompt
            these are operated, so they take the pointer back (hud.css). With
            only ONE storey to ride to there is nothing to unfold: the chip
            says which way F leads and the press is the ride (Treppen v2
            task 4). */}
        {offer === 'elevator' && game.elevator && (
          soleFloor !== null ? (
            <div className="hud-talk">
              {soleFloor > game.elevator.current
                ? t('Press F to go up') : t('Press F to go down')}
            </div>
          ) : game.elevatorOpen ? (
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
        {/* Stairs (stairs task 5): the storey change on foot, and unlike the
            lift there is nothing to choose — a flight leads exactly one storey
            up or down, so the offer IS the button. The vanilla side only
            publishes the offer when the destination storey really has a room
            to enter, so a press can always be honoured. */}
        {offer === 'stairs' && game.stairs && (
          <div className="hud-elevator">
            <button className="hud-elevator-floor"
              onClick={() => gameActions.rideStairs?.()}>
              {game.stairs.dir === 'up'
                ? t('Take the stairs up') : t('Take the stairs down')}
            </button>
          </div>
        )}
        {/* Entering an adjacent location (Etappe 3): same prompt shape. The
            vanilla side owns the rule of WHEN the offer stands (opening
            proximity / free rim) and performs the real server entry on F. */}
        {offer === 'enter' && game.enterOffer && (
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
