"""Character reference renders for the 3D pipeline (T-pose + default pose).

After every outfit change (equip/unequip of a piece, outfit switch) a
DEBOUNCED trigger renders two full-body reference images of the character in
the CURRENT outfit: one in T-pose (the input for image->3D/rigging chains)
and one in the default pose. Both live under characters/<name>/model_refs/,
deliberately separate from the expression-variant cache.

Debounce: getting fully dressed equips several pieces in quick succession —
each mutation resets a per-character timer (trailing edge, latest state
wins), so one render pair fires at the end instead of one per piece. The
window and the on/off switch are admin config (image_generation.*), read
fresh on every call. Rendering itself reuses generate_expression_image()
(appearance + current outfit composer, profile-image identity reference,
image queue with per-backend serialization).
"""

import threading
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.log import get_logger

logger = get_logger(__name__)

# Prompt layering: these defaults are PURE POSE — framing, lighting and
# background come from the use-case style ("tpose" / "tpose_animal"), the
# face from the expression layer (REF_EXPRESSION_PROMPT below).
#
# Kept deliberately SHORT — every extra clause dilutes the load-bearing ones.
# What stays is load-bearing:
# - "arms straight out to the sides at shoulder height, forming the letter T":
#   "T-pose" alone is weakly trained in photo models and drifts into an A-pose.
# - Palms face FORWARD toward the camera (user decision 2026-08-31): shows the
#   mesher the most hand detail. Note the trade-off this reverses: the Mixamo
#   bind pose has palms DOWN, and a mesh generated with turned palms can get
#   its hand bones bound 90° off, twisting the hands in animation clips.
# - Fingers HELD TOGETHER (user decision 2026-09-02): the 2D renders measure
#   anatomically correct (hand length 9.2-9.7% of figure height against a
#   10.5-11% norm), yet the meshes come out with oversized hands — a fanned
#   hand is a thin splayed surface the img2mesh bake inflates into a paddle,
#   while a closed hand is one compact block. "fingers overlapping" was
#   dropped from the negative for this; it fought the closed hand.
# - Legs in a WIDE stance, feet wider than the shoulders, open space visible
#   between them: models under-deliver leg separation — "slightly apart" and
#   even "shoulder-width apart" still rendered (especially female) characters
#   with touching ankles, and the mesher then fuses both legs into one column.
#   Asking for wider than needed lands at roughly the needed width.
# - Hair BEHIND the shoulders (length-neutral — the identity layer says how
#   long it is): hair over the chest bakes into the torso geometry.
# The admin override image_generation.tpose_prompt stays untouched — whoever
# replaces this text takes the responsibility with it.
TPOSE_PROMPT_DEFAULT = (
    "T-pose, standing upright facing the camera, arms straight out to the "
    "sides at shoulder height, forming the letter T, palms facing forward "
    "toward the camera, fingers straight and held together, legs spread "
    "apart in a wide "
    "stance, feet planted wider than the shoulders, open space clearly "
    "visible between the legs, hair behind the shoulders"
)

# Non-humanoid characters (animals): a T-pose is meaningless on four legs.
# What the image-to-3D pass needs: a SYMMETRIC stance (the symmetry comes
# from the pose, not the camera — the 3/4 view is there so body length and
# leg spacing stay visible), the head straight ahead in the body's direction
# (a head turned to the camera bakes a twisted neck into the mesh), legs
# clearly apart, the tail set off from the body, and the mouth closed
# (open jaws produce broken head geometry). Framing/background come from the
# "tpose_animal" use-case style, the species description from the identity.
ANIMAL_POSE_PROMPT_DEFAULT = (
    "standing still in a neutral pose on all four legs, three-quarter view, "
    "head facing straight forward in the direction of the body, not looking "
    "at the camera, all four legs straight and clearly apart, tail extended "
    "away from the body, mouth closed"
)

