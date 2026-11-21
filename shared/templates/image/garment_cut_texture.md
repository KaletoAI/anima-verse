{#- Texture from cut, the FRONT job (occasion garment_cut_texture, app/core/garment_cut_texture.py).
    The first image is the island template of the pieces seen from the front (the front panel, the sleeves, the
    neckband and any collar/placket/cuffs — never the back panel, which is its own job with the back view), every
    island PRE-FILLED with the item's base fabric colour (cut_texture_post.fabric_colour); the second image is the
    full-res item picture (a front).
    User test 2026-11-21: with grey islands and the words "graphic print design" P-H3 invented a magenta shirt with a
    big text print for a plain blue T-shirt, and without them a red one; it also painted a chest embroidery onto one
    sleeve. So: the colour is given, only what the picture really shows is copied, a plain garment stays plain, and
    every island is named by its place in the template. The sleeves and the neckband are filled from the front
    panel's fabric after the answer anyway (unless the item is marked with a sleeve print) — the prompt still says it.
    The ordinals become <Picture 1>/<Picture 2> for P-H3 at the central handoff (prompt_adapters.reference_wording).
    Say everything positively or with "Do not ...": a sentence or clause opening with "no"/"without" would be moved
    to the negative by the composer's negation guard and dropped on this no-fold occasion.
    Variables: piece (e.g. "T-shirt"), pieces (English panel names from the island names), layout (one sentence per
    island: which island of the first image is which piece), sleeves (the sleeve names among the pieces). -#}
A flat 2D UV texture map for a 3D garment, made from the front of the {{ piece }} in the second image. The first image is the sewing pattern of the {{ piece }}, with exactly these pieces: {{ pieces | join(", ") }}.{% if layout %} In the first image, {{ layout | join("; ") }}.{% endif %} Every piece is already filled with the plain fabric colour of the {{ piece }}: keep that colour and give it the material texture of the fabric. Copy only what the second image really shows: an embroidery, print, logo or pattern goes onto the piece and the place where it sits on the garment in the second image, at its size there. A plain {{ piece }} stays plain fabric.{% if sleeves %} The {{ sleeves | join(" and ") }} get only the plain fabric, unless the second image shows a print or embroidery on that sleeve itself.{% endif %} Do not invent text, logos, graphics, patterns or colours that the second image does not show. Unwrap and flatten everything completely onto the pieces, removing all wrinkles, fabric folds, shadows and perspective distortion. Use even, flat studio lighting with zero baked shadows. Keep the exact outlines, layout, proportions and white background of the first image completely unchanged. Do not add labels or pieces that the first image does not have.
