#!/usr/bin/env python3
"""Smoke: the account language settings (GET/POST /account/language).

Usage:
    ./.venv/bin/python scripts/smoke_account_language.py

Pure: a throwaway storage directory is pinned with ``paths.init`` BEFORE the
first app import, the world DB is created there, and the two routes are mounted
on a throwaway FastAPI app together with the real auth gate — no server, no
world.db of a real world, no network, no LLM.

WHY

``system_language`` and ``translation_mode`` used to be writable only through
``POST /store/{user_id}/user_profile`` — the generic key-value surface of the
vanilla UI that was removed in commit 3f434d7. The two settings survived the UI
(``get_user_language_instruction`` turns them into "Always respond in German.",
``models/rules.py`` localizes rule messages with them, ``core/random_events.py``
names the language in its prompts), so deleting the route without a replacement
would have left a setting the server honours and nobody can change.

EXPECTED VALUES, derived by hand from the sources
--------------------------------------------------------------------------
[1] Defaults, from ``app/models/account._default_profile`` — a fresh world
    answers ``system_language="de"``, ``translation_mode="native"``.

[2] The option lists come from the ONE source
    ``shared/config/languages.json`` (12 entries, "de" .. "ko"; served by
    ``/i18n/languages`` as well) and from
    ``app/models/account.TRANSLATION_MODES`` = ("native", "translate").
    The GET therefore offers exactly those values — no second, hand-kept list.

[3] Round trip: POST {"system_language": "en", "translation_mode": "translate"}
    -> 200, and BOTH a following GET and a direct ``get_language_settings()``
    read report the new pair. The write must reach the DB, not only the
    response.

[4] Validation, because the value ends up inside a prompt:
      * an unknown language code ("xx")    -> 400
      * an unknown translation mode ("no") -> 400
      * a partial POST (only the mode)     -> 200 and keeps the language
    and a rejected POST must not have changed the stored pair.

[5] The language instruction derived from the pair
    (``get_user_language_instruction``, the value that goes into the prompt):
      * ("en", "native")    -> "Always respond in English."   (label from
                               languages.json, NOT a second hard-coded map)
      * ("de", "native")    -> "Always respond in German."
      * (any, "translate")  -> ""  (the translation layer handles it)

[6] The auth gate: ``/account/language`` is on no allowlist, so an anonymous
    GET is a 401 — checked through the real ``auth_gate_middleware``, mounted
    exactly as app/server.py mounts it (same harness shape as
    scripts/smoke_auth_gate.py).

FAILS BEFORE / PASSES AFTER: before this change the module
``app.routes.account`` had no ``/language`` route at all, so [2]-[4] and [6]
answer 404/405 instead, and ``app.models.account`` exported neither
``get_language_settings`` nor ``TRANSLATION_MODES`` — the import at the top
would already raise. Confirmed by reading ``git show HEAD:app/routes/account.py``
(three routes, none of them /language) rather than by running it.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="account-language-smoke-"))
_CLIPS = tempfile.mkdtemp(prefix="account-language-clips-")
os.environ["ANIMATION_CLIPS_DIR"] = _CLIPS

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core import auth_dependency  # noqa: E402
from app.models.account import (  # noqa: E402
    TRANSLATION_MODES, get_language_settings, get_user_language_instruction,
    save_language_settings)
from app.routes import account as account_route  # noqa: E402

FAILS: list[str] = []


def check(label: str, got, expected) -> None:
    ok = got == expected
    if not ok:
        FAILS.append(f"{label}: got {got!r}, expected {expected!r}")
    print(f"  [{'ok' if ok else 'FAIL'}] {label}: {got!r}")


# ── throwaway app: the real router behind the real gate ────────────────────
_USERS = {
    "user": {"id": "u_user", "username": "player", "role": "user",
             "allowed_characters": []},
}


def _stub_session_user(request: Request):
    return _USERS.get(request.headers.get("x-test-user", ""))


auth_dependency._get_session_user = _stub_session_user

app = FastAPI()
app.include_router(account_route.router)
# SAME ORDER as app/server.py: gate first (=> innermost), then CORS, then the
# user context (=> outermost of the three).
app.middleware("http")(auth_dependency.auth_gate_middleware)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"],
                   allow_credentials=True, allow_methods=["*"],
                   allow_headers=["*"])
app.middleware("http")(auth_dependency.user_context_middleware)

client = TestClient(app, follow_redirects=False)
AUTH = {"x-test-user": "user"}


def main() -> int:
    print("smoke_account_language")

    print("\n[1] defaults of a fresh world")
    r = client.get("/account/language", headers=AUTH)
    check("GET status", r.status_code, 200)
    body = r.json()
    check("default system_language", body.get("system_language"), "de")
    check("default translation_mode", body.get("translation_mode"), "native")

    print("\n[2] the option lists are the single source")
    codes = [o["value"] for o in body.get("languages", [])]
    check("language codes", codes,
          ["de", "en", "fr", "es", "it", "pt", "nl", "pl", "ru", "ja", "zh", "ko"])
    check("English label of 'en'",
          [o["label"] for o in body["languages"] if o["value"] == "en"], ["English"])
    check("translation modes", body.get("translation_modes"), list(TRANSLATION_MODES))
    check("TRANSLATION_MODES itself", list(TRANSLATION_MODES), ["native", "translate"])

    print("\n[3] round trip through the DB")
    r = client.post("/account/language", headers=AUTH,
                    json={"system_language": "en", "translation_mode": "translate"})
    check("POST status", r.status_code, 200)
    check("POST echo", (r.json().get("system_language"), r.json().get("translation_mode")),
          ("en", "translate"))
    again = client.get("/account/language", headers=AUTH).json()
    check("GET reads it back",
          (again.get("system_language"), again.get("translation_mode")),
          ("en", "translate"))
    stored = get_language_settings()
    check("the model reads it back",
          (stored["system_language"], stored["translation_mode"]), ("en", "translate"))

    print("\n[4] validation")
    r = client.post("/account/language", headers=AUTH, json={"system_language": "xx"})
    check("unknown language", r.status_code, 400)
    r = client.post("/account/language", headers=AUTH, json={"translation_mode": "no"})
    check("unknown mode", r.status_code, 400)
    unchanged = get_language_settings()
    check("a rejected POST changed nothing",
          (unchanged["system_language"], unchanged["translation_mode"]),
          ("en", "translate"))
    r = client.post("/account/language", headers=AUTH, json={"translation_mode": "native"})
    check("partial POST status", r.status_code, 200)
    partial = get_language_settings()
    check("partial POST keeps the language",
          (partial["system_language"], partial["translation_mode"]), ("en", "native"))

    print("\n[5] the derived language instruction (what the prompt sees)")
    check("en/native", get_user_language_instruction(), "Always respond in English.")
    save_language_settings("de", "native")
    check("de/native", get_user_language_instruction(), "Always respond in German.")
    save_language_settings("de", "translate")
    check("translate mode", get_user_language_instruction(), "")

    print("\n[6] the auth gate")
    check("anonymous GET", client.get("/account/language").status_code, 401)
    check("anonymous POST",
          client.post("/account/language", json={"system_language": "en"}).status_code,
          401)

    print()
    if FAILS:
        print(f"FAILED ({len(FAILS)}):")
        for f in FAILS:
            print("  " + f)
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        shutil.rmtree(STORAGE, ignore_errors=True)
        shutil.rmtree(_CLIPS, ignore_errors=True)
    sys.exit(rc)