# OPTIONAL extra views of the T-pose reference render (per character, default
# off, humanoid characters only). They exist for multi-view img2mesh backends:
# a single front image leaves the mesher to HALLUCINATE the back of the head,
# the back of the outfit and the body depth — a back view replaces that guess
# with a rendered surface, the two profiles pin the depth.
#
# Like the front pose these are PURE POSE text; framing, lighting and
# background come from the use-case styles ("tpose_back" / "tpose_side").
#
# The back view deliberately carries NO face token (and gets an EMPTY
# expression layer): every facial word pulls a face into the render, and the
# model then turns the character back toward the camera or paints a face onto
# the back of the head. Hair goes in FRONT of the shoulders here for the same
# reason the front view puts it behind them — it must not cover the surface
# the mesher is supposed to read.
TPOSE_BACK_PROMPT_DEFAULT = (
    "back view, seen directly from behind, face not visible, standing upright "
    "in T-pose, arms straight out to the sides at shoulder height, palms "
    "facing away from the camera, fingers straight and held together, legs "
    "spread apart in a wide stance, feet "
    "planted wider than the shoulders, open space clearly visible between "
    "the legs, hair in front of the shoulders"
)

# Both profiles share one text — the side is the only difference, so they
# cannot drift apart. A profile of a T-pose is the hardest view: the arms
# point at and away from the camera, and models resolve that by drawing the
# arms forward or letting them hang ("toward the camera / away from the
# camera" demonstrably was not enough). So the text says what the picture
# actually SHOWS — a strongly foreshortened near arm that hides the far one —
# and the forward/down failure modes are pushed away in _NEG_TPOSE_SIDE.
TPOSE_SIDE_PROMPT_TEMPLATE = (
    "strict {side} side profile view, the whole body in profile facing the "
    "{side} edge of the frame, standing upright in T-pose, arms straight out "
    "to the sides at shoulder height so the near arm points at the camera and "
    "hides the far arm, strongly foreshortened, palms facing forward, fingers "
    "straight and held together, legs spread apart in a wide stance, hair "
    "behind the shoulders"
)
TPOSE_LEFT_PROMPT_DEFAULT = TPOSE_SIDE_PROMPT_TEMPLATE.format(side="left")
TPOSE_RIGHT_PROMPT_DEFAULT = TPOSE_SIDE_PROMPT_TEMPLATE.format(side="right")

TPOSE_VIEW_PROMPT_DEFAULTS = {
    "back": TPOSE_BACK_PROMPT_DEFAULT,
    "left": TPOSE_LEFT_PROMPT_DEFAULT,
    "right": TPOSE_RIGHT_PROMPT_DEFAULT,
}
TPOSE_VIEWS = ("back", "left", "right")
# File kinds of the extra views. They are NOT part of REF_KINDS: there is no
# own auto-toggle, no own UI tile and no own debounce lane for them — they are
# rendered inside the "tpose" pass and stand or fall with it.
VIEW_KINDS = tuple(f"tpose_{v}" for v in TPOSE_VIEWS)
# Framing/lighting/negatives per view. Both profiles share one use case: the
# framing question ("does the arm span fit") is identical for left and right.
TPOSE_VIEW_USE_CASES = {
    "back": "tpose_back",
    "left": "tpose_side",
    "right": "tpose_side",
}

# Expression layer of both reference renders: deliberately neutral (the
# character presets default to expressive looks, which would bake into 3D
# textures). Verbatim expression content, no style fragments.
REF_EXPRESSION_PROMPT = "neutral relaxed facial expression"

REF_KINDS = ("tpose", "pose")
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")

_lock = threading.Lock()
_pending_timers: Dict[str, threading.Timer] = {}
# Serialization and progress tracking are PER (character, kind): the wardrobe
# tab (default pose) and the 3D tab (T-pose) generate independently — with
# several backends the two renders genuinely run in parallel (the same backend
# still serializes in the provider queue). A second trigger for the SAME image
# queues on its lock; the equipped state is read at run time, latest wins.
_char_locks: Dict[tuple, threading.Lock] = {}
# (character, kind) pairs with a render thread currently running. Together with
# a scheduled debounce timer this makes ``pending`` a true per-image
# "generation in progress" signal — the UI polls until it clears instead of
# holding the button for a fixed timeout.
_running: set = set()


