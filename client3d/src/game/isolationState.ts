/**
 * THE STATE OF THE ISOLATION PANEL — the numbered suspect list, and the codec
 * that carries a chosen set through localStorage and the URL hash.
 *
 * Pure, exactly like `game/perfstats.ts` and `game/prefs.ts`: no DOM, no
 * `three`, no module state. The panel itself (the switchboard that really
 * removes things from the frame) is `debug3d.ts`; everything here is the part
 * that can be hand-checked, and `client3d/scripts/smoke_isolation_state.mjs`
 * does exactly that.
 *
 * WHY A NUMBER AND NOT A NAME. A finding travels as a sentence a person types
 * into a chat window — "3 and 6 off and the shimmer is gone". Numbers survive
 * that trip; camelCase keys do not. So the id IS the label, the list is
 * ordered, and the wire format is nothing but those numbers.
 *
 * THE WIRE FORMAT is `#iso=3,6,11` — ascending, deduplicated, comma-separated.
 * The same string is what goes into localStorage, so a state can be pasted
 * from one browser into another and reads the same. It is deliberately not
 * JSON: a URL a person retypes by hand must not contain a brace.
 */

/** Lowest and highest id the panel knows. Anything outside is dropped on
 *  decode rather than clamped — a `23` in a shared link is a typo or a link
 *  from another client, and honouring it as `22` would isolate the wrong
 *  suspect without saying so.
 *
 *  20 WAS "Terrain culling off" for one day (2026-08-22). It did its job: with
 *  it on the ground stopped vanishing, which is what identified the terrain's
 *  per-piece frustum cull as the cause. The cull is deleted, so that switch
 *  had nothing left to switch — and the id was retired rather than kept as a
 *  no-op, because a suspect list whose entries do nothing is worse than a
 *  shorter one. It is REUSED here for the exploration veil (2026-08-24): the
 *  numbers are a suspect list, not a register of everything this client has
 *  ever had, and the retired switch left no state a link could still carry. */
export const ISO_MIN_ID = 1;
export const ISO_MAX_ID = 22;

/** Where a chosen set is kept between reloads. */
export const ISO_STORAGE_KEY = 'av3d.debug.isolation.v1';

/** The key inside `location.hash` (`#iso=…`). */
export const ISO_HASH_KEY = 'iso';

/**
 * What switching one toggle costs the renderer.
 *
 * - `none` — uniform writes and visibility flags only; the frame after the
 *   click is drawn by the very same program.
 * - `recompile` — the change moves a three PROGRAM PARAMETER (the fog define,
 *   the shadow defines), so every affected material is rebuilt and the picture
 *   hitches for a moment. Expected, not a defect.
 * - `upload` — a texture is re-uploaded with different filtering. Also a
 *   hitch, but a transfer rather than a compile.
 */
export type IsolationCost = 'none' | 'recompile' | 'upload';

export interface IsolationToggle {
  /** the number the user reports */
  id: number;
  /** English, short enough to read at a glance in the panel */
  label: string;
  /** what it really does under the hood — shown as the row's tooltip */
  note: string;
  cost: IsolationCost;
}

/**
 * THE SUSPECTS, in the order the panel lists them.
 *
 * Ordered so the discriminators come first: 1 answers "is the shimmer a HOLE
 * or is it SHADING?" on its own, and everything after it narrows down whichever
 * of the two it was.
 */
