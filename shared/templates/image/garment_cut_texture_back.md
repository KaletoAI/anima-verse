{#- Texture from cut, the BACK job (occasion garment_cut_texture, app/core/garment_cut_texture.py).
    The first image is the clean island template of the back panel alone; the second image is the piece's own BACK
    view (garment_template_views: the item picture turned around, the piece alone), so a print that only the front
    carries is never copied onto the back.
    The ordinals become <Picture 1>/<Picture 2> for P-H3 at the central handoff (prompt_adapters.reference_wording).
    Say everything positively or with "Do not ...": a sentence or clause opening with "no"/"without" would be moved
    to the negative by the composer's negation guard and dropped on this no-fold occasion.
    Variables: piece (e.g. "T-shirt"), pieces (English panel names from the island names). -#}
A flat 2D UV texture map for a 3D garment. Fill the exact {{ piece }} sewing pattern islands in the first image with the back of the {{ piece }} in the second image, which shows the garment from behind: its fabric colour, material texture and only the design that the back itself carries. The pattern has exactly these pieces: {{ pieces | join(", ") }}. A plain back stays plain fabric. Unwrap and flatten the fabric completely onto these pieces, removing all wrinkles, fabric folds, shadows and perspective distortion. Use even, flat studio lighting with zero baked shadows. Keep the exact outlines, layout, proportions and white background of the first image completely unchanged. Do not add prints, text, labels or pieces that the second image and the first image do not have.
