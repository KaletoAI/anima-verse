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
                    content={"detail": f"No access to character '{blocked_char}'"},
                )
            # A path classified sensitive whose character we cannot name is a
            # refusal, not a pass: that gap is what let /secrets/{name} and the
            # inventory import through before (SEC-6). Only paths the
            # classifier calls sensitive reach this, so the ordinary
            # non-character player routes are untouched.
            if is_sensitive and not chars:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "No access to this character data"},
                )
        response = await call_next(request)
        # Sliding sessions have two halves: the DB row (done in get_session) and
        # the browser cookie. Without re-issuing it, the browser drops the cookie
        # exactly SESSION_TTL_HOURS after login — mid-session. Authenticated
        # requests only; an anonymous request never gets a cookie.
        refresh_token = getattr(request.state, "session_refresh_token", "")
        if user and refresh_token and not _sets_session_cookie(response):
            sessions.set_session_cookie(
                response, refresh_token,
                secure=sessions.request_is_secure(request))
        return response
    finally:
        current_user_ctx.reset(token)


# Character-scoped URLs: which path segments ANY logged-in user may read for
# ANY character. Everything else under a character is sensitive.
#
# Inverted on purpose (SEC-6): the old list named the sensitive segments, so
# every segment nobody had thought of — /export, /memory/*, /outfit-batch — was
# public by accident. The public set is small, finite and derived from what the
# Player UI and the 3D client actually need to show the OTHER characters in a
# room: their pictures, their portrait, where they are, what they are doing and
# their 3D model.
_PUBLIC_CHARACTER_SEGMENTS = {
    "images", "profile-image", "expressions", "outfit-expression",
    "current-location", "current-activity", "current-feeling",
    "model", "model3d", "silhouette",
}

# First segment after /characters/ that is a COLLECTION endpoint, not a
# character name (/characters/list, /characters/at-location, ...).
_RESERVED_CHARACTER_NAMES = {
    "list", "chatbots", "at-location", "animate", "available-models",
    "outfit-rules", "outfit-lora-options", "skills", "create", "import",
    "graph", "migrate", "backfill", "",
}


def _path_parts(path: str):
    from urllib.parse import unquote
    return [unquote(p) for p in path.split("/") if p]


def _is_sensitive_character_path(path: str) -> bool:
    """Checks whether the path touches sensitive character data.

    - /characters/{name}/{segment} — sensitive unless the segment is public
    - /characters/{name} — the character itself (read/delete)
    - /secrets/{name}/* — secrets are private
    - /inventory/characters/{name}/* — a character's inventory is private
      (the shared item catalog under /inventory/items is NOT character data)
    - /diary/*, /relationships/*, /assignments/* — private
    """
    parts = _path_parts(path)
    if not parts:
        return False
    head = parts[0]

    if head == "characters":
        if len(parts) < 2 or parts[1] in _RESERVED_CHARACTER_NAMES:
            return False
        if len(parts) == 2:
            return True
        return parts[2] not in _PUBLIC_CHARACTER_SEGMENTS
    if head == "secrets":
        return True
    if head == "inventory":
        return len(parts) >= 2 and parts[1] == "characters"
    if head in ("diary", "relationships", "assignments"):
        return True
    return False


def _extract_characters_from_path(path: str):
    """Extracts character names from character-scoped URLs.

    Returns List[str] — every character name referenced in the path
    (e.g. /relationships/A/B → [A, B]).

    Matches:
      /characters/{name}/*
      /secrets/{name}/*
      /inventory/characters/{name}/*
      /diary/{user_id}/{name}/*
      /relationships/{a}/{b}
    """
    parts = _path_parts(path)
    result = []

    if len(parts) >= 2 and parts[0] == "characters":
        cand = parts[1]
        if cand not in _RESERVED_CHARACTER_NAMES:
            result.append(cand)
    elif len(parts) >= 2 and parts[0] == "secrets":
        cand = parts[1]
        if cand not in _RESERVED_CHARACTER_NAMES:
            result.append(cand)
    elif len(parts) >= 3 and parts[0] == "inventory" and parts[1] == "characters":
        result.append(parts[2])
    elif len(parts) >= 3 and parts[0] == "diary":
        # /diary/{user_id}/{name}
        cand = parts[2]
        if cand not in _RESERVED_CHARACTER_NAMES:
            result.append(cand)
    elif len(parts) >= 3 and parts[0] == "relationships":
        # /relationships/{a}/{b}
        for c in parts[1:3]:
            if c not in _RESERVED_CHARACTER_NAMES:
                result.append(c)
    return result


