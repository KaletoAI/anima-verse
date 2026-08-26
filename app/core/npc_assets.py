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
         "wanderer": bool(wanderer), "wander_target": wander_target or ""},
        queue_name="background", agent_name=name, max_retries=ASSET_RETRIES,
        deduplicate=True)


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
