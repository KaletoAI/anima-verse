"""Exact, consent-bound pair continuations for persisted shared undertakings."""
from __future__ import annotations

from typing import Any, Dict, Optional

from app.core import interaction_engine as IE
from app.core.animation_clips import clip_meta
from app.core.dependencies import get_skill_manager
from app.core.hooks import get_provider
from app.core.timeutils import parse_iso, utc_now
from app.models.character import (get_character_profile,
                                  get_character_skill_config,
                                  is_character_sleeping)
from app.models.intents import get_intent


_REQUEST_PREFIX = "iinv_intent_"


def _available() -> bool:
    skill = get_skill_manager().get_skill("interact")
    return bool(skill and skill.enabled and get_provider("pair_verb_name"))


def shared_activity_options() -> list[str]:
    """Available exact pair catalog keys; no aliases or natural-language actions."""
    if not _available():
        return []
    keys = []
    for key, kind in IE.partner_poses():
        try:
            duration = float((clip_meta(kind) or {}).get("duration_s") or 0)
        except (TypeError, ValueError):
            continue
        if duration > 0:
            keys.append(key)
    return sorted(keys)


def shared_activity_validate(owner: str, target: str, action: Any) -> Dict[str, str]:
    """Normalize a supported pair descriptor or raise a visible refusal."""
    if not isinstance(action, dict) or action.get("type") != "pair":
        raise ValueError("The shared activity must be a pair activity.")
    pose_key = action.get("pose_key")
    if not isinstance(pose_key, str) or not pose_key:
        raise ValueError("The shared activity needs an exact pair pose_key.")
    if not _available():
        raise ValueError("Pair interactions are not available.")
    if pose_key not in shared_activity_options():
        raise ValueError(f"'{pose_key}' is not an available exact pair catalog key.")
    if not isinstance(owner, str) or not isinstance(target, str) or not owner or not target or owner == target:
        raise ValueError("A shared activity needs two different characters.")
    for name in (owner, target):
        if get_character_profile(name) is None:
            raise ValueError(f"{name} does not exist.")
        if get_character_skill_config(name, "interact").get("enabled") is False:
            raise ValueError(f"Pair interactions are disabled for {name}.")
    return {"type": "pair", "pose_key": pose_key}


def _receipt(owner: str, target: str, action: Dict, request_id: str) -> Optional[Dict]:
    """Read ownership from the existing intent, never infer it from a same-pose pair."""
    if not request_id.startswith(_REQUEST_PREFIX):
        return None
    intent = get_intent(request_id[len(_REQUEST_PREFIX):])
    if not intent or intent.get("owner") != owner:
        return None
    if (intent.get("action") or {}).get("after_arrival") != action:
        return None
    state = (intent.get("meta") or {}).get("travel") or {}
    members = state.get("expected_members") or []
    if len(members) != 2 or set(members) != {owner, target}:
        return None
    activity = state.get("activity") or {}
    return activity if activity.get("request_id") == request_id else None


def _matches_invite(invitation: Dict, owner: str, target: str, pose_key: str) -> bool:
    return (invitation.get("inviter") == owner and invitation.get("invitee") == target
            and invitation.get("pose_key") == pose_key)


def _live_pair(owner: str, target: str, pose_key: str, interaction_id: str) -> bool:
    if not interaction_id:
        return False
    for name, partner in ((owner, target), (target, owner)):
        interaction = IE.get_interaction(name)
        if not interaction or interaction.get("id") != interaction_id:
            return False
        if interaction.get("partner") != partner or interaction.get("pose_key") != pose_key:
            return False
    return True


def _owned_pair_id(owner: str, target: str, pose_key: str, request_id: str) -> str:
    """Recover only the invitation provenance written atomically with the pair."""
    actor = IE.get_interaction(owner)
    partner = IE.get_interaction(target)
    if (actor and partner and actor.get("invite_id") == partner.get("invite_id") == request_id
            and actor.get("id") == partner.get("id")
            and actor.get("partner") == target and partner.get("partner") == owner
            and actor.get("pose_key") == partner.get("pose_key") == pose_key):
        return str(actor["id"])
    return ""


def _result(status: str, request_id: str, reason: str = "", interaction_id: str = "") -> Dict:
    result = {"status": status, "invite_id": request_id}
    if reason:
        result["reason"] = reason
    if interaction_id:
        result["interaction_id"] = interaction_id
    return result


