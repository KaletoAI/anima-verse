/**
 * WHERE in the window the camera's aim point lands — pure numbers, no `three`,
 * no DOM, so `scripts/smoke_view_shift.mjs` can check it without a GL context.
 *
 * The camera aims at a point and `lookAt` puts that point in the exact middle
 * of the picture. The HUD's chat window sits ON that picture, bottom left, and
 * the user may drag it up and to the right until it covers most of the screen
 * (`hud/chatPanel.ts`: up to 2400 x 2000). The avatar then stands behind glass
 * in the corner of what is left, and everything around it — the reason for
 * looking at all — is under the transcript.
 *
 * The fix is a FRUSTUM SHIFT, not a camera turn: the engine renders an
 * off-centre cut-out of the same picture (`camera.setViewOffset`), so the
 * viewing direction, the horizon and the avatar's own facing stay exactly as
 * they were and only the aim point moves out of the covered corner. Clicks,
 * name plates, bubbles and culling all go through the same projection matrix
 * and follow along on their own.
 *
 * ---------------------------------------------------------------------------
 * THE RULE
 * ---------------------------------------------------------------------------
 * A panel that hangs in a corner leaves FOUR maximal free strips, each running
 * the full length of the other axis — left of it, right of it, above it, below
 * it. The aim point goes to the average of their centres, each weighted by its
 * area:
 *
 *     centre = Σ areaᵢ · centreᵢ / Σ areaᵢ
 *
 * That is a continuous function of the panel rectangle, and continuity is the
 * whole point: the size is DRAGGED, so a rule that picked "the biggest strip"
 * would jump the world sideways in the middle of the drag. Instead the shift
 * grows with the panel and degrades the way one expects — a wide flat window
 * (the right strip goes to zero) pushes the view up, a narrow tall one pushes
 * it right, a small one barely moves it.
 *
 * The cap is a safety net for the extreme sizes, nothing else: at the default
 * 840 x 680 on a 1920 x 1080 window the rule asks for 248 px right and 127 px
 * up and the cap never comes near it.
 */

/** A rectangle on the screen, in CSS pixels, measured from the top left of the
 *  canvas — the shape `getBoundingClientRect()` hands out. */
export interface ScreenBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** How far the aim point may leave the middle, as a fraction of the HALF axis:
 *  0.35 keeps it inside the middle 70 % of the picture in both directions. A
 *  panel that covers nearly everything would otherwise push the avatar onto
 *  the very edge of the frame, where the picture reads as broken rather than
 *  as framed — 1600 x 900 on a 1920 x 1080 window asks for 370 px of 960, and
 *  this is what answers 336. */
export const MAX_SHIFT_FRACTION = 0.35;

/** The shift, in CSS pixels: `dx` to the right, `dy` DOWN (screen axes, so a
 *  negative `dy` lifts the aim point towards the top of the window). */
export interface ViewShift {
  dx: number;
  dy: number;
}

/** No panel, no shift. */
export const NO_SHIFT: ViewShift = { dx: 0, dy: 0 };

function clamp(v: number, lo: number, hi: number): number {
  return v < lo ? lo : v > hi ? hi : v;
}

/**
 * Where the aim point belongs when `panel` covers part of a `w` x `h` canvas.
 *
 * The panel is clipped to the canvas first — the HUD measures a real DOM box,
 * and one that hangs over an edge (an animation mid-flight, a window being
 * resized) must not make a strip come out negative. A panel that covers
 * everything leaves nothing to weight, and the answer is then the middle: an
 * arbitrary corner would be worse than the honest "there is nothing to see".
 */
export function viewShiftFor(w: number, h: number,
                             panel: ScreenBox | null): ViewShift {
  if (!(w > 0) || !(h > 0) || !panel) return NO_SHIFT;
  const px = clamp(panel.x, 0, w);
  const py = clamp(panel.y, 0, h);
  const pr = clamp(panel.x + panel.w, 0, w);
  const pb = clamp(panel.y + panel.h, 0, h);
  if (!(pr > px) || !(pb > py)) return NO_SHIFT;

  // The four strips: [area, centre x, centre y].
  const strips: Array<[number, number, number]> = [
    [px * h, px / 2, h / 2],                    // left of the panel
    [(w - pr) * h, (pr + w) / 2, h / 2],        // right of it
    [w * py, w / 2, py / 2],                    // above it
    [w * (h - pb), w / 2, (pb + h) / 2],        // below it
  ];
  let area = 0;
  let cx = 0;
  let cy = 0;
  for (const [a, x, y] of strips) {
    if (a <= 0) continue;
    area += a;
    cx += a * x;
    cy += a * y;
  }
  if (area <= 0) return NO_SHIFT;
  cx /= area;
  cy /= area;

  const maxX = MAX_SHIFT_FRACTION * w / 2;
  const maxY = MAX_SHIFT_FRACTION * h / 2;
  return {
    dx: clamp(cx - w / 2, -maxX, maxX),
    dy: clamp(cy - h / 2, -maxY, maxY),
  };
}
