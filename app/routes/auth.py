"""Authentication routes (multiuser phase 1).

Cookie-based sessions. Login sets the HttpOnly cookie, logout clears it; the
cookie helpers live in ``app.core.sessions`` because the middleware re-issues
the cookie on every sliding refresh.
"""
from typing import Dict, Any
from fastapi import APIRouter, Request, Response, HTTPException, Depends, status

from app.core.log import get_logger
from app.core import sessions, users
from app.core.auth_dependency import (
    get_current_user, get_current_user_optional, require_admin)

logger = get_logger("auth")

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/login")
async def login(request: Request, response: Response) -> Dict[str, Any]:
    """Logs a user in and sets the session cookie."""
    import asyncio
    data = await request.json()
    return await asyncio.to_thread(_login_sync, response, data)


def _login_sync(response: Response, data: Any) -> Dict[str, Any]:
    """The blocking body of ``login`` — runs in the threadpool."""
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    if not username or not password:
        raise HTTPException(status_code=400, detail="Benutzername und Passwort erforderlich")

    user = users.check_user_password(username, password)
    if not user:
        raise HTTPException(status_code=401, detail="Ungueltige Anmeldedaten")

    token = sessions.create_session(user["id"])
    users.touch_last_login(user["id"])
    sessions.set_session_cookie(response, token)
    logger.info("Login: %s (role=%s)", user["username"], user["role"])

    # Avatar-only presence: materialize the avatar and (if offmap) bring it back,
    # otherwise it stays "roomless" after logout/reaper. See plan-avatar-only-presence.md.
    try:
        from app.models.account import restore_avatar_on_login
        restore_avatar_on_login(user)
    except Exception:
        logger.warning("restore_avatar_on_login fehlgeschlagen fuer %s", user.get("username"))

    return {
        "status": "success",
        "user": {
            "id": user["id"],
            "username": user["username"],
            "role": user["role"],
            "allowed_characters": user["allowed_characters"],
        },
    }


@router.post("/logout")
def logout(request: Request, response: Response) -> Dict[str, Any]:
    """Logs out — deletes the session server-side and clears the cookie."""
    # Release the avatar (avatar-only characters vanish from the map with it).
    # Before delete_session, while the user is still in the request context.
    try:
        from app.models.account import release_active_character
        release_active_character()
    except Exception:
        pass
    token = request.cookies.get(sessions.SESSION_COOKIE_NAME)
    if token:
        sessions.delete_session(token)
    sessions.clear_session_cookie(response)
    return {"status": "success"}


@router.get("/me")
def me(user = Depends(get_current_user)) -> Dict[str, Any]:
    """Liefert den aktuell eingeloggten User."""
    return {"user": user}


@router.get("/status")
def auth_status(user = Depends(get_current_user_optional)) -> Dict[str, Any]:
    """Status ohne 401 — Frontend prueft ob Login noetig."""
    return {"authenticated": user is not None, "user": user}


# ── User-Verwaltung (Admin-only) ──────────────────────────────────────

@router.get("/users")
def list_users_route(_: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    return {"status": "success", "users": users.list_users()}


@router.post("/users")
async def create_user_route(
    request: Request,
    _: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    import asyncio
    data = await request.json()
    return await asyncio.to_thread(_create_user_route_sync, _, data)


def _create_user_route_sync(_: Dict[str, Any], data: Any) -> Dict[str, Any]:
    """The blocking body of ``create_user_route`` — runs in the threadpool."""
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    role = (data.get("role") or "user").strip()
    allowed = data.get("allowed_characters") or []
    try:
        user_id = users.create_user(username, password, role=role,
                                    allowed_characters=allowed)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "success", "user_id": user_id}


@router.patch("/users/{user_id}")
async def update_user_route(
    user_id: str, request: Request,
    _: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    import asyncio
    data = await request.json()
    return await asyncio.to_thread(_update_user_route_sync, user_id, _, data)


def _update_user_route_sync(user_id: str, _: Dict[str, Any],
                            data: Any) -> Dict[str, Any]:
    """The blocking body of ``update_user_route`` — runs in the threadpool."""
    password = data.pop("password", None)
    try:
        if password:
            users.set_user_password(user_id, password)
        updated = users.update_user(user_id, **data) if data else True
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not updated and not password:
        raise HTTPException(status_code=404, detail="User nicht gefunden")
    return {"status": "success"}


@router.delete("/users/{user_id}")
def delete_user_route(
    user_id: str,
    current: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    if current["id"] == user_id:
        raise HTTPException(status_code=400, detail="Eigener Account nicht loeschbar")
    target = users.get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User nicht gefunden")
    # Letzten Admin nicht loeschen
    if target.get("role") == users.ROLE_ADMIN:
        admins = [u for u in users.list_users() if u.get("role") == users.ROLE_ADMIN]
        if len(admins) <= 1:
            raise HTTPException(status_code=400,
                                detail="Letzter Admin kann nicht geloescht werden")
    users.delete_user(user_id)
    sessions.delete_sessions_for_user(user_id)
    return {"status": "success"}
