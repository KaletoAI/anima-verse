#!/usr/bin/env python3
"""Smoke run for the temporary-NPC finish gate (plan-npc-leben, task 1).

Throwaway storage, throwaway world DB, throwaway task queue — no server, no
real world is touched. NOTHING is generated here: the three producers (profile
image, T-pose render, mesh) are replaced by counting stubs that write the very
files the gate looks for. The gate itself runs unstubbed against REAL files on
disk, because "does the file exist" is the one thing this feature must not
fake (feedback_pruefe_am_verbraucher).

THE RULE, by hand — the gate matrix of the brief's § 0 A:

    A temporary NPC may be placed only when all three of these hold —

      1. profile_image      `get_character_profile_image(name)` is not empty
                            AND `get_character_images_dir(name)/<that name>`
                            exists on disk. A profile field pointing at a file
                            somebody deleted is NOT a profile image.
      2. model3d            `find_model3d(name, current_outfit_state(name)[2])`
                            finds a mesh for the EXACT worn signature. Never
                            `find_model3d_serving` — that one falls back to
                            other outfits and would call a foreign mesh "done".
      3. outfit_description `profile["outfit_description"].strip()` is not
                            empty.

    `npc_assets_complete(name)` reports what is MISSING in exactly that order,
    so an empty list means "ready". Hand-derived expectations:

  [1] A fresh NPC created by `apply_npc` with no image, no mesh and no outfit
      text is missing all three, in the declared order:
        ["profile_image", "model3d", "outfit_description"]
      Filling `outfit_description` alone leaves ["profile_image", "model3d"].
      Pointing `profile_image` at "face.png" WITHOUT writing the file leaves
      the same two entries — criterion 1 is a file check, not a field check.
      Writing the file drops it to ["model3d"].
      The worn signature of an NPC with no equipment is derivable by hand:
      `current_outfit_state` hashes the equipped signature of ({}, []) — the
      empty string — so it is md5("")[:12] = "d41d8cd98f00" (md5 of the empty
      string is d41d8cd98f00b204e9800998ecf8427e). A `<sig>.glb` under that
      name in `<char>/model3d/` empties the list; a mesh stored beside it
      under a DIFFERENT signature does not count.

  [2] The gate is CONFIGURED and TEMPLATE-BOUND. `npc.require_assets` false =
      the old behaviour (never held back), true = hold an unfinished NPC back.
      A name whose template does not carry `temporary_npc` (`is_temporary_npc`)
      is never gated — that is what keeps the ordinary cast out of this.

  [3] `apply_npc` with the gate armed and a location given: the character
      EXISTS (the sheet is written exactly as before — the gate sits after the
      apply, not before it), its row status is 'pooled', its current_location
      is "" (it was never placed), the Game-Admin pool row says what it waits
      for, and the queue holds EXACTLY ONE npc_assets task carrying
      name + location_id + room_id. A second `apply_npc` for the
      same NPC adds NO second task (`submit(deduplicate=True)` matches on
      task_type + agent_name), so the count stays 1. With `require_assets`
      false the same call places it: status '', location set, no task at all.

  [4] `revive_from_pool` uses the very same gate — on an NPC that went into
      the pool the real way (`pool_npc`, which is what takes it off the map) —
      and, when the gate holds it back, still returns True: its caller
      (`npc_spawn.spawn_for_slot`) reads False as "the pool did not deliver"
      and would run the three-turn generation pipeline for an NPC that is
      already claimed. It stays pooled, it stands nowhere, one job is queued.

  [5] The handler places what is already complete WITHOUT generating: with all
      three criteria satisfied up front, all three producer stubs stay at 0
      calls, the status goes back to '' and location + room are set.

  [6] The handler produces ONLY what is missing (partial-failure resumption).
      Gate and handler end to end: an NPC with an outfit text but neither
      image nor mesh is held back with the pool reason "waiting for
      profile_image, model3d", and the handler then calls the image stub once,
      the T-pose stub once and the mesh stub once, places it and clears the
      reason. An NPC that only lacks the mesh calls the image stub NOT AT ALL
      (0) and the other two once each — the T-pose is the mesh's input, so it
      rides on the model3d criterion instead of having one of its own.

  [7] A missing `outfit_description` is NOT generated. It is a text field the
      generation turn fills (`npc-temporary.json` marks it `required`), so the
      handler returns ok=False without touching a single producer and leaves
      the NPC pooled — a retry would only burn GPU time on the other two.

  [8] A producer that does not deliver leaves the NPC pooled and RAISES, which
      is what hands the task back to the queue's own retry mechanism. Nothing
      is placed: status stays 'pooled', current_location stays "".

  [9] A wanderer is sent on its way BY THE HANDLER: with `wanderer` true the
      placement is followed by exactly one `_send_wanderer` call for the
      target. The payload's target is a hint, the profile is the truth (the
      wanderer path stamps `wander_target` only AFTER it asks for the
      placement), so a payload without one falls back to the profile field.
      A non-wanderer payload sends nobody.

 [10] `npc-temporary.json` marks `outfit_description` required, so
      `validate_npc_fields` demands it in the generation/repair turn — the
      gate's third criterion is enforced at its source, not only here.

Usage:  ./.venv/bin/python scripts/smoke_npc_assets.py
"""
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="npcassets-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="npcassets-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core import model3d, model_refs, npc_assets as na, npc_spawn  # noqa: E402
from app.core.npc_ops import apply_npc, validate_npc_fields  # noqa: E402
from app.core.npc_pool import (list_pool, pool_npc,  # noqa: E402
                               revive_from_pool)