def _cfg(key: str, default: Any = None) -> Any:
    from app.core import config
    return config.get(f"image_generation.{key}", default)


def get_tpose_prompt() -> str:
    """T-pose prompt: admin override (image_generation.tpose_prompt) or built-in."""
    override = str(_cfg("tpose_prompt", "") or "").strip()
    return override or TPOSE_PROMPT_DEFAULT


def get_animal_pose_prompt() -> str:
    """Mesh-input pose for NON-humanoid characters: admin override
    (image_generation.animal_pose_prompt) or built-in."""
    override = str(_cfg("animal_pose_prompt", "") or "").strip()
    return override or ANIMAL_POSE_PROMPT_DEFAULT


def get_tpose_view_prompt(view: str) -> str:
    """Pose prompt of one extra T-pose view: admin override
    (image_generation.tpose_<view>_prompt) or built-in."""
    override = str(_cfg(f"tpose_{view}_prompt", "") or "").strip()
    return override or TPOSE_VIEW_PROMPT_DEFAULTS.get(view, "")


def enabled_tpose_views(character_name: str) -> tuple:
    """The extra T-pose views switched on for THIS character (profile field
    ``model_ref_views``), in TPOSE_VIEWS order. All off by default — one extra
    view is one extra render per outfit combination.

    A non-humanoid character never has extra views (a T-pose is meaningless on
    four legs), so the humanoid gate lives HERE and in exactly one place."""
    if not is_humanoid(character_name):
        return ()
    enabled = get_view_kinds(character_name)
    return tuple(v for v in TPOSE_VIEWS if enabled.get(v))


def is_humanoid(character_name: str) -> bool:
    """Template feature flag; unknown characters count as humanoid."""
    try:
        from app.models.character_template import is_feature_enabled
        return bool(is_feature_enabled(character_name, "humanoid"))
    except Exception:
        return True


def _enabled() -> bool:
    val = _cfg("model_ref_renders_enabled", True)
    return bool(True if val is None else val)


def _tpose_size() -> tuple:
    """(width, height) of the T-pose render — square by default. Outstretched
    arms span roughly the body height, so the portrait outfit format crops the
    hands."""
    def _px(key: str, fallback: int) -> int:
        try:
            val = int(_cfg(key, 0) or 0)
        except (TypeError, ValueError):
            val = 0
        return val if val > 0 else fallback
    return _px("tpose_image_width", 1024), _px("tpose_image_height", 1024)


def _debounce_seconds() -> float:
    try:
        val = int(_cfg("model_ref_debounce_seconds", 0) or 0)
    except (TypeError, ValueError):
        val = 0
    return float(val) if val > 0 else 60.0


def get_auto_kinds(character_name: str) -> Dict[str, bool]:
    """Per-character, per-image toggles for the automatic outfit-change
    render (profile field ``model_ref_auto``; missing key = enabled)."""
    from app.models.character import get_character_profile
    try:
        raw = (get_character_profile(character_name) or {}).get("model_ref_auto") or {}
    except Exception:
        raw = {}
    return {k: bool(raw.get(k, True)) for k in REF_KINDS}


def set_auto_kinds(character_name: str, updates: Dict[str, Any]) -> Dict[str, bool]:
    """Merges per-image auto-render toggles into the character profile."""
    from app.models.character import get_character_profile, save_character_profile
    profile = get_character_profile(character_name) or {}
    current = profile.get("model_ref_auto") or {}
    merged = {k: bool(current.get(k, True)) for k in REF_KINDS}
    for key, val in (updates or {}).items():
        if key in REF_KINDS:
            merged[key] = bool(val)
    profile["model_ref_auto"] = merged
    save_character_profile(character_name, profile)
    return merged


