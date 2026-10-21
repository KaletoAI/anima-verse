"""Game-Admin → Setup: the world-scope settings of the open world.

GET returns schema, values, shipped defaults and the world's own
deviations; PUT saves the world part only (config_admin.save_layer).
Admin-only (prefix /admin is on the auth gate's admin list, the dependency
is the second layer).
"""
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core import config, config_admin, config_scope, paths
from app.core.auth_dependency import require_admin
from app.core.config_schema import WORLD_GROUPS

router = APIRouter(prefix="/admin/world-settings", tags=["world-settings"],
                   dependencies=[Depends(require_admin)])


def _payload() -> dict:
    from app.core.config import _DEFAULT_IMAGE_USE_CASES, _PROMPT_STYLE_FAMILIES
    schema = config_scope.schema_for(config_scope.WORLD)
    groups = []
    for g in WORLD_GROUPS:
        sections = [k for k, sec in schema.items() if sec.get("world_group") == g["id"]]
        if sections:
            groups.append({**g, "sections": sections})
    with config._LOCK:
        return {
            "revision": config_admin.issue_revision(config_scope.WORLD),
            "world": paths.get_storage_dir().name,
            "groups": groups,
            "schema": schema,
            "values": config_admin.layer_part(config_scope.WORLD),
            "shipped": config_scope.shipped_tree(config_scope.WORLD),
            "overrides": config_admin.origin(config_scope.WORLD)["overrides"],
            "use_case_defaults": {
                "use_cases": list(_DEFAULT_IMAGE_USE_CASES.keys()),
                "families": _PROMPT_STYLE_FAMILIES,
                "defaults": _DEFAULT_IMAGE_USE_CASES,
            },
        }


@router.get("/extension-motion")
def get_extension_motion():
    from app.core.extension_rig import declared_motion_groups
    return {"groups": declared_motion_groups()}


@router.get("/packages")
def get_packages():
    """Every package on disk for the Setup → Packages checklist; what is
    enabled stays the comma list ``packages.enabled`` in the world values."""
    from app.plugins.loader import package_inventory
    return {"packages": package_inventory()}


@router.get("")
def get_world_settings():
    return _payload()


@router.put("")
async def put_world_settings(request: Request):
    body = await request.json()
    return await asyncio.to_thread(_put_sync, body)


def _put_sync(body):
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    if "base_revision" not in body:
        raise HTTPException(428, {"code": "revision_required", "message":
            "base_revision missing — load the settings first (GET /admin/world-settings, field revision)"})
    if not isinstance(body["base_revision"], str):
        raise HTTPException(400, "base_revision must be a string")
    confirm_drop = body.get("confirm_drop", [])
    if not isinstance(confirm_drop, list) or not all(isinstance(p, str) for p in confirm_drop):
        raise HTTPException(status_code=400, detail="confirm_drop must be a list of strings")
    try:
        result = config_admin.save_layer(config_scope.WORLD, body.get("values"),
                                         body.get("resets") or [], confirm_drop,
                                         base_revision=body["base_revision"])
    except config_admin.LayerStale as e:
        raise HTTPException(409, {"code": "stale", "reason": e.reason,
                                  "paths": e.paths, "message": str(e)}) from e
    except config_admin.LayerDropRefused as e:
        raise HTTPException(status_code=409, detail={
            "code": "would_drop", "paths": e.paths, "message": str(e)}) from e
    except config_admin.LayerSaveError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except config.ConfigWriteRefused as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {**_payload(), **result}
