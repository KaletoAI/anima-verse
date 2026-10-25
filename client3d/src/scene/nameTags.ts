/**
 * The labels over the world map — the rules behind a character's name tag and
 * a location's name, without the DOM. Pure, so the browser (npcs.ts, places.ts,
 * sceneRecipe.ts) and the native client share the cases in
 * shared/test-vectors/overview_labels.json (derivations:
 * client3d/scripts/smoke_overview_labels.mjs).
 */

/** Name tags show only while the camera is closer to its target than this (metres). */
export const TAG_MAX_CAM_DIST = 55;
/** A model figure's tag hangs this far above the top of its head (metres). */
export const TAG_ABOVE_HEAD_M = 0.45;
/** A portrait sprite (no model) carries its tag this far BELOW its root (metres). */
export const TAG_PORTRAIT_Y = -0.15;
/** A location's name floats this far above the top of its place (metres). */
export const LOCATION_LABEL_LIFT_M = 2.2;

/**
 * Whether a figure's name tag shows: the figure is not hidden (storey filter,
 * a closed room), it is not the camera's own first-person body, and the camera
 * is closer than `TAG_MAX_CAM_DIST` — strictly, at 55 m the tags are gone.
 */
export function tagVisible(camDist: number, hidden: boolean, ownFirstPerson: boolean): boolean {
  return !hidden && !ownFirstPerson && camDist < TAG_MAX_CAM_DIST;
}

/** The part of a map character's `travel` block (§ A11) the tag reads. */
export interface TagTravel {
  starts_in_s?: number | null;
  eta_hhmm?: string | null;
}

/**
 * Under way: a travel block exists and its start does not lie ahead. A journey
 * whose `starts_in_s` is still counting is NOT under way — the figure is
 * getting out of its pose and stays where it is.
 */
export function tagTravelling(travel: TagTravel | null | undefined): boolean {
  return !!travel && !travel.starts_in_s;
}

/**
 * The tag's name line: "🚶 HH:MM " before the name while the character is
 * under way (`tagTravelling`), the arrival clock the server rendered
 * (`travel.eta_hhmm`) only when it has one ("🚶 " alone otherwise).
 */
export function tagName(name: string, travel: TagTravel | null | undefined): string {
  if (!tagTravelling(travel)) return name;
  const eta = travel?.eta_hhmm ? ` ${travel.eta_hhmm}` : '';
  return `🚶${eta} ${name}`;
}

/**
 * Height of the tag's anchor above the figure's root: `TAG_ABOVE_HEAD_M` over a
 * model figure of `figureHeight` metres, `TAG_PORTRAIT_Y` for a portrait
 * sprite (`figureHeight` null — no model).
 */
export function tagAnchorY(figureHeight: number | null): number {
  return figureHeight === null ? TAG_PORTRAIT_Y : figureHeight + TAG_ABOVE_HEAD_M;
}

/** Height of a location's name above its place's ground datum: the place's own height plus the lift. */
export function locationLabelLift(placeHeight: number): number {
  return placeHeight + LOCATION_LABEL_LIFT_M;
}
