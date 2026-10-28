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


class AdminRun(AdminCheck):
    execution_id: StrictStr


class AdminResponse(AdminRun):
    accept: StrictBool
    participant: StrictStr


class AdminParticipant(AdminRun):
    participant: StrictStr


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
    return {"issues": issues, "valid": not any(i["severity"] == "error" for i in issues),
            "placement": "not_checked"}


@router.post("/world/props/{prop_id}/check-placement")
def check_placement(prop_id: str, body: AdminCheck, user=Depends(require_admin)):
    _admin_target(prop_id, body)
    return engine.check(body.actor, body.target.model_dump(), body.action_id, body.revision, body.partner,
                        include_plans=True)


@router.post("/world/props/{prop_id}/execute-test")
def execute_test(prop_id: str, body: AdminExecution, user=Depends(require_admin)):
    if body.confirmed is not True:
        raise HTTPException(422, detail="Explicit confirmation required: execution can change world values")
    _admin_target(prop_id, body)
    from app.core import prop_action_store as store
    with engine.request_guard(body.actor, body.request_id):
        previous = store.by_request(body.actor, body.request_id)
        if previous and (previous["data"].get("admin_test") or {}).get("prop_id") != prop_id:
            raise HTTPException(409, detail="Request belongs to another execution")
        before = _participant_snapshots(body.actor, body.partner)
        result, created = engine.request_with_creation(
            body.actor, body.target.model_dump(), body.action_id, body.revision,
            body.partner, body.request_id)
        result = _answer(result)
        admitted = store.get(result["execution_id"])
        if not created and (admitted["data"].get("admin_test") or {}).get("prop_id") != prop_id:
            raise HTTPException(409, detail="Request belongs to another execution")
        if created:
            # Adapter provenance only; Core remains sole owner of run progress.
            with engine._lock(result["execution_id"]), store.transaction() as conn:
                conn.execute("UPDATE prop_action_runs SET data=json_set(data,'$.admin_test',json(?)) "
                             "WHERE execution_id=?",
                             (store.encode(dict(prop_id=prop_id, before=before)), result["execution_id"]))
    return dict(result, observation=_admin_observation(store.get(result["execution_id"])))


def _participant_snapshots(actor, partner, *, allow_missing=False):
    from app.models.character import get_character_profile, get_avatar_sync_snapshot
    result = {}
    for name in (actor, partner):
        if not name:
            continue
        try:
            profile = get_character_profile(name, strict=True)
        except LookupError:
            if not allow_missing:
                raise HTTPException(409, detail=f"Participant no longer exists: {name}") from None
            result[name] = dict(unavailable="participant_not_found")
            continue
        result[name] = dict(stats=profile.get("status_effects") or {},
                            mood=profile.get("current_feeling", ""),
                            conditions=profile.get("active_conditions") or [],
                            sleeping=bool(profile.get("is_sleeping")),
                            position=get_avatar_sync_snapshot(name),
                            place=profile.get("place"))
    return result


def _admin_run(prop_id, body):
    from app.core import prop_action_store as store
    run = store.get(body.execution_id)
    if not run:
        raise HTTPException(404, detail="Execution not found")
    if ((run["data"].get("admin_test") or {}).get("prop_id") != prop_id
            or run["target"] != body.target.model_dump()
            or run["actor"] != body.actor or run["partner"] != body.partner
            or run["action_id"] != body.action_id or run["definition_revision"] != body.revision):
        raise HTTPException(403, detail="Execution does not belong to this exact admin test")
    # Do not resolve today's placement/revision: deletion must not strand cleanup.
    return run


def _admin_observation(run):
    from app.core import prop_action_store as store
    state = engine.state_for(run["partner"] or run["actor"])
    row = next((row for rows in state.values() for row in rows
                if row["execution_id"] == run["execution_id"]), None)
    return dict(run=row or dict(engine._result(run), phase=run["phase"], phase_label="",
                                can_respond=False, can_cancel=run["status"] not in store.TERMINAL),
                before=run["data"]["admin_test"]["before"],
                current=_participant_snapshots(run["actor"], run["partner"], allow_missing=True),
                claims=store.claims(run["execution_id"]),
                plans=run["data"].get("plans", {}))


