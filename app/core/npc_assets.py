"""The finish gate for temporary NPCs: no face, no mesh, no world.

plan-npc-leben § 0 A. A temporary NPC used to appear on the map the moment its
character sheet existed — a nameplate with no portrait, no 3D figure and, often
enough, no outfit text for the image prompts to work from. This module is the
ONE place that decides whether an NPC is finished, plus the queue job that
finishes it.

Four criteria, and every one of them is checked at the CONSUMER (see
feedback_pruefe_am_verbraucher — a profile field that says "face.png" proves
nothing, the file behind it does):

* ``profile_image`` — the profile field is set AND the file is on disk;
* ``model3d`` — a mesh exists for the EXACTLY worn outfit signature
  (``find_model3d(name, current_outfit_state(name)[2])``, never the serving
  lookup: that one falls back to other outfits and would call a foreign mesh
  "done");
* ``outfit_description`` — the free text that IS this character's wardrobe;
* ``expression`` — the DEFAULT expression variant (mood "", pose "") for the
  worn outfit is in the variant cache. That single image is what the 2D
  client shows for this NPC: its template sets
  ``expression_variants_enabled: false``, so no other trigger will ever
  render one, and the profile image is deliberately not a fallback.

The flow: ``npc_ops.apply_npc`` and ``npc_pool.revive_from_pool`` ask
:func:`gate_placement` before they place. When it holds the NPC back, the
character stays ``status='pooled'`` — out of every roster, payload and earshot
list — and ONE ``npc_assets`` job is queued. The handler produces only what is
missing (so a partial failure resumes instead of starting over), re-checks the
gate and does the placement itself. The gate is switchable
(``npc.require_assets``) and template-bound (``temporary_npc``): the ordinary
cast never passes through it.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.core.log import get_logger

logger = get_logger("npc_assets")

#: Queue task type of one finishing job. One job = one NPC.
TASK_TYPE = "npc_assets"

#: The finish criteria, in the order :func:`npc_assets_complete` reports them.
CRITERIA = ("profile_image", "model3d", "outfit_description", "expression")

#: Retries of ONE finishing job. The queue's own default is 0, and this job is
#: the only thing that ever places the NPC — see :func:`submit_assets_job`.
ASSET_RETRIES = 2


def require_assets() -> bool:
    """Whether the gate is armed (config ``npc.require_assets``, default on)."""
    from app.core import config
    value = config.get("npc.require_assets", None)
    return True if value in (None, "") else bool(value)


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------

def npc_assets_complete(name: str) -> List[str]:
    """What this NPC is still MISSING, as criterion slugs. Empty = finished."""
    from app.models.character import (get_character_images_dir,
                                      get_character_profile,
                                      get_character_profile_image)
    if not name:
        return list(CRITERIA)

    missing: List[str] = []

    image = (get_character_profile_image(name) or "").strip()
    if not image or not (get_character_images_dir(name) / image).exists():
        missing.append("profile_image")

    try:
        from app.core.model3d import find_model3d
        from app.core.model_refs import current_outfit_state
        signature = current_outfit_state(name)[2]
        if not find_model3d(name, signature):
            missing.append("model3d")
    except Exception as e:  # noqa: BLE001 — an unreadable state is "not done"
        logger.debug("npc_assets_complete(%s): mesh lookup failed: %s", name, e)
        missing.append("model3d")

    profile = get_character_profile(name) or {}
    if not str(profile.get("outfit_description") or "").strip():
        missing.append("outfit_description")

    try:
        from app.core.expression_regen import peek_cached_expression
        from app.core.model_refs import current_outfit_state
        pieces, items, _sig = current_outfit_state(name)
        # PEEK, not get: a gate check must not forge the variant's LRU
        # bookkeeping (``get_cached_expression`` bumps last_used_at).
        if peek_cached_expression(name, "", "", equipped_pieces=pieces,
                                  equipped_items=items) is None:
            missing.append("expression")
    except Exception as e:  # noqa: BLE001 — an unreadable cache is "not done"
        logger.debug("npc_assets_complete(%s): variant lookup failed: %s",
                     name, e)
        missing.append("expression")

    return missing


def is_awaiting_assets(name: str) -> bool:
    """True while a queued ``npc_assets`` job still owes this NPC a placement.

    A held-back NPC sits in the pool, so without this question every spawn
    could claim it a SECOND time: the pending job carries the first claim's
    location, `submit` deduplicates the second one away, and the second
    claimer counts a slot filled that stays empty. The state lives in the
    QUEUE, not on the profile, so it heals itself — once the job is gone (done
    or finally failed) the NPC is ordinary pool stock again and the next claim
    queues a fresh job.
    """
    from app.core.task_queue import get_task_queue
    if not name:
        return False
    return get_task_queue().has_pending_task(TASK_TYPE, name)


def list_awaiting_assets() -> List[str]:
    """The pooled NPCs a queued job still owes a placement.

    They are neither in the world nor free pool stock, which is exactly why
    the spawn caps have to count them (``npc_spawn.alive_npc_count``): an NPC
    whose portrait is still rendering is already paid for.
    """
    from app.models.character import list_pooled_characters
    return [n for n in list_pooled_characters() if is_awaiting_assets(n)]


def submit_assets_job(name: str, location_id: str, room_id: str = "",
                      wanderer: bool = False, wander_target: str = "",
                      radius_m: float = 0) -> str:
    """Queue the finishing job for one NPC. Returns the task id ("" = deduped).

    Deduplicated per character: a second placement attempt for an NPC that is
    already being finished must not start a second run of the same three
    generations.

    ``radius_m`` rides along for the same reason the road does: the job is
    what places this NPC, and whether it belongs into a room or somewhere
    around the place is the SLOT's decision, made before the gate ran.

    ``max_retries`` is set EXPLICITLY, because the queue's own default is 0
    (``task_queue.MAX_RETRIES_DEFAULT``) and this job is the only thing that
    will ever place the NPC. A `+ New NPC` NPC has no slot that would notice
    and re-queue it: after one transient backend outage it would sit in the
    pool until some wanderer spawn takes it as "any pooled NPC" and revives
    it at a random origin — the admin's placement silently lost.
    """
    from app.core.task_queue import get_task_queue
    return get_task_queue().submit(
        TASK_TYPE,
        {"name": name, "location_id": location_id, "room_id": room_id,
         "wanderer": bool(wanderer), "wander_target": wander_target or "",
         "radius_m": float(radius_m or 0)},
        queue_name="background", agent_name=name, max_retries=ASSET_RETRIES,
        deduplicate=True)


def on_outfit_description_changed(name: str, old: str, new: str) -> Optional[str]:
    """Re-queue the finishing job after a temporary NPC was re-dressed.

    The outfit text IS this NPC's wardrobe (its template has no outfit
    system), and every asset the gate demands is keyed by it: the portrait
    prompt, the T-pose render, the mesh signature
    (``model_refs.outfit_signature``) and the default expression variant
    (``expression_regen._cache_key``). So an edit orphans all of them at once
    and the NPC has to be finished again — otherwise it keeps wearing the old
    clothes in every picture until somebody pools and revives it.

    Called from the ONE choke point every editing path runs through
    (``character.save_character_profile``). Returns the task id, or None when
    nothing was queued. Four conditions, and each of them says no for a
    different reason:

    * not a temporary NPC — a full character's wardrobe is the structured
      outfit system; this text is not what dresses it;
    * ``status != ''`` — a POOLED NPC belongs to :func:`gate_placement`,
      whose job carries the placement the pool return decided on; a job
      queued here would race it with a stale location;
    * :func:`is_awaiting_assets` — a pending job renders the CURRENT state,
      not the state its payload was written for, so the next edit rides along
      in it instead of starting a second run of the same generations;
    * the text did not really change — a profile save that leaves the
      wardrobe alone is not a re-dressing.

    The NPC is deliberately NOT pooled: it keeps standing where it stands and
    wears the old mesh (``find_model3d_serving`` falls back to the nearest
    outfit) until the new assets exist. That is what ``_place``'s pooled guard
    is for. The orphans under the old signature are ``outfit_cache_gc``'s.
    """
    if not name:
        return None
    if (old or "").strip() == (new or "").strip():
        return None
    from app.models.character import (get_character_current_location,
                                      get_character_current_room,
                                      get_character_status, is_temporary_npc)
    if not is_temporary_npc(name):
        return None
    if get_character_status(name) != "":
        return None
    if is_awaiting_assets(name):
        logger.debug("npc_assets(%s): outfit edit rides along in the pending "
                     "job", name)
        return None
    task_id = submit_assets_job(name, get_character_current_location(name) or "",
                                get_character_current_room(name) or "")
    logger.info("NPC '%s' was re-dressed — assets re-queued (job %s)", name,
                task_id or "(already queued)")
    return task_id or None


def gate_placement(name: str, location_id: str, room_id: str = "",
                   wanderer: bool = False, wander_target: str = "",
                   radius_m: float = 0) -> bool:
    """True when the NPC must NOT be placed yet — pooled, and the job queued.

    False means "place it, exactly as before": the gate is off, the character
    is not a temporary NPC, or it is already finished. The side effects
    (pooling + submit) happen only on the True branch, so a caller can treat
    this as one decision.
    """
    from app.models.character import (POOLED_STATUS, get_character_profile,
                                      is_temporary_npc, save_character_profile,
                                      set_character_status)
    if not name or not require_assets() or not is_temporary_npc(name):
        return False
    missing = npc_assets_complete(name)
    if not missing:
        return False

    # The Game-Admin pool list renders this reason — without it a held-back
    # NPC would sit in the pool as a blank row nobody can explain.
    profile = get_character_profile(name) or {}
    profile["npc_pooled_reason"] = "waiting for " + ", ".join(missing)
    save_character_profile(name, profile)
    set_character_status(name, POOLED_STATUS)
    task_id = submit_assets_job(name, location_id, room_id, wanderer,
                                wander_target, radius_m)
    logger.info("NPC '%s' held back for %s — job %s", name,
                ", ".join(missing), task_id or "(already queued)")
    return True


# ---------------------------------------------------------------------------
# The producers
# ---------------------------------------------------------------------------

def _delivered_image(result: str) -> bool:
    """Whether the image service's answer describes a picture that exists.

    NEITHER PRODUCER RAISES. The service reports every failure as PROSE —
    "Error: backend … not available", "Fehler: Keine Instanz … (Timeout)" —
    and a cache hit as the ``NO_NEW_IMAGE`` sentinel; a delivered render
    always names a file path. So a path-shaped answer is the only "yes", and
    everything else is worth a WARNING with the text in it.
    """
    text = (result or "").strip()
    if not text or "NO_NEW_IMAGE" in text:
        return False
    if text.lower().startswith(("error", "fehler")):
        return False
    return "/" in text


def _render_profile_image(name: str) -> str:
    """Render the NPC's portrait through the ordinary image service.

    Returns what went WRONG ("" = the service delivered), so the caller can
    carry the service's own words into the job's error — the queue panel
    shows the exception and nothing else.

    The same request the profile-image route sends (``character_ops.
    generate_profile_image_core``): the FACE prompt, the ``profile`` use-case
    for the style, ``set_profile`` so the service files it as the portrait
    itself, ``auto_enhance`` off because the face prompt IS the finished
    prompt, and the SAME render target — ``resolve_profile_imagegen`` is the
    one chain both callers ask, so an NPC portrait lands on the configured
    backend instead of whatever the pool happens to pick. Blocking — this runs
    in a queue worker.
    """
    from app.core.character_ops import (_resolve_face_prompt,
                                        resolve_profile_imagegen)
    from app.imagegen.service import get_image_service
    from app.models.character import get_character_profile
    from app.models.character_template import get_template

    profile = get_character_profile(name) or {}
    template = profile.get("template") or ""
    prompt = _resolve_face_prompt(profile, name,
                                  get_template(template) if template else None)
    target = resolve_profile_imagegen(profile)
    result = str(get_image_service().generate_from_input(json.dumps({
        "prompt": prompt,
        "agent_name": name,
        "auto_enhance": False,
        "set_profile": True,
        "image_use_case": "profile",
        "workflow": target["workflow"],
        "backend": target["backend"],
    })) or "")
    if _delivered_image(result):
        logger.debug("npc_assets(%s): profile render said %s", name,
                     result[:200])
        return ""
    logger.warning("npc_assets(%s): the profile render delivered no image: %s",
                   name, result[:200] or "(nothing at all)")
    return result[:200] or "the image service answered nothing"


def _render_mesh(name: str) -> str:
    """T-pose reference, then the mesh for the worn outfit. Blocking.

    Returns what went WRONG ("" = both were happy). ``generate_for_current_
    outfit`` reports a failure as ``{"ok": False, "error": …}`` instead of
    raising, and that text is the only thing that says WHY there is no mesh —
    discarding it leaves a job whose error reads "still incomplete: model3d"
    and explains nothing.
    """
    from app.core.model3d import generate_for_current_outfit
    from app.core.model_refs import generate_model_ref_images

    notes: List[str] = []
    refs = generate_model_ref_images(name, kinds=("tpose",)) or {}
    if not refs.get("tpose"):
        logger.warning("npc_assets(%s): no T-pose reference was rendered — "
                       "the mesh has no input", name)
        notes.append("T-pose: no reference render")
    result = generate_for_current_outfit(name) or {}
    if not result.get("ok"):
        error = str(result.get("error") or "mesh generation failed")
        logger.warning("npc_assets(%s): the mesh producer said %s", name, error)
        notes.append(f"mesh: {error}")
    return "; ".join(notes)[:200]


def _render_default_expression(name: str) -> str:
    """Render the ONE expression variant this NPC is shown by. Blocking.

    Returns what went WRONG ("" = the variant exists), same contract as the
    other producers — ``generate_expression_image`` swallows every failure
    and answers None, so the complaint has to be worded here.

    The BLOCKING call, never ``trigger_expression_generation``: that one runs
    a daemon thread (this is already a queue worker, so the job would report
    success while nothing had been rendered) and, more importantly, it asks
    the ``expression_variants_enabled`` feature gate — which this NPC's
    template switches off. Going through the generator directly is what keeps
    the gate closed for every OTHER trigger: no mood, no pose, no grid, one
    picture.

    Mood "" and pose "" are the DEFAULT coordinates: they resolve to the
    catalog defaults for both axes and produce exactly the file the route's
    default-variant fallback looks for
    (``routes/characters.py`` → ``get_cached_expression(name, "", "", …)``).
    """
    from app.core.expression_regen import generate_expression_image
    from app.core.model_refs import current_outfit_state

    pieces, items, _sig = current_outfit_state(name)
    path = generate_expression_image(name, "", "", equipped_pieces=pieces,
                                     equipped_items=items)
    if path is not None:
        logger.debug("npc_assets(%s): default variant at %s", name, path)
        return ""
    logger.warning("npc_assets(%s): the default expression variant was not "
                   "rendered", name)
    return "the generator delivered no variant"


# ---------------------------------------------------------------------------
# The job
# ---------------------------------------------------------------------------

def _place(name: str, location_id: str, room_id: str,
           radius_m: float = 0) -> None:
    """Put the finished NPC into the world — the order of ``revive_from_pool``.

    Back into the roster BEFORE the placement: the location setter runs the
    ordinary arrival side effects, and those read the roster.

    A NO-OP for an NPC that is not pooled. The job is re-queued whenever a
    temporary NPC's outfit text is edited, and that NPC is standing in the
    world at the time — placing it again would drag it back to wherever the
    ORIGINAL job was headed, hours of world time later.

    ``radius_m`` is the slot's home area, carried in the payload: the same
    helper decides room-or-point for all three placement paths.
    """
    from app.core.npc_home import place_npc
    from app.models.character import (POOLED_STATUS, get_character_profile,
                                      get_character_status,
                                      save_character_profile,
                                      set_character_status)
    if get_character_status(name) != POOLED_STATUS:
        logger.debug("npc_assets(%s): already in the world — not placed again",
                     name)
        return
    profile = get_character_profile(name) or {}
    if profile.pop("npc_pooled_reason", None) is not None:
        save_character_profile(name, profile)   # it is not waiting any more
    set_character_status(name, "")
    if location_id:
        place_npc(name, location_id, room_id, radius_m)


def _handle_npc_assets(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Produce the missing assets of one NPC, then place it.

    Runs in a task-queue worker: blocking image/mesh generation belongs here,
    and an exception is the queue's own retry signal.
    """
    from app.models.character import get_character_profile, is_temporary_npc

    name = str(payload.get("name") or "").strip()
    if not name or not is_temporary_npc(name):
        return {"ok": False, "error": "not a temporary NPC", "name": name}

    location_id = str(payload.get("location_id") or "")
    room_id = str(payload.get("room_id") or "")
    profile = get_character_profile(name) or {}
    wanderer = bool(payload.get("wanderer") or profile.get("npc_wanderer"))
    # The PAYLOAD carries the road. Both placement paths stamp the route onto
    # the profile before they ask the gate, so the job that the gate queues
    # already knows where this wanderer was headed — no worker can pick it up
    # in a window where the target is not written yet.
    wander_target = str(payload.get("wander_target") or "").strip()
    try:
        radius_m = float(payload.get("radius_m") or 0)
    except (TypeError, ValueError):
        radius_m = 0.0

    missing = npc_assets_complete(name)
    if "outfit_description" in missing:
        # Nothing here can produce prose. The field is `required` in the NPC
        # template, so the generation/repair turn is what fills it — retrying
        # this job would only burn GPU time on the other two.
        logger.error("NPC '%s' has no outfit_description — cannot be finished",
                     name)
        return {"ok": False, "name": name, "missing": missing}

    # Only what is actually missing: a job that comes back after a partial
    # failure resumes instead of re-rendering what already exists.
    # The producers' own complaints are COLLECTED, because neither of them
    # raises — the error the queue panel shows is built from them below.
    notes: List[str] = []
    if "profile_image" in missing:
        logger.info("NPC '%s': rendering the profile image", name)
        note = _render_profile_image(name)
        if note:
            notes.append(f"profile image: {note}")
    if "model3d" in missing:
        logger.info("NPC '%s': rendering the T-pose and the mesh", name)
        note = _render_mesh(name)
        if note:
            notes.append(note)
    if "expression" in missing:
        # LAST, although it needs only the outfit and never the mesh: run
        # before the mesh, a dead mesh backend would take the NPC's only
        # picture down with it. Every producer above runs off its own
        # criterion and only COLLECTS its complaint, so a failure up there
        # does not skip this one.
        logger.info("NPC '%s': rendering the default expression variant", name)
        note = _render_default_expression(name)
        if note:
            notes.append(f"expression: {note}")

    still_missing = npc_assets_complete(name)
    if still_missing:
        # Stays pooled. Raising is what hands the job back to the queue's own
        # retry mechanism (ASSET_RETRIES). The message carries the producers'
        # own words: "still incomplete: model3d" alone makes a dead backend
        # look like a mystery in the queue panel.
        detail = f" — {'; '.join(notes)}" if notes else ""
        raise RuntimeError(
            f"NPC '{name}' still incomplete after the attempt: "
            f"{', '.join(still_missing)}{detail}")

    _place(name, location_id, room_id, radius_m)
    sent = False
    if wanderer and wander_target:
        from app.core.npc_spawn import _send_wanderer
        sent = _send_wanderer(name, wander_target)
    logger.info("NPC '%s' finished and placed at %s%s", name,
                location_id or "(nowhere)", " (walking)" if sent else "")
    return {"ok": True, "name": name, "location_id": location_id,
            "room_id": room_id, "produced": missing, "walking": sent}


def register_npc_assets_handler() -> None:
    from app.core.task_queue import get_task_queue
    get_task_queue().register_handler(TASK_TYPE, _handle_npc_assets)