def get_view_kinds(character_name: str) -> Dict[str, bool]:
    """Per-character, per-view toggles for the extra T-pose renders that feed
    multi-view img2mesh (profile field ``model_ref_views``; missing key =
    off)."""
    from app.models.character import get_character_profile
    try:
        raw = (get_character_profile(character_name) or {}).get("model_ref_views") or {}
    except Exception:
        raw = {}
    return {k: bool(raw.get(k, False)) for k in TPOSE_VIEWS}


def set_view_kinds(character_name: str, updates: Dict[str, Any]) -> Dict[str, bool]:
    """Merges per-view toggles for the extra T-pose renders into the character
    profile."""
    from app.models.character import get_character_profile, save_character_profile
    profile = get_character_profile(character_name) or {}
    current = profile.get("model_ref_views") or {}
    merged = {k: bool(current.get(k, False)) for k in TPOSE_VIEWS}
    for key, val in (updates or {}).items():
        if key in TPOSE_VIEWS:
            merged[key] = bool(val)
    profile["model_ref_views"] = merged
    save_character_profile(character_name, profile)
    return merged


def get_model_refs_dir(character_name: str) -> Path:
    """Reference-render directory (see get_character_images_dir for the
    base-dir existence gate that avoids ghost dirs on read paths)."""
    from app.models.character import get_character_dir
    base = get_character_dir(character_name)
    refs_dir = base / "model_refs"
    if base.exists():
        refs_dir.mkdir(parents=True, exist_ok=True)
    return refs_dir


#: Separator between the outfit part and the state part of a signature.
#: md5 hex is [0-9a-f] only, so the dash is unambiguous.
STATE_SIG_SEP = "-s"


def state_fingerprint(character_name: str) -> str:
    """8-hex fingerprint of the triggered image-modifier state, "" when no
    ``image_modifier`` directive is active.

    Folded into the outfit signature so a reference render taken while a
    state rewrites the appearance ("neat hair -> messy tousled hair") never
    claims the neutral cache entry — and the neutral render survives the
    state. Directives are sorted, so trigger order does not matter."""
    import hashlib
    try:
        from app.core.prompt_filters import collect_image_modifiers
        replacements, additive = collect_image_modifiers(character_name)
        lines = sorted([f"{a}->{b}" for a, b in replacements] + list(additive))
        if not lines:
            return ""
        return hashlib.md5("\n".join(lines).encode()).hexdigest()[:8]
    except Exception:  # noqa: BLE001
        return ""


def neutral_signature(signature: str) -> str:
    """Outfit-only base of a signature (state suffix stripped, if any)."""
    return (signature or "").split(STATE_SIG_SEP, 1)[0]


def outfit_signature_raw(equipped_pieces: Optional[Dict[str, str]],
                         equipped_items: Optional[list],
                         character_name: str = "") -> str:
    """The RAW string that identifies one worn outfit — what
    :func:`outfit_signature` hashes, and the ONE description of "the same
    outfit combination" in this codebase.

    The stably sorted equipped state
    (``expression_regen._equipped_signature``). When NOTHING structured is
    worn the character can still be dressed: a template without an outfit
    system (a temporary NPC) renders the profile's free-text
    ``outfit_description``, so that text has to identify the outfit too —
    otherwise every such character in the world shares one signature and the
    first one's T-pose render and mesh get served to all of them.

    The free-text branch returns ``render_outfit(...)["full"]``, EXACTLY what
    the image prompt is built from: "" for an undressed character
    (``outfit_worn`` false) and "" when no text is set, so the bare case
    keeps its historical empty string and no cache entry of a wardrobe
    character moves.

    Public because the expression-variant cache keys on the same rule
    (``expression_regen._cache_key``) — it hashes this string TOGETHER with
    its own two catalog axes, so it needs the string and not a hash of it.
    """
    from app.core.expression_regen import _equipped_signature
    raw = _equipped_signature(equipped_pieces, equipped_items)
    if not raw and character_name:
        try:
            from app.core.outfit_renderer import render_outfit
            raw = render_outfit(character_name=character_name,
                                equipped_pieces={},
                                equipped_items=[]).get("full", "") or ""
        except Exception:  # noqa: BLE001 — an unreadable profile must not
            raw = ""       # break signing; the bare key still renders
    return raw


