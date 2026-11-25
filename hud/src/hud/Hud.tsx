/**
 * HUD v1 of the 3D client (plan-3d-game stage 2, tasks 5 + 6). hud.css carries
 * the structure, theme-fantasy.css the look (variables redefined under #hud).
 *
 * Layout: the top bar carries the world name and, behind a separator, one row
 * of panel buttons; every panel except the chat opens as a DROPDOWN hanging
 * below the bar, side by side left to right in opening order, at most
 * `MAX_DROPS` at once (dropdowns.ts). The chat is a docked panel bottom-left,
 * the avatar's plans and the minimap share the top-right corner. The root
 * never catches the pointer — only the bar and the panels do (hud.css), so
 * camera dragging on the canvas keeps working everywhere else.
 *
 * Stage 6 added the remaining /play panels (inventory, mind, phone, news,
 * tasks) to the button row. They are the identical components out of
 * `@anima/player-ui` and poll themselves, so the frame is all this file adds;
 * `requires` on a button entry hides it when the bound skill package is gone.
 *
 * This container owns the ONE `/play/scene` poll: ScenePanel receives data +
 * refresh as props and never polls itself. The `photoDialog` slot is filled
 * with `PlayerPhotoDialog` (stage 6), the package's slim player-side dialog —
 * the big game-admin `ImageGenDialog` stays in the admin. Gallery regeneration, Instagram
 * regeneration/animation and profile portraits use slim player dialogs too.
 * One character-form host provides the portrait dialog throughout this HUD.
 *
 * The CHAT panel additionally runs in an auto mode (E3 acceptance) — it shows
 * itself when something is said and withdraws when the room stays silent; see
 * the block around CHAT_IDLE_MS below. Self/Others stay purely manual.
 */
import { setPairFacing } from '@anima/player-ui/pairInteractions';
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import {
  SYNC_ENDPOINTS, apiGet, apiPost, usePoll, useI18n, useToast, Icon, ErrorBoundary,
  ScenePanel, ActionsTree, SelfPanel, OthersPanel,
  BelongingsPanel, MindPanel, PhonePanel, NewsPanel, TaskPanel, QuestsPanel,
  AvatarSettingsPanel, GalleryPanel, InstagramPanel, NoticeBanner, useOpenTopics,
  PlayerPhotoDialog, PlayerRegenDialog, PlayerAnimateDialog, PlayerProfileImageDialog,
  CharacterFormHostContext, type CharacterFormHost, SCENE_ROW_ID_ATTR,
  type ScreenshotPhoto, type SceneData, type SceneLine, type IconName,
} from '@anima/player-ui';
import { CharacterPlaque } from './CharacterPlaque';
import { ChatPortraits } from './ChatPortraits';
import { GameMenu } from './GameMenu';
import { InfoPanel } from './InfoPanel';
import { IntentsBox } from './IntentsBox';
import { PartyBadge } from './PartyBadge';
import {
  DROP_MAX, DROP_MIN, DROP_WIDTHS_KEY, openDrop, readDropWidths, toggleDrop,
} from './dropdowns';
import { SceneTile } from './SceneTile';
import { TILE_COLLAPSE_BELOW_PX } from './sceneTile';
import { PlaceMenu } from './PlaceMenu';
import { TravelBar } from './TravelBar';
import type { TravelPick } from '../game/travelPick';
import { Minimap } from './Minimap';
import { PerfOverlay } from './PerfOverlay';
import { authStatus, ttsSpeak, ttsStatus } from '../api';
import { elevatorOptions, elevatorSoleOption } from '../game/elevator';
import { nearestOffer } from '../game/offers';
import { loadGraphicsPrefs, loadPrefs, loadScatterPrefs, saveGraphicsPrefs,
  savePrefs, saveScatterPrefs, GRAPHICS_PREFS_KEY, PREFS_KEY, SCATTER_PREFS_KEY,
  type GraphicsPrefs, type Prefs, type ScatterPrefs } from '../game/prefs';
import { SHOW_ALL_KEY } from '../game/prefs';
import { MINIMAP_PREF_KEY } from '../game/minimap';
import {
  afterOwnLine, createVoiceover, newSceneLines, roomChanged, sceneStampOf,
  speakableLines, type SceneSnapshot, type Voiceover,
} from '../game/voiceover';
import { isTypingTarget } from './dom';
import {
  CHAT_ALPHA_DEFAULT, CHAT_ALPHA_KEY, CHAT_MIN_H, CHAT_MIN_W,
  CHAT_PORTRAITS_KEY, CHAT_SIZE_KEY, CHAT_VIEWPORT_MARGIN_W,
  PORTRAITS_DEFAULT, PORTRAITS_MAX,
  PORTRAITS_MIN, chatFocusId, clampChatSize, pickPortraitSpeakers,
  readChatAlpha, readChatSize, readPortraitCount, rowAtCenter, writeChatSize,
  type ChatSize, type RowExtent,
  actionsDrawerSide,
} from './chatPanel';
import { mergeRects } from './bridge';
import { gameActions, getHudUiState, getBoot, subscribeBoot, setHudUiState, setPerfStats, getGameState, setGameState, subscribeGameState, uiActions } from './bus';
import '@anima/player-ui/panels.css';
import './hud.css';
// Load order matters: the fantasy theme redefines the custom properties and
// overrides the plain rules of hud.css, so it must come last.
import './theme-fantasy.css';

type PanelId = 'chat' | 'others' | 'menu'
  | 'belongings' | 'mind' | 'phone' | 'news' | 'tasks' | 'quests' | 'gallery'
  | 'instagram' | 'avatar';

/** `requires` = the skill id the panel is bound to: without the skill
 *  package the button is gone, so removing a
 *  package degrades the HUD by itself instead of leaving a dead button. */
const PANELS: Array<{ id: PanelId; icon: IconName; title: string; requires?: string }> = [
  { id: 'chat', icon: 'chat', title: 'Chat' },
  { id: 'avatar', icon: 'avatar', title: 'Avatar' },
  { id: 'others', icon: 'others', title: 'Others' },
  { id: 'belongings', icon: 'backpack', title: 'Inventory' },
  { id: 'mind', icon: 'brain', title: 'Mind' },
  // The gallery carries no `requires`: looking at the
  // avatar's own images is not bound to a skill package.
  { id: 'gallery', icon: 'gallery', title: 'Gallery' },
  // Bound to the instagram skill package: no package, no feed, no button.
  { id: 'instagram', icon: 'instagram', title: 'Instagram', requires: 'instagram' },
  { id: 'phone', icon: 'phone', title: 'Phone', requires: 'send_message' },
  { id: 'news', icon: 'news', title: 'News' },
  { id: 'quests', icon: 'scroll', title: 'Quests' },
  { id: 'tasks', icon: 'tasks', title: 'Tasks' },
];

/** What a spectator may open: the panels that need no avatar. The menu is
 *  not in the button row at all — it has its own button at the far right of
 *  the bar, next to "Log out", and drops down there (user ruling). */
const SPECTATOR_PANELS = new Set<PanelId>(['news', 'tasks']);

/** The panels that are a full reading surface rather than a status strip.
 *  As a dropdown they take a FIXED height (hud.css `.hud-drop-tall`) instead
 *  of their content's: their lists scroll inside, and a dropdown that grew and
 *  shrank with every poll would jump under the pointer. Self/Others/Menu are
 *  short and size to their content. */
const CONTENT_PANELS = new Set<PanelId>([
  'belongings', 'mind', 'phone', 'news', 'tasks', 'quests', 'gallery',
  'instagram', 'avatar']);

/** Panels that need more than the default 320px (user finding, acceptance of
 *  stage 6 part 1): the inventory is a table of item rows, and MindPanel puts
 *  a navigation column NEXT to its content and folds that column down to bare
 *  icons below 340px. The quest book joins them: a beat row is a timestamp
 *  column NEXT to its text. The gallery fills 72px thumbnail columns, so 320px
 *  is three pictures per row and 480px is five. Instagram for the plainest
 *  reason of all: a post is a full-width picture, so the panel width IS the
 *  picture width. A width the player dragged wins over this (dropdowns.ts). */
