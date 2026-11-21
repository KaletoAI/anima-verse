{#- Texture from cut, the FRONT job of a PLAIN item (occasion garment_cut_texture, app/core/garment_cut_texture.py).
    Reference 1 is the island template of the pieces seen from the front (the front panel, the sleeves, the neckband
    and any collar/placket/cuffs, never the back panel), every island PRE-FILLED with the item's base fabric colour;
    reference 2 is the full-res item picture. One section per edit-prompt dialect (app/imagegen/edit_prompt.py,
    docs/edit-prompts.md section 6); the render picks the section of the backend it runs on, ref(n) is that dialect's
    token, so a section never carries a foreign one.
    picture_edit: the short P-H3 winner of the prompt test 2026-11-21 (23 local jobs, Kai / Dario / Tilda; the long
    prompt invented emblems on Kai's plain shirt), with the "Edit <Picture 1>." the engine node put in front of it.
    picture_subject: candidate N of the MiniMax A/B 2026-11-21 (the model's own subject format; the only variant clean
    on all four cases, with fabric structure); the SAME text as the decorated front.
    image_tag: research draft for Qwen-Image-2.1 (instruction first, roles named, untested; Qwen is in no chain).
    ordinal: the picture_edit text without the edit frame (Flux, Z-Image and every other backend).
    Do not name a colour. The picture_subject text keeps its "without ..." clause (compose keep_negations).
    Variables: piece ("T-shirt"), pieces (panel names in pattern order), layout (one sentence per island, which
    island is which), sleeves (the sleeve pieces whose fabric stays plain; empty with sleeve_print "picture"),
    front_place (unused here). -#}
## picture_edit
Edit {{ ref(1) }}. Texture the sewing pattern in {{ ref(1) }} with the fabric of the {{ piece }} in {{ ref(2) }}. Keep every shape, its colour and the white background exactly. Add only the fine weave of the fabric, flat and evenly lit.
## picture_subject
The flat sewing pattern of a {{ piece }} on a white background in {{ ref(1) }} is <Subject 1>; it has exactly these pieces: {{ pieces | join(", ") }}{% if layout %}, where {{ layout | join("; ") }}{% endif %}, each filled with a plain colour. The {{ piece }} in {{ ref(2) }} is <Subject 2>. The fabric of <Subject 2>, its colour and fine weave, is <Subject 3>. The target image shows <Subject 1> as a flat, evenly lit texture map covered with <Subject 3>. <Subject 1> is partially preserved; every outline, the layout, the proportions and the white background remain exactly, while the plain fill of every piece becomes <Subject 3>. <Subject 3> supplies the exact colour and weave transferred to every piece of <Subject 1>. <Subject 2> serves only as the source of its fabric and its front decoration. Any embroidery, print or logo that <Subject 2> shows on its front appears on the front panel of <Subject 1> at the same place and size.{% if sleeves %} The {{ sleeves | join(" and ") }} of <Subject 1> carry only the plain fabric.{% endif %} The fabric lies perfectly flat with even light, without folds, wrinkles, shadows, perspective, buttons, labels, text or anything that <Subject 2> does not show.
## image_tag
Fill the sewing pattern in {{ ref(1) }} with the fabric of the {{ piece }} in {{ ref(2) }}, as a flat texture map. {{ ref(1) }} is the canvas: the flat sewing pattern of a {{ piece }} on a white background with exactly these pieces: {{ pieces | join(", ") }}{% if layout %}; {{ layout | join("; ") }}{% endif %}, each filled with a plain colour. {{ ref(2) }} is the material source: take its fabric colour and fine weave. Cover every piece of {{ ref(1) }} with that fabric, perfectly flat and evenly lit. Keep every outline, the layout, the proportions and the white background of {{ ref(1) }} unchanged. Keep the fabric free of folds, shadows, buttons, labels, text and anything that {{ ref(2) }} does not show.
## ordinal
Texture the sewing pattern in {{ ref(1) }} with the fabric of the {{ piece }} in {{ ref(2) }}. Keep every shape, its colour and the white background exactly. Add only the fine weave of the fabric, flat and evenly lit.
