"""The image routing occasion catalog — the ONE list of render occasions.

Every render the app starts belongs to exactly one OCCASION ("photo",
"location", "mesh_building", ...). The admin page Media Generation → Routing
keeps one ordered backend chain per occasion (config
``image_generation.routing``); ``app/imagegen/routing.py`` resolves it. Like
``app.core.llm_tasks.TASK_TYPES`` on the LLM side, this dict is the only place
an occasion is declared — resolver, admin page, save validator and the config
migration all read it.

Spec: development_instructions/plan-image-routing.md (+ its binding review
notes).

Per occasion:
  label               English, shown on the admin pages.
  media               "image" | "video" | "mesh" — the backend MEDIA_TYPE.
  category            "render": every image/video backend except inpaint
                      (img2img is preferred when a reference is slotted);
                      "img2mesh": an unrigged image-to-mesh backend;
                      "img2hair": hair cards from one character image
                      (HairDeck) — never matched by an img2mesh occasion;
                      "txt2hair": hair strands from text (HAAR) — a
                      params-only job, never matched by another occasion;
                      "mesh2rig": a standalone mesh-to-rig backend.
  rig                 Required delivery rig, never a backend property.
                      Rig occasions require a configured mesh2rig chain; an
                      empty rig chain raises NoRouteError, never a cheapest pick.
                      Configure it in /admin/settings → Media Generation → Routing.
  character_scoped    True: the character's own backend match
                      (profile.outfit_imagegen.<char_spec_field>) is
                      position 0 in front of the occasion chain.
  char_spec_field     outfit_imagegen field read for position 0.
  char_spec_fallback  read when char_spec_field is empty ("" = none); a
                      tuple names several fields, tried in order.
  needs_ref_slot      True: only backends with ref_slot_count >= 1.
  style_use_cases     info only — the style use cases these renders use.
  covers              info only — the call sites (admin tooltip).
  pose_check          True: the occasion renders people, so the routing page
                      offers the LLM pose check before generating
                      (app/imagegen/pose_check.py, config
                      ``image_generation.pose_check``).
  hint                optional English advice shown with the occasion on the
                      routing page and the character's backend globs.
"""
from typing import Any, Dict, List, Tuple

_CHAR = {"character_scoped": True, "char_spec_field": "workflow",
         "char_spec_fallback": ""}
_WORLD = {"character_scoped": False, "char_spec_field": "",
          "char_spec_fallback": ""}
# Occasions that render people: they offer the pose check.
_PEOPLE = {"pose_check": True}


def _image(label: str, covers: str, style_use_cases: List[str],
           scope: Dict[str, Any], **extra: Any) -> Dict[str, Any]:
    return {"label": label, "media": "image", "category": "render", "rig": "",
            "needs_ref_slot": False, "style_use_cases": style_use_cases,
            "covers": covers, **scope, **extra}


def _mesh(label: str, covers: str, rig: str,
          scope: Dict[str, Any] = _WORLD) -> Dict[str, Any]:
    return {"label": label, "media": "mesh", "category": "img2mesh", "rig": rig,
            "needs_ref_slot": False, "style_use_cases": [], "covers": covers,
            **scope}


# A character's mesh match (Characters → 3D) covers whichever of the two
# character mesh occasions its rig selects; objects and buildings stay world-only.
_CHAR_MESH = {"character_scoped": True, "char_spec_field": "mesh_workflow",
              "char_spec_fallback": ""}


