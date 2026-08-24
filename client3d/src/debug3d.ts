/**
 * THE CLIENT'S DEBUG FACILITY — one file, two instruments, and they are meant
 * to be used together.
 *
 * [A] `initDebug3d` — a numeric on-screen probe for remote diagnosis (§ B5a:
 * findings travel as NUMBERS). Activated ONLY via URL params, renders a DOM
 * overlay a browser-automation session can read with plain HTML extraction —
 * the automation tools cannot execute JS, so everything must be visible in the
 * DOM. No effect whatsoever without the param; safe to keep in the tree.
 *
 *   ?debug3d=1            overlay on (updates 2×/s)
 *   &goto=<loc name/id>   fly the camera to that tile after boot
 *   &dist=<m>             camera distance for goto (default 15)
 *   &sweep=1              oscillate the distance 30 ↔ 8 every 5 s — the
 *                         "trees vanish while zooming" reproduction loop
 *
 * [B] `initIsolation` — the ISOLATION panel, opened with **Shift + I**. Where
 * [A] READS the picture, this one takes it apart: twenty numbered switches,
 * each of which really removes one suspect from the frame, live and
 * reversibly, so a defect nobody can reproduce by staring can be bisected in
 * half a minute. Always available (no URL param) because the case it exists
 * for — "it shimmers only while I turn the camera" — cannot be reproduced by
 * anyone who was not already looking at it.
 *
 * The panel's own state, its numbering and its `#iso=…` codec are the pure
 * module `game/isolationState.ts`, hand-checked by
 * `client3d/scripts/smoke_isolation_state.mjs`. What is HERE is the wiring: the
 * DOM, and the switch each number really throws.
 */
import * as THREE from 'three';
import { setSurfaceSky } from '@anima/scene-render';
import { isTypingTarget, type Engine } from './scene/engine';
import type { Ground } from './scene/ground';
import type { Tile } from './scene/tiles';
import { setLayerCompositorFlat, setLayerSurfaceFiltering } from './scene/layerGround';
import { setFogVeilDebugOff, setFogVeilSky } from './scene/fogVeil';
import { setNaturalGroundDebugOff } from './scene/naturalGround';
import { setTerrainLodDebug } from './scene/terrainLod';
import { newFpsMeter, pushFrame } from './game/perfstats';
import { yawToCompassDeg } from './game/minimap';
import {
  decodeIsolation, encodeIsolation, ISO_STORAGE_KEY, ISOLATION_TOGGLES,
  readIsoHash, writeIsoHash,
} from './game/isolationState';

interface MeshRow {
  n: string;      // name chain (self←parent←…, truncated)
  y: number;      // world y of the mesh origin
  v: number;      // 1 = visible incl. the whole parent chain
  o: number;      // material opacity
  t: number;      // material transparent flag
  m: string;      // map: '-' none, 'ld' loaded, 'pend' not decoded yet
  tri: number;    // triangle count
}

const params = new URLSearchParams(location.search);