def outfit_signature(equipped_pieces: Optional[Dict[str, str]],
                     equipped_items: Optional[list],
                     character_name: str = "") -> str:
    """The 12-hex outfit key of the per-outfit render caches — the ONE rule
    both caches (``model_refs/``, ``model3d/``) and the cache GC judge an
    entry by.

    md5[:12] of :func:`outfit_signature_raw`, and nothing else: the bare case
    keeps its historical md5("") key.
    """
    import hashlib
    raw = outfit_signature_raw(equipped_pieces, equipped_items, character_name)
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def current_outfit_state(character_name: str) -> tuple:
    """(equipped_pieces, equipped_items, signature) of the CURRENT worn
    state. The signature comes from ``outfit_signature`` — the equipped
    state, or the free-text outfit when nothing structured is worn — so both
    caches agree on what counts as "the same outfit combination". Public:
    the per-outfit mesh store (app/core/model3d.py) keys on the same
    signature.

    With active image-modifier states the signature carries a state suffix
    (``<base>-s<fp>``); the neutral state keeps the bare base hash, so
    existing cache entries and the outfit batch's pre-warmed (always
    neutral) combinations stay valid."""
    from app.models.inventory import get_equipped_pieces, get_equipped_items
    pieces = get_equipped_pieces(character_name)
    items = get_equipped_items(character_name)
    sig = outfit_signature(pieces, items, character_name)
    state = state_fingerprint(character_name)
    if state:
        sig = f"{sig}{STATE_SIG_SEP}{state}"
    return pieces, items, sig


def find_ref_image(character_name: str, kind: str,
                   signature: Optional[str] = None) -> Optional[Path]:
    """Path of the stored render of this kind for the given outfit
    combination (default: the currently worn one), or None.

    ``signature=None`` means "what should be shown right now" and falls
    back to the neutral entry of the same outfit when the state variant is
    not rendered yet. An EXPLICIT signature is matched exactly — the
    generation skip-check must not mistake the neutral render for the
    state variant it is about to produce."""
    if kind not in REF_KINDS and kind not in VIEW_KINDS:
        return None
    candidates = [signature]
    if signature is None:
        try:
            _, _, sig = current_outfit_state(character_name)
        except Exception:
            return None
        candidates = list(dict.fromkeys([sig, neutral_signature(sig)]))
    from app.models.character import get_character_dir
    refs_dir = get_character_dir(character_name) / "model_refs"
    for sig in candidates:
        for ext in _IMAGE_EXTS:
            p = refs_dir / f"{kind}_{sig}{ext}"
            if p.exists():
                return p
    return None


def _cleanup_legacy(refs_dir: Path, kind: str) -> None:
    """Drops leftovers of the retired fixed-name scheme ({kind}.ext). The
    per-combination cache itself is NOT pruned — its size is naturally
    bounded by the number of outfit combinations actually worn."""
    for ext in _IMAGE_EXTS + (".json",):
        legacy = refs_dir / f"{kind}{ext}"
        if legacy.exists():
            legacy.unlink()


def _ref_info(path: Optional[Path]) -> Optional[Dict[str, Any]]:
    """UI info for one stored render: filename plus what its sidecar knows."""
    import json
    if not path:
        return None
    info: Dict[str, Any] = {"filename": path.name}
    meta_path = path.with_suffix(".json")
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            info["created_at"] = meta.get("created_at", "")
            info["prompt"] = meta.get("prompt", "")
            info["backend"] = meta.get("service", "")
        except (OSError, ValueError):
            pass
    return info