# ── Default-deny gate (SEC-2) ─────────────────────────────────────────
#
# Authentication used to be per route: a request without a session simply ran
# through every middleware and reached the router, so hundreds of endpoints
# answered anonymous callers. The gate turns that around — everything needs a
# session unless it is on the allowlist below.
#
# The allowlist is what an unauthenticated BROWSER needs to reach a login form,
# plus the two endpoints that carry their own credential:
#   /                      -> redirect to /play
#   /play, /game-admin     -> the React shells; both render <AuthGate>, which
#                             shows the login form itself. A 401 here would
#                             hand back JSON and no login form could ever load.
#   /static/*              -> the built bundles + CSS the shells load
#   /i18n/*                -> <I18nProvider> wraps <AuthGate>; the login form is
#                             already translated
#   /auth/login|logout|status -> the login round trip itself
#   /health, /favicon.ico  -> liveness + the browser's automatic icon request
#   /api/images            -> authenticated by X-API-Key
_PUBLIC_EXACT = {
    "/",
    "/health",
    "/favicon.ico",
    "/play", "/play/",
    "/game-admin", "/game-admin/",
    "/auth/login", "/auth/logout", "/auth/status",
    "/api/images",
}
_PUBLIC_PREFIXES = ("/static", "/i18n")

# Coarse second rule: prefixes a logged-in NON-admin has no business in. This
# is not a substitute for the per-route Depends(require_admin) that some of
# these routers already carry — it is the blanket for the routers that carry
# none at all. Annotating ~250 single routes would be the alternative.
_ADMIN_PREFIXES = (
    "/admin",          # settings, users, models, agent-loop, assist, observer,
                       # storyteller, world-setup
    "/api/content",    # marketplace (installs executable packages)
    "/dashboard",
    "/improvements",
    "/logs",
    "/npc",
    "/world-dev",
    "/story",          # storyteller files (raw read/write/delete)
    "/story-dev",
    "/scheduler",
)
# Readable for a player, writable only for an admin. /templates/{id} is what
# the player's own avatar settings render from (character settings come from
# the template, never from a hardcoded form) — writing a template is not.
_ADMIN_WRITE_PREFIXES = ("/templates",)
# Single state-changing routes that belong to an otherwise player-facing
# router. /inventory/items/import and /characters/import unpack an uploaded
# ZIP into the storage directory; /characters/create makes a new character.
_ADMIN_EXACT = {
    "/inventory/items/import",
    "/characters/import",
    "/characters/create",
}
# Deleting a location, a prop or a surface texture is an admin act.
_ADMIN_DELETE_PREFIXES = ("/world",)
_WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")


def _under(path: str, prefix: str) -> bool:
    """True when ``path`` IS ``prefix`` or lies below it — segment-wise, so
    ``/playful`` never counts as being under ``/play``."""
    return path == prefix or path.startswith(prefix + "/")


def is_public_path(path: str) -> bool:
    """True for the paths that answer without a session."""
    if path in _PUBLIC_EXACT:
        return True
    return any(_under(path, p) for p in _PUBLIC_PREFIXES)


def is_admin_only_path(path: str, method: str) -> bool:
    """True when only an admin may call this path with this method."""
    method = method.upper()
    if path in _ADMIN_EXACT:
        return True
    if any(_under(path, p) for p in _ADMIN_PREFIXES):
        return True
    if method in _WRITE_METHODS:
        if any(_under(path, p) for p in _ADMIN_WRITE_PREFIXES):
            return True
    if method == "DELETE":
        if any(_under(path, p) for p in _ADMIN_DELETE_PREFIXES):
            return True
        # DELETE /characters/{name} removes the character itself. Deeper
        # deletes under a character (a gallery image, an animation) stay with
        # the player and are covered by the allowed_characters filter.
        parts = _path_parts(path)
        if (len(parts) == 2 and parts[0] == "characters"
                and parts[1] not in _RESERVED_CHARACTER_NAMES):
            return True
    return False


def wants_html(method: str, accept: str) -> bool:
    """True for a browser NAVIGATION rather than an API call.

    A navigation gets a redirect to the login page (a JSON 401 would just be
    printed as text in the address bar); everything else — fetch/XHR, <img>,
    the three.js loaders — gets the 401 its client already knows how to
    handle (it raises `auth:required` and the SPA shows its login form).
    """
    return method.upper() in ("GET", "HEAD") and "text/html" in (accept or "").lower()


def login_redirect_target(path: str) -> str:
    """Where an anonymous navigation is sent so the user can sign in.

    Both shells render <AuthGate>, and its login form reads ``?return=`` and
    navigates there after a successful login.
    """
    from urllib.parse import quote
    base = "/game-admin" if any(_under(path, p) for p in _ADMIN_PREFIXES) else "/play"
    return f"{base}?return={quote(path, safe='/')}"


async def auth_gate_middleware(request: Request, call_next):
    """Default-deny: no session -> 401 (or a redirect for a navigation).

    Registered so that it runs INSIDE user_context_middleware — it reads the
    user that one has already resolved into the contextvar. CORS preflights
    are never gated: they carry no cookie by definition and are answered by
    CORSMiddleware further in.
    """
    from fastapi.responses import JSONResponse, RedirectResponse

    path = request.url.path
    method = request.method.upper()

    if method == "OPTIONS" or is_public_path(path):
        return await call_next(request)

    user = current_user_ctx.get()
    if not user:
        if wants_html(method, request.headers.get("accept", "")):
            return RedirectResponse(url=login_redirect_target(path), status_code=302)
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})

    if user.get("role") != users.ROLE_ADMIN and is_admin_only_path(path, method):
        return JSONResponse(status_code=403, content={"detail": "Admin role required"})

    return await call_next(request)
