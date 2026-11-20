{#- Texture from cut (occasion garment_cut_texture, app/core/garment_cut_texture.py).
    The first image is the piece's clean island template, the second the full-res item image.
    The ordinals become <Picture 1>/<Picture 2> for P-H3 at the central handoff (prompt_adapters.reference_wording).
    Say everything positively or with "Do not ...": a sentence or clause opening with "no"/"without" would be moved
    to the negative by the composer's negation guard and dropped on this no-fold occasion.
    Variables: piece (e.g. "T-shirt"), pieces (English panel names from the island names). -#}
A flat 2D UV texture map for a 3D garment. Fill the exact {{ piece }} sewing pattern islands in the first image with the fabric colour, material texture and graphic print design from the {{ piece }} in the second image. The pattern has exactly these pieces: {{ pieces | join(", ") }}. Unwrap and flatten the design completely onto these pieces, removing all wrinkles, fabric folds, shadows and perspective distortion. Use even, flat studio lighting with zero baked shadows. Keep the exact outlines, layout, proportions and white background of the first image completely unchanged. Do not add text, labels or pieces that the first image does not have.