def get_model_refs_info(character_name: str) -> Dict[str, Any]:
    """Per-kind info for the UI — always for the CURRENTLY worn outfit
    combination (filename + sidecar meta, or None if not rendered yet).

    ``views`` carries ALL extra T-pose views of a humanoid character (empty
    for a non-humanoid one) as ``{"enabled": bool, "info": <info|None>}``: the
    UI needs every view to render its checkbox, the switched-off ones
    included. The views have no own pending lane — they ride with "tpose"."""
    try:
        _, _, signature = current_outfit_state(character_name)
    except Exception:
        signature = ""
    out: Dict[str, Any] = {"signature": signature}
    for kind in REF_KINDS:
        path = find_ref_image(character_name, kind, signature) if signature else None
        out[kind] = _ref_info(path)
    views: Dict[str, Any] = {}
    if is_humanoid(character_name):
        enabled = set(enabled_tpose_views(character_name))
        for view in TPOSE_VIEWS:
            path = (find_ref_image(character_name, f"tpose_{view}", signature)
                    if signature else None)
            views[view] = {"enabled": view in enabled, "info": _ref_info(path)}
    out["views"] = views
    auto = get_auto_kinds(character_name)
    out["auto"] = auto
    # Pending PER KIND: a running render of one image must not lock the other
    # tab's button. A scheduled debounce timer counts for exactly the kinds it
    # will render (the auto-checked ones).
    with _lock:
        timer_scheduled = character_name in _pending_timers
        out["pending"] = {
            kind: ((character_name, kind) in _running
                   or (timer_scheduled and auto.get(kind, True)))
            for kind in REF_KINDS
        }
    return out