export function initDebug3d(engine: Engine, tiles: Map<string, Tile>): void {
  if (params.get('debug3d') !== '1') return;
  const el = document.createElement('pre');
  el.id = 'debug3d';
  el.style.cssText = 'position:fixed;left:4px;top:4px;z-index:9999;'
    + 'background:rgba(0,0,0,0.75);color:#9f9;font:10px monospace;'
    + 'padding:4px;max-width:46vw;max-height:92vh;overflow:auto;'
    + 'pointer-events:none;white-space:pre-wrap;';
  document.body.appendChild(el);
  const errors: string[] = [];
  window.addEventListener('error', (e) => {
    errors.push(String(e.message).slice(0, 160));
  });
  window.addEventListener('unhandledrejection', (e) => {
    errors.push('rej: ' + String(e.reason).slice(0, 160));
  });

  // Raycast probe: `window.__pick3d(nx, ny)` (normalized 0..1 screen coords)
  // answers "WHAT renders this pixel" — object chain, height, material colour
  // and texture. The one question a screenshot cannot answer numerically.
  (window as unknown as { __pick3d?: unknown }).__pick3d =
    (nx: number, ny: number) => {
      const ray = new THREE.Raycaster();
      ray.setFromCamera(new THREE.Vector2(nx * 2 - 1, -(ny * 2 - 1)),
                        engine.camera);
      return ray.intersectObjects(engine.scene.children, true)
        .slice(0, 5).map((hit) => {
          const mesh = hit.object as THREE.Mesh;
          const mat = (Array.isArray(mesh.material) ? mesh.material[0]
            : mesh.material) as THREE.MeshStandardMaterial | undefined;
          const chain: string[] = [];
          for (let p: THREE.Object3D | null = mesh; p && chain.length < 5;
               p = p.parent) chain.push(p.name || p.type);
          return {
            chain: chain.join('<'),
            y: Math.round(hit.point.y * 1000) / 1000,
            color: mat?.color ? '#' + mat.color.getHexString() : '-',
            map: String(((mat?.map as THREE.Texture | null)?.image as
              { src?: string } | undefined)?.src || '')
              .split('/').slice(-1)[0].slice(0, 30),
            opacity: mat?.opacity,
            tri: Math.round(((mesh.geometry as THREE.BufferGeometry)
              ?.attributes?.position?.count || 0) / 3),
          };
        });
    };

  const wp = new THREE.Vector3();
  const rowsOf = (root: THREE.Object3D | null | undefined,
                  tag: string): MeshRow[] => {
    const out: MeshRow[] = [];
    root?.traverse((o) => {
      const mesh = o as THREE.Mesh;
      if (!mesh.isMesh || out.length >= 60) return;
      const mat = (Array.isArray(mesh.material) ? mesh.material[0]
        : mesh.material) as THREE.MeshStandardMaterial | undefined;
      let chainVisible = 1;
      for (let p: THREE.Object3D | null = mesh; p; p = p.parent) {
        if (!p.visible) { chainVisible = 0; break; }
      }
      const g = mesh.geometry as THREE.BufferGeometry | undefined;
      const n = g ? (g.index ? g.index.count : g.attributes.position?.count || 0) : 0;
      mesh.getWorldPosition(wp);
      const img = (mat?.map as THREE.Texture | null)?.image as
        { complete?: boolean; width?: number; src?: string } | undefined;
      const src = (img?.src || '').split('/').slice(-1)[0].slice(0, 28);
      out.push({
        n: tag + ':' + [mesh.name || mesh.type, mesh.parent?.name || '']
          .filter(Boolean).join('<').slice(0, 42),
        y: Math.round(wp.y * 1000) / 1000,
        v: chainVisible,
        o: Math.round(((mat?.opacity ?? 1)) * 100) / 100,
        t: mat?.transparent ? 1 : 0,
        m: mat?.map ? ((img && (img.complete === undefined || img.complete
          || (img.width || 0) > 0)) ? ('ld:' + src) : 'pend') : '-',
        tri: Math.round(n / 3),
      });
    });
    return out;
  };

  let flew = false;
  let sweepHigh = false;
  let lastSweep = 0;
  const targetName = (params.get('goto') || '').toLowerCase();

  const findTile = (): Tile | null => {
    if (targetName) {
      for (const t of tiles.values()) {
        const loc = (t as unknown as { loc?: { id?: string; name?: string } }).loc;
        if ((loc?.name || '').toLowerCase().includes(targetName)
            || (loc?.id || '').toLowerCase() === targetName) return t;
      }
      return null;
    }
    let best: Tile | null = null;
    let bd = Infinity;
    for (const t of tiles.values()) {
      const d = Math.hypot(engine.target.x - t.center.x,
                           engine.target.z - t.center.z);
      if (d < bd) { bd = d; best = t; }
    }
    return best;
  };

  setInterval(() => {
    const tile = findTile();
    if (!tile) { el.textContent = 'debug3d: tile not found (yet)'; return; }
    if (targetName && !flew) {
      engine.flyTo(new THREE.Vector3(tile.center.x, 0, tile.center.z),
                   parseFloat(params.get('dist') || '15') || 15);
      flew = true;
    }
    if (params.get('sweep') === '1' && Date.now() - lastSweep > 5000) {
      lastSweep = Date.now();
      sweepHigh = !sweepHigh;
      engine.flyTo(new THREE.Vector3(tile.center.x, 0, tile.center.z),
                   sweepHigh ? 30 : 8);
    }
    const t = tile as unknown as Record<string, unknown>;
    // The `ground` readout (y / visible / opacity / transparent / map of the
    // tile's own plate) died with the plate itself ("Ein Boden" E3): a tile
    // owns no ground any more, the terrain under it does.
    const head = {
      loc: (t.loc as { name?: string })?.name,
      dist: Math.round(engine.dist * 10) / 10,
      fade: Math.round((tile.fade || 0) * 100) / 100,
      fadeTarget: tile.fadeTarget,
      shellArea: !!t.modelIsShellArea,
      terrain: !!t.terrain,
      levelFilter: t.levelFilter,
    };
    const rows = [
      ...rowsOf(tile.group, 'G'),
      ...rowsOf((t.interior as THREE.Object3D) || null, 'I'),
    ];
    el.textContent = 'DEBUG3D ' + JSON.stringify(head) + '\nERR '
      + JSON.stringify(errors.slice(-4)) + '\n'
      + rows.map((r) => JSON.stringify(r)).join('\n');
  }, 500);
}

