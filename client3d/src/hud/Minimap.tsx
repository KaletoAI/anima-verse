/**
 * The minimap of the embodied mode (Etappe 5, task 3).
 *
 * ONE canvas, top right, showing the WHOLE world frame at once — north up, no
 * scrolling and no zoom. That is the point of it in a stage about the fog of
 * war: a map that panned along with the avatar would say where one is looking
 * but never how much of the world is still dark. Known cells are terrain
 * squares, everything else stays the dark backdrop, and the backdrop is the
 * fog.
 *
 * PRESENTATIONAL, and cheap by construction. It owns no state and asks the
 * scene nothing: `main.ts` publishes a finished slice on the minimap store of
 * `bus.ts` (its own listener set, like the performance readout — these updates
 * must not re-render the chat and the rail), and it publishes only when the
 * picture actually changes. So one notification means one redraw, and standing
 * still costs neither.
 *
 * All the arithmetic is in `game/minimap.ts` and hand-checked in
 * `scripts/smoke_walk_math.mjs`; nothing here computes a coordinate of its own.
 */
import { useEffect, useRef, useSyncExternalStore } from 'react';
import { useI18n } from '@anima/player-ui';
import {
  cellToPx, minimapLayout, terrainColor, yawToCompassDeg, MINIMAP_SIZE_PX,
} from '../game/minimap';
import { getMinimap, subscribeMinimap } from './bus';

/** Canvas backdrop — everything the avatar does not know about stays this.
 *  Dark and slightly transparent, so the map reads as a veil over the world
 *  rather than as a second window. */
const FOG_FILL = 'rgba(10, 12, 16, 0.72)';
/** The avatar dot and its view wedge. The same warm yellow the selection ring
 *  in `scene/tiles.ts` uses (0xf2cd6e) — one accent for "this is you". */
const AVATAR_FILL = '#f2cd6e';
/** Half opening angle of the view wedge, in degrees. Roughly the camera's own
 *  horizontal field of view, so the wedge covers what is on screen. */
const WEDGE_HALF_DEG = 26;
/** Compass rose in the top-right corner of the canvas. */
const ROSE_R = 14;

/** Canvas angle of a compass bearing. Canvas angles start at +x and grow
 *  clockwise (y points down), and a bearing of 0 is straight UP — so the two
 *  differ by a quarter turn. */
const canvasAngle = (bearingDeg: number) => (bearingDeg - 90) * Math.PI / 180;

export function Minimap() {
  const { t } = useI18n();
  const state = useSyncExternalStore(subscribeMinimap, getMinimap);
  const ref = useRef<HTMLCanvasElement | null>(null);
  /** the north letter, read once per render — the draw runs outside React */
  const north = t('N');

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx) return;
    const size = MINIMAP_SIZE_PX;
    // Capped at 2: a 3x display would quadruple the pixels for a 160px picture
    // of flat squares, and nothing in it has the detail to show for it.
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    if (canvas.width !== size * dpr) {
      canvas.width = size * dpr;
      canvas.height = size * dpr;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, size, size);
    ctx.fillStyle = FOG_FILL;
    ctx.fillRect(0, 0, size, size);

    const layout = minimapLayout(state.bounds, size);
    if (layout.scale > 0) {
      // At least one pixel per cell, and cells are drawn edge to edge: a world
      // of a hundred cells across gives 1.6 px each, and a gap between them
      // would leave more fog on the map than there is in the world.
      const s = Math.max(layout.scale, 1);
      for (const cell of state.cells) {
        const { px, py } = cellToPx(cell, layout);
        ctx.fillStyle = terrainColor(cell.terrain);
        ctx.fillRect(px - s / 2, py - s / 2, s, s);
      }
    }

    if (state.avatar && layout.scale > 0) {
      const { px, py } = cellToPx(state.avatar, layout);
      const bearing = yawToCompassDeg(state.yaw);
      const mid = canvasAngle(bearing);
      const half = WEDGE_HALF_DEG * Math.PI / 180;
      // The wedge reaches a bit beyond the cell the avatar stands on, with a
      // floor for the wide maps where a cell is only a pixel or two.
      const reach = Math.max(layout.scale * 1.8, 14);
      ctx.beginPath();
      ctx.moveTo(px, py);
      ctx.arc(px, py, reach, mid - half, mid + half);
      ctx.closePath();
      ctx.fillStyle = 'rgba(242, 205, 110, 0.28)';
      ctx.fill();
      ctx.beginPath();
      ctx.arc(px, py, 3, 0, Math.PI * 2);
      ctx.fillStyle = AVATAR_FILL;
      ctx.fill();
      ctx.lineWidth = 1;
      ctx.strokeStyle = 'rgba(0, 0, 0, 0.65)';
      ctx.stroke();
    }

    // --- The compass ---------------------------------------------------------
    // The map itself is north-up and cannot turn, so the rose is what says
    // WHERE ONE LOOKS: a fixed N at the top of the ring and a needle on the
    // camera's bearing. Drawn last, so it is never covered by a cell.
    const cx = size - ROSE_R - 4;
    const cy = ROSE_R + 4;
    ctx.beginPath();
    ctx.arc(cx, cy, ROSE_R, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(10, 12, 16, 0.8)';
    ctx.fill();
    ctx.lineWidth = 1;
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.35)';
    ctx.stroke();
    ctx.fillStyle = 'rgba(255, 255, 255, 0.8)';
    ctx.font = 'bold 8px system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillText(north, cx, cy - ROSE_R + 1);
    const needle = canvasAngle(yawToCompassDeg(state.yaw));
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + Math.cos(needle) * (ROSE_R - 4),
      cy + Math.sin(needle) * (ROSE_R - 4));
    ctx.lineWidth = 2;
    ctx.strokeStyle = AVATAR_FILL;
    ctx.stroke();
  }, [state, north]);

  return (
    <div className="hud-minimap">
      <canvas ref={ref} role="img" aria-label={t('Minimap')}
        style={{ width: MINIMAP_SIZE_PX, height: MINIMAP_SIZE_PX }} />
    </div>
  );
}
