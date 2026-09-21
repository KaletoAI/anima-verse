"""Character Template API Routes - Multiple templates in storage/templates/"""
from typing import Dict, Any
from fastapi import APIRouter, HTTPException, Request
from app.core.log import get_logger

logger = get_logger("templates")

from app.models.character_template import (
    list_templates,
    get_template,
    save_template,
    delete_template)

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("/list")
def list_all_templates(template_type: str = "") -> Dict[str, Any]:
    """List all available templates."""
    templates = list_templates(template_type=template_type or None)
    return {"templates": templates}


@router.get("/{template_name}")
def get_template_route(template_name: str) -> Dict[str, Any]:
    """Get a template by name."""
    template = get_template(template_name)
    if template is None:
        raise HTTPException(status_code=404, detail=f"Template '{template_name}' not found")
    return template


@router.post("/{template_name}")
async def save_template_route(template_name: str, request: Request) -> Dict[str, Any]:
    """Create or update a template."""
    import asyncio
    body = await request.json()
    return await asyncio.to_thread(_save_template_route_sync, template_name,
                                   body)


def _save_template_route_sync(template_name: str, body: Any) -> Dict[str, Any]:
    """The blocking body of ``save_template_route`` — runs in the
    threadpool."""
    template = body.get("template")

    if not template:
        raise HTTPException(status_code=400, detail="template required")

    ok = save_template(template_name, template)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to save template")

    return {"status": "ok", "name": template_name}


@router.delete("/{template_name}")
def delete_template_route(template_name: str) -> Dict[str, Any]:
    """Delete a template (cannot delete 'human-default')."""
    if template_name == "human-default":
        raise HTTPException(status_code=400, detail="Cannot delete default template")
    ok = delete_template(template_name)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Template '{template_name}' not found")
    return {"status": "ok"}
