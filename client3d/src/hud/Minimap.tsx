/**
 * The minimap of the embodied mode (Etappe 5, task 3).
 *
 * ONE canvas, top right, north up: a WINDOW around the avatar as wide as one
 * can see (`MINIMAP_VIEW_RADIUS_M` — the scene's own fog end), with the figure
 * in the middle. Without a figure it falls back to the whole world frame. The
 * painted terrain is filled polygons, the world's RELIEF is a shading layer
 * over them, the known places are dots on top of that, and everything else
 * stays the dark backdrop.
 *
 * Nothing is clipped by hand: what lies outside the window misses the canvas
 * and is thereby not drawn — places included, which is why none of them is
 * pinned to the rim.
 *
 * PRESENTATIONAL, and cheap by construction. It owns no state and asks the
 * scene nothing: `main.ts` publishes a finished slice on the minimap store of
 * `bus.ts` (its own listener set, like the performance readout — these updates
 * must not re-render the chat and the rail), and it publishes only when the
 * picture actually changes. So one notification means one redraw, and standing
 * still costs neither.
 *
 * All the arithmetic is in `game/minimap.ts` and hand-checked in
 * `client3d/scripts/smoke_walk_math.mjs`; the shading is `hillshadeImage` of
 * `@anima/scene-render` (hand-checked in `smoke_hillshade.mjs`, computed in
 * `main.ts` once per field). Nothing here computes a coordinate or a grey of
 * its own — this file only says where the finished picture lands.
 */
import { useEffect, useRef, useSyncExternalStore } from 'react';
import { useI18n } from '@anima/player-ui';
import { minimapView, worldToPx, yawToCompassDeg, MINIMAP_SIZE_PX } from '../game/minimap';
import type { MinimapRelief } from '../game/minimap';
import { getMinimap, subscribeMinimap } from './bus';

/** Canvas backdrop — whatever nothing is painted over stays this. Dark and
 *  slightly transparent, so the map reads as part of the HUD rather than as a
 *  second window. It is NOT a veil (contract v6 Nr. 8 struck those): the
 *  painted terrain covers the whole world, so what shows through here is the
 *  margin outside it. */
const BACKDROP_FILL = 'rgba(10, 12, 16, 0.72)';
/** The avatar dot and its view wedge. The same warm yellow the selection ring
 *  in `scene/tiles.ts` uses (0xf2cd6e) — one accent for "this is you". */
const AVATAR_FILL = '#f2cd6e';
/** Half opening angle of the view wedge, in degrees. Roughly the camera's own
 *  horizontal field of view, so the wedge covers what is on screen. */
const WEDGE_HALF_DEG = 26;
/** A known place, drawn over the painted ground. Pale stone, so it reads
 *  against both a meadow and a lake without being the accent colour — that
 *  one belongs to the avatar alone. */
const LOCATION_FILL = 'rgba(232, 226, 214, 0.9)';
const LOCATION_R = 2.5;
/** Compass rose in the top-right corner of the canvas. */
const ROSE_R = 14;

/** Canvas angle of a compass bearing. Canvas angles start at +x and grow
 *  clockwise (y points down), and a bearing of 0 is straight UP — so the two
 *  differ by a quarter turn. */
const canvasAngle = (bearingDeg: number) => (bearingDeg - 90) * Math.PI / 180;

/** One shading image as a bitmap the canvas can stretch — the ONE place in
 *  this app that turns the shared RGBA answer into pixels. Kept as a `cols ×
 *  rows` off-screen canvas so `drawImage` does the scaling, smoothed, on every
 *  redraw; `null` when the browser gives no 2D context. */
function reliefBitmap(relief: MinimapRelief): HTMLCanvasElement | null {
  const { image } = relief;
  const src = document.createElement('canvas');
  src.width = image.cols;
  src.height = image.rows;
  const sctx = src.getContext('2d');
  if (!sctx) return null;
  // `createImageData` + `set`, not `new ImageData(data, …)`: the shared answer
  // is a plain `Uint8ClampedArray` over an unspecified buffer kind, and the
  // constructor's typing insists on a plain `ArrayBuffer` one. The copy is a
  // few hundred kilobytes ONCE per field — `putImageData` copies anyway.
  const bits = sctx.createImageData(image.cols, image.rows);
  bits.data.set(image.data);
  sctx.putImageData(bits, 0, 0);
  return src;
}