// ═══════════════════════════════════════════════════════════════════════════
// [B] THE ISOLATION PANEL
// ═══════════════════════════════════════════════════════════════════════════

/** What the panel needs a handle on. Everything else it reaches through the
 *  module-level switches of the scene packages. */
export interface IsolationDeps {
  engine: Engine;
  ground: Ground;
  /** the mountain ring (`scene/backdrop.ts` group) */
  backdrop: THREE.Object3D;
  /** every character in the world (`NpcManager.group`) */
  figures: THREE.Object3D;
  /** the location tiles, read live — tiles are built and torn down as the
   *  player travels, so this is the map itself and never a snapshot of it */
  tiles: Map<string, Tile>;
}

/** The colour toggle 1 paints the sky in. Pure magenta is chosen for the one
 *  property that matters here: nothing in this world is ever near it, so a
 *  pixel that turns magenta HAS to be sky showing through. */
const ISO_MAGENTA = 0xff00ff;

/** How often the readout is refreshed while the panel is open, in ms. Four
 *  times a second: fast enough to read a yaw while turning, slow enough that
 *  the readout is not itself a load. */
const ISO_READOUT_MS = 250;

/** Mark every material under `root` for a rebuild. Needed by the two toggles
 *  that move a three PROGRAM PARAMETER (fog, shadows) — a uniform change would
 *  not need it, and the hitch this causes is the price of those two. */
function bumpMaterials(root: THREE.Object3D): void {
  root.traverse((o) => {
    const mat = (o as THREE.Mesh).material as
      THREE.Material | THREE.Material[] | undefined;
    if (!mat) return;
    if (Array.isArray(mat)) for (const m of mat) m.needsUpdate = true;
    else mat.needsUpdate = true;
  });
}

/**
 * Build the ISOLATION panel and bind its hotkey.
 *
 * HOW THE STATE IS HELD, and why it is held in two halves:
 *  - the TRANSITION half (`apply`) runs once per click. Everything that costs
 *    something — a program rebuild, a texture upload, restoring the sky from
 *    the world clock — belongs here and nowhere else.
 *  - the PER-FRAME half (`enforce`) runs in a frame hook, i.e. immediately
 *    before the render. Everything the GAME rewrites by itself belongs here:
 *    `setGameHour` repaints sky and light intensities on every world-clock
 *    poll, and the 1 Hz LOD tick writes the `visible` flag of every scatter
 *    mesh. A one-shot write would be undone within the second, and the toggle
 *    would look broken.
 *
 * VISIBILITY IS FORCED THROUGH A LEDGER (`forced`), so every hide is
 * reversible: the first frame that hides an object records what it was, and
 * releasing puts exactly that back. For the layers whose owner writes the flag
 * anyway (scatter, undergrowth) the restored value may be one tick stale — the
 * next LOD beat corrects it, which is why the ledger is not asked to be
 * cleverer than that.
 */