OCCASIONS: Dict[str, Dict[str, Any]] = {
    "photo": _image(
        "Photo", "TakePhoto, scene photo button, story image + visualize, "
        "video still", ["character", "story"], _CHAR, **_PEOPLE),
    "instagram": _image("Instagram post", "Instagram post", ["instagram"], _CHAR,
                        **_PEOPLE),
    "profile": _image(
        "Profile portrait", "Character portrait, temporary NPC portrait",
        ["profile"], {"character_scoped": True, "char_spec_field": "profile_workflow",
                      "char_spec_fallback": ""}, **_PEOPLE),
    "expression": _image(
        "Expression & outfit variant",
        "Mood/activity variants, wardrobe preview, NPC default variant",
        ["expression", "expression_head", "expression_edit", "outfit"], _CHAR, **_PEOPLE),
    "tpose": _image(
        "T-pose main reference", "Standard pose reference, main mesh input",
        ["tpose", "tpose_animal", "outfit"],
        {"character_scoped": True, "char_spec_field": "tpose_workflow",
         "char_spec_fallback": "workflow"}),
    "tpose_view": _image(
        "T-pose reference views", "Extra humanoid and animal reference views",
        ["tpose_back", "tpose_side", "face_view", "tpose_animal_view"],
        {"character_scoped": True, "char_spec_field": "tpose_view_workflow",
         "char_spec_fallback": ""}),
    # Garment edits (base-body phase 4): the worn and garment-only views are
    # edits of the stored base view, so a reference slot is mandatory. Kept
    # apart from tpose_view on purpose — that occasion triggers the mesh-input
    # matte, which trims the image sides and breaks the shared framing.
    "garment_view": _image(
        "Garment & hair edits", "Wardrobe: worn and garment-only views; HairDeck hair: beard-free picture",
        ["garment_edit"],
        {"character_scoped": True, "char_spec_field": "tpose_view_workflow",
         "char_spec_fallback": ""}, needs_ref_slot=True),
    # Base-body pipeline (spec 2026-11-08-base-body-outfits-design.md § A/B):
    # every step its own chain, per character overridable like the T-pose.
    # The fallback fields keep a character's existing T-pose picks in force;
    # config._migrate_base_body_routing seeds the chains from tpose /
    # tpose_view once.
    "base_front": _image(
        "Base body — front", "Base body tab: the bald A-pose base-body front",
        ["base_front", "base_front_edit"],
        {"character_scoped": True, "char_spec_field": "base_front_workflow",
         "char_spec_fallback": ("tpose_workflow", "workflow")},
        hint="An edit of the profile picture (a backend that takes a reference "
             "image is required while there is one); an accurate (non-turbo) "
             "model is recommended."),
    # The full-body references (Ruling A87, app/core/full_body_reference.py):
    # the picture the A-pose front is an edit of. Each render is an EDIT of
    # a reference image (``require_reference``), so a backend without a
    # reference slot never serves it (``needs_ref_slot``) and an empty chain
    # is no route (``requires_chain``) — never the cheapest (possibly paid)
    # backend. config._migrate_reference_routing seeds the chains from
    # base_front / outfit_front once; a character's own glob is the one of
    # the front it feeds (no field of its own).
    "base_reference": {**_image(
        "Base body — full-body reference", "Base body tab: the full-body reference the A-pose front is an edit of "
                                           "(an edit of the profile picture)",
        ["base_reference"],
        {"character_scoped": True, "char_spec_field": "base_front_workflow",
         "char_spec_fallback": ("tpose_workflow", "workflow")}, needs_ref_slot=True,
        hint="An edit of the profile picture: a backend that takes a reference image is required. Generated "
             "only by a click on Generate (Base body → Views)."), "requires_chain": True},
    "base_view": _image(
        "Base body — back/side views", "Base body tab: base-body back, left and right (edits of the front)",
        ["base_view_back", "base_view_side"],
        {"character_scoped": True, "char_spec_field": "base_view_workflow",
         "char_spec_fallback": "tpose_view_workflow"}),
    "outfit_front": _image(
        "Outfit — front edit", "Figure tab, Dressed views: the dressed front — an edit of the base front, the "
                               "outfit's full-body reference as a second picture (Ruling A125)",
        ["outfit_edit", "base_front_edit"],
        {"character_scoped": True, "char_spec_field": "outfit_front_workflow",
         "char_spec_fallback": "tpose_view_workflow"}),
    "outfit_reference": {**_image(
        "Outfit — full-body reference", "Figure tab, Dressed views: the outfit's full-body reference (an edit of "
                                        "the plain body's full-body reference, else of the profile picture)",
        ["outfit_reference"],
        {"character_scoped": True, "char_spec_field": "outfit_front_workflow",
         "char_spec_fallback": "tpose_view_workflow"}, needs_ref_slot=True,
        hint="An edit of a reference picture: a backend that takes a reference image is required. Generated only "
             "by a click on Generate (Figure → Dressed views)."), "requires_chain": True},
    "outfit_back_draft": _image(
        "Outfit — back draft", "Figure tab, Dressed views: back draft, an edit of the base back view (the outfit's "
                               "reference or the dressed front as a second picture)",
        ["outfit_edit"],
        {"character_scoped": True, "char_spec_field": "outfit_back_draft_workflow",
         "char_spec_fallback": "tpose_view_workflow"},
        hint="An edit of the base back view that only changes the clothing (Ruling A125) — composited back onto "
             "it on the CPU (no second render). A view-change model is wrong here: route a plain edit model."),
    # The second step of a dressed back/side view — the draft's clothing put
    # onto the base view — is a CPU composite (app/core/view_composite.py,
    # Task 11g): the model-fit occasions outfit_back / outfit_side are gone
    # (config.REMOVED_FIT_OCCASIONS drops their stored chains).
    # Dressed side views (world setting base_body.dressed_side_views, off by
    # default): a draft like the back's. A character's own glob falls back to
    # its back draft glob, then the T-pose views glob;
    # config._migrate_outfit_side_routing seeds the chain from the back's.
    "outfit_side_draft": _image(
        "Outfit — side draft", "Figure tab, Dressed views: left/right draft, an edit of the base side view (the "
                               "outfit's reference or the dressed front as a second picture)",
        ["outfit_edit"],
        {"character_scoped": True, "char_spec_field": "outfit_side_draft_workflow",
         "char_spec_fallback": ("outfit_back_draft_workflow", "tpose_view_workflow")},
        hint="An edit of the dressed front in profile; only its clothing is used — composited onto the "
             "base side view on the CPU (no second render). Runs only with the world setting Dressed side views."),
    "scene_view": _image("Rendered scene view", "Player 'Rendered' view",
                         ["scene"], _WORLD, **_PEOPLE),
    "location": _image(
        "Location & room image", "New location, location gallery, room image",
        ["location", "building", "building_outdoor", "room_model",
         "room_model_outdoor"], _WORLD),
    "timevariant": _image("Day/night variant", "Day/night variant convert",
                          ["location"], _WORLD, needs_ref_slot=True),
    "event": _image("Random event image", "Random event illustration",
                    ["event"], _WORLD, **_PEOPLE),
    "prop": _image("Prop source image", "Prop source front/back/side",
                   ["prop", "prop_back", "prop_side"], _WORLD),
    "surface_texture": _image("Surface texture", "Ground/wall surface texture",
                              ["surface_texture"], _WORLD),
    "item": _image("Item image", "Inventory item image", ["item"], _WORLD),
    "regenerate": _image(
        "Gallery regenerate", "Character/Instagram gallery regenerate",
        ["character"], _CHAR, **_PEOPLE),
    "frame": _image("Messaging frame", "Messaging frame product shot", [],
                    _WORLD),
    "video": {"label": "Video (animate)", "media": "video", "category": "render",
              "rig": "", "needs_ref_slot": False, "style_use_cases": [],
              "covers": "Animate dialog, Instagram animate, video skill",
              **_WORLD},
    "mesh_humanoid": _mesh("3D mesh — humanoid", "Character mesh (humanoid)",
                           "none", _CHAR_MESH),
    "mesh_creature": _mesh("3D mesh — creature", "Character mesh (non-humanoid)",
                           "none", _CHAR_MESH),
    "rig_humanoid": {**_mesh("3D rig — humanoid", "Character rig (humanoid)", "mixamo"),
                     "category": "mesh2rig", "requires_chain": True},
    "rig_creature": {**_mesh("3D rig — creature", "Character rig (non-humanoid)", "generic"),
                     "category": "mesh2rig", "requires_chain": True},
    "upscale": {**_image("Upscale — reference image", "Face retexture reference", [], _WORLD),
                "category": "upscale", "requires_chain": False,
                "default_chain": ["Iris-3B-Upscale", "Real-ESRGAN-CPU"]},
    "face_retexture": {**_mesh("Face retexture", "Character face texture correction", "none"),
                       "category": "face_retexture", "requires_chain": False},
    "mesh_object": _mesh("3D mesh — object", "Prop mesh", "none"),
    "mesh_building": _mesh("3D mesh — building", "Building/room mesh", "none"),
    "mesh_garment": _mesh("3D mesh — garment", "Garment meshes (clothing pieces)", "none"),
    # Footwear (plan 2026-11-10-footwear-rigid-shoes): one rigid shoe per item,
    # meshed from the empty-shoe edit of the inventory item image. Both are
    # world-scoped — the source belongs to the item, not to whoever wears it;
    # config._migrate_footwear_routing seeds them from mesh_garment /
    # garment_view once.
    "mesh_footwear": _mesh("3D mesh — footwear", "Wardrobe: shoe from the item image", "none"),
    "footwear_empty": _image("Footwear — empty shoe edit",
                             "Wardrobe: the item image as one empty shoe",
                             ["footwear_source"], _WORLD, needs_ref_slot=True),
    # HairDeck (plan 2026-11-09-hairdeck-hair): hair cards straight from one
    # character image — its own category so no img2mesh occasion ever picks it.
    "hair_mesh": {**_mesh("3D mesh — hair cards", "Hair mode HairDeck", "none",
                          {"character_scoped": True, "char_spec_field": "hair_mesh_workflow",
                           "char_spec_fallback": ""}),
                  "category": "img2hair", "requires_chain": False,
                  "hint": "Hair cards from one image of the character (e.g. HairDeck)."},
    # HAAR (spec 2026-11-13-strand-hair § 6.3.3): hair strands from the
    # hairstyle's text — its own category, a params-only job. Unrouted until
    # an instance adds the backend entry (Ruling H-R6); the hint says how.
    "hair_strands": {**_mesh("3D hair — strands from text", "Hair mode HAAR", "none",
                             {"character_scoped": True, "char_spec_field": "hair_strands_workflow",
                              "char_spec_fallback": ""}),
                     "category": "txt2hair", "requires_chain": False,
                     "hint": ("Hair strands from the hairstyle's text (HAAR). Needs a backend entry "
                              "in Media Generation: type openai_mesh, alias (model) HAAR, category "
                              "txt2hair. One hub job per seed, about 30–55 s each. HAAR is "
                              "licensed CC BY-NC 4.0 (non-commercial).")},
    "pose_animation": {"label": "3D animation — pose clip", "media": "animation",
                       "category": "mesh2anim", "rig": "", "needs_ref_slot": False,
                       "style_use_cases": [], "covers": "Poses tab: generate animation",
                       "requires_chain": True, **_WORLD},
    "pose_transition": {"label": "3D animation — transition clip", "media": "animation",
        "category": "motion2transition", "requires_chain": True,
        "covers": "Poses tab: generate transition", "rig": "",
        "needs_ref_slot": False, "style_use_cases": [], **_WORLD},
}

