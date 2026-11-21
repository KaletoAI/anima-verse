{#- Texture from cut, the FRONT job (occasion garment_cut_texture, app/core/garment_cut_texture.py).
    The first image is the island template of the pieces seen from the front (the front panel, the sleeves, the
    neckband and any collar/placket/cuffs — never the back panel, which is its own job), every island PRE-FILLED with
    the item's base fabric colour (cut_texture_post.fabric_colour); the second image is the full-res item picture.
    Prompt test 2026-11-21 (23 local P-H3 jobs, Kai / Dario / Tilda, same seeds; prompts by Fable): SHORT wins. The
    long prompt (layout sentences, piece list, "only if the picture shows a print") invented emblems on Kai's plain
    shirt; the short plain prompt is clean on all three, the short decorated prompt keeps Dario's embroidery on the
    front panel with the sleeves plain. CODE picks the variant, never the model: ``decorated`` is the item picture's
    detail density above garment_cut_texture.DECORATED_DETAIL; ``front_place`` the front island's place in the
    template ("top left"). Do not name a colour and do not write "no ..." (the composer's negation guard moves it to
    the negative).
    The ordinals become <Picture 1>/<Picture 2> for P-H3 at the central handoff (prompt_adapters.reference_wording).
    Variables: piece (e.g. "T-shirt"), decorated (bool), front_place (e.g. "top left"). -#}
{% if decorated %}
The {{ front_place }} shape of the first image is the front of the {{ piece }} in the second image, laid flat. Paint it as that front: same fabric, same print or embroidery at the same place. The other shapes get plain fabric only. Outlines, colour and white background stay unchanged.
{% else %}
Texture the sewing pattern in the first image with the fabric of the {{ piece }} in the second image. Keep every shape, its colour and the white background exactly. Add only the fine weave of the fabric, flat and evenly lit.
{% endif %}