const WIDE_PANELS = new Set<PanelId>(['belongings', 'mind', 'quests', 'gallery',
  'instagram', 'avatar']);

/** Quiet time after which an unpinned chat panel withdraws. Long enough to
 *  read the line that brought it up and start typing, short enough that a
 *  silent room clears the view without anyone reaching for its button. Roughly
 *  four poll intervals (5 s), so a late answer still counts as "the
 *  conversation goes on" and not as a fresh interruption. */
const CHAT_IDLE_MS = 20000;
/** Storage key of the performance readout — separate from the audio prefs on
 *  purpose, see the block that reads it. */
const PERF_KEY = 'av3d.perf.v1';
/** Storage key of the action drawer beside the chat: "1" = open. */
const CHAT_ACTIONS_KEY = 'av3d.chat.actions';
/** The idle timeout ran out while the panel was still in use (focus inside it,
 *  or one of its picker modals open) — look again after this. */
const CHAT_BUSY_RECHECK_MS = 5000;

/** The positions the portrait-count switch in the chat head offers. Derived
 *  from the range, so the switch cannot drift from the stored value's check. */
const PORTRAIT_CHOICES = Array.from(
  { length: PORTRAITS_MAX - PORTRAITS_MIN + 1 }, (_, i) => PORTRAITS_MIN + i);

/** How close to the bottom still counts as "the transcript sticks to the end".
 *  The SAME slack `ScenePanel` uses for its own auto-scroll — the two must
 *  agree, or the picture column would show a resting state the transcript is
 *  no longer in. Written down here rather than imported because the package
 *  keeps it private; if it ever moves, this comment is where to look. */
const SCENE_STICK_SLACK_PX = 48;