#: Image occasions whose renders are mesh inputs: the mesh-input matte, the
#: character's tpose_loras and the mesh-part LoRA filter apply
#: (``expression_regen.render_character_image``). The garment edits stay out —
#: the matte trims the image sides and breaks their shared framing.
MESH_INPUT_OCCASIONS: Tuple[str, ...] = (
    "tpose", "tpose_view", "base_front", "base_view",
    "outfit_front", "outfit_back_draft", "outfit_side_draft",
    # Ruling A87: the full-body references the A-pose fronts are edits of —
    # the character's tpose LoRAs as on the front (the user's validated chain
    # ran both steps with the same LoRA); their caller skips the matte.
    "base_reference", "outfit_reference")

#: Image occasions whose negative is NEVER folded into the prompt on a backend
#: without a negative input (review 2026-11-11): the mesh-input renders and the
#: garment / footwear edits carry 230–265-word negatives (``_NEG_TPOSE*`` +
#: ``base_body.BASE_NEGATIVE``), and folding them turned a 27-word edit into
#: 346 words — Venice refused every such request ("prompt is outside the
#: model's text length bounds") and the fallback chain was dead. On these
#: occasions the negative is dropped instead; everything that must hold is
#: positive text at the front of the prompt.
NO_FOLD_OCCASIONS: Tuple[str, ...] = MESH_INPUT_OCCASIONS + ("garment_view", "footwear_empty")

