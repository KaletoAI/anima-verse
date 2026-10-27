"""Thin session-avatar and explicitly confirmed admin adapters to one executor."""
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


class AdminExecution(AdminCheck):
    confirmed: StrictBool


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
    from app.routes.play import _player_action_gate
    skill = _player_action_gate(actor, "prop_action")
    result = _answer(_request(actor, body))
    if skill is not None and result["status"] not in ("failed", "cancelled"):
        from app.core.skill_gate import charge
        charge(actor, skill.SKILL_ID)
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


@router.post("/world/props/{prop_id}/validate")
def validate(prop_id: str, body: Document, user=Depends(require_admin)):
    if not props.read_sidecar(prop_id, read_only=True):
        raise HTTPException(404, detail="Unknown prop")
    issues = prop_actions.validate_document(body.document)
    return {"issues": issues, "valid": not any(i["severity"] == "error" for i in issues),
            "placement": "not_checked"}


@router.post("/world/props/{prop_id}/check-placement")
def check_placement(prop_id: str, body: AdminCheck, user=Depends(require_admin)):
    _admin_target(prop_id, body)
    return engine.check(body.actor, body.target.model_dump(), body.action_id, body.revision, body.partner)


@router.post("/world/props/{prop_id}/execute-test")
def execute_test(prop_id: str, body: AdminExecution, user=Depends(require_admin)):
    if body.confirmed is not True:
        raise HTTPException(422, detail="Explicit confirmation required: execution can change world values")
    _admin_target(prop_id, body)
    return _answer(_request(body.actor, body))
