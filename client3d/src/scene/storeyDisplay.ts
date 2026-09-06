/**
 * WHAT A PIECE OF A DECLARED STOREY IS DRAWN AT — one rule, one place.
 *
 * THE DEFECT THIS CLOSES (user finding 2026-09-06, "sometimes the floor is
 * see-through"). The scene payload ghosts every storey above the lowest one:
 * `_opacity_role` (`app/core/scene_recipe.py`) marks it `upper`, and the
 * renderer then builds that piece `transparent` at `style.upper_floor_opacity`
 * (0.4) / `upper_wall_opacity` (0.45). That is the FAR view's look — seen from
 * above, an opaque top storey would hide everything under it.
 *
 * Inside, since the acceptance round of 2026-07-31, exactly ONE storey is
 * drawn and the others are gone by `visible`, so nothing is left for the ghost
 * to open up. `applyLevelDisplay` therefore takes the ghosting back off — but
 * it only ever did so for the storey's CONTOUR plate (`levelSlabs`) and its
 * WALLS (`levelWallMats`). A room's own floor plate was registered nowhere and
 * kept its 0.4: measured on "Wohnung von Kira" (`app/core/scene_recipe._plates`
 * with that location's real layout), storey 3 composes
 *
 *     (storey slab)  top_y 9.380  thickness 0.14  role upper
 *     Kueche         top_y 9.400  thickness 0.02  role upper
 *
 * so the kitchen floor was drawn at 40 % over the slab 2 cm below it. In a
 * room whose plate has NO slab under it — an `always_visible` zone stays
 * visible while the switch shows another storey, and its storey plate does
 * not — the same 40 % looks straight down onto the terrain.
 *
 * THE RULE, and it is the one `applyLevelDisplay` already applies to walls:
 * the storey that is DISPLAYED is drawn solid, every other one keeps the
 * ghost the payload composed it with. Both directions matter — the storey
 * switch moves back and forth, and a piece raised to 1 on its own storey has
 * to fall back to the ghost when the view leaves it, or an always-visible
 * zone would stay opaque over a storey it does not belong to.
 *
 * Pure arithmetic and no import at all, so `client3d/scripts/smoke_storey_display.mjs`
 * can transpile this file on its own and derive the cases by hand (§ B5a).
 */

/** What a piece of the storey the view SHOWS is drawn at. Solid: the storey is
 *  alone in the picture, so there is nothing behind it to open up. */
export const STOREY_SHOWN_OPACITY = 1

/**
 * The opacity one storey piece is drawn at.
 *
 * @param pieceLevel  the storey the piece belongs to (`plate.level`)
 * @param shownLevel  the storey the view displays (`tile.levelFilter`)
 * @param ghost       the opacity the payload composed the piece with — for an
 *                    `opacity_role: 'upper'` piece the style's ghost value, for
 *                    a `ground` piece 1, in which case this answers 1 either way
 */
export function storeyPieceOpacity(pieceLevel: number, shownLevel: number,
                                   ghost: number): number {
  return pieceLevel === shownLevel ? STOREY_SHOWN_OPACITY : ghost
}