#: Ruling A93: the mesh-input occasions whose SLOT TEXTS are those of an ordinary image — the full-body
#: references are appearance pictures (``app/core/full_body_reference.py``): no mesh-input line is added. Ruling
#: A93b: a slot that declares a ``mesh_part`` names nothing there and its LoRAs are dropped, whether its switch is
#: on or off (``body_slots.filter_appearance_reference_loras``). Everything else of ``MESH_INPUT_OCCASIONS`` (the
#: tpose LoRAs, no negative fold) stays.
APPEARANCE_REFERENCE_OCCASIONS: Tuple[str, ...] = ("base_reference", "outfit_reference")


def mesh_input_text(occasion_id: str) -> bool:
    """Whether a render of this occasion describes the figure as a mesh input (``mesh_input`` of the slot texts
    and of the LoRA filter, Ruling A74a): the mesh-input occasions except ``APPEARANCE_REFERENCE_OCCASIONS``."""
    return occasion_id in MESH_INPUT_OCCASIONS and occasion_id not in APPEARANCE_REFERENCE_OCCASIONS


def folds_negative(occasion_id: str) -> bool:
    """Whether a backend without a negative input folds the negative of
    this occasion into the positive prompt (``""`` / unknown: yes)."""
    return (occasion_id or "").strip() not in NO_FOLD_OCCASIONS


