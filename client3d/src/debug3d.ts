/**
 * debug3d — numeric on-screen probe for remote diagnosis (§ B5a: findings
 * travel as NUMBERS). Activated ONLY via URL params, renders a DOM overlay a
 * browser-automation session can read with plain HTML extraction — the
 * automation tools cannot execute JS, so everything must be visible in the
 * DOM. No effect whatsoever without the param; safe to keep in the tree.
 *
 *   ?debug3d=1            overlay on (updates 2×/s)
 *   &goto=<loc name/id>   fly the camera to that tile after boot
 *   &dist=<m>             camera distance for goto (default 15)
 *   &sweep=1              oscillate the distance 30 ↔ 8 every 5 s — the
 *                         "trees vanish while zooming" reproduction loop
 */
import * as THREE from 'three';
import type { Engine } from './scene/engine';
import type { Tile } from './scene/tiles';

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
