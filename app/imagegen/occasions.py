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
                      "img2mesh": a mesh backend that is not a mesh2mesh
                      reduction alias.
  rig                 mesh only — "mixamo" | "generic" | "none". A chain entry
                      only resolves to a backend of this rig, so a fallback
                      stays in the rig (a wrong-rig mesh binds unusably).
  character_scoped    True: the character's own backend match
                      (profile.outfit_imagegen.<char_spec_field>) is
                      position 0 in front of the occasion chain.
  char_spec_field     outfit_imagegen field read for position 0.
  char_spec_fallback  read when char_spec_field is empty ("" = none).
  needs_ref_slot      True: only backends with ref_slot_count >= 1.
  style_use_cases     info only — the style use cases these renders use.
  covers              info only — the call sites (admin tooltip).
"""
from typing import Any, Dict, List, Tuple

_CHAR = {"character_scoped": True, "char_spec_field": "workflow",
         "char_spec_fallback": ""}
_WORLD = {"character_scoped": False, "char_spec_field": "",
          "char_spec_fallback": ""}


def _image(label: str, covers: str, style_use_cases: List[str],
           scope: Dict[str, Any], **extra: Any) -> Dict[str, Any]:
    return {"label": label, "media": "image", "category": "render", "rig": "",
            "needs_ref_slot": False, "style_use_cases": style_use_cases,
            "covers": covers, **scope, **extra}


def _mesh(label: str, covers: str, rig: str) -> Dict[str, Any]:
    return {"label": label, "media": "mesh", "category": "img2mesh", "rig": rig,
            "needs_ref_slot": False, "style_use_cases": [], "covers": covers,
            **_WORLD}


OCCASIONS: Dict[str, Dict[str, Any]] = {
    "photo": _image(
        "Photo", "TakePhoto, scene photo button, story image + visualize, "
        "video still", ["character", "story"], _CHAR),
    "instagram": _image("Instagram post", "Instagram post", ["instagram"], _CHAR),
    "profile": _image(
        "Profile portrait", "Character portrait, temporary NPC portrait",
        ["profile"], _CHAR),
    "expression": _image(
        "Expression & outfit variant",
        "Mood/activity variants, wardrobe preview, NPC default variant",
        ["expression", "outfit"], _CHAR),
    "tpose": _image(
        "T-pose & reference views", "Standard pose reference, T-pose + views",
        ["tpose", "tpose_animal", "tpose_back", "tpose_side", "outfit"],
        {"character_scoped": True, "char_spec_field": "tpose_workflow",
         "char_spec_fallback": "workflow"}),
    "scene_view": _image("Rendered scene view", "Player 'Rendered' view",
                         ["scene"], _WORLD),
    "location": _image(
        "Location & room image", "New location, location gallery, room image",
        ["location", "building", "building_outdoor", "room_model",
         "room_model_outdoor"], _WORLD),
    "timevariant": _image("Day/night variant", "Day/night variant convert",
                          ["location"], _WORLD, needs_ref_slot=True),
    "event": _image("Random event image", "Random event illustration",
                    ["event"], _WORLD),
    "prop": _image("Prop source image", "Prop source front/back/side",
                   ["prop", "prop_back", "prop_side"], _WORLD),
    "surface_texture": _image("Surface texture", "Ground/wall surface texture",
                              ["surface_texture"], _WORLD),
    "item": _image("Item image", "Inventory item image", ["item"], _WORLD),
    "regenerate": _image(
        "Gallery regenerate", "Character/Instagram gallery regenerate",
        ["character"], _CHAR),
    "frame": _image("Messaging frame", "Messaging frame product shot", [],
                    _WORLD),
    "video": {"label": "Video (animate)", "media": "video", "category": "render",
              "rig": "", "needs_ref_slot": False, "style_use_cases": [],
              "covers": "Animate dialog, Instagram animate, video skill",
              **_WORLD},
    "mesh_humanoid": _mesh("3D mesh — humanoid", "Character mesh (humanoid)",
                           "mixamo"),
    "mesh_creature": _mesh("3D mesh — creature", "Character mesh (non-humanoid)",
                           "generic"),
    "mesh_object": _mesh("3D mesh — object", "Prop mesh", "none"),
    "mesh_building": _mesh("3D mesh — building", "Building/room mesh", "none"),
}

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


def occasion_ids() -> List[str]:
    return list(OCCASIONS.keys())


def backend_fits(occasion_id: str, kind: Dict[str, Any]) -> bool:
    """Whether a backend of this KIND may serve the occasion at all —
    media, category, rig and reference-slot budget; nothing about its
    current availability. ``kind`` is a plain dict (``routing.describe_backend``
    for a live backend, ``routing.describe_config_backend`` for a config
    entry), so the save validator and the admin page share this rule."""
    occ = get_occasion(occasion_id)
    if (kind.get("media") or "image") != occ["media"]:
        return False
    category = str(kind.get("category") or "").lower()
    if occ["media"] == "mesh":
        if category == "mesh2mesh":
            return False
        return (str(kind.get("rig") or "mixamo").lower() or "mixamo") == occ["rig"]
    if category == "inpaint":
        return False
    if occ.get("needs_ref_slot") and int(kind.get("ref_slot_count") or 0) < 1:
        return False
    return True


def mesh_occasion_for_rig(rig: str, *, building: bool = False) -> str:
    rig = (rig or "mixamo").strip().lower()
    if rig == "none":
        return "mesh_building" if building else "mesh_object"
    return MESH_OCCASIONS_BY_RIG.get(rig, ("mesh_humanoid",))[0]


def catalog_payload() -> List[Dict[str, Any]]:
    """The catalog for the admin pages, in catalog order."""
    return [{"id": oid, "label": o["label"], "media": o["media"],
             "category": o["category"], "rig": o.get("rig", ""),
             "character_scoped": bool(o["character_scoped"]),
             "needs_ref_slot": bool(o.get("needs_ref_slot")),
             "covers": o.get("covers", "")}
            for oid, o in OCCASIONS.items()]