export function Hud({ avatar, username, role }: {
  avatar: string; username: string; role: string;
}) {
  useEffect(() => setPairFacing((phase, id, partner) => gameActions.pairFacing?.(phase, id, partner)), []);
  const { t } = useI18n();
  const spectating = !avatar;
  const characterFormHost = useMemo<CharacterFormHost>(() => ({
    renderImageDialog: (ctl) => <PlayerProfileImageDialog ctl={ctl} />,
  }), []);
  const game = useSyncExternalStore(subscribeGameState, getGameState);
  const boot = useSyncExternalStore(subscribeBoot, getBoot).state;
  /** The chat panel (bottom-left, auto mode below) is not a dropdown. */
  const [chatShown, setChatShown] = useState(true);
  /** The open dropdowns, oldest first — see dropdowns.ts for the cap. */
  const [drops, setDrops] = useState<PanelId[]>([]);
  /** The game menu: its own button at the right end of the bar, its own
   *  dropdown under it (not part of `drops`). */
  const [menuOpen, setMenuOpen] = useState(false);
  /** The party dropdown under the party badge in the bar (PartyBadge). */
  const [partyOpen, setPartyOpen] = useState(false);
  const partyOpenRef = useRef(partyOpen);
  partyOpenRef.current = partyOpen;
  const isOpen = (id: PanelId) => (id === 'chat' ? chatShown : drops.includes(id));
  const [tabsEl, setTabsEl] = useState<HTMLElement | null>(null);
  const dropsOpen = drops.length > 0;
  /** The world's name for the top bar. `/auth/status` carries it for a
   *  signed-in caller; asked once per mount, the product name stands in until
   *  (and unless) it arrives. */
  const [worldName, setWorldName] = useState('');
  useEffect(() => {
    let alive = true;
    authStatus().then((s) => { if (alive) setWorldName((s.world || '').trim()); })
      .catch(() => { /* the product name stays */ });
    return () => { alive = false; };
  }, []);
  const [winW, setWinW] = useState(() => window.innerWidth);
  const narrow = winW < TILE_COLLAPSE_BELOW_PX;
  useEffect(() => {
    const resize = () => setWinW(window.innerWidth);
    window.addEventListener('resize', resize);
    return () => window.removeEventListener('resize', resize);
  }, []);
  const unread = useOpenTopics(drops.includes('instagram'));
  /** `chatShown` for callbacks that must not re-subscribe on every toggle. */
  const chatOpen = useRef(chatShown);
  chatOpen.current = chatShown;
  /**
   * The chat panel knows two modes, and its button switches between them:
   * unpinned (the auto mode — shows itself on a new line, withdraws when
   * idle) and pinned open (stays until it is closed again). ONE click
   * decides it: opening by hand pins, closing unpins — the auto state is
   * simply discarded, there is no three-click cycle to learn. Closing keeps
   * the auto SHOW alive on purpose: "away for now" is not "never again", and
   * the next spoken line brings the panel back.
   */
  const [chatPinned, setChatPinned] = useState(false);
  /** the rendered chat section — for the focus check of the idle timeout */
  const chatRef = useRef<HTMLElement | null>(null);
  const toggle = useCallback((id: PanelId) => {
    if (id === 'chat') {
      setChatPinned(!chatOpen.current);
      setChatShown((c) => !c);
      return;
    }
    // The menu hangs under its own button at the right edge and does not
    // count against the dropdown row's cap.
    if (id === 'menu') {
      setMenuOpen((m) => !m);
      return;
    }
    // A fourth dropdown closes the oldest one — see dropdowns.ts.
    setDrops((d) => toggleDrop(d, id));
  }, []);
  const showDrop = useCallback((id: PanelId) => setDrops((d) => openDrop(d, id)), []);

  // --- Game menu (E4-T4) ---------------------------------------------------
  //
  // The menu is a dropdown like the others, so its OPEN state lives here
  // with theirs — one place, one shape. The vanilla side (M, Esc) reaches it
  // through `uiActions`, the same direction the F key already uses for the
  // chat. A separate UI snapshot tells the scene which HUD owns a key.
  //
  // Publish menu ownership separately from the command that closes it.
  // The party dropdown hangs from the bar as well and closes on Esc the same
  // way, so the bus flag means "a bar dropdown is open": one Esc closes the
  // party dropdown first, the next one the game menu.
  useEffect(() => {
    setHudUiState({ menuOpen: menuOpen || partyOpen });
  }, [menuOpen, partyOpen]);
  useEffect(() => {
    uiActions.toggleMenu = () => toggle('menu');
    uiActions.closeMenu = () => {
      if (partyOpenRef.current) setPartyOpen(false);
      else setMenuOpen(false);
    };
    return () => { uiActions.toggleMenu = undefined; uiActions.closeMenu = undefined; };
  }, [toggle]);

  /** Focus and portalled overlays belong to the HUD. Publish plain flags so
   *  scene keyboard decisions also work with an embedded browser bridge. */
  useEffect(() => {
    const updateFocus = (e?: FocusEvent) => {
      setHudUiState({ typing: isTypingTarget({ target: e?.type === 'focusout'
        ? e.relatedTarget : document.activeElement } as Event) });
    };
    const updateOverlays = () => {
      setHudUiState({ overlayOpen: !!document.querySelector(
        '.lb-overlay, .ga-modal-backdrop, .player-gallery-overlay') });
    };
    updateFocus();
    updateOverlays();
    document.addEventListener('focusin', updateFocus);
    document.addEventListener('focusout', updateFocus);
    const observer = new MutationObserver(updateOverlays);
    observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['class'] });
    return () => {
      document.removeEventListener('focusin', updateFocus);
      document.removeEventListener('focusout', updateFocus);
      observer.disconnect();
      setHudUiState({ menuOpen: false, typing: false, overlayOpen: false, hitRects: [] });
    };
  }, []);

  /** Measure only non-modal surfaces. Portalled overlays own the full window
   *  through overlayOpen, never through a full-screen hit rectangle. */
  useEffect(() => {
    const selector = '.hud-scene-tile, .hud-scene-icon, .hud-drop, .hud-panel, .hud-self, .hud-intents, .hud-mode, .hud-party-drop, '
      + '.hud-travel, .hud-talk, .hud-elevator, .hud-plaque, .hud-minimap, .ga-toast, '
      // The action drawer's handle: its panel is a `.hud-panel` already, and
      // the drawer's own box is drag-through (it is as tall as the chat).
      + '.hud-chat-actions-handle, '
      // The notice banner's root is zero-height by design: measure its rows,
      // or a native/iframe host passes the click on × through to the scene.
      + '.hud-top, .info-panel, .open-view-badge, .hud-notices .player-notice';
    let frame = 0;
    const observed = new Set<Element>();
    const measure = () => {
      frame = 0;
      const nodes = new Set(document.querySelectorAll(selector));
      for (const node of observed) if (!nodes.has(node)) { resize.unobserve(node); observed.delete(node); }
      const rects = [];
      for (const node of nodes) {
        if (!observed.has(node)) { observed.add(node); resize.observe(node); }
        const { x, y, width: w, height: h } = node.getBoundingClientRect();
        if (w > 0 && h > 0 && getComputedStyle(node).visibility !== 'hidden') rects.push({ x, y, w, h });
      }
      const next = mergeRects(rects);
      if (JSON.stringify(next) !== JSON.stringify(getHudUiState().hitRects)) setHudUiState({ hitRects: next });
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(measure); };
    const resize = new ResizeObserver(schedule);
    const mutations = new MutationObserver(schedule);
    mutations.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['class', 'style'] });
    window.addEventListener('resize', schedule);
    schedule();
    return () => {
      cancelAnimationFrame(frame);
      resize.disconnect(); mutations.disconnect();
      window.removeEventListener('resize', schedule);
    };
  }, []);

  // The local settings of this browser. Loaded once — `localStorage` has no
  // other writer in this tab — and sent to the scene audio handler here, so
  // the stored volumes hold from the first note on and not only after somebody
  // opens the menu.
  const [prefs, setPrefsState] = useState<Prefs>(
    () => loadPrefs(localStorage.getItem(PREFS_KEY)));
  useEffect(() => {
    gameActions.setVolumes?.(prefs);
    // Mount only: every later change goes through `setPrefs` below, which
    // lets the scene apply only the volumes that changed.
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
    gameActions.setVolumes?.(next);
    localStorage.setItem(PREFS_KEY, savePrefs(next));
    gameActions.applyAudioPrefs?.(next);
    setPrefsState(next);
  }, []);

  /**
   * The performance readout (stage 5) — a LOCAL view setting like the volumes
   * above, but with its own storage key: `PREFS_KEY` is versioned as the AUDIO
   * prefs (`av3d.audio.v1`), and a display switch has no business in there.
   *
   * One boolean, so no `loadPrefs`-style reader is needed: anything that is
   * not the string "1" means off, which is also what an empty store and a
   * hand-edited value give. `HudUiState.perfOn` is what actually gates the
   * measuring in `main.ts` — while this is off, nothing is traversed at all.
   * Switching it off also drops the last numbers, so re-opening never shows a
   * frozen picture from minutes ago.
   */
  const [perfOn, setPerfOn] = useState(() => localStorage.getItem(PERF_KEY) === '1');
  useEffect(() => {
    setHudUiState({ perfOn });
    if (!perfOn) setPerfStats(null);
    localStorage.setItem(PERF_KEY, perfOn ? '1' : '0');
  }, [perfOn]);

  /**
   * The minimap (stage 5, task 3) — a local view setting like the readout
   * above, and stored the same way. The DEFAULT IS ON, which is why the reader
   * tests for "0" rather than for "1": a fresh browser has nothing stored, and
   * a map one has to go and switch on is a map nobody finds.
   *
   * There is no `setMinimapEnabled` counterpart to `HudUiState.perfOn`: the slice
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
   * The graphics settings (Task 26d) — anti-aliasing and shadows, the
   * Graphics tab next to the detail distances. Same contract as those: stored
   * at once, the CHANGE goes to the scene through the action, and the scene
   * reads the store for itself at startup (the browser's anti-aliasing can
   * ONLY be read there — WebGL fixes it at context creation).
   */
  const [graphicsPrefs, setGraphicsPrefsState] = useState<GraphicsPrefs>(
    () => loadGraphicsPrefs(localStorage.getItem(GRAPHICS_PREFS_KEY)));
  const setGraphicsPrefs = useCallback((p: GraphicsPrefs) => {
    localStorage.setItem(GRAPHICS_PREFS_KEY, saveGraphicsPrefs(p));
    gameActions.applyGraphicsPrefs?.(p);
    setGraphicsPrefsState(p);
  }, []);

  /**
   * "Show all locations" (stage 5) — the administrator's way past the
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
   * The width of each dropdown — the player's, once they have said so.
   *
   * A LOCAL view setting like the readout and the minimap above, but dragged
   * rather than switched, so it is written at the END of a gesture and not on
   * every state change: a drag produces a value per frame. `dragRef` carries
   * the running value for the pointer-up handler, which needs the number, not
   * a render.
   *
   * Per PANEL id: the inventory wants a different width than the menu, and a
   * single shared width would make every panel follow the last one dragged.
   * An id without an entry follows WIDE_PANELS. A stored width WINS over that,
   * because it is an inline style and the wide class is a class; `max-width`
   * in the stylesheet still caps it against a narrow window.
   */
  const [dropWidths, setDropWidths] = useState<Record<string, number>>(
    () => readDropWidths(localStorage.getItem(DROP_WIDTHS_KEY)));
  const dropWidthsRef = useRef(dropWidths);
  dropWidthsRef.current = dropWidths;
  /** The running drag: which panel, where it started, how wide the panel was
   *  then, the last width, and whether it has moved at all — a plain click on
   *  the handle is not an adjustment, and the double-click reset is made of
   *  two of them. Null while nothing is being dragged. */
  const dragRef = useRef<
    { id: PanelId; x: number; w: number; last: number; moved: boolean } | null>(null);

  const onGripDown = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    const id = e.currentTarget.dataset.panel as PanelId | undefined;
    if (!id) return;
    // The MEASURED width, not the stored one: with nothing stored the drag has
    // to continue from whatever the stylesheet is giving (320 or 480), or the
    // first pixel of movement would jump the panel.
    const w = e.currentTarget.parentElement?.getBoundingClientRect().width ?? DROP_MIN;
    dragRef.current = { id, x: e.clientX, w, last: w, moved: false };
    e.currentTarget.setPointerCapture(e.pointerId);
    e.preventDefault();
  }, []);

  const onGripMove = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag) return;
    // The handle sits on the RIGHT edge and the panel grows to the right.
    const next = Math.round(Math.min(DROP_MAX, Math.max(DROP_MIN,
      drag.w + (e.clientX - drag.x))));
    drag.moved = true;
    drag.last = next;
    setDropWidths((all) => (all[drag.id] === next ? all : { ...all, [drag.id]: next }));
  }, []);

  const onGripUp = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    dragRef.current = null;
    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId);
    }
    if (!drag?.moved) return;
    localStorage.setItem(DROP_WIDTHS_KEY, JSON.stringify(
      { ...dropWidthsRef.current, [drag.id]: drag.last }));
  }, []);

  /** Double-click on the handle = forget this panel's width. Not "back to
   *  320": with the entry gone the panel follows WIDE_PANELS again, which is
   *  the behaviour someone who never touched the handle has. */
  const onGripReset = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    const id = e.currentTarget.dataset.panel;
    dragRef.current = null;
    if (!id) return;
    const next = { ...dropWidthsRef.current };
    delete next[id];
    setDropWidths(next);
    localStorage.setItem(DROP_WIDTHS_KEY, JSON.stringify(next));
  }, []);

  /**
   * --- The chat window's own size (plan-hud-chat-portraits.md 2a) ----------
   *
   * The chat is the ONE panel that is not a dropdown, so it carries handles
   * of its own: the top edge, the right edge and the corner between them —
   * the two directions a panel anchored bottom-left can grow in.
   *
   * The GESTURE is the dropdown handle's, down to the details that make it usable:
   * pointer capture (at any real speed the cursor leaves a 9px strip at once),
   * the start size MEASURED rather than read from the store (with nothing
   * stored the drag has to continue from whatever the stylesheet is giving, or
   * the first pixel of movement jumps), a `moved` flag so a plain click stores
   * nothing, the write on pointer-up only instead of one per frame, and a
   * double-click that FORGETS the size rather than setting a number — with the
   * entry gone the stylesheet decides again, which is what somebody who never
   * touched a handle has.
   *
   * The panel hangs bottom-left and grows up and to the right, so the top
   * edge is -Δy and the right edge +Δx.
   *
   * The dragged size is an INLINE style and therefore beats the stylesheet's
   * `width`/`height`. It also lifts the stylesheet's DEFAULT width cap: that
   * one stops short of the bottom-centre plaque, which is right for a panel
   * nobody has touched and wrong for one the user is pulling wider on purpose.
   * So a dragged size writes its own `max-width` of "the window", and the
   * clamp keeps the same ceiling in JS (`clampChatSize`, window handed in).
   * `max-height` is untouched — the plaque question is a width question.
   */
  const [chatSize, setChatSize] = useState<ChatSize | null>(
    () => readChatSize(localStorage.getItem(CHAT_SIZE_KEY)));
  const chatSizeRef = useRef<ChatSize | null>(chatSize);
  /** The running drag: where it started, how big the panel was then, WHICH
   *  handle is being pulled, and whether it has actually moved yet. */
  const chatDragRef = useRef<
    { x: number; y: number; w: number; h: number; edge: string; moved: boolean }
    | null>(null);

  const onChatGripDown = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    const box = chatRef.current?.getBoundingClientRect();
    chatDragRef.current = {
      x: e.clientX,
      y: e.clientY,
      w: box?.width ?? CHAT_MIN_W,
      h: box?.height ?? CHAT_MIN_H,
      // The handle says which axes it moves; the corner moves both.
      edge: e.currentTarget.dataset.edge || 'corner',
      moved: false,
    };
    e.currentTarget.setPointerCapture(e.pointerId);
    e.preventDefault();
  }, []);

  const onChatGripMove = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    const drag = chatDragRef.current;
    if (!drag) return;
    // The window is MEASURED here and handed over; the rule itself reads
    // nothing, which is what keeps it checkable outside a browser.
    const next = clampChatSize(
      drag.edge === 'top' ? drag.w : drag.w + (e.clientX - drag.x),
      drag.edge === 'right' ? drag.h : drag.h - (e.clientY - drag.y),
      { w: window.innerWidth, h: window.innerHeight });
    drag.moved = true;
    chatSizeRef.current = next;
    setChatSize(next);
  }, []);

  const onChatGripUp = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    const drag = chatDragRef.current;
    chatDragRef.current = null;
    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId);
    }
    if (!drag?.moved || !chatSizeRef.current) return;
    localStorage.setItem(CHAT_SIZE_KEY, writeChatSize(chatSizeRef.current));
  }, []);

  /** Double-click on a handle = forget the size, not "back to 840 x 680". */
  const onChatGripReset = useCallback(() => {
    chatDragRef.current = null;
    chatSizeRef.current = null;
    setChatSize(null);
    localStorage.removeItem(CHAT_SIZE_KEY);
  }, []);

  /**
   * --- The action drawer on the chat's right edge -------------------------
   *
   * What the avatar can START (poses, furniture, pair actions) left the
   * transcript for a drawer beside it (`ActionsTree`); the running rows
   * (Accept / Stop / meters) stay in the chat. Open or closed is a LOCAL view
   * setting like the portrait count, so it survives a reload.
   *
   * The chat clips its children (`.hud-panel { overflow: hidden }`), so the
   * drawer cannot be a child hanging out of it: it is a SIBLING that follows
   * the chat's measured box. The observer catches every size the panel takes
   * (the drag included) and fires once on its own when it starts; the window
   * listener catches the moves that keep the size (the panel hangs on the
   * bottom edge). OFFSETS, not the bounding rect: the arrival animation's
   * transform must not shift the drawer. Its handle lies OUTSIDE the chat,
   * so the chat's right-edge grip (inside it) keeps working. With the chat
   * dragged to the right window edge the drawer flips to the chat's LEFT
   * edge (`actionsDrawerSide` in chatPanel.ts) instead of being squeezed.
   */
  const [actionsOpen, setActionsOpen] = useState(
    () => localStorage.getItem(CHAT_ACTIONS_KEY) === '1');
  useEffect(() => {
    localStorage.setItem(CHAT_ACTIONS_KEY, actionsOpen ? '1' : '0');
  }, [actionsOpen]);
  const toggleActions = useCallback(() => setActionsOpen((o) => !o), []);
  /** the rendered drawer — for the idle timeout's "still in use" check */
  const actionsRef = useRef<HTMLDivElement | null>(null);
  // `cw`: the width of the chat's container — what the drawer may use on
  // either side (`actionsDrawerSide`, chatPanel.ts).
  const [chatBox, setChatBox] = useState<
    { x: number; y: number; w: number; h: number; cw: number } | null>(null);
  useEffect(() => {
    const el = chatRef.current;
    if (!chatShown || spectating || !el) return;
    const measure = () => setChatBox((prev) => {
      const cw = (el.offsetParent as HTMLElement | null)?.clientWidth ?? window.innerWidth;
      const next = { x: el.offsetLeft, y: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight, cw };
      return prev && prev.x === next.x && prev.y === next.y && prev.w === next.w
        && prev.h === next.h && prev.cw === next.cw ? prev : next;
    });
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    window.addEventListener('resize', measure);
    return () => {
      ro.disconnect();
      window.removeEventListener('resize', measure);
    };
  }, [chatShown, spectating]);

  /**
   * How solid the chat window is drawn over the world (2d) and how many
   * portraits stand next to the transcript (2e). Two LOCAL view settings like
   * the minimap and the performance readout, each with its own key and its own
   * range check — a hand-edited store must never leave the window invisible or
   * the column empty.
   *
   * Both are CLICKED, not dragged, so they are written straight away; the ref
   * next to each is what keeps a repeated value from writing again.
   */
  const [chatAlpha, setChatAlphaState] = useState(
    () => readChatAlpha(localStorage.getItem(CHAT_ALPHA_KEY)) ?? CHAT_ALPHA_DEFAULT);
  const chatAlphaRef = useRef(chatAlpha);
  const setChatAlpha = useCallback((v: number) => {
    if (v === chatAlphaRef.current) return;
    chatAlphaRef.current = v;
    localStorage.setItem(CHAT_ALPHA_KEY, String(v));
    setChatAlphaState(v);
  }, []);

  const [chatPortraits, setChatPortraitsState] = useState(
    () => readPortraitCount(localStorage.getItem(CHAT_PORTRAITS_KEY))
      ?? PORTRAITS_DEFAULT);
  const chatPortraitsRef = useRef(chatPortraits);
  const setChatPortraits = useCallback((n: number) => {
    if (n === chatPortraitsRef.current) return;
    chatPortraitsRef.current = n;
    localStorage.setItem(CHAT_PORTRAITS_KEY, String(n));
    setChatPortraitsState(n);
  }, []);

  const { data, refresh: refreshScene } = usePoll<SceneData>(
    'play-scene', () => apiGet<SceneData>('/play/scene'), SYNC_ENDPOINTS.scene);

  const [travelPick, setTravelPick] = useState<TravelPick | null>(null);
  useEffect(() => {
    if (data?.travel || (travelPick && data?.location_id === travelPick.id)) setTravelPick(null);
  }, [data?.travel, data?.location_id, travelPick]);

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

  // Leaving the party and taking back an own invitation: PartyBadge is
  // presentational, so the posts and the refresh sit here. No optimistic UI —
  // the badge changes when the next scene payload says so. Invitations put TO
  // the avatar stay in ScenePanel; answering the same invite from two
  // surfaces would resolve it twice.
  const leaveParty = useCallback(async () => {
    try {
      await apiPost('/play/party/leave', {});
      await refreshScene();
    } catch { /* stale invite/party — the next poll corrects the view */ }
  }, [refreshScene]);
  const takeBackPartyInvite = useCallback(async (inviteId: string) => {
    try {
      await apiPost('/play/party/cancel', { invite_id: inviteId });
    } catch { /* answered in the meantime — the refresh shows the outcome */ }
    await refreshScene();
  }, [refreshScene]);

  // The header names who stands IN the room (`present_detail`, the figures),
  // not the earshot roster `present` — a passer-by outside the walls stays
  // addressable but is not "here".
  const inRoom = (data?.present_detail || []).map((p) => p.name);
  const avatarName = data?.avatar || avatar;

  // The party badge in the bar: there while the avatar is in a party or
  // waits for an answer to its own invitation, never while spectating. A
  // dropdown whose badge has gone closes with it, so no invisible dropdown
  // keeps the Esc key.
  const partyShown = !spectating
    && (!!data?.party || (data?.party_invites_sent?.length ?? 0) > 0);
  useEffect(() => { if (!partyShown) setPartyOpen(false); }, [partyShown]);
  // The faces' cache-busters: the history's speakers, the present and the
  // avatar each carry theirs in the same payload.
  const faceVersions = useMemo(() => {
    const v: Record<string, string> = { ...(data?.speaker_expr_versions ?? {}) };
    for (const p of data?.present_detail ?? []) if (p.expr_version) v[p.name] = p.expr_version;
    if (data?.avatar && data.avatar_expr_version) v[data.avatar] = data.avatar_expr_version;
    return v;
  }, [data?.speaker_expr_versions, data?.present_detail, data?.avatar, data?.avatar_expr_version]);

  // Party follower (E3-T3): `party.role === 'follower'` locks movement. The
  // vanilla side reads it off the bus and stops steering; the server refuses
  // the step regardless.
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

  // The CORRIDOR of every storey of that place (§ A13b), by storey. Same case
  // as the ground room above and travelling the same way: a corridor is what
  // is NOT a room on its storey, so it carries no geometry either and is
  // recognised by its flag, never by the server's reserved id. Keyed by the
  // serialised map because a fresh object every poll would publish on every
  // tick (the pattern the lock maps below use).
  const floorRoomIds = Object.fromEntries((data?.rooms || [])
    .filter((r) => r.is_floor && r.level !== null)
    .map((r) => [String(r.level), r.id]));
  const floorRoomKey = JSON.stringify(floorRoomIds);
  useEffect(() => {
    setGameState({ floorRoomIds: JSON.parse(floorRoomKey) as Record<string, string> });
  }, [floorRoomKey]);

  // What this avatar may NOT walk into (task C2, plan-betreten-und-tueren.md
  // § 3 decision 2). The same poll already carries both verdicts — the rooms
  // of the current place and the four neighbour locations — so the lock state
  // costs no extra request, and it stays OUT of the cached scene payloads: the
  // scene binds it by id when it draws and when the player presses a key.
  //
  // Published only on a real CHANGE, keyed by the serialised maps: `usePoll`
  // hands out a fresh object every five seconds, and pushing that through the
  // bus would re-render the whole HUD island for an unchanged answer.
  // The location travels WITH the room locks: a room id is unique only within
  // its location, so the receiver may only bind these locks to the rooms of
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
  /** Counts hails onto an already open chat; drives the flash below. */
  const [chatHail, setChatHail] = useState(0);
  const [chatFlash, setChatFlash] = useState(false);
  const [screenshotPhoto, setScreenshotPhoto] = useState<ScreenshotPhoto | null>(null);
  const screenshotHandled = useCallback((shot: ScreenshotPhoto) => {
    setScreenshotPhoto(pending => pending === shot ? null : pending);
  }, []);
  useEffect(() => {
    uiActions.openScreenshotPhoto = shot => {
      setScreenshotPhoto(shot);
      setChatShown(true);
      setChatHail(count => count + 1);
    };
    return () => { uiActions.openScreenshotPhoto = undefined; };
  }, []);
  useEffect(() => {
    uiActions.openChat = () => {
      if (chatOpen.current) setChatHail((n) => n + 1);
      else setChatShown(true);
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
      play: async (url) => { await gameActions.speak?.(url); },
      // SPEECH ONLY — music and the ambience bed keep playing.
      stop: () => gameActions.stopSpeech?.(),
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
    if (!chatOpen.current) setChatShown(true);
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
  // new line and every talk key, `chatShown` the panel coming up, and
  // talkTarget/elevatorOpen are standing offers that must not be answered by a
  // vanishing panel. A pinned panel is not this effect's business at all.
  useEffect(() => {
    if (!chatShown || chatPinned || screenshotPhoto) return;
    if (game.talkTarget || game.elevatorOpen) return;
    let timer = 0;
    function expire() {
      // Still in use? Typing in the composer, or one of its picker modals open
      // (they portal to document.body, and unmounting the panel would tear the
      // open picker down with it). Wait and look again.
      // The action drawer beside it counts as the chat: hovering it or a
      // focused chip in it means the panel is in use.
      if (chatRef.current?.contains(document.activeElement)
          || actionsRef.current?.contains(document.activeElement)
          || actionsRef.current?.matches(':hover')
          || document.querySelector('.ga-modal-backdrop')) {
        timer = window.setTimeout(expire, CHAT_BUSY_RECHECK_MS);
        return;
      }
      setChatShown(false);
    }
    timer = window.setTimeout(expire, CHAT_IDLE_MS);
    return () => window.clearTimeout(timer);
  }, [chatShown, chatPinned, chatHail, game.talkTarget, game.elevatorOpen, screenshotPhoto]);

  // --- Which row the picture column follows (2c, decision E4) --------------
  //
  // Two things decide it, and both are MEASURED on the transcript rather than
  // remembered: whether it still sticks to its end, and which row crosses the
  // vertical middle of the scroll window. The rule that turns the two into an
  // answer is `chatFocusId`, and it is pure — this block only reads the DOM.
  //
  // Reading it is all it does. `ScenePanel` owns the "stick to bottom"
  // behaviour and must keep owning it, so this LISTENS ALONG on the same
  // element with a second `addEventListener` instead of taking the handler
  // over; the rows are found by the id attribute the package writes on every
  // row for exactly this purpose (`SCENE_ROW_ID_ATTR`).
  const [chatScroll, setChatScroll] = useState<
    { stuck: boolean; centeredId: number | null }>({ stuck: true, centeredId: null });
  const measureChat = useCallback(() => {
    const el = chatRef.current?.querySelector<HTMLElement>('.player-scene-scroll');
    if (!el) return;
    const stuck = el.scrollHeight - el.scrollTop - el.clientHeight < SCENE_STICK_SLACK_PX;
    const box = el.getBoundingClientRect();
    const rows: RowExtent[] = [];
    el.querySelectorAll<HTMLElement>(`[${SCENE_ROW_ID_ATTR}]`).forEach((node) => {
      const raw = node.getAttribute(SCENE_ROW_ID_ATTR);
      if (raw === null || raw === '') return;
      const id = Number(raw);
      if (!Number.isFinite(id)) return;
      const r = node.getBoundingClientRect();
      rows.push({ id, top: r.top, bottom: r.bottom });
    });
    const centeredId = rowAtCenter(rows, box.top + box.height / 2);
    // Published only on a real change: a scroll fires dozens of times a second
    // and an unchanged answer must not re-render the whole HUD island.
    setChatScroll((prev) => (prev.stuck === stuck && prev.centeredId === centeredId
      ? prev : { stuck, centeredId }));
  }, []);
  useEffect(() => {
    if (!chatShown) return;
    const el = chatRef.current?.querySelector<HTMLElement>('.player-scene-scroll');
    if (!el) return;
    measureChat();
    el.addEventListener('scroll', measureChat, { passive: true });
    const ro = new ResizeObserver(measureChat);
    ro.observe(el);
    return () => {
      el.removeEventListener('scroll', measureChat);
      ro.disconnect();
    };
  }, [chatShown, measureChat]);
  // A new line moves every row, and so does a dragged size. Measuring again
  // here is safe AFTER the transcript has been redrawn and scrolled: a child's
  // effects run before its parent's, so ScenePanel's auto-scroll has already
  // happened by the time this does.
  useEffect(() => { measureChat(); }, [sceneStamp, chatSize, measureChat]);

  // --- The camera aims BESIDE the chat window ------------------------------
  //
  // The panel lies on the picture, bottom left, and may be dragged over most
  // of it. The scene answers by shifting its frustum so the avatar leaves the
  // covered corner (`scene/viewShift.ts`) — but only the HUD knows where the
  // panel actually is, so this measures it and hands the rectangle over.
  //
  // Two listeners, two different events. The observer catches every size the
  // panel takes, the drag included. The window listener is for the moves that
  // do NOT change its size: the panel hangs on the BOTTOM edge, so a shorter
  // window slides it upwards while leaving it exactly as big as it was.
  useEffect(() => {
    const el = chatRef.current;
    if (!chatShown || !el) {
      gameActions.setChatBox?.(null);
      return;
    }
    const report = () => {
      const r = el.getBoundingClientRect();
      gameActions.setChatBox?.({ x: r.left, y: r.top, w: r.width, h: r.height });
    };
    report();
    const ro = new ResizeObserver(report);
    ro.observe(el);
    window.addEventListener('resize', report);
    return () => {
      ro.disconnect();
      window.removeEventListener('resize', report);
      gameActions.setChatBox?.(null);
    };
  }, [chatShown]);

  // WHOSE faces the column shows. The pointer half comes from the panel:
  // `ScenePanel` forwards `onRowHover` to every row, so this only stores what
  // it is told — the rule decides, and it lets the pointer win over both the
  // middle row and the resting state.
  const [hoveredRowId, setHoveredRowId] = useState<number | null>(null);
  // A closing window never sends the leaving pointer (React fires no
  // `mouseleave` on unmount), so the last hovered row would outlive it and
  // still govern the column on the next opening.
  useEffect(() => { if (!chatShown) setHoveredRowId(null); }, [chatShown]);
  const chatFocus = chatFocusId({
    hoveredId: hoveredRowId,
    centeredId: chatScroll.centeredId,
    stuck: chatScroll.stuck,
  });
  const speakerVersions = data?.speaker_expr_versions || {};
  const portraitNames = pickPortraitSpeakers(
    data?.scene || [], speakerVersions, chatPortraits, chatFocus);

  const panelHead = (id: PanelId, icon: IconName, title: string) => (
    <header className="hud-panel-head">
      <Icon name={icon} size={14} />
      <span className="hud-panel-title">{title}</span>
      {id === 'chat' && (
        <span className="hud-panel-sub">
          {inRoom.length ? `· ${inRoom.join(', ')}` : `· ${t('You are alone here.')}`}
        </span>
      )}
      {/* How many faces stand next to the transcript (2e). A SWITCH and not a
          rule derived from the window width (user ruling): how much of the
          conversation one wants to see is a decision, and a width that quietly
          added a third portrait would be taking it away. */}
      {id === 'chat' && (
        <span className="hud-chat-count" role="group" aria-label={t('Portraits')}>
          {PORTRAIT_CHOICES.map((n) => (
            <button key={n} type="button" aria-pressed={n === chatPortraits}
              className={n === chatPortraits ? 'on' : ''}
              title={t('Portrait count: {n}').replace('{n}', String(n))}
              onClick={() => setChatPortraits(n)}>
              {n}
            </button>
          ))}
        </span>
      )}
      <button className="hud-panel-close" onClick={() => toggle(id)}
        title={t('Close')} aria-label={t('Close')}>
        <Icon name="close" size={14} />
      </button>
    </header>
  );

  // Two served storeys leave nothing to choose, so the chip names the one
  // direction F leads and the picker never unfolds (Stairs v2 task 4).
  const soleFloor = game.elevator ? elevatorSoleOption(game.elevator) : null;

  // WHICH offer the bottom row shows: the NEAREST one standing, decided by the
  // same function the F key asks (`game/offers.ts`, bug round 2026-08-30). All
  // four may stand at once and exactly one is drawn — the one the key answers,
  // so the player always sees what F does.
  const offer = nearestOffer(game);

  // A window too narrow for all of them shows the NEWEST that fit (240px
  // minimum + 10px gap each); the older ones stay open and come back when the
  // window grows — closing them would be a decision the window size made.
  // The Self strip (hud.css `.hud-self`, 250px + gap) takes the left edge.
  const selfShown = !spectating && !!avatarName;
  const dropsThatFit = Math.max(1, Math.floor((winW - 14 - (selfShown ? 262 : 0)) / 250));
  const shownDrops = drops.filter((id) => !spectating || SPECTATOR_PANELS.has(id))
    .slice(-dropsThatFit);

  /** The game menu, under its own button at the right end of the bar. */
  // Esc and M are handled HERE as well, not only in main.ts: the global
  // key path ignores anything typed into a form control, and a volume
  // slider is one — so after touching a slider the keys would be
  // swallowed. The panel holds no text field, so both keys are
  // unambiguous inside it. And ONLY for those: the global chain listens
  // in the CAPTURE phase and has therefore already answered every other
  // press by the time this runs — with the storey choice FIRST, which is
  // why closing the menu here as well made one Esc close two things
  // (E4-T4 minor). The guard is the same predicate main.ts uses, so
  // there is exactly one rule about what "typed into a control" means.
  const menuPanel = (
    <section className="hud-panel hud-menu-panel"
      onKeyDown={(e) => {
        if (e.key !== 'Escape' && e.key.toLowerCase() !== 'm') return;
        if (e.ctrlKey || e.metaKey || e.altKey) return;
        if (!isTypingTarget(e.nativeEvent)) return;
        e.stopPropagation();
        setMenuOpen(false);
      }}>
      {panelHead('menu', 'settings', t('Menu'))}
      <div className="hud-panel-body">
        <ErrorBoundary inline label="Menu">
          <GameMenu prefs={prefs} onChange={setPrefs}
            perfOn={perfOn} onPerfChange={setPerfOn}
            minimapOn={minimapOn} onMinimapChange={setMinimapOn}
            chatAlpha={chatAlpha} onChatAlphaChange={setChatAlpha}
            scatterPrefs={scatterPrefs} onScatterChange={setScatterPrefs}
            graphicsPrefs={graphicsPrefs} onGraphicsChange={setGraphicsPrefs}
            isAdmin={role === 'admin'} showAll={showAll} onShowAllChange={setShowAll}
            onBackToTitle={() => gameActions.backToTitle?.()} />
        </ErrorBoundary>
      </div>
    </section>
  );

  /** One dropdown's panel. The content panels (stage 6) are shared from
   *  @anima/player-ui — they poll themselves and take no scene data, so there
   *  is nothing to wire beyond the frame. */
  const dropPanel = (id: PanelId) => {
    const simple = (icon: IconName, title: string, label: string, body: React.ReactNode) => (
      <section className="hud-panel">
        {panelHead(id, icon, title)}
        <div className="hud-panel-body">
          <ErrorBoundary inline label={label}>{body}</ErrorBoundary>
        </div>
      </section>
    );
    switch (id) {
      case 'others': return simple('others', t('Others'), 'Others', <OthersPanel />);
      case 'belongings': return simple('backpack', t('Inventory'), 'Inventory', <BelongingsPanel />);
      case 'mind': return simple('brain', t('Mind'), 'Mind', <MindPanel character={avatarName} />);
      case 'gallery': return simple('gallery', t('Gallery'), 'Gallery',
        <GalleryPanel regenDialog={(ctl) => <PlayerRegenDialog ctl={ctl} />} />);
      case 'avatar': return simple('avatar', t('Avatar'), 'Avatar',
        <AvatarSettingsPanel avatar={avatarName} />);
      case 'instagram': return simple('instagram', t('Instagram'), 'Instagram',
        <InstagramPanel
          imageGenDialog={(ctl) => <PlayerRegenDialog ctl={ctl} />}
          animateDialog={(ctl) => <PlayerAnimateDialog ctl={ctl} />} />);
      case 'phone': return simple('phone', t('Phone'), 'Phone', <PhonePanel />);
      case 'news': return simple('news', t('News'), 'News', <NewsPanel />);
      case 'quests': return simple('scroll', t('Quests'), 'Quests', <QuestsPanel />);
      case 'tasks': return simple('tasks', t('Tasks'), 'Tasks', <TaskPanel />);
      default: return null;
    }
  };

  return (
    <CharacterFormHostContext.Provider value={characterFormHost}>
      <div className="hud-top">
        <div className="hud-title" title={worldName || 'Anima Verse'}>⚜ {worldName || 'Anima Verse'}</div>
        <span className="hud-sep" aria-hidden="true" />
        {/* The panel buttons, one row in the bar. Spectating keeps only the
            panels that need no avatar; `requires` hides a button whose skill
            package is gone. The collapsed scene tile portals its button in
            here as the last one (SceneTile). */}
        <nav ref={setTabsEl} className="hud-tabs" aria-label={t('Panels')}>
          {PANELS.filter((p) => (!spectating || SPECTATOR_PANELS.has(p.id))
            && (!p.requires || hasCapability(p.requires))).map((p) => (
            <button key={p.id} className={isOpen(p.id) ? 'on' : ''}
              onClick={() => toggle(p.id)} aria-pressed={isOpen(p.id)}
              title={t(p.title)} aria-label={t(p.title)}>
              <Icon name={p.icon} size={18} />
              {(p.id === 'phone' || p.id === 'instagram') && unread[p.id] > 0 && (
                <span className="hud-unread-badge">{unread[p.id]}</span>
              )}
            </button>
          ))}
        </nav>
        {/* The party, right behind the panel buttons: faces in a pill, the
            details in a dropdown under it (PartyBadge). Fed from THIS
            container's scene poll — no second request. */}
        {partyShown && (
          <PartyBadge party={data?.party} sent={data?.party_invites_sent}
            avatar={avatarName} versions={faceVersions}
            open={partyOpen} onOpenChange={setPartyOpen}
            onLeave={leaveParty} onTakeBack={takeBackPartyInvite} />
        )}
        <div className="hud-right">
          <span className={`hud-status ${game.connection === 'ok' ? 'ok' : 'err'}`}
            aria-label={t('Connection')} title={game.connection === 'ok' ? t('Connected') : t('Backend unreachable')} />
          <span className="hud-clock" title={t('Game time')}>{game.clock ? `🕰 ${game.clock}` : ''}</span>
          <span className="hud-user">{avatar ? `${username} · ${t('Avatar')}: ${avatar}` : username}</span>
          {spectating && <>
            <span title={t('Take control to chat, act or take photos.')}>{t('Spectating')}</span>
            <button className="player-chip" onClick={() => setMenuOpen(true)}>
              {t('Take control')}
            </button>
          </>}
          <button className="hud-logout" onClick={() => gameActions.backToTitle?.()}>{t('Log out')}</button>
          {/* The menu at the very right edge, beside "Log out" (user ruling). */}
          <button className={'hud-menu-toggle' + (menuOpen ? ' on' : '')} onClick={() => toggle('menu')}
            aria-pressed={menuOpen} title={t('Menu')} aria-label={t('Menu')}>
            <Icon name="settings" size={18} />
          </button>
        </div>
      </div>
      {/* The avatar's own values, always on screen: top-left under the world
          name, the dropdown row starts beside it (user ruling — it replaced
          the Self panel). No panel frame: it is part of the view, laid over
          the scene with a light translucent backing (hud.css `.hud-self`).
          "Take control" sits beside the name; only outside the embodied mode,
          where the mode chip is the way out. */}
      {!spectating && avatarName && (
        <section className="hud-self" aria-label={t('Self')}>
          <div className="hud-self-head">
            <span className="hud-self-name">{avatarName}</span>
            {game.mode !== 'embodied' && (
              <button className="player-chip" onClick={() => gameActions.takeControl?.()}>
                {t('Take control')}
              </button>
            )}
          </div>
          <ErrorBoundary inline label="Self"><SelfPanel layout="strip" /></ErrorBoundary>
        </section>
      )}
      {!spectating && <div className="hud-notices"><NoticeBanner onOpenGallery={() => showDrop('gallery')} /></div>}
      {game.info && <InfoPanel info={game.info} onPick={setTravelPick} />}
      {game.openView?.trim() && game.mode !== 'embodied' && <div className="open-view-badge">
        <span className="ovb-name">{game.openView}</span>
        <button className="ovb-close" title={t('Close view')} onClick={() => gameActions.closeOpenView?.()}>✕</button>
      </div>}
      {game.placeMenu && <PlaceMenu menu={game.placeMenu} />}
      {/* Performance readout (stage 5): shown while the menu switch is on,
          top-left and read-only — see PerfOverlay.tsx. */}
      {perfOn && <PerfOverlay />}

      {/* The top-right corner, ONE column so nothing in it has to guess the
          height of what stands above it: the minimap first, the avatar's open
          plans below it (user ruling; they fold, and vanish while empty).
          Minimap (stage 5, task 3): as far as one can see, north up. Only in
          the embodied mode — in the overview one IS looking at the map, and a
          second small copy of it would say nothing. The switch in the game
          menu is the other half of the condition. */}
      <div className="hud-corner">
        {game.mode === 'embodied' && minimapOn && <Minimap onPick={setTravelPick} />}
        {!spectating && <IntentsBox avatar={avatarName} />}
      </div>

      {/* Mode indicator (E3-T2): the ONLY sign of the embodied mode in the HUD
          chrome — one chip below the top bar that also leaves again.
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

      {!spectating && <SceneTile scene={data ?? null} collapsed={dropsOpen || !!game.info || narrow} tabsEl={tabsEl} />}

      {!spectating && chatShown && (
        <section ref={chatRef}
          className={`hud-panel hud-chat${chatFlash ? ' hud-flash' : ''}`}
          style={{
            // A DRAGGED size also lifts the stylesheet's default width cap
            // (which stops short of the bottom-centre plaque) down to the
            // window itself — whoever pulls the edge has decided, and sees the
            // overlap while doing it. Untouched, nothing is written here and
            // the stylesheet's cap stands.
            ...(chatSize
              ? {
                width: chatSize.w,
                height: chatSize.h,
                maxWidth: `calc(100vw - ${CHAT_VIEWPORT_MARGIN_W}px)`,
              }
              : null),
            '--hud-chat-alpha': String(chatAlpha),
          } as React.CSSProperties}>
          {/* The window's own surface (2d). The panel's opaque vellum is
              switched off for this one panel in hud.css and this layer stands
              in for it, with its ALPHA on a custom property — never `opacity`,
              which would fade the transcript text along with the background.
              It holds no text of its own, so nothing here can be dimmed. */}
          <div className="hud-chat-backdrop" aria-hidden="true" />
          {/* Three handles (2a): top edge, right edge, and the corner between
              them. Absolutely positioned OUT of the flex column, or each would
              eat a share of the height the head and the transcript divide
              between them — a flex child would eat a share of the height. */}
          <div className="hud-chat-grip hud-chat-grip-top" data-edge="top"
            role="separator" aria-orientation="horizontal"
            title={t('Drag to resize · double-click to reset')}
            aria-label={t('Drag to resize · double-click to reset')}
            onPointerDown={onChatGripDown} onPointerMove={onChatGripMove}
            onPointerUp={onChatGripUp} onPointerCancel={onChatGripUp}
            onDoubleClick={onChatGripReset} />
          <div className="hud-chat-grip hud-chat-grip-right" data-edge="right"
            role="separator" aria-orientation="vertical"
            title={t('Drag to resize · double-click to reset')}
            aria-label={t('Drag to resize · double-click to reset')}
            onPointerDown={onChatGripDown} onPointerMove={onChatGripMove}
            onPointerUp={onChatGripUp} onPointerCancel={onChatGripUp}
            onDoubleClick={onChatGripReset} />
          <div className="hud-chat-grip hud-chat-grip-corner" data-edge="corner"
            role="separator"
            title={t('Drag to resize · double-click to reset')}
            aria-label={t('Drag to resize · double-click to reset')}
            onPointerDown={onChatGripDown} onPointerMove={onChatGripMove}
            onPointerUp={onChatGripUp} onPointerCancel={onChatGripUp}
            onDoubleClick={onChatGripReset} />
          {panelHead('chat', 'chat', avatarName || '—')}
          <ErrorBoundary inline label="Chat">
            {/* photoDialog `key`: a second prepared payload is a NEW dialog,
                not the old one with new props — without the key the edited
                prompt and the chip selection of the previous 📷 press would
                survive into it. */}
            {/* `highlightedId` is the SAME answer the portrait column
                follows: the row the faces belong to is the row the
                transcript marks. Resting (`null`) marks nothing — the
                column then simply shows the last speakers. */}
            {/* Two columns (2b, decision E2), and only around the TRANSCRIPT:
                it keeps its width and every extra pixel of the window goes
                LEFT, to the pictures, while the composer below stays as wide
                as the window. The column is handed over ALWAYS, faces or not:
                it used to be left out when nobody had a portrait, and the
                transcript then widened to the whole window — the panel jumped
                the moment the narrator was all that had been said. What the
                column draws with nobody to show is `portraitSlots`' business,
                not this line's. */}
            <ScenePanel data={data} refreshScene={refreshScene} avatar={avatarName}
              hasCapability={hasCapability} moving={moving} onEnterRoom={handleEnterRoom}
              screenshotPhoto={screenshotPhoto} onScreenshotPhotoHandled={screenshotHandled}
              photoDialog={(ctl) => <PlayerPhotoDialog key={ctl.dialogId} {...ctl} />}
              highlightedId={chatFocus} onRowHover={setHoveredRowId}
              transcriptAside={
                <ChatPortraits names={portraitNames} versions={speakerVersions} />} />
          </ErrorBoundary>
        </section>
      )}

      {/* The action drawer, glued to the chat's right edge — or its left
          edge when the right side is too narrow (see the block around
          `chatBox`). Only with an avatar of one's own: a spectator
          starts nothing. */}
      {!spectating && chatShown && !!data?.avatar && chatBox && (() => {
        // Right of the chat, or left of it when the chat sits at the right
        // window edge and the right side cannot hold the drawer.
        const place = actionsDrawerSide(chatBox, chatBox.cw);
        const flipped = place.side === 'left';
        return (
          <div ref={actionsRef}
            className={`hud-chat-actions${actionsOpen ? ' open' : ''}${flipped ? ' flipped' : ''}`}
            style={{
              left: flipped ? undefined : chatBox.x + chatBox.w,
              right: flipped ? chatBox.cw - chatBox.x : undefined,
              top: chatBox.y,
              height: chatBox.h,
              '--hud-actions-room': `${place.room}px`,
            } as React.CSSProperties}>
            <button type="button" className="hud-chat-actions-handle"
              aria-expanded={actionsOpen}
              title={actionsOpen ? t('Hide actions') : t('Show actions')}
              aria-label={actionsOpen ? t('Hide actions') : t('Show actions')}
              onClick={toggleActions}>
              {actionsOpen !== flipped ? '◂' : '▸'}
            </button>
            {actionsOpen && (
              <section className="hud-panel hud-chat-actions-panel" aria-label={t('Actions')}>
                <header className="hud-panel-head">
                  <span className="hud-panel-title">{t('Actions')}</span>
                  <button className="hud-panel-close" onClick={toggleActions}
                    title={t('Close')} aria-label={t('Close')}>
                    <Icon name="close" size={14} />
                  </button>
                </header>
                <div className="hud-panel-body">
                  <ErrorBoundary inline label="Actions">
                    <ActionsTree avatar={data.avatar} present={data.present || []}
                      busy={data.present_busy} interaction={data.interaction} onChanged={refreshScene}
                      partyInvite={{ skill: data.capability_actions?.party_invite || '',
                        capabilities: data.capabilities, blocks: data.capability_blocks,
                        party: data.party, sent: data.party_invites_sent }} />
                  </ErrorBoundary>
                </div>
              </section>
            )}
          </div>
        );
      })()}

      {/* The dropdowns: one column each, hanging below the top bar, side by
          side in opening order. The row itself stays drag-through; only the
          panels and their width handles catch. */}
      {shownDrops.length > 0 && (
        <div className="hud-drops">
          {shownDrops.map((id) => (
            <div key={id}
              className={'hud-drop'
                + (WIDE_PANELS.has(id) ? ' hud-drop-wide' : '')
                + (CONTENT_PANELS.has(id) ? ' hud-drop-tall' : '')}
              style={dropWidths[id] != null ? { width: dropWidths[id] } : undefined}>
              {dropPanel(id)}
              {/* The width handle on the panel's RIGHT edge, out of the flex
                  flow. Pointer events (not mouse) with capture, so the drag
                  survives the cursor leaving the strip, which at speed it
                  always does. */}
              <div className="hud-drop-grip" data-panel={id}
                role="separator" aria-orientation="vertical"
                title={t('Drag to resize · double-click to reset')}
                aria-label={t('Drag to resize · double-click to reset')}
                onPointerDown={onGripDown} onPointerMove={onGripMove}
                onPointerUp={onGripUp} onPointerCancel={onGripUp}
                onDoubleClick={onGripReset} />
            </div>
          ))}
        </div>
      )}

      {menuOpen && (
        <div className="hud-drop hud-menu-drop">{menuPanel}</div>
      )}

      {/* Bottom centre, ONE stack (E3-T5): the talk prompt sits directly above
          the plaque instead of floating over it. Both belong to the figure in
          the scene, not to a panel, so they share the viewport centre — and
          stacking them means a plaque that grows a row can never push the
          prompt out of place. The prompt is read, not operated, so it stays
          pointer-transparent (see the pointer rule in hud.css). */}
      <div className="hud-bottom">
        {/* Travel shares the bottom stack above offers so growing status text
            cannot overlap them; chat and minimap keep their corner positions. */}
        <TravelBar pick={travelPick} clear={() => setTravelPick(null)} travel={data?.travel}
          locked={game.movementLocked} leader={game.partyLeader} />
        {boot.note?.kind === 'characters' && (
          <div className="hud-talk" role="status">{t('Loading characters…')}</div>
        )}
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
            says which way F leads and the press is the ride (Stairs v2
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
        {/* Entering an adjacent location (stage 3): same prompt shape. The
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
    </CharacterFormHostContext.Provider>
  );
}
