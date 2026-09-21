#!/usr/bin/env python3
"""Smoke: the default-deny auth gate, the character filter and the login throttle.

Covers the 2026-09-20 security review findings SEC-2, SEC-6 and SEC-5 (b)+(c).
Nothing here needs a server or a world: the gate is mounted on a throwaway
Starlette app built inside this script, and the session lookup is stubbed, so
``app.server`` is never imported and no world.db is opened.

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

A) THE GATE (SEC-2) — ``auth_gate_middleware``, mounted exactly as
   ``app/server.py`` mounts it: the gate added FIRST, then CORSMiddleware,
   then ``user_context_middleware``. ``add_middleware`` prepends, so execution
   runs user_context -> CORS -> gate -> router. Expected, derived from the
   allowlist in ``auth_dependency`` by hand:

     anonymous GET /characters/list          -> 401   (not on the allowlist)
     anonymous GET /auth/status              -> 200   (login round trip)
     anonymous GET /i18n/translations/de     -> 200   (login form is translated)
     anonymous GET /play                     -> 200   (shell renders <AuthGate>)
     anonymous GET /play/self                -> 401   (data route, NOT the shell)
     anonymous GET /health                   -> 200
     anonymous GET /static/game_admin/x.js   -> 200
     anonymous GET /admin/settings, Accept: text/html
                                             -> 302 to
                                                /game-admin?return=/admin/settings
     anonymous GET /play/self, Accept: text/html
                                             -> 302 to /play?return=/play/self
     user      GET /play/self                -> 200   (player surface stays open)
     user      GET /queue/status             -> 200   (the queue panel polls it)
     user      DELETE /queue/tasks/t1        -> 200   (cancelling one's own task)
     user      GET /templates/human-roleplay -> 200   (the avatar settings render
                                               from the character template)
     user      POST /templates/human-roleplay-> 403   (writing one is admin)
     user      DELETE /characters/Mara       -> 403   (deleting a character)
     user      DELETE /characters/Mara/images/x/animation
                                             -> 200   (own gallery, deeper path)
     user      GET /admin/settings           -> 403   (admin prefix)
     user      DELETE /world/locations/x     -> 403   (admin DELETE rule)
     admin     GET /admin/settings           -> 200
     OPTIONS   /characters/list (preflight)  -> 200 + access-control-allow-origin
                                                (answered by CORSMiddleware,
                                                 never blocked by the gate)

B) THE CHARACTER FILTER (SEC-6) — the pure helpers
   ``_is_sensitive_character_path`` / ``_extract_characters_from_path`` plus
   the end-to-end behaviour through the mounted middleware for a user whose
   ``allowed_characters`` is ["Mara"]. Expected, by hand from the inverted
   rule ("everything under a character is sensitive unless the segment is in
   the small public set"):

     /characters/Kira/export       sensitive=True,  chars=['Kira'] -> 403
       (the old code had no 'export' in its sensitive list -> 200; this is the
        finding's own reproduction case)
     /secrets/Kira                 sensitive=True,  chars=['Kira'] -> 403
       (the old code extracted nothing here and classified it not sensitive)
     /inventory/items/import       -> 403 for a non-admin (admin-only route)
       (the old code ran its block only ``if chars:`` and chars was empty)
     /characters/Kira/images/profile  sensitive=False -> 200 (the Player UI
       shows the portraits of the OTHER characters in the room)
     /characters/Kira/outfit-expression -> 200 (same reason)
     /characters/Mara/profile      chars=['Mara'], allowed -> 200
     /characters/list              not character-scoped -> 200
     /inventory/items              shared item catalog, not character data -> 200

C) THE LOGIN THROTTLE (SEC-5b) — ``auth.login_retry_after``, pure. With
   LOGIN_FAIL_LIMIT=5 and LOGIN_FAIL_WINDOW_SECONDS=900, and `now` given
   explicitly:

     4 failures at t=0, now=0   -> 0        (under the limit)
     5 failures at t=0, now=0   -> 901      (900 - 0 + 1)
     5 failures at t=0, now=899 -> 2        (900 - 899 + 1)
     5 failures at t=0, now=900 -> 0        (all aged out of the window)
     5 failures, 1 of them at t=500, now=901 -> 0  (only 4 left in the window)

D) THE SECURE COOKIE (SEC-5c) — ``sessions.is_secure_request``:

     ("https", "")                -> True
     ("http",  "")                -> False   (plain local setup must still work)
     ("http",  "https")           -> True    (TLS-terminating reverse proxy)
     ("https", "http")            -> False   (header wins, first hop counts)
     ("http",  "https, http")     -> True    (first entry = client-facing hop)

E) WORLD-LEVEL WRITES ARE ADMIN-ONLY (user decision 2026-09-21) — the table
   below is ``is_admin_only_path(path, method)`` read off the four rules by
   hand. Writes are POST/PUT/PATCH/DELETE (``_WRITE_METHODS``); GET and HEAD
   are untouched by all four, so every GET row is False.

     1. everything under /world (incl. the prop-variant routes, which
        ``app/routes/prop_variants.py`` registers under the same prefix) —
        True for a write, with exactly ONE exception:
        POST /world/imagegen-enhance-prompt, the "Improve" button of the
        image-generation dialog, which the player UI reaches and which only
        rewrites the prompt text the player typed (``_PLAYER_WRITE_EXCEPTIONS``).
        The old ``_ADMIN_DELETE_PREFIXES = ("/world",)`` is folded into this
        rule; DELETE /characters/{name} keeps its own rule.
     2. everything under /rules, /intents, /events — True for a write.
     3. /inventory: writes under /inventory/items (the shared catalogue, which
        now covers the formerly exact /inventory/items/import) and under
        /inventory/rooms are True; /inventory/characters/... stays False —
        it is character-scoped and the allowed_characters filter governs it
        (the player's GiftPicker posts
        POST /inventory/characters/{avatar}/{item_id}/give).
     4. /queue: POST /queue/force-resume and DELETE /queue/tasks/clear are
        True (global queue control); DELETE /queue/tasks/{task_id} and
        POST /queue/tasks/item/{task_id}/retry stay False (the player's
        TaskPanel cancels and retries its own jobs). /queue/tasks/clear and
        /queue/tasks/{task_id} share a shape, so these two are EXACT matches,
        never a prefix.

   Prefix neighbours: ``_under`` is segment-wise, so /worldly, /rulesx,
   /eventsful, /intentsful and /inventory/itemsy are NOT under the rules above
   and stay False even for a write.

F) NO PLAYER SURFACE POSTS TO AN ADMIN-ONLY PATH — a source scan, not a
   request. It walks every write call (``apiPost``/``apiPut``/``apiPatch``/
   ``apiDelete``/``apiUpload`` and ``fetch(url, { method: ... })``) in the
   files a logged-in PLAYER can reach:

     packages/player-ui/src/**            the shared player panels
     frontend/src/player/**               the /play shell
     frontend/src/components/ImageGenDialog.tsx   slotted into /play
     frontend/src/tabs/characters/{TemplateTab,TemplateSectionForm,BodyEditor,
                                    SoulEditor,FieldImage}.tsx
                                          pulled in by AvatarSettingsPanel
     client3d/src/**                      the 3D client

   and asserts that none of their URL literals is admin-only under the rules
   of E. Template placeholders (``${...}``) become one opaque segment and a
   query string is cut off, so ``/queue/tasks/${id}`` is checked as
   ``/queue/tasks/X``. A future player feature that posts to /world therefore
   fails this smoke instead of silently 403ing in the browser.

   One documented exemption, verified by hand in the source:
     POST /world/compose-preview (ImageGenDialog) — both call sites are
     guarded by ``composeKey``, which is empty unless the ``composeRequest``
     prop is passed. The only caller that passes it is
     frontend/src/tabs/world/LocationGallery.tsx (Game-Admin); the three
     ImageGenDialog instantiations in frontend/src/player/PlayerApp.tsx do not.
   Not in the scanned set, for the same kind of reason: GameClock posts
   /world/game-time, but /play renders it ``readOnly`` (PlayerApp.tsx), which
   draws a plain <span> and no editor.

Usage:  ./.venv/bin/python scripts/smoke_auth_gate.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="authgate-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="authgate-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config  # noqa: E402
config.load(STORAGE / "config.json")

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core import auth_dependency, sessions  # noqa: E402
from app.routes import auth as auth_route  # noqa: E402


FAILS = []


def check(label, got, expected):
    ok = got == expected
    if not ok:
        FAILS.append(f"{label}: got {got!r}, expected {expected!r}")
    print(f"  [{'ok' if ok else 'FAIL'}] {label}: {got!r}")


# ── The throwaway app ────────────────────────────────────────────────
#
# Stubbed session lookup: the test client sends the role in a header instead
# of a cookie, so no DB, no sessions table, no users table is involved.
_USERS = {
    "user": {"id": "u_user", "username": "player", "role": "user",
             "allowed_characters": ["Mara"]},
    "admin": {"id": "u_admin", "username": "boss", "role": "admin",
              "allowed_characters": []},
}


def _stub_session_user(request: Request):
    return _USERS.get(request.headers.get("x-test-user", ""))


auth_dependency._get_session_user = _stub_session_user

app = FastAPI()
# SAME ORDER as app/server.py: gate first (=> innermost), then CORS, then the
# user context (=> outermost of the three).
app.middleware("http")(auth_dependency.auth_gate_middleware)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"],
                   allow_credentials=True, allow_methods=["*"],
                   allow_headers=["*"])
app.middleware("http")(auth_dependency.user_context_middleware)


@app.api_route("/{full_path:path}", methods=["GET", "POST", "DELETE", "PUT"])
async def catch_all(full_path: str):
    """Whatever survives the middleware chain lands here."""
    return {"reached": "/" + full_path}


client = TestClient(app, follow_redirects=False)


def status(method, path, role="", accept="*/*"):
    headers = {"accept": accept}
    if role:
        headers["x-test-user"] = role
    return client.request(method, path, headers=headers).status_code


def location(method, path, accept):
    r = client.request(method, path, headers={"accept": accept})
    return r.headers.get("location", "")


print("A) default-deny gate (SEC-2)")
check("anon GET /characters/list", status("GET", "/characters/list"), 401)
check("anon GET /auth/status", status("GET", "/auth/status"), 200)
check("anon GET /auth/login (POST)", status("POST", "/auth/login"), 200)
check("anon GET /i18n/translations/de", status("GET", "/i18n/translations/de"), 200)
check("anon GET /play", status("GET", "/play"), 200)
check("anon GET /play/self", status("GET", "/play/self"), 401)
check("anon GET /game-admin", status("GET", "/game-admin"), 200)
check("anon GET /health", status("GET", "/health"), 200)
check("anon GET /", status("GET", "/"), 200)
check("anon GET /static/game_admin/assets/x.js",
      status("GET", "/static/game_admin/assets/x.js"), 200)
check("anon POST /api/images", status("POST", "/api/images"), 200)
check("anon GET /api/content/catalogs", status("GET", "/api/content/catalogs"), 401)
check("anon HTML nav /admin/settings",
      status("GET", "/admin/settings", accept="text/html,application/xhtml+xml"), 302)
check("anon HTML nav /admin/settings -> where",
      location("GET", "/admin/settings", "text/html"),
      "/game-admin?return=/admin/settings")
check("anon HTML nav /play/self -> where",
      location("GET", "/play/self", "text/html"), "/play?return=/play/self")
check("user GET /play/self", status("GET", "/play/self", "user"), 200)
check("user GET /queue/status", status("GET", "/queue/status", "user"), 200)
check("user DELETE /queue/tasks/t1", status("DELETE", "/queue/tasks/t1", "user"), 200)
check("user GET /templates/human-roleplay",
      status("GET", "/templates/human-roleplay", "user"), 200)
check("user POST /templates/human-roleplay",
      status("POST", "/templates/human-roleplay", "user"), 403)
check("user DELETE /characters/Mara", status("DELETE", "/characters/Mara", "user"), 403)
check("user DELETE /characters/Mara/images/x/animation",
      status("DELETE", "/characters/Mara/images/x/animation", "user"), 200)
check("user GET /admin/settings", status("GET", "/admin/settings", "user"), 403)
check("user GET /logs/llm", status("GET", "/logs/llm", "user"), 403)
check("user DELETE /world/locations/x",
      status("DELETE", "/world/locations/x", "user"), 403)
check("user GET /world/locations", status("GET", "/world/locations", "user"), 200)
check("user GET /rules", status("GET", "/rules", "user"), 200)
check("user GET /characters/list", status("GET", "/characters/list", "user"), 200)
check("admin GET /admin/settings", status("GET", "/admin/settings", "admin"), 200)
check("admin DELETE /world/locations/x",
      status("DELETE", "/world/locations/x", "admin"), 200)

pre = client.request(
    "OPTIONS", "/characters/list",
    headers={"origin": "http://localhost:5173",
             "access-control-request-method": "GET"})
check("CORS preflight status", pre.status_code, 200)
check("CORS preflight allow-origin",
      pre.headers.get("access-control-allow-origin", ""), "http://localhost:5173")

print()
print("B) character filter (SEC-6)")
sens = auth_dependency._is_sensitive_character_path
chars = auth_dependency._extract_characters_from_path
check("sensitive /characters/Kira/export", sens("/characters/Kira/export"), True)
check("chars /characters/Kira/export", chars("/characters/Kira/export"), ["Kira"])
check("sensitive /secrets/Kira", sens("/secrets/Kira"), True)
check("chars /secrets/Kira", chars("/secrets/Kira"), ["Kira"])
check("sensitive /characters/Kira/memory/today",
      sens("/characters/Kira/memory/today"), True)
check("sensitive /characters/Kira/images/profile",
      sens("/characters/Kira/images/profile"), False)
check("sensitive /characters/Kira/outfit-expression",
      sens("/characters/Kira/outfit-expression"), False)
check("sensitive /characters/Kira/model3d/file",
      sens("/characters/Kira/model3d/file"), False)
check("sensitive /characters/list", sens("/characters/list"), False)
check("sensitive /inventory/items", sens("/inventory/items"), False)
check("sensitive /inventory/characters/Kira",
      sens("/inventory/characters/Kira"), True)
check("chars /inventory/characters/Kira",
      chars("/inventory/characters/Kira"), ["Kira"])
# /relationships/* had its own rule in both helpers. The four routes under
# that prefix were deleted (DE-14, user decision 2026-09-21) and nothing else
# lives there, so the rule had to go with them — a prefix rule outliving its
# routes silently governs whatever takes the name next.
check("sensitive /relationships/A/B", sens("/relationships/A/B"), False)
check("chars /relationships/A/B", chars("/relationships/A/B"), [])

check("user GET /characters/Kira/export",
      status("GET", "/characters/Kira/export", "user"), 403)
check("user GET /secrets/Kira", status("GET", "/secrets/Kira", "user"), 403)
check("user POST /inventory/items/import",
      status("POST", "/inventory/items/import", "user"), 403)
check("user GET /characters/Kira/images/profile",
      status("GET", "/characters/Kira/images/profile", "user"), 200)
check("user GET /characters/Kira/outfit-expression",
      status("GET", "/characters/Kira/outfit-expression", "user"), 200)
check("user GET /characters/Mara/profile",
      status("GET", "/characters/Mara/profile", "user"), 200)
check("user GET /secrets/Mara", status("GET", "/secrets/Mara", "user"), 200)
check("user GET /inventory/items", status("GET", "/inventory/items", "user"), 200)
check("admin GET /characters/Kira/export",
      status("GET", "/characters/Kira/export", "admin"), 200)

print()
print("C) login throttle (SEC-5b)")
ra = auth_route.login_retry_after
check("limit constant", auth_route.LOGIN_FAIL_LIMIT, 5)
check("window constant", auth_route.LOGIN_FAIL_WINDOW_SECONDS, 900)
check("4 failures at t=0, now=0", ra([0.0] * 4, 0.0), 0)
check("5 failures at t=0, now=0", ra([0.0] * 5, 0.0), 901)
check("5 failures at t=0, now=899", ra([0.0] * 5, 899.0), 2)
check("5 failures at t=0, now=900", ra([0.0] * 5, 900.0), 0)
check("4 old + 1 at t=500, now=901", ra([0.0] * 4 + [500.0], 901.0), 0)

print()
print("D) secure cookie (SEC-5c)")
sec = sessions.is_secure_request
check("https, no header", sec("https", ""), True)
check("http, no header", sec("http", ""), False)
check("http, x-forwarded-proto https", sec("http", "https"), True)
check("https, x-forwarded-proto http", sec("https", "http"), False)
check("http, 'https, http'", sec("http", "https, http"), True)

print()
print("E) world-level writes are admin-only")
admin_only = auth_dependency.is_admin_only_path

# (method, path, expected) — see section E of the docstring for the derivation.
WRITE_RULE_CASES = [
    # Rule 1 — /world (and the prop-variant routes registered under it)
    ("POST", "/world/locations", True),
    ("PUT", "/world/locations/tavern", True),
    ("PATCH", "/world/locations/tavern", True),
    ("DELETE", "/world/locations/tavern", True),
    ("POST", "/world/game-time", True),
    ("POST", "/world/compose-preview", True),
    ("POST", "/world/prop-variants/chair/split", True),
    ("DELETE", "/world/surface-textures/forest", True),
    ("GET", "/world/locations", False),
    ("HEAD", "/world/locations", False),
    ("GET", "/world", False),
    # the one player exception
    ("POST", "/world/imagegen-enhance-prompt", False),
    ("GET", "/world/imagegen-enhance-prompt", False),
    # ... exact, not a prefix: a deeper path is admin-only again
    ("POST", "/world/imagegen-enhance-prompt/x", True),
    # Rule 2 — /rules, /intents, /events
    ("POST", "/rules", True),
    ("PUT", "/rules/r1", True),
    ("DELETE", "/rules/r1", True),
    ("GET", "/rules", False),
    ("POST", "/intents", True),
    ("DELETE", "/intents/i1", True),
    ("GET", "/intents", False),
    ("POST", "/events", True),
    ("DELETE", "/events/e1", True),
    ("GET", "/events", False),
    # Rule 3 — /inventory
    ("POST", "/inventory/items", True),
    ("PUT", "/inventory/items/apple", True),
    ("DELETE", "/inventory/items/apple", True),
    ("POST", "/inventory/items/import", True),
    ("POST", "/inventory/items/apple/generate-image", True),
    ("POST", "/inventory/rooms/tavern/bar", True),
    ("DELETE", "/inventory/rooms/tavern/bar/apple", True),
    ("GET", "/inventory/items", False),
    ("GET", "/inventory/rooms/tavern/bar", False),
    ("POST", "/inventory/characters/Mara/apple/give", False),
    ("POST", "/inventory/characters/Mara/equip", False),
    ("DELETE", "/inventory/characters/Mara/apple", False),
    # Rule 4 — /queue
    ("POST", "/queue/force-resume", True),
    ("DELETE", "/queue/tasks/clear", True),
    ("DELETE", "/queue/tasks/abc", False),
    ("POST", "/queue/tasks/item/abc/retry", False),
    ("GET", "/queue/status", False),
    ("GET", "/queue/tasks/status", False),
    ("GET", "/queue/force-resume", False),
    # Segment-wise prefixes: the neighbours are NOT matched
    ("POST", "/worldly", False),
    ("POST", "/worldly/locations", False),
    ("POST", "/rulesx", False),
    ("POST", "/intentsful/x", False),
    ("POST", "/eventsful/x", False),
    ("POST", "/inventory/itemsy", False),
    ("POST", "/inventory/roomsy/x", False),
    ("POST", "/queue/force-resumed", False),
]
for _m, _p, _exp in WRITE_RULE_CASES:
    check(f"admin_only {_m} {_p}", admin_only(_p, _m), _exp)

# The same rules end to end through the mounted middleware: a player is
# refused, an admin passes, and the open routes stay open for the player.
for _m, _p in [("POST", "/world/locations"), ("DELETE", "/world/locations/x"),
               ("POST", "/rules"), ("POST", "/intents"), ("POST", "/events"),
               ("POST", "/inventory/items"), ("POST", "/inventory/rooms/a/b"),
               ("POST", "/queue/force-resume"), ("DELETE", "/queue/tasks/clear")]:
    check(f"user {_m} {_p}", status(_m, _p, "user"), 403)
    check(f"admin {_m} {_p}", status(_m, _p, "admin"), 200)
for _m, _p in [("POST", "/world/imagegen-enhance-prompt"),
               ("POST", "/inventory/characters/Mara/apple/give"),
               ("DELETE", "/queue/tasks/abc"),
               ("POST", "/queue/tasks/item/abc/retry"),
               ("GET", "/world/locations"), ("GET", "/rules"),
               ("GET", "/events"), ("GET", "/inventory/items")]:
    check(f"user {_m} {_p}", status(_m, _p, "user"), 200)

print()
print("F) no player surface writes to an admin-only path")

import re  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
# Every file a logged-in player's browser can execute — see section F.
PLAYER_TREES = [
    REPO / "packages" / "player-ui" / "src",
    REPO / "frontend" / "src" / "player",
    REPO / "client3d" / "src",
]
PLAYER_FILES = [
    REPO / "frontend" / "src" / "components" / "ImageGenDialog.tsx",
    REPO / "frontend" / "src" / "tabs" / "characters" / "TemplateTab.tsx",
    REPO / "frontend" / "src" / "tabs" / "characters" / "TemplateSectionForm.tsx",
    REPO / "frontend" / "src" / "tabs" / "characters" / "BodyEditor.tsx",
    REPO / "frontend" / "src" / "tabs" / "characters" / "SoulEditor.tsx",
    REPO / "frontend" / "src" / "tabs" / "characters" / "FieldImage.tsx",
]
# Write calls whose URL IS admin-only but which no player can trigger. Each
# entry needs a reason that was verified in the source, not a hunch.
SCAN_EXEMPT = {
    ("POST", "/world/compose-preview"):
        "ImageGenDialog: guarded by composeKey, set only via the composeRequest "
        "prop — passed by tabs/world/LocationGallery.tsx (Game-Admin), never by "
        "the three ImageGenDialog sites in player/PlayerApp.tsx",
}

_CALL_RE = re.compile(
    r"(?:api(?P<api>Post|Put|Patch|Delete|Upload)\s*(?:<[^()]*?>)?\s*\(|fetch\s*\()")
_METHOD_RE = re.compile(r"method\s*:\s*['\"](\w+)['\"]")
_API_METHOD = {"Post": "POST", "Put": "PUT", "Patch": "PATCH",
               "Delete": "DELETE", "Upload": "POST"}


def _string_literal(tail: str):
    """The first argument when it is a plain/template string, else None."""
    tail = tail.lstrip()
    if not tail or tail[0] not in "'\"`":
        return None
    quote, i, out = tail[0], 1, []
    while i < len(tail) and tail[i] != quote:
        if tail[i] == "\\":
            i += 2
            continue
        out.append(tail[i])
        i += 1
    return "".join(out)


def _normalise(url: str) -> str:
    """`${expr}` -> one opaque segment, query string dropped."""
    return re.sub(r"\$\{[^}]*\}", "X", url).split("?")[0].split("#")[0]


def _scan(text: str):
    """Yields (method, normalised_url) for every write call with a literal URL."""
    for m in _CALL_RE.finditer(text):
        tail = text[m.end():m.end() + 600]
        lit = _string_literal(tail)
        if lit is None or not lit.startswith("/"):
            continue
        api = m.group("api")
        if api:
            method = _API_METHOD[api]
        else:
            # A bare fetch() without an options object is a GET.
            hit = _METHOD_RE.search(tail)
            method = hit.group(1).upper() if hit else "GET"
        if method not in auth_dependency._WRITE_METHODS:
            continue
        yield method, _normalise(lit)


sources = list(PLAYER_FILES)
for tree in PLAYER_TREES:
    check(f"player tree exists: {tree.relative_to(REPO)}", tree.is_dir(), True)
    sources += [p for p in tree.rglob("*") if p.suffix in (".ts", ".tsx")]

found, offenders = {}, []
for src in sorted(set(sources)):
    if not src.is_file():
        check(f"player file exists: {src.relative_to(REPO)}", False, True)
        continue
    for method, url in _scan(src.read_text(errors="replace")):
        found.setdefault((method, url), set()).add(str(src.relative_to(REPO)))
for (method, url), where in sorted(found.items()):
    if not admin_only(url, method):
        continue
    if (method, url) in SCAN_EXEMPT:
        continue
    offenders.append(f"{method} {url}  <- {', '.join(sorted(where))}")

print(f"  scanned {len(sources)} files, {len(found)} distinct write calls")
# A lower bound so a broken regex cannot pass by finding nothing. Counted on
# 2026-09-21: 55 distinct (method, url) write pairs across 146 scanned files.
check("write calls found (>= 40)", len(found) >= 40, True)
check("player writes hitting an admin-only path", offenders, [])
# The exemption list must not rot: every entry has to still be found and still
# be admin-only, otherwise it is silently covering nothing.
for key in SCAN_EXEMPT:
    check(f"exemption still present {key[0]} {key[1]}",
          key in found and admin_only(key[1], key[0]), True)

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}):")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("all checks passed")
