{#- Texture from cut, the BACK job (occasion garment_cut_texture, app/core/garment_cut_texture.py).
    The first image is the ZOOMED island template of the back panel alone (``back_frame``: the island's box + 12 %,
    a white square scaled to the canvas, so the panel fills ~40 % instead of ~15 %), PRE-FILLED with the item's base
    fabric colour; the second image is the piece's own BACK view (garment_template_views).
    Prompt test 2026-11-21 (see the front job's file): on the un-zoomed template every short prompt copied the
    back-view photo into the empty canvas (coverage 0.84-0.91) and the long one drew an extra garment or invented a
    print; zoomed + this short prompt passed Kai, Dario and Tilda clean (coverage >= 0.999, detail 0.0). Both are
    needed. Do not name a colour and do not write "no ...".
    The ordinals become <Picture 1>/<Picture 2> for P-H3 at the central handoff (prompt_adapters.reference_wording).
    Variables: piece (e.g. "T-shirt"). -#}
Texture the shape in the first image with the fabric on the back of the {{ piece }} in the second image. Keep the shape, its colour and the white background exactly. Add only the fine weave of the fabric, flat and evenly lit.