def generate_model_ref_images(character_name: str,
                              kinds: Optional[tuple] = None,
                              force: bool = False, *,
                              pieces: Optional[Dict[str, str]] = None,
                              items: Optional[list] = None,
                              signature: Optional[str] = None
                              ) -> Dict[str, Optional[str]]:
    """Render the reference images sequentially (the image queue serializes
    per backend anyway). Blocking — call from a worker thread.

    Cached per outfit combination: kinds whose render for the CURRENT
    combination already exists are skipped unless ``force`` — switching
    back to a known outfit costs no GPU run. ``kinds`` None = exactly what
    the automatic outfit-change trigger would render (per-character
    toggles).

    ``pieces``/``items``/``signature`` render a GIVEN combination instead of
    the worn one (the outfit batch pre-warms combinations without dressing
    the character). All three or none — a partial override would key the
    cache on a signature that does not describe the rendered pieces.
    Everything downstream (cache skip, output stem, prompt chain) is
    identical, so an overridden run is indistinguishable from a worn one.

    The "tpose" kind additionally renders the extra views switched on for
    this character (back/left/right, humanoid characters only) as
    ``tpose_<view>_<signature>``: input for multi-view img2mesh backends.
    They ride along with the front render — the kind counts as cached only
    once every enabled view exists too, and an already rendered front image
    is then reused instead of being generated again. A failing view is
    logged and skipped; only the front render is essential."""
    from app.core.expression_regen import generate_expression_image
    from app.core.expression_pose_maps import default_pose_prompt

    override = (pieces, items, signature)
    if any(o is not None for o in override) and any(o is None for o in override):
        raise ValueError(
            "generate_model_ref_images: pieces, items and signature must be "
            "given together (or none of them)")
    # Pre-warm runs (explicit signature) render the NEUTRAL look — their
    # signature carries no state fingerprint, so the image must not either.
    # Worn-state runs apply the modifiers; current_outfit_state keys them
    # into the matching state-suffixed cache entry.
    prewarm = signature is not None

    if kinds is None:
        auto = get_auto_kinds(character_name)
        kinds = tuple(k for k in REF_KINDS if auto.get(k))
    else:
        kinds = tuple(k for k in kinds if k in REF_KINDS)
    if not kinds:
        return {}

    if signature is None:
        pieces, items, signature = current_outfit_state(character_name)
    # Non-humanoid characters get their own mesh-input pose (a T-pose makes no
    # sense on four legs) and their own framing use case. Their default-pose
    # ref carries NO human pose template either — the empty override lets the
    # renderer fall back to the animal's own anatomy. Read BEFORE the cache
    # skip: it decides whether the extra views count into it.
    humanoid = is_humanoid(character_name)
    views = enabled_tpose_views(character_name)
    if not force:
        cached = tuple(k for k in kinds
                       if find_ref_image(character_name, k, signature)
                       and (k != "tpose"
                            or all(find_ref_image(character_name,
                                                  f"tpose_{v}", signature)
                                   for v in views)))
        if cached:
            logger.info("Model-Refs fuer %s: Kombination %s bereits gerendert (%s)",
                        character_name, signature, ", ".join(cached))
        kinds = tuple(k for k in kinds if k not in cached)
    if not kinds:
        return {}

    refs_dir = get_model_refs_dir(character_name)
    prompts = {
        "tpose": get_tpose_prompt() if humanoid else get_animal_pose_prompt(),
        "pose": default_pose_prompt() if humanoid else "",
    }
    results: Dict[str, Optional[str]] = {}

    # No own task tracking here: the image service tracks every render as its
    # own queue task already — a wrapper would show a SECOND header task for
    # one image. Progress for the UI comes from the per-kind pending signal.
    try:
        for kind in kinds:
            # T-pose: the pose leads the prompt (prompt_prefix) instead of
            # trailing a long outfit description — trailing pose text gets
            # too little weight and the render drifts into an A-pose. The
            # default-pose ref keeps the canonical content order.
            _tpose = kind == "tpose"
            _w, _h = _tpose_size() if _tpose else (None, None)
            # A kind only reaches this loop when something is missing — for
            # "tpose" that may be an extra view alone, and then the existing
            # front render is reused instead of burning a second GPU run.
            path: Optional[Path] = (
                None if force else find_ref_image(character_name, kind, signature))
            if path is None:
                path = generate_expression_image(
                    character_name, mood="", pose_key="",
                    equipped_pieces=pieces, equipped_items=items,
                    prompt_prefix=prompts[kind] if _tpose else "",
                    pose_prompt_override="" if _tpose else prompts[kind],
                    expression_prompt_override=REF_EXPRESSION_PROMPT,
                    # The mesh-input render has its own style (flat shadowless
                    # light, full-body framing) — humanoid vs animal framing
                    # differ; the default-pose ref shares "outfit".
                    image_use_case=("tpose" if humanoid else "tpose_animal") if _tpose else "outfit",
                    # ... and its own aspect: the portrait outfit format cuts the
                    # outstretched hands off at the edges.
                    override_width=_w, override_height=_h,
                    output_stem=refs_dir / f"{kind}_{signature}",
                    apply_state_modifiers=not prewarm)
            results[kind] = str(path) if path else None
            if path is None:
                logger.warning("Model-Ref %s fuer %s (%s): Render fehlgeschlagen",
                               kind, character_name, signature)
            else:
                _cleanup_legacy(refs_dir, kind)
            # Extra views for multi-view img2mesh — same outfit, same size,
            # same signature, only the pose/use-case layer differs. Missing
            # views are never fatal: the mesh runs off the front render.
            if _tpose and humanoid and path is not None:
                for view in views:
                    view_kind = f"tpose_{view}"
                    if not force and find_ref_image(character_name, view_kind,
                                                    signature):
                        continue
                    try:
                        view_path = generate_expression_image(
                            character_name, mood="", pose_key="",
                            equipped_pieces=pieces, equipped_items=items,
                            prompt_prefix=get_tpose_view_prompt(view),
                            pose_prompt_override="",
                            # No face is visible from behind — an expression
                            # layer there only tempts the model to turn the
                            # character around or paint a face on the back.
                            expression_prompt_override=(
                                "" if view == "back" else REF_EXPRESSION_PROMPT),
                            image_use_case=TPOSE_VIEW_USE_CASES[view],
                            override_width=_w, override_height=_h,
                            output_stem=refs_dir / f"{view_kind}_{signature}",
                            apply_state_modifiers=not prewarm,
                            # Nothing uncovered is visible from behind, so
                            # the exposed body-slot fragments (and the
                            # LoRAs bound to them) are dropped for this
                            # view: they describe the FRONT and drag the
                            # figure around toward the camera, which is
                            # exactly what this view must not do.
                            include_exposed=view != "back")
                    except Exception as e:
                        view_path = None
                        logger.warning(
                            "Model-Ref %s fuer %s (%s) fehlgeschlagen: %s",
                            view_kind, character_name, signature, e)
                    results[view_kind] = str(view_path) if view_path else None
                    if view_path is None:
                        logger.warning(
                            "Model-Ref %s fuer %s (%s): Render fehlgeschlagen",
                            view_kind, character_name, signature)
    finally:
        logger.info("Model-Refs fuer %s (%s): %s", character_name, signature,
                    {k: bool(v) for k, v in results.items()})
    return results


