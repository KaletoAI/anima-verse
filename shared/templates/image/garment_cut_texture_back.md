{#- Texture from cut, the BACK job (occasion garment_cut_texture, app/core/garment_cut_texture.py).
    The first image is the island template of the back panel alone, PRE-FILLED with the item's base fabric colour
    (cut_texture_post.fabric_colour — the item picture is the colour truth for both jobs); the second image is the
    piece's own BACK view (garment_template_views: the item picture turned around, the piece alone), so a print that
    only the front carries is never copied onto the back.
    User test 2026-11-21 (see the front job's file): the colour is given, only what the back really shows is copied,
    a plain back stays plain, and the island is named by its place in the template.
    The ordinals become <Picture 1>/<Picture 2> for P-H3 at the central handoff (prompt_adapters.reference_wording).
    Say everything positively or with "Do not ...": a sentence or clause opening with "no"/"without" would be moved
    to the negative by the composer's negation guard and dropped on this no-fold occasion.
    Variables: piece (e.g. "T-shirt"), pieces (English panel names from the island names), layout (one sentence per
    island), sleeves (unused: the back job has no sleeves). -#}
A flat 2D UV texture map for a 3D garment, made from the back of the {{ piece }} in the second image, which shows the garment from behind. The first image is the sewing pattern of the back, with exactly these pieces: {{ pieces | join(", ") }}.{% if layout %} In the first image, {{ layout | join("; ") }}.{% endif %} It is already filled with the plain fabric colour of the {{ piece }}: keep that colour and give it the material texture of the fabric. Copy only what the back in the second image really shows: an embroidery, print or logo goes onto the place where it sits on the back, at its size there. A plain back stays plain fabric. Do not invent text, logos, graphics, patterns or colours that the second image does not show. Unwrap and flatten the fabric completely onto these pieces, removing all wrinkles, fabric folds, shadows and perspective distortion. Use even, flat studio lighting with zero baked shadows. Keep the exact outlines, layout, proportions and white background of the first image completely unchanged. Do not add labels or pieces that the first image does not have.