@router.get("/world/prop-action-tests")
def admin_test_runs(user=Depends(require_admin)):
    """Recover durable Admin tests, including all live runs regardless of age."""
    from app.core import prop_action_store as store
    conn = store.db.get_connection()
    live = conn.execute(
        "SELECT * FROM prop_action_runs WHERE status NOT IN ('completed','cancelled','failed') "
        "AND json_type(data,'$.admin_test.prop_id')='text' ORDER BY created_at,execution_id")
    recent = conn.execute(
        "SELECT * FROM prop_action_runs WHERE status IN ('completed','cancelled','failed') "
        "AND json_type(data,'$.admin_test.prop_id')='text' "
        "AND julianday(updated_at)>=julianday('now','-30 minutes') "
        "ORDER BY updated_at DESC,execution_id DESC LIMIT 20")
    tests = []
    for raw in [*live, *recent]:
        run = store._decode(raw)
        tests.append(dict(prop_id=run["data"]["admin_test"]["prop_id"],
                          request=dict(target=run["target"], action_id=run["action_id"],
                                       revision=run["definition_revision"], actor=run["actor"],
                                       partner=run["partner"], execution_id=run["execution_id"]),
                          observation=_admin_observation(run)))
    return dict(tests=tests)


@router.post("/world/props/{prop_id}/test-state")
def admin_test_state(prop_id: str, body: AdminRun, user=Depends(require_admin)):
    return _admin_observation(_admin_run(prop_id, body))


@router.post("/world/props/{prop_id}/test-respond")
def admin_test_respond(prop_id: str, body: AdminResponse, user=Depends(require_admin)):
    run = _admin_run(prop_id, body)
    if body.participant != run["partner"] or not run["partner"]:
        raise HTTPException(403, detail="Only the exact invited partner can answer")
    _answer(engine.respond(body.participant, body.execution_id, body.accept))
    return admin_test_state(prop_id, body, user)


@router.post("/world/props/{prop_id}/test-cancel")
def admin_test_cancel(prop_id: str, body: AdminParticipant, user=Depends(require_admin)):
    run = _admin_run(prop_id, body)
    if body.participant not in (run["actor"], run["partner"]) or not body.participant:
        raise HTTPException(403, detail="Only an exact participant can stop")
    _answer(engine.cancel(body.participant, body.execution_id))
    return admin_test_state(prop_id, body, user)


@router.post("/world/props/{prop_id}/test-wake")
def admin_test_wake(prop_id: str, body: AdminParticipant, user=Depends(require_admin)):
    from app.models.character import get_character_profile
    from app.core import prop_action_store as store
    run = _admin_run(prop_id, body)
    if body.participant not in (run["actor"], run["partner"]) or not body.participant:
        raise HTTPException(403, detail="Only an exact participant can wake")
    # A stale test must never wake somebody now owned by a replacement run.
    with engine._lock(body.execution_id):
        run = _admin_run(prop_id, body)
        owner = store.held(store.person_key(body.participant))
        try:
            profile = get_character_profile(body.participant, strict=True)
        except LookupError:
            raise HTTPException(409, detail="Participant no longer exists") from None
        if (run["status"] != "sleeping" or owner != body.execution_id
                or (profile.get("place") or {}).get("execution_id") != body.execution_id):
            raise HTTPException(409, detail="This test no longer owns the sleeping participant")
        # Core's owned cleanup atomically compares the place execution ID,
        # wakes through the existing lifecycle and releases only this bed.
        engine.interrupt(body.participant, "awake", execution_id=body.execution_id)
    return admin_test_state(prop_id, body, user)