def _kind_lock(key: tuple) -> threading.Lock:
    with _lock:
        return _char_locks.setdefault(key, threading.Lock())


def _run_generation(character_name: str, kind: str, force: bool = False) -> None:
    # Serial per (character, kind); the equipped state is read at run time,
    # so the latest outfit always wins.
    key = (character_name, kind)
    with _lock:
        _running.add(key)
    try:
        with _kind_lock(key):
            generate_model_ref_images(character_name, kinds=(kind,), force=force)
    except Exception as e:
        logger.error("Model-Ref-Render fuer %s (%s) fehlgeschlagen: %s",
                     character_name, kind, e)
    finally:
        with _lock:
            _running.discard(key)
    # Auto-mesh (opt-in per character): ONLY after the T-pose pass, and the
    # hook itself verifies the T-pose file exists for the current
    # combination — a mesh run never starts before its input succeeded.
    # Spawns its own worker; the tpose kind lock is released here.
    if kind == "tpose":
        try:
            from app.core.model3d import maybe_auto_generate_for_outfit
            maybe_auto_generate_for_outfit(character_name)
        except Exception as e:
            logger.debug("Model3D-Auto-Hook fuer %s fehlgeschlagen: %s",
                         character_name, e)


def _fire_kinds(character_name: str, kinds: tuple, force: bool = False) -> None:
    """One worker thread per kind: the images generate independently — with
    several backends they run in parallel; the same backend serializes in the
    provider queue."""
    for kind in kinds:
        threading.Thread(target=_run_generation,
                         args=[character_name, kind, force],
                         daemon=True).start()


def _fire(character_name: str) -> None:
    with _lock:
        _pending_timers.pop(character_name, None)
    auto = get_auto_kinds(character_name)
    _fire_kinds(character_name,
                tuple(k for k in REF_KINDS if auto.get(k)))


def schedule_outfit_render(character_name: str) -> None:
    """Debounced trigger after an outfit mutation (trailing edge, latest
    state wins). No-op when disabled in config or when every per-image
    toggle of this character is off."""
    if not _enabled():
        return
    if not any(get_auto_kinds(character_name).values()):
        return
    delay = _debounce_seconds()
    with _lock:
        old = _pending_timers.pop(character_name, None)
        if old:
            old.cancel()
        timer = threading.Timer(delay, _fire, args=[character_name])
        timer.daemon = True
        _pending_timers[character_name] = timer
        timer.start()


def trigger_now(character_name: str, kinds: Optional[tuple] = None) -> None:
    """Manual trigger (UI button): fires the render immediately — no debounce,
    force=True so a fresh render replaces the cached one of the current
    combination. ``kinds`` narrows to specific images (each tab passes its
    own, so wardrobe and 3D generate independently); None = the per-image
    auto toggles decide, like the automatic trigger."""
    auto = get_auto_kinds(character_name)
    auto_kinds = tuple(k for k in REF_KINDS if auto.get(k))
    if kinds is None:
        kinds = auto_kinds
    else:
        kinds = tuple(k for k in kinds if k in REF_KINDS)
    if not kinds:
        return
    # A pending debounce timer would re-render the auto kinds right after the
    # manual run — only cancel it when this trigger covers those kinds anyway.
    if set(auto_kinds).issubset(set(kinds)):
        with _lock:
            old = _pending_timers.pop(character_name, None)
            if old:
                old.cancel()
    _fire_kinds(character_name, kinds, force=True)
