#!/usr/bin/env python3
"""Smoke: the character list's open-step badges (Ruling A112) — ``figure_build.open_steps`` and
``GET /characters/open-steps``.

Usage: ./.venv/bin/python scripts/smoke_open_steps.py

Runs without a server on a temporary world (``STORAGE_DIR`` / ``INSTANCE_DIR`` set to temp dirs BEFORE
``app.server`` is imported; that import calls ``paths.init()`` / ``paths.init_instance()`` itself). The Build's
plan is the source of truth and is NOT re-derived here: ``figure_build.plan`` is replaced by fixed step lists, so
what is checked is the split and the counting on top of it. Expected values, by hand:

A) Mara's plan = plain_body (6 jobs, manual) · base_repair (0) · shape (4) · pieces (None — unknown) ·
   assemble (0).
   BASE_STEPS = {plain_body, base_repair, tip_smoothing}, so
     base   = [plain_body, base_repair] -> count 2, hub_jobs 6 + 0 = 6, hold True (plain_body is manual)
     outfit = [shape, pieces, assemble] -> count 3, hub_jobs None (pieces unknown), hold False
   Each row's ``hold`` = failed or manual: [True, False] / [False, False, False].
B) Nell's plan = texture (3, failed "view refused") · fits (0)
     base   -> count 0, hub_jobs 0, hold False
     outfit -> count 2, hub_jobs 3, hold True (texture failed), why "view refused"
C) Memo: a second ``open_steps("Mara")`` with nothing changed does not call ``plan`` again (calls stay 1).
D) A plan that raises -> empty groups + ``error`` (never an exception).
E) The route: admin GET -> 200 and only Mara and Nell (Olli's plan is empty, so he is absent);
   player GET -> 403 (``require_admin``); anonymous GET -> 401 (default-deny gate).
F) "open-steps" is a reserved route segment, so no character can shadow the URL.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="smoke_open_steps_"))
os.environ["STORAGE_DIR"] = str(TMP / "world")
os.environ["INSTANCE_DIR"] = str(TMP / "instance")
os.environ["ANIMATION_CLIPS_DIR"] = str(TMP / "clips")
(TMP / "world").mkdir()
(TMP / "instance").mkdir()
(TMP / "clips").mkdir()

from app.core import paths  # noqa: E402
paths.init(str(TMP / "world"))
paths.init_instance(str(TMP / "instance"))

from fastapi.testclient import TestClient  # noqa: E402
from app.server import app  # noqa: E402
from app.core import figure_build, sessions, users  # noqa: E402
from app.core.character_name import RESERVED_ROUTE_SEGMENTS  # noqa: E402
from app.core.figure_build import Step  # noqa: E402

failures = []


def check(name, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + f"{name}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        failures.append(name)


PLANS = {
    "Mara": [Step("plain_body", "Plain body: views 4 + mesh + rig", 6, manual="No base body yet"),
             Step("base_repair", "Mesh repair", 0), Step("shape", "Body shape: views 2 + mesh + rig", 4),
             Step("pieces", "Own mesh · Coat", None, item_id="i1"), Step("assemble", "Assemble the figure", 0)],
    "Nell": [Step("texture", "Texture: views 3", 3, failed="view refused"), Step("fits", "Fits on the CPU", 0)],
    "Olli": [],
}
calls = {"n": 0}


def fake_plan(name, *, profile=None, explicit=True, resolved=None):
    calls["n"] += 1
    if name == "Boom":
        raise RuntimeError("broken sidecar")
    return list(PLANS.get(name, []))


figure_build.plan = fake_plan
from app.core import figure  # noqa: E402
# The memo key's first field is the figure generation (stored only while it did not move); no world reads.
figure_build._info_key = lambda name, profile, build: (figure._generation[0], name)
figure_build._profile_of = lambda name, profile: {}

# A) and C)
a = figure_build.open_steps("Mara")
check("A base count", a["base"]["count"], 2)
check("A base hub_jobs", a["base"]["hub_jobs"], 6)
check("A base hold", a["base"]["hold"], True)
check("A base rows hold", [r["hold"] for r in a["base"]["steps"]], [True, False])
check("A outfit count", a["outfit"]["count"], 3)
check("A outfit hub_jobs", a["outfit"]["hub_jobs"], None)
check("A outfit hold", a["outfit"]["hold"], False)
check("A building", a["building"], False)
figure_build.open_steps("Mara")
check("C memo: plan called once", calls["n"], 1)
# B)
b = figure_build.open_steps("Nell")
check("B base", (b["base"]["count"], b["base"]["hub_jobs"], b["base"]["hold"]), (0, 0, False))
check("B outfit", (b["outfit"]["count"], b["outfit"]["hub_jobs"], b["outfit"]["hold"]), (2, 3, True))
check("B why", b["outfit"]["steps"][0]["why"], "view refused")
# D)
d = figure_build.open_steps("Boom")
check("D error", (d["base"]["count"], d["outfit"]["count"], d.get("error")), (0, 0, "broken sidecar"))
# F)
check("F reserved", "open-steps" in RESERVED_ROUTE_SEGMENTS, True)

# E) the route under the real gate
import app.models.character as character_model  # noqa: E402
character_model.list_available_characters = lambda include_pooled=False, include_dormant=False, **_: [
    "Mara", "Nell", "Olli"]
admin = users.create_user("demo", "demo-pass-123456", role="admin")
player = users.create_user("demo2", "demo-pass-123456", role="user")
anon = TestClient(app, follow_redirects=False)
check("E anonymous", anon.get("/characters/open-steps").status_code, 401)
pc = TestClient(app, follow_redirects=False)
pc.cookies.set(sessions.SESSION_COOKIE_NAME, sessions.create_session(player))
check("E player", pc.get("/characters/open-steps").status_code, 403)
ac = TestClient(app, follow_redirects=False)
ac.cookies.set(sessions.SESSION_COOKIE_NAME, sessions.create_session(admin))
r = ac.get("/characters/open-steps")
check("E admin status", r.status_code, 200)
check("E admin names", sorted(r.json()["characters"]), ["Mara", "Nell"])
check("E admin Mara base", r.json()["characters"]["Mara"]["base"]["count"], 2)

print("FAILED: " + ", ".join(failures) if failures else "all ok")
sys.exit(1 if failures else 0)
