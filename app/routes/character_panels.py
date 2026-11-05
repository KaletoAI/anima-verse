"""Package character panels — admin routes (thin HTTP adapter).

The logic lives in ``app/core/character_panels.py``; this file maps it to HTTP:
no provider for the package / unknown character → 404, a provider that raises
or answers outside the contract → 500 with the traceback in the log. A refused
save/delete/action is NOT an HTTP error: it answers 200 ``{"ok": false,
"error": ...}`` so the panel can show the reason inline in its card.

``lang`` is the requesting UI's language as a query parameter (``?lang=``,
the convention of ``/world/game-time`` and ``/events``); the provider
translates its labels and messages with it.
"""
from typing import Any, Callable, Dict

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.core import character_panels as panels
from app.core.auth_dependency import require_admin
from app.core.log import get_logger

logger = get_logger("character_panels")

router = APIRouter(prefix="/characters", tags=["character-panels"])


def _run(what: str, package_id: str, character_name: str, fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except panels.PanelNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("character panel %s (%s, %s) failed: %s", what, package_id,
                     character_name, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Panel {what} failed: {e}")


def _body(body: Any) -> Dict[str, Any]:
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON object expected")
    return body


@router.get("/{character_name}/panels/{package_id}")
def get_character_panel(character_name: str, package_id: str, lang: str = Query("en"),
                        _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """The package's panel for this character (title, intro, cards, create form)."""
    return _run("describe", package_id, character_name,
                lambda: panels.describe_panel(package_id, character_name, lang))


@router.post("/{character_name}/panels/{package_id}/save")
def save_character_panel(character_name: str, package_id: str, body: Any = Body(...),
                         lang: str = Query("en"),
                         _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Body ``{card_id: str | null, values: {...}}`` — ``card_id`` null creates."""
    data = _body(body)
    return _run("save", package_id, character_name,
                lambda: panels.save_panel_card(package_id, character_name, data.get("card_id"),
                                               data.get("values"), lang))


@router.post("/{character_name}/panels/{package_id}/delete")
def delete_character_panel(character_name: str, package_id: str, body: Any = Body(...),
                           lang: str = Query("en"),
                           _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Body ``{card_id}``."""
    data = _body(body)
    return _run("delete", package_id, character_name,
                lambda: panels.delete_panel_card(package_id, character_name,
                                                 data.get("card_id"), lang))


@router.post("/{character_name}/panels/{package_id}/action")
def run_character_panel_action(character_name: str, package_id: str, body: Any = Body(...),
                               lang: str = Query("en"),
                               _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Body ``{card_id, action_id, value?}`` (``card_id`` ``""`` = a
    panel-level action; ``value`` = the text an action with ``input`` asked for)."""
    data = _body(body)
    return _run("action", package_id, character_name,
                lambda: panels.run_panel_action(package_id, character_name, data.get("card_id"),
                                                data.get("action_id"), lang,
                                                value=data.get("value")))
