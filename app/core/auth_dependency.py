"""FastAPI dependencies for auth (multiuser phase 1).

Usage in routes:

    from app.core.auth_dependency import get_current_user, require_admin

    @router.get("/protected")
    def foo(user = Depends(get_current_user)): ...

    @router.get("/admin-only")
    def bar(user = Depends(require_admin)): ...

Additionally the contextvar `current_user_ctx` — set by the middleware and
readable from arbitrary code (get_current_user_from_ctx) without a request.
"""
from contextvars import ContextVar
from typing import Optional, Dict, Any
from fastapi import Request, HTTPException, status

from app.core import sessions, users
from app.core.log import get_logger

logger = get_logger("auth_dep")

current_user_ctx: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "current_user_ctx", default=None
)


def get_current_user_from_ctx() -> Optional[Dict[str, Any]]:
    """Returns the current user from the request context (via middleware).
    None when there is no request context (e.g. a background task)."""
    return current_user_ctx.get()


def _sets_session_cookie(response) -> bool:
    """Does this response already carry a Set-Cookie for the session cookie?

    The route runs BEFORE the sliding re-issue below, so whatever it wrote for
    that cookie would be followed by a second Set-Cookie of the same name — and
    the browser keeps the LAST one. On /auth/logout that turns the route's
    delete into a re-issue of the token the server has just destroyed: the
    browser holds a cookie no session row backs any more, so the next request
    is a guaranteed 401.

    Whoever writes the cookie in the response owns it, and the slide steps
    aside. Deliberately generic — a name check, not a list of paths that would
    have to learn about every future route that logs out or rotates a token.
    """
    prefix = f"{sessions.SESSION_COOKIE_NAME}="
    return any(
        raw.lstrip().startswith(prefix)
        for raw in response.headers.getlist("set-cookie")
    )


def _get_session_user(request: Request) -> Optional[Dict[str, Any]]:
    """Resolves the session cookie to a user.

    Side effect for the middleware: when the session slid (sessions.get_session
    reports a refresh), the token is remembered on ``request.state`` so the
    response can carry a fresh cookie. The flag is only ever set to True — a
    later call within the same request (dependencies run after the middleware)
    is throttled and must not erase an earlier refresh.
    """
    token = request.cookies.get(sessions.SESSION_COOKIE_NAME)
    path = request.url.path
    if not token:
        if path.startswith("/world-dev/") or path.startswith("/admin/"):
            cookie_keys = list(request.cookies.keys())
            logger.warning("auth: no session cookie at %s (available cookies=%s)",
                           path, cookie_keys)
        return None
    sess, refreshed = sessions.get_session(token)
    if refreshed:
        request.state.session_refresh_token = token
    if not sess:
        if path.startswith("/world-dev/") or path.startswith("/admin/"):
            logger.warning("auth: session token unknown/expired at %s (token=%s...)",
                           path, token[:8])
        return None
    user = users.get_user_by_id(sess["user_id"])
    if not user and (path.startswith("/world-dev/") or path.startswith("/admin/")):
        logger.warning("auth: session ok but user_id %s not in DB at %s",
                       sess["user_id"], path)
    return user


def get_current_user(request: Request) -> Dict[str, Any]:
    """Dependency: returns the logged-in user or raises 401."""
    user = _get_session_user(request)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Not authenticated")
    return user


def get_current_user_optional(request: Request) -> Optional[Dict[str, Any]]:
    """Dependency: returns the user or None (never 401)."""
    return _get_session_user(request)


def require_admin(request: Request) -> Dict[str, Any]:
    """Dependency: enforces the admin role."""
    user = get_current_user(request)
    if user.get("role") != users.ROLE_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Admin role required")
    return user


def filter_characters(request: Request, character_names):
    """Filters a character list by the current user's access rights.

    Not logged in: empty list. Otherwise only the assigned characters — for
    admins too.
    """
    user = get_current_user_optional(request)
    if not user:
        return []
    allowed = set(user.get("allowed_characters") or [])
    return [c for c in character_names if c in allowed]


def user_can_access_character(request: Request, character_name: str) -> bool:
    """True when the current user has the character in allowed_characters."""
    user = get_current_user_optional(request)
    if not user:
        return False
    return character_name in (user.get("allowed_characters") or [])


