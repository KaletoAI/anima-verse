/**
 * WHICH STANDING OFFER THE F KEY ANSWERS (bug round 2026-08-30).
 *
 * Four rules can offer the avatar something at the same moment — talking to
 * whoever is in range (`proximity.ts`), riding the lift (`elevator.ts`),
 * taking a flight of stairs (`stairs.ts`) and entering the neighbouring
 * location (`enterLocation.ts`). Until now F walked a FIXED chain over them
 * (talk, then lift, then stairs, then entry) and stopped at the first one
 * standing. The reaches, though, are not the same size: talking reaches
 * 2.5 m, a landing 1.5 m. So anybody standing in the same room within 2.5 m
 * took the key away from a staircase the avatar was standing right at — the
 * reported bug, and the HUD hid the stair button under the very same
 * condition, which left no second way to use it.
 *
 * THE RULE IS NOW THE MEASURED DISTANCE, not the reach and not the rank: of
 * the offers that stand, the NEAREST one is the one F answers. An NPC 2.4 m
 * away loses to a landing 1.0 m away; an NPC 0.5 m away beats a landing at
 * 1.4 m. Whether an offer stands AT ALL is untouched — each rule keeps its own
 * reach, storey and room conditions and reports `null` when it does not offer;
 * this module never re-derives them and never measures anything itself.
 *
 * ONE RESOLUTION, ONE PLACE: the F handler and the HUD chip both call this
 * function on the same published state, so the chip always names what the key
 * would do (user ruling: exactly one offer is shown, and it is the one F
 * triggers).
 *
 * Pure like `walk.ts`, `proximity.ts` and `stairs.ts`: plain numbers, no
 * Three, no DOM, no module state and no import at all — which is what lets
 * `scripts/smoke_offer_resolve.mjs` check it with hand-derived numbers.
 */

/** The four kinds of offer, in the order that breaks a tie (see below). */
export type OfferKind = 'talk' | 'elevator' | 'stairs' | 'enter';

/** How an offer looks to this module: a measured XZ distance in world metres,
 *  or `null`/absent for "this rule makes no offer here". */
export interface OfferDistance {
  dist: number;
}

/**
 * The standing offers, exactly as the game state publishes them — the field
 * names are the state's own, so `nearestOffer(getGameState())` is the whole
 * call and there is no second record to keep in step with the first.
 */
export interface OfferSource {
  talkTarget: OfferDistance | null;
  elevator: OfferDistance | null;
  stairs: OfferDistance | null;
  enterOffer: OfferDistance | null;
}

/**
 * TIE-BREAK ORDER, written down so it cannot drift: two offers at exactly the
 * same distance fall to the one listed first here — the old fixed priority
 * (talk, lift, stairs, entry). It decides nothing else; any difference in
 * distance, however small, wins over it.
 */
export const OFFER_TIEBREAK: readonly OfferKind[] = ['talk', 'elevator', 'stairs', 'enter'];

/**
 * The offer the F key answers and the HUD shows, or `null` when none stands.
 *
 * A candidate counts only with a FINITE, non-negative distance: `null` is the
 * normal "no offer" answer of every rule, and a NaN (a degenerate payload
 * point) must not be able to win a comparison it cannot lose either.
 */
export function nearestOffer(src: OfferSource): OfferKind | null {
  let best: OfferKind | null = null;
  let bestDist = Infinity;
  for (const kind of OFFER_TIEBREAK) {
    const offer = kind === 'talk' ? src.talkTarget
      : kind === 'elevator' ? src.elevator
        : kind === 'stairs' ? src.stairs : src.enterOffer;
    if (!offer) continue;
    const dist = offer.dist;
    if (!Number.isFinite(dist) || dist < 0) continue;
    // Strictly nearer, so an equal distance keeps the kind found first — that
    // IS the tie-break above.
    if (dist < bestDist) {
      best = kind;
      bestDist = dist;
    }
  }
  return best;
}
