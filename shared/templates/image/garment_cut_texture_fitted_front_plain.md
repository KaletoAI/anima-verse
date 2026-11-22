{#- Texture from cut, the FRONT job of a PLAIN close-fitting piece (group A: briefs, bra, gloves, tights, trousers;
    occasion garment_cut_texture, app/core/garment_cut_texture.py, family "fitted"). Reference 1 is the island template
    of the pieces the front job fills (the main pieces — front leg panels, a brief's front, the tights' legs, the bra's
    cups, the backs of the hands — and the small pieces: waistband, cuffs, bands, straps, gusset, thumbs, gore), every
    island PRE-FILLED with the item's base fabric colour; reference 2 is the full-res item picture. Sections as in
    garment_cut_texture_front_plain.md (the top's tested files, which stay byte-identical).
    picture_edit: the top's short P-H3 winner, "fine weave" widened to the fabric's surface (leather, lace, scales are
    no weave).
    picture_subject: the top's candidate N in subject form, the pieces named from the pattern; the small pieces the
    code fills with the main pieces' fabric are named as plain.
    image_tag: the top's draft for Qwen-Image-2.1 with the fitted wording (untested; Qwen is in no chain).
    ordinal: the picture_edit text without the edit frame.
    Do not name a colour. Left and right are the wearer's (the subject-form and image-tag sections say so).
    Variables: piece, a_piece ("a balconette bra", "a pair of gloves") ("trousers"), pieces, layout, sleeves (the small pieces kept plain), main / main_count /
    main_names (garment_cut_texture.main_words; unused here). -#}
## picture_edit
Edit {{ ref(1) }}. Texture the sewing pattern in {{ ref(1) }} with the fabric of the {{ piece }} in {{ ref(2) }}. Keep every shape, its colour and the white background exactly. Add only the fine surface of the fabric, flat and evenly lit.
## picture_subject
The flat sewing pattern of {{ a_piece }} on a white background in {{ ref(1) }} is <Subject 1>; it has exactly these pieces: {{ pieces | join(", ") }}{% if layout %}, where {{ layout | join("; ") }}{% endif %}, each filled with a plain colour; left and right are the wearer's. The {{ piece }} in {{ ref(2) }} is <Subject 2>. The fabric of <Subject 2>, its colour and fine surface, is <Subject 3>. The target image shows <Subject 1> as a flat, evenly lit texture map covered with <Subject 3>. <Subject 1> is partially preserved; every outline, the layout, the proportions and the white background remain exactly, while the plain fill of every piece becomes <Subject 3>. <Subject 3> supplies the exact colour and surface transferred to every piece of <Subject 1>. <Subject 2> serves only as the source of its fabric.{% if sleeves %} The {{ (sleeves[:-1] | join(", ") ~ " and " ~ sleeves[-1]) if sleeves | length > 1 else sleeves[0] }} of <Subject 1> carry only the plain fabric.{% endif %} The fabric lies perfectly flat with even light, without folds, wrinkles, shadows, perspective, skin, labels, text or anything that <Subject 2> does not show.
## image_tag
Fill the sewing pattern in {{ ref(1) }} with the fabric of the {{ piece }} in {{ ref(2) }}, as a flat texture map. {{ ref(1) }} is the canvas: the flat sewing pattern of {{ a_piece }} on a white background with exactly these pieces: {{ pieces | join(", ") }}{% if layout %}; {{ layout | join("; ") }}{% endif %}, each filled with a plain colour; left and right are the wearer's. {{ ref(2) }} is the material source: take its fabric colour and fine surface. Cover every piece of {{ ref(1) }} with that fabric, perfectly flat and evenly lit.{% if sleeves %} The {{ (sleeves[:-1] | join(", ") ~ " and " ~ sleeves[-1]) if sleeves | length > 1 else sleeves[0] }} show only the plain fabric.{% endif %} Keep every outline, the layout, the proportions and the white background of {{ ref(1) }} unchanged. Keep the fabric free of folds, shadows, skin, labels, text and anything that {{ ref(2) }} does not show.
## ordinal
Texture the sewing pattern in {{ ref(1) }} with the fabric of the {{ piece }} in {{ ref(2) }}. Keep every shape, its colour and the white background exactly. Add only the fine surface of the fabric, flat and evenly lit.
