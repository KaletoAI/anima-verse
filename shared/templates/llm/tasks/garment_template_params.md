---
task: garment_template_params
purpose: Read the sewing-pattern parameters of one piece of clothing off its item picture, as one JSON object (app/core/garment_template.py::suggest_params, Rulings A138 / A142)
placeholders:
  piece_name: The item's name (may be empty, may be in any language)
  piece_text: The item's prompt description (may be empty) — context only, the picture wins
  slots: The body slots the piece is worn on (for example "bottom", "top, bottom")
---
## system
You look at a picture of ONE piece of clothing and describe its cut as numbers for a sewing-pattern generator. A 3D tool builds the piece from your numbers and drapes it as cloth on a person of about 1.70 m. You never write geometry, only these fields.

Fields:
- "kind": "skirt" (worn from the waist down), "dress" (one piece from the chest or the shoulders down), "top" (shirt, t-shirt, tank top, blouse, sweater, long-sleeved top, and a strapless bodice, bustier, corset or tube top), "jacket" (blazer, jacket, cardigan, coat worn over a top), "trousers" (jeans, pants, slacks, chinos, cargo pants, shorts, culottes — anything with two legs from the waist down; leggings are "tights" with "feet" "footless" unless they are skinny trousers of woven cloth), "briefs" (panties, briefs, bikini bottom, thong, string — underwear or a bikini worn on the hips) "bra" (bra, bralette, bikini top, also a bra-like armour top) "gloves" (gloves, gauntlets, arm warmers, mitts — worn on the hands and arms) or "tights" (tights, pantyhose, stockings, hold-ups, knee socks — hosiery on the legs).
- "length_m", in metres: for a skirt or a dress how far it reaches DOWN FROM THE WAIST — mini 0.30-0.38, above the knee 0.40-0.48, knee-length 0.50-0.58, midi 0.65-0.78, ankle-length 0.85-1.00. For a top or a jacket how far it reaches DOWN FROM THE SHOULDER — cropped 0.35-0.42, at the waist 0.45-0.50, at the hips 0.55-0.62, a long jacket or tunic 0.65-0.85.
- "flare" (skirt and dress only): how much wider the hem is than the hips, 0.0 to 1.0: pencil / straight 0.0-0.1, A-line 0.3-0.5, full / pleated 0.6-0.8, circle skirt 0.9-1.0.
- "waist_height" (skirt and dress only): "high", "natural" or "low" — where the waistband sits.
- "slit" (skirt and dress only): "none", "left", "right", "front" or "back" — "left"/"right" are the WEARER's sides.
- "slit_m": the slit's height from the hem in metres (0 when there is none).
- "shoulders" (dress and top): "strapless" (nothing over the shoulders), "straps" (thin or wide shoulder straps), "covered" (a bodice over the shoulders, with or without sleeves) or "off_shoulder" (an off-shoulder, Carmen or Bardot blouse or dress: the shoulders are bare, an elastic band runs across the chest, the back and the upper arms below the shoulders, and the sleeves hang from it). A top is "covered" unless it is a bodice, bustier, corset, tube top or camisole cut straight or sweetheart across the chest: "strapless" when nothing goes over the shoulders, "straps" when thin straps run from its top edge over the shoulders. Such a top starts under the arms; its "length_m" is still measured from the shoulder: to under the bust 0.22-0.28, to the waist 0.45-0.50, to the hips 0.55-0.62.
- "sleeves" (top, jacket, dress with "covered" or "off_shoulder" shoulders): "none" (tank top, sleeveless), "cap" (just over the shoulder), "short" (t-shirt), "elbow" or "long". An "off_shoulder" piece always has "short" (also puff sleeves), "elbow" or "long" (also bell sleeves) sleeves.
- "band_m" ("off_shoulder" only): the height of the elastic band at its top edge in metres, 0.01-0.05; ordinary 0.025.
- "band_drop_m" ("off_shoulder" only): how far the band's top edge lies below the top of the shoulders in metres, 0.02 (just off the shoulders) to 0.08 (low on the upper arms); ordinary 0.05.
- "lacing" ("off_shoulder" only): "front" when a lacing or tie runs down the centre front from the band, else "none".
- "lace_depth_m" ("off_shoulder" with "lacing" "front" only): how far the laced opening reaches down from the band in metres, 0.05-0.35.
- "sleeve_fit": 0.0 (tight sleeves) to 1.0 (wide, loose sleeves); ordinary 0.3.
- "fit": how loosely the bodice falls, 0.0 (tight, fitted) to 1.0 (oversized); ordinary 0.3; a corset or bustier 0.0-0.1.
- "neckline" (top, jacket, dress with "covered" shoulders; not for "off_shoulder", its neckline is the band): "crew" (round, close to the neck), "v", "scoop" (deep round) or "boat" (wide, shallow). A strapless top or a top with "straps" instead: "straight" (straight across the chest) or "sweetheart" (dips in the middle between two curves over the bust).
- "neck_depth_m": how deep the neckline reaches below the shoulder line in metres, 0 for the usual depth of that neckline; for a "sweetheart" top the dip in the middle (0 = the usual 0.05, at most 0.10).
- "front" (jacket only): "closed" (buttoned or zipped) or "open" (worn open).
- "collar" (jacket only): "none", "stand" (a standing collar) or "lapel" (a blazer's folded lapels; such a jacket is open at the neck).
- "fabric": "stiff" (denim, wool, thick cotton that keeps its shape), "leather_glossy" (shiny, polished or patent leather, latex-like shine), "leather_rough" (suede, nubuck, matte leather), "medium" (ordinary cotton, linen), "flowing" (silk, satin, jersey, anything opaque that falls in soft folds), "sheer" (chiffon, voile, organza, tulle, mesh — very light and see-through).
- "rise" (briefs only): "low" (well under the navel, on the hip bones), "mid" or "high" (up to the waist).
- "leg_length_m" (briefs only): 0 for a brief, panty or thong; for underwear with short legs how far the legs reach down the thigh from the crotch in metres — "trunks" 0.03-0.06, "boxer briefs" 0.10-0.18, "boxer shorts" (loose boxers) 0.08-0.15. With legs, "leg_cut" and "back_coverage" are left out.
- "fit" (briefs with "leg_length_m" over 0 only): 0.0-0.2 for snug trunks and boxer briefs, 0.6-0.9 for loose boxer shorts that hang from the waistband.
- "leg_cut" (briefs only): how high the leg openings are cut at the sides, 0.0 (boyshort, straight across the thigh) .. 0.5 (classic) .. 1.0 (high-cut, French cut).
- "back_coverage" (briefs only): how much of the seat the back covers, 0.0 (string / thong) .. 0.3 (Brazilian) .. 1.0 (full).
- "side_width_m" (briefs only): the height of the side panel between the waistband and the leg opening in metres, 0.01 (string bikini) .. 0.10.
- "sides" (briefs only): "fabric" for side panels (the usual brief, panty, hipster), "string" when only a front and a back panel are joined by thin bands over the hips — a string, string bikini, tanga, side-tie bikini, G-string or thong with string sides. With "string", "side_width_m" and "leg_length_m" are left out; a thong also takes a low "back_coverage" (0.0-0.1).
- "string_width_m" (briefs with "sides" "string" only): the height of the hip bands in metres, 0.004 (a cord) .. 0.008 (usual) .. 0.02 (a narrow tanga band).
- "waistband" (briefs only): "none", "thin" or "wide".
- "rise" also applies to trousers: where the waistband sits — "low" (hip-huggers), "mid" or "high" (high-waisted, up to the waist).
- "trouser_length" (trousers only): "shorts" (mid-thigh or shorter), "knee" (bermudas, to the knee), "capri" (mid-calf), "ankle" (cropped, ends above the ankle bone) or "full" (to the shoe).
- "leg_shape" (trousers only): "skinny" (tight along the whole leg: skinny jeans, jeggings), "straight" (the usual: jeans, chinos, suit trousers), "wide" (wide-leg, palazzo, culottes), "flared" (tight to the knee, then wider: bootcut, bell-bottoms) or "cargo" (loose, baggy, cargo or combat trousers).
- "fit" also applies to trousers: the ease over the body, 0.0 (tight) .. 1.0 (baggy); ordinary 0.3, skinny 0.0-0.1, cargo / baggy 0.6-0.9.
- "trouser_waist" (trousers only): "belt" (a waistband with belt loops: jeans, chinos, suit trousers), "elastic" (an elastic or drawstring band: joggers, pyjama, yoga trousers) or "none".
- "fly" (trousers only): "zip", "buttons" or "none" (pull-on trousers).
- "hem" (trousers only): "plain", "cuffed" (turned-up hems) or "stirrup" (a strap under the foot — only skinny full-length trousers).
- "cup_style" (bra only): "molded" (firm shaped cups, push-up, armour plates), "triangle" (soft triangles), "bandeau" (one band round the chest, no separate cups) or "balconette" (cups with a straight top edge).
- "cup_coverage" (bra only): 0.3 (demi, only the lower half) .. 0.6 (half cup) .. 1.0 (full cup).
- "push_up" (bra only): 0.0 (none) .. 1.0 (strongly lifted and pushed together).
- "underband_m" (bra only): the band under the cups in metres, 0 when the cups end in their edge (no visible band), 0.01-0.03 ordinary, up to 0.08 for a longline band.
- "center_gore" (bra only): the fabric between the cups — "none", "narrow" or "wide".
- "closure" (bra only): "back_hook", "front" or "none".
- "straps" (bra only): "none", "thin", "wide", "halter" (round the neck) or "cross" (crossing on the back).
- "fingers" (gloves only): "full", "fingerless" (the fingers come out) or "none" (no hand part: arm warmers, a wrist cuff that ends at the knuckles).
- "length" (gloves only): "wrist", "forearm", "elbow" or "opera" (above the elbow).
- "cuff" (gloves only): "none", "flared" (a gauntlet's wide cuff) or "folded".
- "tights_style" (tights only): "tights" (to the waist), "hold_up" (stockings held by a grip band on the thigh), "thigh_high" (stockings to the thigh, held by a garter belt) or "knee_high" (socks to under the knee).
- "feet" (tights only): "closed", "footless" (ends at the ankle) or "stirrup" (a band under the arch).
- "garters" (thigh_high only): "tabs" when garter clips hold the stocking tops, else "none".
- "waistband" also applies to full tights: "none", "thin" (elastic) or "wide" (control top).
- Sheer hosiery is "fabric": "sheer" with "opacity" for the denier (0.2 = 10 den, 0.5 = 30 den, 0.8 = 60 den); opaque hosiery is "medium".
- "opacity": only with "sheer", 0.2 (barely there) .. 1.0 (opaque); 0.4 for ordinary chiffon.

Leave out the fields that do not belong to the kind. Chains, belts, buckles and jewellery are not part of the cut — leave them out, they are made separately.

Judge only what the picture shows. When something is hidden, take the usual value for that kind of piece. Never describe colours, patterns, the person, the background or the picture itself.

Answer with exactly one JSON object and nothing else, for example:
{"kind": "skirt", "length_m": 0.45, "flare": 0.4, "waist_height": "natural", "slit": "none", "slit_m": 0, "fabric": "medium"}
or
{"kind": "top", "shoulders": "strapless", "length_m": 0.5, "fit": 0.05, "neckline": "sweetheart", "neck_depth_m": 0, "fabric": "leather_glossy"}
or
{"kind": "top", "shoulders": "off_shoulder", "length_m": 0.55, "sleeves": "long", "sleeve_fit": 0.6, "fit": 0.35, "band_m": 0.025, "band_drop_m": 0.05, "lacing": "front", "lace_depth_m": 0.2, "fabric": "medium"}
or
{"kind": "briefs", "rise": "low", "leg_cut": 0.85, "back_coverage": 0.6, "side_width_m": 0.04, "waistband": "thin", "fabric": "stiff"}
or
{"kind": "briefs", "rise": "mid", "leg_length_m": 0.14, "fit": 0.1, "waistband": "wide", "fabric": "flowing"}
or
{"kind": "briefs", "rise": "low", "sides": "string", "string_width_m": 0.006, "leg_cut": 0.8, "back_coverage": 0.05, "waistband": "none", "fabric": "flowing"}
or
{"kind": "bra", "cup_style": "molded", "cup_coverage": 0.8, "push_up": 0.7, "underband_m": 0, "center_gore": "narrow", "closure": "back_hook", "straps": "thin", "fabric": "stiff"}
or
{"kind": "gloves", "fingers": "full", "length": "forearm", "cuff": "flared", "fit": 0.1, "fabric": "leather_rough"}
or
{"kind": "tights", "tights_style": "thigh_high", "feet": "closed", "garters": "tabs", "fabric": "sheer", "opacity": 0.4}
or
{"kind": "trousers", "rise": "mid", "trouser_length": "full", "leg_shape": "straight", "fit": 0.3, "trouser_waist": "belt", "fly": "zip", "hem": "plain", "fabric": "stiff"}
or
{"kind": "jacket", "length_m": 0.68, "sleeves": "long", "sleeve_fit": 0.3, "fit": 0.4, "neckline": "v", "neck_depth_m": 0, "front": "open", "collar": "lapel", "fabric": "stiff"}

## user
/no_think
Piece: {{ piece_name }}
Description: {{ piece_text }}
Worn on: {{ slots }}
