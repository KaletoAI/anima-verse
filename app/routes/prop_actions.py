"""Session-avatar execution and read-only admin authoring adapters."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr
from app.core.auth_dependency import get_current_user, require_admin
from app.core import prop_actions, prop_action_engine as engine, places, props

router = APIRouter(tags=["prop-actions"])


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Target(Input):
    location_id: StrictStr
    room_id: StrictStr
    placement_id: StrictStr
    variant_uid: StrictStr


class ActionRequest(Input):
    target: Target
    action_id: StrictStr
    revision: StrictStr
    partner: StrictStr = ""
    request_id: StrictStr = ""


class ResponseRequest(Input):
    execution_id: StrictStr
    accept: StrictBool


class CancelRequest(Input):
    execution_id: StrictStr


class AdminCheck(ActionRequest):
    actor: StrictStr


class Document(Input):
    document: dict


def _avatar(user):
    from app.models.account import get_active_character_for_user
    name = get_active_character_for_user(user["id"])
    if not name:
        raise HTTPException(403, detail="No authorized active avatar")
    return name


def _answer(result):
    if result["status"] == "refused":
        reason = result["reason"]
        status = 403 if reason in ("not_invitee", "not_participant") else 409
        raise HTTPException(status, detail=result)
    return result


def _request(actor, body):
    return engine.request(actor, body.target.model_dump(), body.action_id, body.revision,
                          body.partner, body.request_id)


@router.get("/play/prop-actions")
def offers(user=Depends(get_current_user)):
    return prop_actions.offers(_avatar(user))


@router.get("/play/prop-actions/state")
def state(user=Depends(get_current_user)):
    return engine.state_for(_avatar(user))


@router.post("/play/prop-actions/request")
def request(body: ActionRequest, user=Depends(get_current_user)):
    actor = _avatar(user)
    from app.core import prop_action_store as store
    from app.routes.play import _player_action_gate
    with engine.request_guard(actor, body.request_id):
        if store.by_request(actor, body.request_id):
            # Core verifies the full fingerprint; a mismatched nonce is never
            # a gate bypass and never pays a cost.
            return _answer(_request(actor, body))
        try:
            skill = _player_action_gate(actor, "prop_action")
        except HTTPException:
            # Another Core caller/process may have committed this nonce while
            # the gate read the newly depleted profile. Recheck before refusing.
            if store.by_request(actor, body.request_id):
                return _answer(_request(actor, body))
            raise
        result, created = engine.request_with_creation(
            actor, body.target.model_dump(), body.action_id, body.revision,
            body.partner, body.request_id)
        result = _answer(result)
        if created and skill is not None and result["status"] not in ("failed", "cancelled"):
            from app.core.skill_gate import charge
            charge(actor, skill.SKILL_ID)
    if created:
        # Deferred consent listeners run after the charge/outer guard. Project
        # their real current outcome just as an ordinary Core request does.
        result = engine._result(store.get(result["execution_id"]))
    return result


@router.post("/play/prop-actions/respond")
def respond(body: ResponseRequest, user=Depends(get_current_user)):
    return _answer(engine.respond(_avatar(user), body.execution_id, body.accept))


@router.post("/play/prop-actions/cancel")
def cancel(body: CancelRequest, user=Depends(get_current_user)):
    return _answer(engine.cancel(_avatar(user), body.execution_id))


def _admin_target(prop_id, body):
    if not props.read_sidecar(prop_id, read_only=True):
        raise HTTPException(404, detail="Unknown prop")
    candidates = places._compose(body.target.location_id).get(body.target.room_id, [])
    if not any(p.get("prop_id") == prop_id and p.get("placement_id") == body.target.placement_id
               and p.get("variant_uid") == body.target.variant_uid for p in candidates):
        raise HTTPException(409, detail="Placement does not resolve to this prop/variant")


@router.get("/world/props/{prop_id}/check-targets")
def check_targets(prop_id: str, location_id: str, user=Depends(require_admin)):
    """Saved, resolvable placements and the actual room census; never build assets."""
    from app.models.world import get_location_by_id
    from app.models.character import is_character_sleeping
    document = props.read_sidecar(prop_id, read_only=True)
    if not document:
        raise HTTPException(404, detail="Unknown prop")
    location = get_location_by_id(location_id)
    if not location:
        raise HTTPException(404, detail="Location not found")
    composed = places._compose(location_id)
    rooms = []
    for room in location.get("rooms", []):
        room_id = room.get("id", "")
        targets = {}
        for place in composed.get(room_id, []):
            if place.get("prop_id") != prop_id:
                continue
            placement_id, variant_uid = place.get("placement_id"), place.get("variant_uid")
            if placement_id and variant_uid:
                targets[(placement_id, variant_uid)] = dict(
                    location_id=location_id, room_id=room_id,
                    placement_id=placement_id, variant_uid=variant_uid)
        if targets:
            rooms.append(dict(id=room_id, name=room.get("name") or room_id,
                              placements=[dict(target=target) for target in targets.values()],
                              persons=[dict(name=name, sleeping=bool(is_character_sleeping(name)))
                                       for name, _ in places._present(location_id, room_id)]))
    return dict(revision=props._document_revision(document), rooms=rooms)


@router.post("/world/props/{prop_id}/validate")
def validate(prop_id: str, body: Document, user=Depends(require_admin)):
    if not props.read_sidecar(prop_id, read_only=True):
        raise HTTPException(404, detail="Unknown prop")
    issues = prop_actions.validate_document(body.document)
    valid = not any(i["severity"] == "error" for i in issues)
    from app.core.prop_action_access import preview_access
    return {"issues": issues, "valid": valid, "placement": "not_checked",
            "derived_bindings": {v.get("uid"): prop_actions.derive_bindings(body.document, v)
                                 for v in body.document.get("model_variants", []) if isinstance(v, dict)} if valid else {},
            "access_previews": preview_access(body.document, prop_id=prop_id) if valid else {}}


@router.post("/world/props/{prop_id}/check-placement")
def check_placement(prop_id: str, body: AdminCheck, user=Depends(require_admin)):
    _admin_target(prop_id, body)
    return engine.check(body.actor, body.target.model_dump(), body.action_id, body.revision, body.partner,
                        include_plans=True)
