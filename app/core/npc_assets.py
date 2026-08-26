"""The finish gate for temporary NPCs: no face, no mesh, no world.

plan-npc-leben § 0 A. A temporary NPC used to appear on the map the moment its
character sheet existed — a nameplate with no portrait, no 3D figure and, often
enough, no outfit text for the image prompts to work from. This module is the
ONE place that decides whether an NPC is finished, plus the queue job that
finishes it.

Three criteria, and every one of them is checked at the CONSUMER (see
feedback_pruefe_am_verbraucher — a profile field that says "face.png" proves
nothing, the file behind it does):

* ``profile_image`` — the profile field is set AND the file is on disk;
* ``model3d`` — a mesh exists for the EXACTLY worn outfit signature
  (``find_model3d(name, current_outfit_state(name)[2])``, never the serving
  lookup: that one falls back to other outfits and would call a foreign mesh
  "done");
* ``outfit_description`` — the free text that IS this character's wardrobe.

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
from typing import Any, Dict, List

from app.core.log import get_logger

logger = get_logger("npc_assets")

#: Queue task type of one finishing job. One job = one NPC.
TASK_TYPE = "npc_assets"

#: The finish criteria, in the order :func:`npc_assets_complete` reports them.
CRITERIA = ("profile_image", "model3d", "outfit_description")


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
                      wanderer: bool = False, wander_target: str = "") -> str:
    """Queue the finishing job for one NPC. Returns the task id ("" = deduped).

    Deduplicated per character: a second placement attempt for an NPC that is
    already being finished must not start a second run of the same three
    generations.
    """
    from app.core.task_queue import get_task_queue
    return get_task_queue().submit(
        TASK_TYPE,
        {"name": name, "location_id": location_id, "room_id": room_id,
         "wanderer": bool(wanderer), "wander_target": wander_target or ""},
        queue_name="background", agent_name=name, deduplicate=True)


def gate_placement(name: str, location_id: str, room_id: str = "",
                   wanderer: bool = False, wander_target: str = "") -> bool:
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
                                wander_target)
    logger.info("NPC '%s' held back for %s — job %s", name,
                ", ".join(missing), task_id or "(already queued)")
    return True


# ---------------------------------------------------------------------------
# The producers
# ---------------------------------------------------------------------------

def _render_profile_image(name: str) -> None:
    """Render the NPC's portrait through the ordinary image service.

    The same request the profile-image route sends (``character_ops.
    generate_profile_image_core``): the FACE prompt, the ``profile`` use-case
    for the style, ``set_profile`` so the service files it as the portrait
    itself, and ``auto_enhance`` off because the face prompt IS the finished
    prompt. Blocking — this runs in a queue worker.
    """
    from app.core.character_ops import _resolve_face_prompt
    from app.imagegen.service import get_image_service
    from app.models.character import get_character_profile
    from app.models.character_template import get_template

    profile = get_character_profile(name) or {}
    template = profile.get("template") or ""
    prompt = _resolve_face_prompt(profile, name,
                                  get_template(template) if template else None)
    result = get_image_service().generate_from_input(json.dumps({
        "prompt": prompt,
        "agent_name": name,
        "auto_enhance": False,
        "set_profile": True,
        "image_use_case": "profile",
    }))
    logger.debug("npc_assets(%s): profile render said %s", name,
                 str(result)[:200])


def _render_mesh(name: str) -> None:
    """T-pose reference, then the mesh for the worn outfit. Blocking."""
    from app.core.model3d import generate_for_current_outfit
    from app.core.model_refs import generate_model_ref_images

    generate_model_ref_images(name, kinds=("tpose",))
    generate_for_current_outfit(name)


# ---------------------------------------------------------------------------
# The job
# ---------------------------------------------------------------------------

def _place(name: str, location_id: str, room_id: str) -> None:
    """Put the finished NPC into the world — the order of ``revive_from_pool``.

    Back into the roster BEFORE the placement: the location setter runs the
    ordinary arrival side effects, and those read the roster.
    """
    from app.models.character import (get_character_profile,
                                      save_character_current_location,
                                      save_character_current_room,
                                      save_character_profile,
                                      set_character_status)
    profile = get_character_profile(name) or {}
    if profile.pop("npc_pooled_reason", None) is not None:
        save_character_profile(name, profile)   # it is not waiting any more
    set_character_status(name, "")
    if location_id:
        save_character_current_location(name, location_id)
        if room_id:
            save_character_current_room(name, room_id)


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
    if "profile_image" in missing:
        logger.info("NPC '%s': rendering the profile image", name)
        _render_profile_image(name)
    if "model3d" in missing:
        logger.info("NPC '%s': rendering the T-pose and the mesh", name)
        _render_mesh(name)

    still_missing = npc_assets_complete(name)
    if still_missing:
        # Stays pooled. Raising is what hands the job back to the queue's own
        # retry mechanism (max_retries default).
        raise RuntimeError(
            f"NPC '{name}' still incomplete after the attempt: "
            f"{', '.join(still_missing)}")

    _place(name, location_id, room_id)
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
