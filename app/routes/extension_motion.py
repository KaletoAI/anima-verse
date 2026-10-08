"""Admin character motion overrides, independent of mesh option routes."""
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.auth_dependency import require_admin

router = APIRouter(prefix="/characters", tags=["extension-motion"],
                   dependencies=[Depends(require_admin)])


@router.post("/{character_name}/model3d/extension-motion")
async def set_extension_motion(character_name: str, request: Request):
    body = await request.json()
    return await asyncio.to_thread(_set_extension_motion_sync, character_name, body)


def _set_extension_motion_sync(character_name: str, body):
    from app.models.character import get_character_dir
    from app.core.model3d import set_model3d_options
    if not get_character_dir(character_name).exists():
        raise HTTPException(404, "Character not found")
    if not isinstance(body, dict) or set(body) != {"extension_motion"}:
        raise HTTPException(400, "extension_motion group overrides required")
    try:
        return {"options": set_model3d_options(character_name, body)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