export const ISOLATION_TOGGLES: readonly IsolationToggle[] = [
  { id: 1, label: 'Sky = MAGENTA',
    note: 'scene.background, fog colour, hemisphere sky colour and the water '
      + 'mirror sky all forced to 0xff00ff. THE discriminator: a shimmer that '
      + 'turns magenta is holes/transparency letting the sky through; one that '
      + 'stays light blue is lighting or shading.',
    cost: 'none' },
  { id: 2, label: 'Shadows off',
    note: 'renderer.shadowMap.enabled = false plus needsUpdate on every '
      + 'material in the scene.',
    cost: 'recompile' },
  { id: 3, label: 'Fog off',
    note: 'scene.fog = null plus needsUpdate on every material — the fog is a '
      + 'program define, so the programs are rebuilt.',
    cost: 'recompile' },
  { id: 4, label: 'Hemisphere + fill light off',
    note: 'engine.hemi.intensity = 0 and engine.fill.intensity = 0, re-asserted '
      + 'per frame because setGameHour rewrites both on every world-clock poll.',
    cost: 'none' },
  { id: 5, label: 'Sun off',
    note: 'engine.sun.intensity = 0, re-asserted per frame for the same reason.',
    cost: 'none' },
  { id: 6, label: 'Terrain normal FLAT',
    note: 'uTlodFlatNormal = 1 — tlodNormalAt() returns (0,1,0) instead of the '
      + 'central difference of the height field, so every ground fragment is '
      + 'shaded as if the world were level.',
    cost: 'none' },
  { id: 7, label: 'Layer compositor off',
    note: 'The mask windows are switched off (near size 0, far size 0x0) and '
      + 'the surface array is swapped for one neutral grey texel, so the ground '
      + 'is painted in one flat colour. The HEIGHTS are untouched.',
    cost: 'none' },
  { id: 8, label: 'Natural-ground patch off',
    note: 'uNgStrength = 0 — the height AO, the tint and the anti-tiling chain '
      + 'of scene/naturalGround.ts read nothing at all.',
    cost: 'none' },
  { id: 9, label: 'Geomorph off',
    note: 'uTlodNoMorph = 1 — the per-vertex morph factor t is forced to 0, so '
      + 'every vertex sits on its own node lattice. Expect LOD cracks; that is '
      + 'the point of the test.',
    cost: 'none' },
  { id: 10, label: 'LOD frozen',
    note: 'The quadtree selection stops re-running in the terrain mesh’s '
      + 'onBeforeRender, AND the eye the per-vertex morph is measured from is '
      + 'pinned to that frame (uTlodFreeze). So the ground keeps exactly the '
      + 'geometry of the frame the toggle was flipped on, seen from a moving '
      + 'viewpoint — not a frozen list re-morphed against a live camera, which '
      + 'would open cracks of its own.',
    cost: 'none' },
  { id: 11, label: 'Waterfalls hidden',
    note: 'visible = false on every waterfall curtain and foam disc. The water '
      + 'SURFACE is the terrain itself (Wasser v2 K-A) — toggle 22 drops that.',
    cost: 'none' },
  { id: 12, label: 'Undergrowth hidden',
    note: 'visible = false on the terrain-undergrowth group.',
    cost: 'none' },
  { id: 13, label: 'Scatter + impostors hidden',
    note: 'visible = false on every scatter InstancedMesh (low and full tier) '
      + 'and on every impostor billboard layer. Re-asserted per frame, because '
      + 'the 1 Hz LOD tick writes those flags itself.',
    cost: 'none' },
  { id: 14, label: 'Backdrop hidden',
    note: 'visible = false on the backdrop group (the mountain ring).',
    cost: 'none' },
  { id: 15, label: 'Figures / NPCs hidden',
    note: 'visible = false on the NpcManager group — every character, the '
      + 'avatar included.',
    cost: 'none' },
  { id: 16, label: 'Location tiles / scenes hidden',
    note: 'visible = false on every tile group: buildings, area shells, '
      + 'interiors, door marks and everything mounted from a scene recipe.',
    cost: 'none' },
  { id: 17, label: 'Terrain hidden',
    note: 'visible = false on the CDLOD terrain mesh. If the picture still '
      + 'shimmers with this on, the ground is innocent.',
    cost: 'none' },
  { id: 18, label: 'Terrain texture filtering off',
    note: 'The surface array texture drops to LINEAR without mipmaps and '
      + 'anisotropy 1 — the texture-filtering shimmer test.',
    cost: 'upload' },
  { id: 19, label: 'Wireframe terrain',
    note: 'material.wireframe on the terrain material — the crack/hole test.',
    cost: 'none' },
  { id: 20, label: 'Fog off',
    note: 'uFogAlpha = 0 — the exploration veil reads no cells texture and '
      + 'mixes nothing into the ground colour. Switching it back on restores '
      + 'whatever the camera height says NOW, not what it said when the toggle '
      + 'was flipped.',
    cost: 'none' },
  // 13 SWITCHES OFF BOTH HALVES OF THE SCATTER AND THIS ONE ONLY THE FAR ONE,
  // which is what makes the pair a measurement instead of a verdict (perf
  // finding 2026-08-24: the scatter alone is ~11 ms of a 29 ms frame on an
  // Intel iGPU, and nothing said which half spends it). The two halves are
  // made cheaper in opposite ways — the near meshes by drawing fewer or
  // coarser trees, the far billboards by drawing fewer or smaller quads — so
  // 13 minus 21 is the mesh half and 21 alone is the billboard half.
  { id: 21, label: 'Impostor billboards hidden',
    note: 'visible = false on the FAR half of the scatter only — the baked '
      + 'billboards beyond the cull distance. The prop meshes inside it keep '
      + 'drawing. Re-asserted per frame, because the 1 Hz LOD tick writes '
      + 'those flags itself.',
    cost: 'none' },
  { id: 22, label: 'Water off (lift and shading)',
    note: 'uTlodNoWater = 1 — the terrain\'s WATER variant stops lifting its '
      + 'vertices to max(h, w_level) and draws the bed the height field '
      + 'really holds (Wasser v2, K-A E3). Since E4 that ALSO takes the water '
      + 'shading with it, through the same uniform and not a second one: the '
      + 'lift is what the fragment measures its depth from, so no lift means '
      + 'depth 0 means the plain ground look. It is a uniform and not a '
      + 'define, so the same program keeps drawing and the same pieces keep '
      + 'going through it: what the toggle removes is the water alone, never '
      + 'the second draw call. Since H3 it also hides the figures\' underwater '
      + 'ghost (the second, GreaterDepth draw that gives a wading figure a '
      + 'body below the waterline) — with no water surface there is nothing '
      + 'for that draw to be behind.',
    cost: 'none' },
];