def spec_fields(occ: Dict[str, Any]) -> List[str]:
    """The ``outfit_imagegen`` fields read for an occasion's position 0, in
    order: ``char_spec_field`` (default ``workflow``), then the fallback
    field(s)."""
    fallback = occ.get("char_spec_fallback") or ()
    if isinstance(fallback, str):
        fallback = (fallback,)
    return [occ.get("char_spec_field") or "workflow", *fallback]


MESH_OCCASIONS_BY_RIG: Dict[str, Tuple[str, ...]] = {
    "mixamo": ("mesh_humanoid",),
    "generic": ("mesh_creature",),
    "none": ("mesh_object", "mesh_building"),
}


class UnknownOccasionError(ValueError):
    """An occasion id the catalog does not declare."""


def get_occasion(occasion_id: str) -> Dict[str, Any]:
    occ = OCCASIONS.get(str(occasion_id or "").strip())
    if occ is None:
        raise UnknownOccasionError(f"unknown image occasion '{occasion_id}'")
    return occ


def requires_chain(occasion_id: str) -> bool:
    """Whether this occasion requires an explicitly configured routing chain."""
    return bool(get_occasion(occasion_id).get("requires_chain", False))


def occasion_ids() -> List[str]:
    return list(OCCASIONS.keys())


def backend_fits(occasion_id: str, kind: Dict[str, Any]) -> bool:
    """Whether a backend of this KIND may serve the occasion at all —
    media, category and reference-slot budget; nothing about its
    current availability. ``kind`` is a plain dict (``routing.describe_backend``
    for a live backend, ``routing.describe_config_backend`` for a config
    entry), so the save validator and the admin page share this rule."""
    occ = get_occasion(occasion_id)
    if (kind.get("media") or "image") != occ["media"]:
        return False
    category = str(kind.get("category") or "").lower()
    if occ["media"] in ("mesh", "animation"):
        return category == occ["category"]
    if occ["category"] == "upscale":
        return category == "upscale"
    if category in ("inpaint", "upscale"):
        return False
    if occ.get("needs_ref_slot") and int(kind.get("ref_slot_count") or 0) < 1:
        return False
    return True


def mesh_occasion_for_rig(rig: str, *, building: bool = False) -> str:
    """The mesh occasion a generation of this rig runs on. An empty rig is
    "mixamo" (the character default); a rig the catalog does not know raises
    ``UnknownOccasionError`` — guessing a humanoid chain for it would mesh
    with a skeleton nobody asked for."""
    rig = (rig or "mixamo").strip().lower() or "mixamo"
    if rig not in MESH_OCCASIONS_BY_RIG:
        raise UnknownOccasionError(f"no mesh occasion for rig '{rig}'")
    if rig == "none":
        return "mesh_building" if building else "mesh_object"
    return MESH_OCCASIONS_BY_RIG[rig][0]


def catalog_payload() -> List[Dict[str, Any]]:
    """The catalog for the admin pages, in catalog order."""
    return [{"id": oid, "label": o["label"], "media": o["media"],
             "category": o["category"], "rig": o.get("rig", ""),
             "character_scoped": bool(o["character_scoped"]),
             "needs_ref_slot": bool(o.get("needs_ref_slot")),
             "covers": o.get("covers", ""),
             "pose_check": bool(o.get("pose_check")),
             "hint": o.get("hint", ""),
             "default_chain": list(o.get("default_chain", []))}
            for oid, o in OCCASIONS.items()]