from app.core.task_queue import get_task_queue  # noqa: E402
from app.imagegen import service as imagegen_service  # noqa: E402
from app.models import world  # noqa: E402
from app.models.character import (get_character_current_location,  # noqa: E402
                                  get_character_current_room,
                                  get_character_dir,
                                  get_character_images_dir,
                                  get_character_profile,
                                  get_character_status,
                                  save_character_profile,
                                  set_character_profile_image,
                                  set_character_status)

# No worker threads in a smoke: `submit` auto-starts the pool on the first
# task, and this run inspects the queued ROWS instead of executing them (the
# handler is called directly, so a worker would only race with it).
get_task_queue()._started = True
QUEUE_DB = STORAGE / "task_queue.db"

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def raises(label, exc_type, fn):
    global CHECKED
    CHECKED += 1
    try:
        fn()
    except exc_type as e:
        print(f"  OK  {label}: {exc_type.__name__}({str(e)[:60]!r})")
        return
    except Exception as e:  # noqa: BLE001 — anything else is the defect
        print(f"  FAIL {label}: {type(e).__name__}({e})")
        FAILURES.append(label)
        return
    print(f"  FAIL {label}: no exception")
    FAILURES.append(label)


# ── helpers ─────────────────────────────────────────────────────────────────

def set_require_assets(value: bool) -> None:
    cfg = config.get_all()
    cfg.setdefault("npc", {})["require_assets"] = value
    config.save(cfg, STORAGE / "config.json")


def tasks_for(name: str):
    """The npc_assets rows of one NPC, read straight out of the queue DB."""
    conn = sqlite3.connect(f"file:{QUEUE_DB}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT payload FROM tasks WHERE task_type=? AND agent_name=?",
            (na.TASK_TYPE, name)).fetchall()
    finally:
        conn.close()
    return [json.loads(r[0]) for r in rows]


LOC = world.add_location("Crossroads Inn", "A stone house at the fork.",
                         rooms=[{"name": "Taproom", "description": "Benches."},
                                {"name": "Yard", "description": "Mud."}])
LOC_ID = LOC["id"]
TAPROOM = world.get_location_by_id(LOC_ID)["rooms"][0]["id"]

LOC2 = world.add_location("Mill", "A watermill downstream.",
                          rooms=[{"name": "Grinding floor", "description": "x"}])
LOC2_ID = LOC2["id"]