/** Lookup by id, `undefined` for an id the panel does not know. */
export function isolationToggle(id: number): IsolationToggle | undefined {
  return ISOLATION_TOGGLES.find((t) => t.id === id);
}

/** True for an id this client has a switch for. */
export function isIsolationId(id: number): boolean {
  return Number.isInteger(id) && id >= ISO_MIN_ID && id <= ISO_MAX_ID;
}

/**
 * A chosen set as the wire string — ascending, deduplicated, comma-separated.
 * The empty set is the empty string (and NOT `"0"`, so an empty state can be
 * removed from the hash instead of written into it).
 */
export function encodeIsolation(ids: Iterable<number>): string {
  const seen = new Set<number>();
  for (const id of ids) if (isIsolationId(id)) seen.add(id);
  return [...seen].sort((a, b) => a - b).join(',');
}

/**
 * The wire string back to a sorted, deduplicated id list.
 *
 * STRICTLY DIGITS PER TOKEN, after trimming: `"3"` and `"03"` are 3, while
 * `"3.5"`, `"+3"`, `"-3"`, `"3px"` and `""` are dropped. `Number()` would take
 * every one of those and turn a mistyped link into a state nobody chose —
 * a decoder that guesses is worse than one that drops.
 *
 * Never throws and never returns `null`: a corrupt localStorage entry is an
 * empty set, which is the client as it ships.
 */
export function decodeIsolation(text: string | null | undefined): number[] {
  if (typeof text !== 'string' || !text) return [];
  const seen = new Set<number>();
  for (const raw of text.split(',')) {
    const token = raw.trim();
    if (!/^\d+$/.test(token)) continue;
    const id = Number(token);
    if (isIsolationId(id)) seen.add(id);
  }
  return [...seen].sort((a, b) => a - b);
}

/**
 * The `iso=` value out of a `location.hash`, or `null` when the hash does not
 * carry one.
 *
 * `null` and `''` are DIFFERENT answers and both are used: `null` means "the
 * link says nothing about the isolation, so keep what localStorage holds",
 * while `''` (`#iso=`) means "the link says: nothing isolated" and clears it.
 * The key is matched WHOLE, so `#isotope=1` is not an isolation state.
 */
export function readIsoHash(hash: string | null | undefined): string | null {
  if (typeof hash !== 'string' || !hash) return null;
  const body = hash.startsWith('#') ? hash.slice(1) : hash;
  for (const part of body.split('&')) {
    const eq = part.indexOf('=');
    const key = eq < 0 ? part : part.slice(0, eq);
    if (key !== ISO_HASH_KEY) continue;
    return eq < 0 ? '' : part.slice(eq + 1);
  }
  return null;
}

/**
 * A hash with the `iso=` key set to `value` — replaced in place where it
 * already stands (so a shared link keeps the order of its other keys), appended
 * otherwise, and REMOVED when `value` is empty.
 *
 * Returns `''` rather than `'#'` for a hash that ends up empty: a bare `#` in
 * the address bar is a jump to the top of the document and reads as a link
 * that does something.
 */
export function writeIsoHash(hash: string | null | undefined,
                             value: string): string {
  const body = (typeof hash === 'string' && hash.startsWith('#'))
    ? hash.slice(1) : (hash || '');
  const parts = body ? body.split('&').filter((p) => p !== '') : [];
  const out: string[] = [];
  let written = false;
  for (const part of parts) {
    const eq = part.indexOf('=');
    const key = eq < 0 ? part : part.slice(0, eq);
    if (key !== ISO_HASH_KEY) { out.push(part); continue; }
    if (!value || written) continue;      // dropped, or a duplicate key
    out.push(`${ISO_HASH_KEY}=${value}`);
    written = true;
  }
  if (value && !written) out.push(`${ISO_HASH_KEY}=${value}`);
  return out.length ? `#${out.join('&')}` : '';
}