export function Minimap() {
  const { t } = useI18n();
  const state = useSyncExternalStore(subscribeMinimap, getMinimap);
  const ref = useRef<HTMLCanvasElement | null>(null);
  /** The shading, rasterised once per FIELD and kept across redraws: the slice
   *  is republished on every step, the relief only when the world's heights
   *  change. Keyed on the published object, which `main.ts` replaces exactly
   *  then. */
  const relief = useRef<{ src: MinimapRelief | null; bitmap: HTMLCanvasElement | null }>(
    { src: null, bitmap: null });
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
    ctx.fillStyle = BACKDROP_FILL;
    ctx.fillRect(0, 0, size, size);

    // The framing is decided ONCE, here, and everything below strokes through
    // `worldToPx` with it: the window around the avatar while one stands in the
    // world, the whole frame while no figure is on the map.
    const layout = minimapView(state.avatar, state.bounds, size);
    if (layout.scale > 0) {
      // The painted ground first, in the order it was published — that order
      // IS the layering (`z_order`, then paint order), so a path drawn over a
      // meadow covers it here exactly as it does in the world.
      for (const area of state.areas) {
        if (area.polygon.length < 3) continue;
        ctx.beginPath();
        area.polygon.forEach(([x, z], i) => {
          const { px, py } = worldToPx({ x, z }, layout);
          if (i === 0) ctx.moveTo(px, py);
          else ctx.lineTo(px, py);
        });
        ctx.closePath();
        ctx.fillStyle = area.color;
        ctx.fill();
      }
      // THE RELIEF over the painted ground and under everything else: hills as
      // light and shadow (`hillshadeImage`, the routine the 2D player map
      // shades with — nothing here computes a grey of its own). Over the areas
      // because it modulates the ground; under the places and the avatar
      // because those are not ground and keep their colours exactly.
      //
      // WHERE IT LANDS, and why it needs no flip: pixel (i, j) IS the support
      // point (origin_x + i·step, origin_z + j·step), row 0 the smallest z =
      // the northernmost line. The destination rectangle is half a step larger
      // on every side, so the smoothed `drawImage` puts pixel centre
      // (j + 0.5)/rows of the rectangle back on the support point itself — and
      // `worldToPx` grows py with z, so row 0 lands at the SMALLEST py. North
      // is up, exactly as it is for every dot on this canvas.
      //
      // The window framing changes NOTHING about that: it is another offset and
      // another scale in the same `worldToPx`, so the half-step rectangle keeps
      // landing on the support points — it simply reaches past the canvas edges
      // now, and the shading one can see is the shading of the ground one is
      // standing on.
      if (state.relief) {
        if (relief.current.src !== state.relief) {
          relief.current = { src: state.relief, bitmap: reliefBitmap(state.relief) };
        }
        const { bitmap } = relief.current;
        const { image, origin_x: ox, origin_z: oz, step_m: step } = state.relief;
        if (bitmap) {
          const nw = worldToPx({ x: ox - step / 2, z: oz - step / 2 }, layout);
          ctx.imageSmoothingEnabled = true;
          ctx.drawImage(bitmap, nw.px, nw.py,
            image.cols * step * layout.scale, image.rows * step * layout.scale);
        }
      }
      // The known places on top of the ground: a dot each, big enough to find
      // on a 160-pixel canvas and small enough not to be a floor plan.
      ctx.fillStyle = LOCATION_FILL;
      for (const loc of state.locations) {
        const { px, py } = worldToPx(loc, layout);
        ctx.beginPath();
        ctx.arc(px, py, LOCATION_R, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    if (state.avatar && layout.scale > 0) {
      const { px, py } = worldToPx(state.avatar, layout);
      const bearing = yawToCompassDeg(state.yaw);
      const mid = canvasAngle(bearing);
      const half = WEDGE_HALF_DEG * Math.PI / 180;
      // The wedge is a reading aid, not a measurement: a couple of metres of
      // reach, with a floor for the framings where a metre is a fraction of a
      // pixel (the sight window at 160 px is one such).
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