def make_npc(name: str, *, outfit: str = "", location_id: str = "") -> str:
    """Create a temporary NPC through the real apply path, gate OFF."""
    set_require_assets(False)
    data = {"character_name": name,
            "character_appearance": "a weathered farmhand",
            "face_appearance": "a broad face, grey stubble",
            "standing_task": "sweeping the yard"}
    if outfit:
        data["outfit_description"] = outfit
    apply_npc(data, location_id, template="npc-temporary",
              created_by="smoke_npc_assets")
    return name


def give_profile_image(name: str, *, write_file: bool = True) -> None:
    images = get_character_images_dir(name)
    images.mkdir(parents=True, exist_ok=True)
    if write_file:
        (images / "face.png").write_bytes(b"\x89PNG fake")
    set_character_profile_image(name, "face.png")


def give_mesh(name: str, signature: str = "") -> None:
    sig = signature or model_refs.current_outfit_state(name)[2]
    d = get_character_dir(name) / "model3d"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{sig}.glb").write_bytes(b"glTF fake")


def give_outfit(name: str, text: str = "a grey linen apron") -> None:
    profile = get_character_profile(name)
    profile["outfit_description"] = text
    save_character_profile(name, profile)


# ── the producer stubs ──────────────────────────────────────────────────────

CALLS = {"image": 0, "tpose": 0, "mesh": 0, "send": 0}
SENT = []


class FakeImageService:
    """Stands in for the image service. Writes the file the gate checks."""

    enabled = True

    def __init__(self, ok: bool):
        self.ok = ok
        self.inputs = []

    def generate_from_input(self, input_data: str) -> str:
        CALLS["image"] += 1
        payload = json.loads(input_data)
        self.inputs.append(payload)
        if not self.ok:
            return "Fehler: kein Backend"
        give_profile_image(payload["agent_name"])
        return f"/characters/{payload['agent_name']}/images/face.png"


IMAGE_SERVICE = {"current": None}


def install_stubs(*, image_ok=True, mesh_ok=True):
    """Replace the three producers plus the wanderer dispatch."""
    service = FakeImageService(image_ok)
    IMAGE_SERVICE["current"] = service
    imagegen_service.get_image_service = lambda: service

    def fake_tpose(name, kinds=None, force=False, **kwargs):
        CALLS["tpose"] += 1
        return {"tpose": "fake.png"}

    def fake_mesh(name, **kwargs):
        CALLS["mesh"] += 1
        if not mesh_ok:
            return {"ok": False, "error": "stub"}
        give_mesh(name)
        return {"ok": True}

    def fake_send(name, target_id):
        CALLS["send"] += 1
        SENT.append((name, target_id))
        return True

    model_refs.generate_model_ref_images = fake_tpose
    model3d.generate_for_current_outfit = fake_mesh
    npc_spawn._send_wanderer = fake_send
    for k in CALLS:
        CALLS[k] = 0
    SENT.clear()


# ── [1] the gate matrix, against real files ─────────────────────────────────
print("[1] the gate matrix — real files, exact signature")
A = make_npc("Torvin")
check("a fresh NPC misses all three, in the declared order",
      na.npc_assets_complete(A),
      ["profile_image", "model3d", "outfit_description"])
give_outfit(A)
check("the outfit text alone leaves two", na.npc_assets_complete(A),
      ["profile_image", "model3d"])
give_profile_image(A, write_file=False)
check("a profile_image field pointing at nothing is still missing",
      na.npc_assets_complete(A), ["profile_image", "model3d"])
give_profile_image(A)
check("the file on disk satisfies it", na.npc_assets_complete(A), ["model3d"])
check("the worn signature of an unequipped NPC is md5('')[:12]",
      model_refs.current_outfit_state(A)[2], "d41d8cd98f00")
give_mesh(A, "deadbeefcafe")
check("a mesh under a foreign signature does not count",
      na.npc_assets_complete(A), ["model3d"])
give_mesh(A)
check("the mesh of the WORN signature does", na.npc_assets_complete(A), [])

