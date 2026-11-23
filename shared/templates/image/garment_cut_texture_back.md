{#- Texture from cut, the BACK job (occasion garment_cut_texture, app/core/garment_cut_texture.py).
    Reference 1 is the ZOOMED island template of the back panel alone (back_frame: the island's box + 12 %, a white
    square scaled to the canvas, so the panel fills ~40 % instead of ~15 %), PRE-FILLED with the item's base fabric
    colour; reference 2 is the piece's own BACK view (garment_template_views). Sections: see
    garment_cut_texture_front_plain.md.
    picture_edit: the short P-H3 winner (prompt test 2026-11-21: on the un-zoomed template every short prompt copied
    the back-view photo into the empty canvas; zoomed + this prompt passed Kai, Dario and Tilda).
    picture_subject: candidate N back of the MiniMax A/B — tested on the UN-zoomed template only (Kai, Dario: pass);
    the zoomed case is the live E2E's to show.
    image_tag: research draft (untested). Variables: piece, weave ("fine weave"; "fine vertical stripes" behind a
    striped front answer — cut_texture_post.stripe_words, stage "details" 2026-11-23); the others are unused here. -#}
## picture_edit
Edit {{ ref(1) }}. Texture the shape in {{ ref(1) }} with the fabric on the back of the {{ piece }} in {{ ref(2) }}. Keep the shape, its colour and the white background exactly. Add only the {{ weave }} of the fabric, flat and evenly lit.
## picture_subject
The flat sewing pattern of the back panel of a {{ piece }} on a white background in {{ ref(1) }} is <Subject 1>, filled with a plain colour. The back of the {{ piece }} in {{ ref(2) }} is <Subject 2>. The fabric of <Subject 2>, its colour and {{ weave }}, is <Subject 3>. The target image shows <Subject 1> as a flat, evenly lit texture map covered with <Subject 3>. <Subject 1> is partially preserved; its outline, proportions and the white background remain exactly, while its plain fill becomes <Subject 3>. <Subject 3> supplies the exact colour and weave transferred to <Subject 1>. <Subject 2> serves only as the source of its fabric and of any decoration on its back. An embroidery, print or logo that <Subject 2> shows appears on <Subject 1> at the same place and size; a plain back stays plain fabric. The fabric lies perfectly flat with even light, without folds, wrinkles, shadows, perspective, labels, text or anything that <Subject 2> does not show.
## image_tag
Fill the back panel in {{ ref(1) }} with the fabric of the {{ piece }} in {{ ref(2) }}, as a flat texture map. {{ ref(1) }} is the canvas: the flat sewing pattern of the back panel of a {{ piece }} on a white background, filled with a plain colour. {{ ref(2) }} is the material source and shows the {{ piece }} from behind: take its fabric colour and {{ weave }}, and only an embroidery, print or logo that its back really shows. Cover the panel of {{ ref(1) }} with that fabric, perfectly flat and evenly lit; a plain back stays plain fabric. Keep the outline, the proportions and the white background of {{ ref(1) }} unchanged. Keep the fabric free of folds, shadows, labels, text and anything that {{ ref(2) }} does not show.
## ordinal
Texture the shape in {{ ref(1) }} with the fabric on the back of the {{ piece }} in {{ ref(2) }}. Keep the shape, its colour and the white background exactly. Add only the {{ weave }} of the fabric, flat and evenly lit.