export function initIsolation(deps: IsolationDeps): void {
  const { engine, ground } = deps;
  const active = new Set<number>();
  const boxes = new Map<number, HTMLInputElement>();
  /** Objects this panel has hidden, mapped to the `visible` they had. */
  const forced = new Map<THREE.Object3D, boolean>();
  /** The scene fog while toggle 3 holds it out of the scene. */
  let savedFog: THREE.Scene['fog'] = null;
  /** What `renderer.shadowMap.enabled` was last set to by this panel — so the
   *  material sweep runs on a real change and not on every click. */
  let shadowsOff = false;
  const fpsMeter = newFpsMeter();
  let fpsNow = 0;

  let panel: HTMLDivElement | null = null;
  let readout: HTMLPreElement | null = null;
  let timer: ReturnType<typeof setInterval> | null = null;

  const on = (id: number): boolean => active.has(id);

  // ── persistence ─────────────────────────────────────────────────────────
  //
  // The hash WINS over the store: a link somebody pasted is an explicit
  // statement about the state, the store is only what this browser did last.

  function persist(): void {
    const text = encodeIsolation(active);
    try {
      localStorage.setItem(ISO_STORAGE_KEY, text);
    } catch {
      // A private window, a full quota, storage switched off — the panel works
      // without it, it just does not survive a reload.
    }
    try {
      const hash = writeIsoHash(location.hash, text);
      history.replaceState(null, '', location.pathname + location.search + hash);
    } catch {
      // Some embeddings refuse replaceState; the panel is not worth an error.
    }
  }

  function loadState(): number[] {
    const fromHash = readIsoHash(location.hash);
    if (fromHash !== null) return decodeIsolation(fromHash);
    try {
      return decodeIsolation(localStorage.getItem(ISO_STORAGE_KEY));
    } catch {
      return [];
    }
  }

  function setState(ids: Iterable<number>): void {
    active.clear();
    for (const id of decodeIsolation(encodeIsolation(ids))) active.add(id);
    for (const [id, box] of boxes) box.checked = active.has(id);
    apply();
  }

  // ── the visibility ledger ───────────────────────────────────────────────

  function force(obj: THREE.Object3D | null | undefined): void {
    if (!obj) return;
    if (!forced.has(obj)) forced.set(obj, obj.visible);
    obj.visible = false;
  }

  function releaseForced(): void {
    for (const [obj, was] of forced) obj.visible = was;
    forced.clear();
  }

  // ── the transition half ─────────────────────────────────────────────────

  function apply(): void {
    // Shadows (2) and fog (3) are the two that cost a program rebuild, so both
    // act only on a real change.
    if (on(2) !== shadowsOff) {
      shadowsOff = on(2);
      engine.renderer.shadowMap.enabled = !shadowsOff;
      bumpMaterials(engine.scene);
    }
    if (on(3) && engine.scene.fog) {
      savedFog = engine.scene.fog;
      engine.scene.fog = null;
      bumpMaterials(engine.scene);
    } else if (!on(3) && savedFog) {
      engine.scene.fog = savedFog;
      savedFog = null;
      bumpMaterials(engine.scene);
    }
    setTerrainLodDebug({ flatNormal: on(6), noMorph: on(9) });
    setLayerCompositorFlat(on(7));
    setNaturalGroundDebugOff(on(8));
    setFogVeilDebugOff(on(20));
    ground.setTerrainFrozen(on(10));
    setLayerSurfaceFiltering(on(18));
    if (!on(19)) {
      const mat = ground.terrainMaterial() as THREE.MeshStandardMaterial | null;
      if (mat) mat.wireframe = false;
    }
    // Everything the world clock owns — sky colour, fog colour, the three light
    // intensities, the water mirror's sky — is restored by asking the clock
    // again rather than by remembering values here. `engine.gameHour` inverts
    // the very angle `setGameHour` set, so this is an exact no-op when nothing
    // is isolated, and `enforce` paints the magenta/zero state back on top of
    // it before the next frame is drawn (no flicker: the frame hook runs first).
    engine.setGameHour(engine.gameHour);
    releaseForced();
  }

  // ── the per-frame half ──────────────────────────────────────────────────

  function enforce(dt: number): void {
    if (panel && panel.style.display !== 'none') fpsNow = pushFrame(fpsMeter, dt);
    if (!active.size) return;
    if (on(1)) {
      const bg = engine.scene.background;
      if (bg instanceof THREE.Color) bg.setHex(ISO_MAGENTA);
      if (engine.scene.fog) engine.scene.fog.color.setHex(ISO_MAGENTA);
      engine.hemi.color.setHex(ISO_MAGENTA);
      // …and the water: its mirror is a Fresnel blend towards the sky colour,
      // so a lake that stays blue under a magenta sky is a finding of its own.
      setSurfaceSky(ISO_MAGENTA);
      // …and the exploration veil, which takes the sky colour for the same
      // reason the water does: haze that stayed blue under a magenta sky would
      // read as ground rather than as air.
      setFogVeilSky(ISO_MAGENTA);
    }
    if (on(4)) {
      engine.hemi.intensity = 0;
      engine.fill.intensity = 0;
    }
    if (on(5)) engine.sun.intensity = 0;
    if (on(19)) {
      const mat = ground.terrainMaterial() as THREE.MeshStandardMaterial | null;
      if (mat) mat.wireframe = true;
    }
    if (on(11) || on(12) || on(13) || on(17)) {
      const parts = ground.debugParts();
      if (on(11)) for (const o of parts.water) force(o);
      if (on(12)) for (const o of parts.undergrowth) force(o);
      if (on(13)) for (const o of parts.scatter) force(o);
      if (on(17)) for (const o of parts.terrain) force(o);
    }
    if (on(14)) force(deps.backdrop);
    if (on(15)) force(deps.figures);
    if (on(16)) for (const tile of deps.tiles.values()) force(tile.group);
  }

  // ── the readout ─────────────────────────────────────────────────────────

  const sunDir = new THREE.Vector3();
  function refreshReadout(): void {
    if (!readout) return;
    sunDir.copy(engine.sun.position).sub(engine.sun.target.position);
    // Compass bearings, both of them: 0 = north, rising clockwise, north being
    // −z (`game/minimap.yawToCompassDeg`, whose derivation this shares).
    const sunAz = ((Math.atan2(sunDir.x, -sunDir.z) * 180 / Math.PI) % 360 + 360) % 360;
    const sunEl = Math.atan2(sunDir.y, Math.hypot(sunDir.x, sunDir.z)) * 180 / Math.PI;
    const hour = engine.gameHour;
    const hh = Math.floor(((hour % 24) + 24) % 24);
    const mm = Math.floor((((hour % 1) + 1) % 1) * 60);
    const r1 = (v: number) => (Math.round(v * 10) / 10).toFixed(1);
    readout.textContent =
      `yaw ${r1(yawToCompassDeg(engine.yaw))}°   dist ${r1(engine.dist)} m\n`
      + `game ${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}   `
      + `sun az ${r1(sunAz)}°  el ${r1(sunEl)}°\n`
      // `nodes` is the whole selection — nothing is culled since 2026-08-22, so
      // this is what the one draw call really submits. `cap/capacity` are both
      // MAX_NODES and must stay equal: a cap below the capacity would mean
      // three froze its own number at the first bind and the tail of every
      // larger selection is silently missing.
      + `nodes ${ground.terrainNodeCount()}   cap ${ground.terrainInstanceCap().cap}`
      + `/${ground.terrainInstanceCap().capacity}   ground tri `
      + `${Math.round(ground.terrainTriangleCount() / 1000)}k   `
      + `height tiles ${ground.heightTileCount()}\n`
      + `fps ${r1(fpsNow)}   off: ${encodeIsolation(active) || '-'}`;
  }

  // ── the DOM ─────────────────────────────────────────────────────────────

  function build(): HTMLDivElement {
    const el = document.createElement('div');
    el.id = 'isolation-panel';
    el.style.cssText = 'position:fixed;right:8px;top:8px;z-index:10000;'
      + 'width:330px;max-height:94vh;overflow:auto;box-sizing:border-box;'
      + 'background:rgba(12,14,18,0.92);color:#dfe6ee;border:1px solid #3a4450;'
      + 'border-radius:6px;padding:8px;font:11px/1.45 ui-monospace,monospace;';

    const head = document.createElement('div');
    head.style.cssText = 'display:flex;align-items:center;gap:6px;'
      + 'margin-bottom:6px;font-weight:700;letter-spacing:0.04em;';
    const title = document.createElement('span');
    title.textContent = 'ISOLATION';
    title.style.flex = '1';
    const clear = document.createElement('button');
    clear.textContent = 'reset';
    clear.title = 'Clear every switch — the picture as the client ships it';
    const close = document.createElement('button');
    close.textContent = '×';
    close.title = 'Close (Shift+I)';
    for (const b of [clear, close]) {
      b.style.cssText = 'background:#26303c;color:#dfe6ee;border:1px solid #47535f;'
        + 'border-radius:4px;padding:1px 7px;font:11px ui-monospace,monospace;'
        + 'cursor:pointer;';
    }
    clear.addEventListener('click', () => { setState([]); persist(); });
    close.addEventListener('click', () => setOpen(false));
    head.append(title, clear, close);

    readout = document.createElement('pre');
    readout.style.cssText = 'margin:0 0 8px;padding:5px 6px;background:#151b22;'
      + 'border:1px solid #2b343d;border-radius:4px;color:#9fe0a8;'
      + 'white-space:pre;font:11px/1.45 ui-monospace,monospace;';

    const list = document.createElement('div');
    for (const t of ISOLATION_TOGGLES) {
      const row = document.createElement('label');
      row.style.cssText = 'display:flex;align-items:flex-start;gap:6px;'
        + 'padding:2px 3px;border-radius:3px;cursor:pointer;';
      row.addEventListener('pointerenter', () => { row.style.background = '#1d242c'; });
      row.addEventListener('pointerleave', () => { row.style.background = ''; });
      row.title = `${t.id}. ${t.label}\n\n${t.note}`
        + (t.cost === 'recompile'
          ? '\n\n[!] rebuilds every material — expect a hitch on both edges.'
          : t.cost === 'upload'
            ? '\n\n[!] re-uploads the surface array — expect a hitch on both edges.'
            : '');
      const box = document.createElement('input');
      box.type = 'checkbox';
      // The panel is built LAZILY, on the first open — which for a state
      // restored from a link or from the store is AFTER that state was already
      // applied. So the box takes its tick from the state, never the other way
      // round, or a restored isolation would show as an untouched panel.
      box.checked = active.has(t.id);
      box.style.cssText = 'margin:2px 0 0;flex:none;';
      box.addEventListener('change', () => {
        if (box.checked) active.add(t.id);
        else active.delete(t.id);
        apply();
        persist();
        refreshReadout();
      });
      boxes.set(t.id, box);
      const num = document.createElement('span');
      num.textContent = String(t.id).padStart(2, ' ');
      num.style.cssText = 'flex:none;color:#7f8c9b;white-space:pre;';
      const text = document.createElement('span');
      text.textContent = t.label + (t.cost === 'none' ? '' : ' *');
      text.style.flex = '1';
      row.append(box, num, text);
      list.appendChild(row);
    }

    const foot = document.createElement('div');
    foot.style.cssText = 'margin-top:7px;padding-top:6px;border-top:1px solid #2b343d;'
      + 'color:#7f8c9b;';
    foot.textContent = 'Shift+I closes · hover a row for what it really does · '
      + '* = rebuild/upload, one hitch per flip · the state rides in the URL '
      + '(#iso=…) and in localStorage.';

    el.append(head, readout, list, foot);
    document.body.appendChild(el);
    return el;
  }

  function setOpen(next: boolean): void {
    if (next && !panel) panel = build();
    if (!panel) return;
    panel.style.display = next ? 'block' : 'none';
    if (next) {
      refreshReadout();
      if (timer === null) timer = setInterval(refreshReadout, ISO_READOUT_MS);
    } else if (timer !== null) {
      clearInterval(timer);
      timer = null;
    }
  }

  // ── wiring ──────────────────────────────────────────────────────────────

  engine.addFrameHook(enforce);

  // THE HOTKEY: Shift + I. Ctrl/Meta/Alt are excluded so the browser's own
  // Ctrl+Shift+I (developer tools) is not also an isolation panel, and typing
  // is excluded by the same rule the camera keeps (`isTypingTarget`) — a
  // capital I in the chat window is a letter, not a debug switch.
  window.addEventListener('keydown', (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey || !e.shiftKey) return;
    if (e.key.toLowerCase() !== 'i' || isTypingTarget(e)) return;
    e.preventDefault();
    setOpen(!panel || panel.style.display === 'none');
  });

  // A link pasted into the running client takes effect at once — that is what
  // makes "share this state" true rather than "share this state and reload".
  window.addEventListener('hashchange', () => {
    const fromHash = readIsoHash(location.hash);
    if (fromHash === null) return;
    setState(decodeIsolation(fromHash));
    // Written straight back into the store as well, so a link somebody pasted
    // survives the reload that usually follows it. `writeIsoHash` is
    // idempotent, so the address bar does not move.
    persist();
    refreshReadout();
  });

  const initial = loadState();
  if (initial.length) {
    // A state restored from the store or from a link is a state the picture is
    // ALREADY in, and a panel that is not open cannot say so. So it opens.
    setState(initial);
    setOpen(true);
  }
  console.info('[isolation] Shift+I opens the isolation panel (20 switches, '
    + 'state in #iso=… and localStorage)');
}