# ── [2] the gate is configured and template-bound ───────────────────────────
print("[2] configured + template-bound")
B = make_npc("Halda")
set_require_assets(False)
check("gate off = never held back", na.gate_placement(B, LOC_ID), False)
set_require_assets(True)
check("gate on + unfinished = held back", na.gate_placement(B, LOC_ID), True)
check("and it is pooled by the gate itself", get_character_status(B), "pooled")
set_character_status(B, "")
give_outfit(B)
give_profile_image(B)
give_mesh(B)
check("gate on + finished = not held back", na.gate_placement(B, LOC_ID), False)
check("an unknown/non-NPC name is never gated",
      na.gate_placement("nobody-at-all", LOC_ID), False)

# ── [3] apply_npc ───────────────────────────────────────────────────────────
print("[3] apply_npc holds the unfinished NPC back")
set_require_assets(True)
C = "Brenna"
apply_npc({"character_name": C, "character_appearance": "a thin carter",
           "standing_task": "loading sacks"},
          LOC_ID, room_id=TAPROOM, template="npc-temporary",
          created_by="smoke_npc_assets")
check("the character sheet was written anyway",
      get_character_profile(C).get("standing_task"), "loading sacks")
check("the row is pooled", get_character_status(C), "pooled")
check("it stands nowhere", get_character_current_location(C), "")
check("exactly one npc_assets task", len(tasks_for(C)), 1)
check("the pool row says what it is waiting for",
      [r["reason"] for r in list_pool() if r["name"] == C],
      ["waiting for profile_image, model3d, outfit_description"])
check("the task carries the placement",
      {k: tasks_for(C)[0][k] for k in ("name", "location_id", "room_id")},
      {"name": C, "location_id": LOC_ID, "room_id": TAPROOM})
apply_npc({"character_name": C, "character_appearance": "a thin carter"},
          LOC_ID, room_id=TAPROOM, template="npc-temporary",
          created_by="smoke_npc_assets")
check("a second apply adds no second task", len(tasks_for(C)), 1)

set_require_assets(False)
D = "Ansgar"
apply_npc({"character_name": D, "character_appearance": "a stable boy"},
          LOC2_ID, template="npc-temporary", created_by="smoke_npc_assets")
check("gate off places as before",
      (get_character_status(D), get_character_current_location(D)),
      ("", LOC2_ID))
check("and queues nothing", len(tasks_for(D)), 0)

# ── [4] revive_from_pool ────────────────────────────────────────────────────
print("[4] revive_from_pool returns True when it holds back")
set_require_assets(True)
pool_npc(D, reason="smoke")          # the real way in — it also unplaces
check("pooling took it off the map", get_character_current_location(D), "")
check("held back, but True for the caller",
      revive_from_pool(D, LOC_ID, TAPROOM, slot_role="stablehand"), True)
check("still pooled", get_character_status(D), "pooled")
check("still nowhere", get_character_current_location(D), "")
check("one job", len(tasks_for(D)), 1)

# ── [5] the handler places what is already complete ─────────────────────────
print("[5] the handler places a finished NPC without generating")
install_stubs()
E = make_npc("Yrsa", outfit="a patched brown cloak")
give_profile_image(E)
give_mesh(E)
set_character_status(E, "pooled")
set_require_assets(True)
res = na._handle_npc_assets({"name": E, "location_id": LOC_ID,
                             "room_id": TAPROOM})
check("ok", res.get("ok"), True)
check("nothing was produced",
      (CALLS["image"], CALLS["tpose"], CALLS["mesh"]), (0, 0, 0))
check("back in the world", get_character_status(E), "")
check("placed", (get_character_current_location(E),
                 get_character_current_room(E)), (LOC_ID, TAPROOM))

# ── [6] the handler produces only what is missing ───────────────────────────
print("[6] only the missing half is produced")
install_stubs()
F = make_npc("Odger", outfit="a leather jerkin")
set_require_assets(True)
check("the gate holds it back", na.gate_placement(F, LOC_ID), True)
check("and says so in the pool",
      [r["reason"] for r in list_pool() if r["name"] == F],
      ["waiting for profile_image, model3d"])
