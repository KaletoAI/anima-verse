"""Notification API routes.

Listing, the unread counter and the style preference lived here for the old
vanilla UI. The Player reads its notices through ``GET /play/notices`` (which
carries ``notifications`` and ``unread_count`` already), so only the two
mark-as-read writes remain (DE-13, user decision 2026-09-21).
"""
from typing import Any, Dict
from fastapi import APIRouter, HTTPException
from app.core.log import get_logger

logger = get_logger("notifications")

from app.models.notifications import mark_read, mark_all_read

router = APIRouter(prefix="/notifications")


@router.post("/{notification_id}/read")
def read_notification(notification_id: str) -> Dict[str, Any]:
    """Mark a single notification as read."""
    found = mark_read(notification_id)
    if not found:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"success": True}


@router.post("/read-all")
def read_all_notifications() -> Dict[str, Any]:
    """Mark as read what the player's notice banner shows.

    The banner lists the ACTIVE AVATAR's notifications (``GET /play/notices``
    filters by it), so "all" means exactly those — never the notifications of
    characters the player is not looking at. Without an avatar there is no
    banner and nothing to mark.
    """
    from app.models.account import get_active_character
    avatar = (get_active_character() or "").strip()
    if not avatar:
        return {"success": True, "marked": 0}
    count = mark_all_read(character_whitelist=[avatar])
    return {"success": True, "marked": count}