async def user_context_middleware(request: Request, call_next):
    """Sets current_user_ctx from the session cookie for the request duration.

    Character access policy:
    - Admin: sees and changes everything (no character filter)
    - User: may read images/expression/basic states of all characters
            (profile picture + expression visible), but no sensitive data
            (profile, schedule, knowledge, memories, secrets, diary, inventory)
    - User write operations: only on assigned (allowed_characters) chars
    - allowed_characters is primarily about avatar selection (see /account)
    """
    from fastapi.responses import JSONResponse

    user = _get_session_user(request)
    token = current_user_ctx.set(user)
    try:
        if user and user.get("role") != users.ROLE_ADMIN:
            path = request.url.path
            method = request.method.upper()
            chars = _extract_characters_from_path(path)
            if chars:
                allowed = set(user.get("allowed_characters") or [])
                is_write = method in ("POST", "PUT", "PATCH", "DELETE")
                is_sensitive = _is_sensitive_character_path(path)
                blocked_char = ""
                for c in chars:
                    if c in allowed:
                        continue
                    if is_write or is_sensitive:
                        blocked_char = c
                        break
                if blocked_char:
                    return JSONResponse(
                        status_code=403,
                        content={"detail": f"Kein Zugriff auf Character '{blocked_char}'"},
                    )
        response = await call_next(request)
        # Sliding sessions have two halves: the DB row (done in get_session) and
        # the browser cookie. Without re-issuing it, the browser drops the cookie
        # exactly SESSION_TTL_HOURS after login — mid-session. Authenticated
        # requests only; an anonymous request never gets a cookie.
        refresh_token = getattr(request.state, "session_refresh_token", "")
        if user and refresh_token and not _sets_session_cookie(response):
            sessions.set_session_cookie(response, refresh_token)
        return response
    finally:
        current_user_ctx.reset(token)


# Sensitive paths — readable only with allowed_characters (or as admin)
_SENSITIVE_SEGMENTS = {
    "profile", "personality", "config", "appearance", "scheduler",
    "knowledge", "memories", "secrets", "diary", "assignments",
    "evolution", "generate-appearance", "generate-task",
    "thoughts", "notifications", "story-arcs", "soul",
}


def _is_sensitive_character_path(path: str) -> bool:
    """Checks whether the path touches sensitive character data.

    - /characters/{name}/profile, /personality, /scheduler/*, /knowledge, ...
    - /inventory/characters/{name}/* — the inventory is private
    - /diary/*/{name}/* — the diary is private
    - /relationships/... — relationships are private
    """
    from urllib.parse import unquote
    parts = [unquote(p) for p in path.split("/") if p]

    if len(parts) >= 1 and parts[0] == "inventory":
        return True  # the whole inventory subtree is sensitive
    if len(parts) >= 1 and parts[0] == "diary":
        return True
    if len(parts) >= 1 and parts[0] == "relationships":
        return True
    if len(parts) >= 1 and parts[0] == "assignments":
        return True

    if len(parts) >= 3 and parts[0] == "characters":
        # /characters/{name}/{segment}
        seg = parts[2]
        if seg in _SENSITIVE_SEGMENTS:
            return True
    return False


def _extract_characters_from_path(path: str):
    """Extracts character names from character-scoped URLs.

    Returns List[str] — every character name referenced in the path
    (e.g. /relationships/A/B → [A, B]).

    Matches:
      /characters/{name}/*
      /inventory/characters/{name}/*
      /diary/{user_id}/{name}/*
      /assignments-for-character/{name}/* (if it exists)
      /relationships/{a}/{b}
    """
    from urllib.parse import unquote
    parts = [unquote(p) for p in path.split("/") if p]
    result = []

    reserved = {
        "list", "chatbots", "at-location", "animate", "available-models",
        "outfit-rules", "outfit-lora-options",
        "graph", "migrate", "backfill", "",
    }

    if len(parts) >= 2 and parts[0] == "characters":
        cand = parts[1]
        if cand not in reserved:
            result.append(cand)
    elif len(parts) >= 3 and parts[0] == "inventory" and parts[1] == "characters":
        result.append(parts[2])
    elif len(parts) >= 3 and parts[0] == "diary":
        # /diary/{user_id}/{name}
        cand = parts[2]
        if cand not in reserved:
            result.append(cand)
    elif len(parts) >= 3 and parts[0] == "relationships":
        # /relationships/{a}/{b}
        for c in parts[1:3]:
            if c not in reserved:
                result.append(c)
    return result