res = na._handle_npc_assets({"name": F, "location_id": LOC_ID})
check("ok", res.get("ok"), True)
check("image once, tpose once, mesh once",
      (CALLS["image"], CALLS["tpose"], CALLS["mesh"]), (1, 1, 1))
check("the render is a set_profile render of the profile use-case",
      {k: IMAGE_SERVICE["current"].inputs[0][k]
       for k in ("agent_name", "set_profile", "image_use_case")},
      {"agent_name": F, "set_profile": True, "image_use_case": "profile"})
check("and it carries the character's face prompt",
      IMAGE_SERVICE["current"].inputs[0]["prompt"],
      "a broad face, grey stubble")
check("placed", get_character_current_location(F), LOC_ID)
check("and it is no longer waiting for anything",
      get_character_profile(F).get("npc_pooled_reason"), None)

install_stubs()
G = make_npc("Sunniva", outfit="a blue shawl")
give_profile_image(G)
set_character_status(G, "pooled")
res = na._handle_npc_assets({"name": G, "location_id": LOC_ID})
check("the existing face is not rendered again",
      (CALLS["image"], CALLS["tpose"], CALLS["mesh"]), (0, 1, 1))
check("placed", get_character_current_location(G), LOC_ID)

# ── [7] a missing outfit text is never generated ────────────────────────────
print("[7] a missing outfit_description stops the handler cold")
install_stubs()
H = make_npc("Kettil")
set_character_status(H, "pooled")
res = na._handle_npc_assets({"name": H, "location_id": LOC_ID})
check("not ok", res.get("ok"), False)
check("and nothing was produced",
      (CALLS["image"], CALLS["tpose"], CALLS["mesh"]), (0, 0, 0))
check("still pooled", get_character_status(H), "pooled")

# ── [8] a producer that fails leaves it pooled and raises ───────────────────
print("[8] an unfinished attempt raises into the queue retry")
install_stubs(mesh_ok=False)
I_ = make_npc("Ragna", outfit="a felted hat")
set_character_status(I_, "pooled")
raises("the handler raises", RuntimeError,
       lambda: na._handle_npc_assets({"name": I_, "location_id": LOC_ID}))
check("still pooled", get_character_status(I_), "pooled")
check("still nowhere", get_character_current_location(I_), "")

# ── [9] the wanderer is sent by the handler ─────────────────────────────────
print("[9] the wanderer leaves once its assets exist")
install_stubs()
J = make_npc("Vidar", outfit="a road-stained coat")
set_character_status(J, "pooled")
res = na._handle_npc_assets({"name": J, "location_id": LOC_ID,
                             "wanderer": True, "wander_target": LOC2_ID})
check("ok", res.get("ok"), True)
check("sent exactly once, to the payload's target", SENT, [(J, LOC2_ID)])

install_stubs()
L = make_npc("Solveig", outfit="a travelling cloak")
_p = get_character_profile(L)
_p["npc_wanderer"] = True
_p["wander_target"] = LOC2_ID
save_character_profile(L, _p)
set_character_status(L, "pooled")
na._handle_npc_assets({"name": L, "location_id": LOC_ID})
check("a payload without a target falls back to the profile", SENT,
      [(L, LOC2_ID)])

install_stubs()
K = make_npc("Gerd", outfit="an apron")
set_character_status(K, "pooled")
na._handle_npc_assets({"name": K, "location_id": LOC_ID})
check("a non-wanderer is not sent anywhere", CALLS["send"], 0)

# ── [10] the outfit text is required at its source ──────────────────────────
print("[10] npc-temporary demands the outfit text in the generation turn")
_gaps = validate_npc_fields({"character_name": "Nameless",
                             "character_appearance": "a farmhand",
                             "standing_task": "sweeping"}, "npc-temporary")
check("a draft without outfit_description is reported as a gap",
      [g for g in _gaps if g.startswith("outfit_description")],
      ["outfit_description — missing, Outfit description is required"])

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    print("FAILED: " + ", ".join(FAILURES))
    sys.exit(1)
print("all green")