def shared_activity_status(owner: str, target: str, action: Any, request_id: str) -> Dict:
    """Inspect only this question and its actual start receipt; never submit or restart."""
    if not isinstance(request_id, str) or not request_id:
        return _result("blocked", "", "The shared activity request id is missing.")
    try:
        normalized = shared_activity_validate(owner, target, action)
    except ValueError as error:
        return _result("blocked", request_id, str(error))
    invitation = IE.get_invite(request_id)
    receipt = _receipt(owner, target, normalized, request_id)
    recorded_id = str((receipt or {}).get("interaction_id") or "")
    provenance_id = _owned_pair_id(owner, target, normalized["pose_key"], request_id)
    if provenance_id and (not recorded_id or recorded_id == provenance_id):
        if invitation and not _matches_invite(invitation, owner, target, normalized["pose_key"]):
            return _result("blocked", request_id, "The request id belongs to a different invitation.")
        return _result("running", request_id, interaction_id=provenance_id)
    if not invitation:
        if receipt is not None and not receipt.get("submitted") and not receipt.get("interaction_id"):
            return _result("not_found", request_id, "The shared activity has not been requested yet.")
        return _result("blocked", request_id, "The owned shared activity invitation is missing.")
    if not _matches_invite(invitation, owner, target, normalized["pose_key"]):
        return _result("blocked", request_id, "The request id belongs to a different invitation.")
    status = invitation.get("status")
    if status == "declined":
        return _result("declined", request_id, f"{target} declined the shared activity.")
    if status == "accepted":
        interaction_id = recorded_id
        if _live_pair(owner, target, normalized["pose_key"], interaction_id):
            return _result("running", request_id, interaction_id=interaction_id)
        return _result("blocked", request_id,
                       "The accepted invitation has no matching live owned interaction.")
    if status not in ("pending", "answering", "approaching"):
        return {**_result("blocked", request_id,
                          f"The shared activity invitation is {status or 'invalid'}."),
                "terminal": True}
    try:
        fresh = (utc_now() - parse_iso(invitation["created_at"])).total_seconds() <= IE.INVITE_MAX_AGE_MIN * 60
    except (KeyError, TypeError, ValueError):
        return _result("blocked", request_id, "The shared activity invitation has an invalid timestamp.")
    if not fresh:
        return {**_result("blocked", request_id, "The shared activity invitation expired before it started."),
                "terminal": True}
    if status == "approaching":
        for name in (owner, target):
            if is_character_sleeping(name):
                return _result("blocked", request_id, f"{name} is asleep.")
            if IE.get_interaction(name):
                return _result("blocked", request_id, f"{name} is already busy with someone.")
        return _result("approaching", request_id, "Consent was given; the partner is walking over.")
    if status == "answering":
        return _result("pending", request_id, "The partner's answer is being processed.")
    blocked = IE.check_can_pair(owner, target)
    if blocked:
        return _result("blocked", request_id, blocked)
    return _result("pending", request_id, "Waiting for the partner's explicit answer.")


def shared_activity_request(owner: str, target: str, action: Any, request_id: str) -> Dict:
    """Ask through the normal invitation flow once, preserving actual consent."""
    status = shared_activity_status(owner, target, action, request_id)
    if status["status"] != "not_found":
        return status
    normalized = shared_activity_validate(owner, target, action)
    blocked = IE.check_can_pair(owner, target)
    if blocked:
        return _result("blocked", request_id, blocked)
    if IE.create_invite(owner, target, normalized["pose_key"], request_id=request_id) != request_id:
        return _result("blocked", request_id, "The owned shared activity invitation could not be recorded.")
    # A normal NPC/temporary-NPC answer can settle synchronously inside the
    # invitation hook. Read back the real outcome rather than reporting pending.
    return shared_activity_status(owner, target, normalized, request_id)


def shared_activity_cancel(owner: str, target: str, action: Any, request_id: str, *,
                           interaction_id: str = "") -> bool:
    """Cancel only this exact question/pair, even if a new same-pose pair exists."""
    if not isinstance(action, dict) or action.get("type") != "pair":
        return False
    pose_key = action.get("pose_key")
    if not isinstance(pose_key, str) or not isinstance(request_id, str) or not request_id:
        return False
    normalized = {"type": "pair", "pose_key": pose_key}
    invitation = IE.get_invite(request_id)
    receipt = _receipt(owner, target, normalized, request_id)
    if invitation and not _matches_invite(invitation, owner, target, pose_key):
        return False
    recorded_id = str((receipt or {}).get("interaction_id") or "")
    provenance_id = _owned_pair_id(owner, target, pose_key, request_id)
    owned_id = recorded_id or provenance_id
    if interaction_id and interaction_id != owned_id:
        return False
    cancelled = bool(invitation and IE.cancel_invite(request_id))
    if not recorded_id:
        # The answer can win after the first snapshot but before cancellation.
        owned_id = _owned_pair_id(owner, target, pose_key, request_id)
        if interaction_id and interaction_id != owned_id:
            return cancelled
    if owned_id and _live_pair(owner, target, pose_key, owned_id):
        cancelled = IE.end_interaction(owner, reason="cancelled", interaction_id=owned_id) or cancelled
    return cancelled
