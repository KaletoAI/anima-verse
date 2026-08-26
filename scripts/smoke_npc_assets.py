#!/usr/bin/env python3
"""Smoke run for the temporary-NPC finish gate (plan-npc-leben, task 1).

Throwaway storage, throwaway world DB, throwaway task queue — no server, no
real world is touched. NOTHING is generated here: the four producers (profile
image, T-pose render, mesh, default expression) are replaced by counting stubs
that write the very files the gate looks for. The gate itself runs unstubbed
against REAL files on disk, because "does the file exist" is the one thing this
feature must not fake (feedback_pruefe_am_verbraucher).

THE RULE, by hand — the gate matrix of the brief's § 0 A, plus the fourth
criterion of spec-npc-heimat-zeitfenster § E0:

    A temporary NPC may be placed only when all four of these hold —

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
      4. expression         `peek_cached_expression(name, "", "",
                            equipped_*=<the currently worn state>)` finds the
                            DEFAULT variant — mood empty, pose empty. That is
                            the one image `/play` shows for this NPC: its
                            template has `expression_variants_enabled: false`,
                            so no other trigger will ever render one, and the
                            profile image is deliberately not a fallback.
                            `peek_`, not `get_`, so a gate check does not
                            forge the variant's LRU bookkeeping.

    `npc_assets_complete(name)` reports what is MISSING in exactly that order,
    so an empty list means "ready". Hand-derived expectations:

  [1] A fresh NPC created by `apply_npc` with no image, no mesh, no outfit
      text and no variant is missing all four, in the declared order:
        ["profile_image", "model3d", "outfit_description", "expression"]
      Filling `outfit_description` alone leaves
        ["profile_image", "model3d", "expression"].
      Pointing `profile_image` at "face.png" WITHOUT writing the file leaves
      the same three entries — criterion 1 is a file check, not a field check.
      Writing the file drops it to ["model3d", "expression"].
      The worn signature of this NPC is derivable by hand: it owns no
      wardrobe piece, so `current_outfit_state` hashes what dresses it
      instead — the free-text outfit line `render_outfit(…)["full"]`, which
      for the `give_outfit` text above reads "wearing: a grey linen apron".
      md5 of that is 3bdb2ee2463ced85c866bb4320b425ad, so the signature is
      "3bdb2ee2463c" — and NOT the md5("")[:12] = "d41d8cd98f00" of an NPC
      with neither pieces nor outfit text (which is what every temporary NPC
      used to share, one undressed T-pose and mesh for all of them). A
      `<sig>.glb` under that name in `<char>/model3d/` empties that entry; a
      mesh stored beside it under a DIFFERENT signature does not count.

      THE VARIANT FILE NAME, by hand. `expression_regen._cache_key` builds
      `f"{expression_key}:{pose}:{eq}"` (`app/core/expression_regen.py:178`),
      md5's it, takes 12 hex and — with a character name — prefixes
      `f"{_safe_name(character_name)}_"`. For the default variant:
        * `expression_key = resolve_expression_key("")`, and
          `pose_catalog.resolve_to_catalog("", …)` answers the catalog
          default for empty text → "neutral";
        * `pose = _canonical_pose_key("")` → `get_default_key("pose")` →
          "standing";
        * `eq = outfit_signature_raw({}, [], name)` — the SAME raw string
          `model_refs.outfit_signature` hashes, so a piece-less NPC folds in
          its free text: "wearing: a grey linen apron";
        * `state_fp` is "" — no `image_modifier` directive is active.
      So the raw string is
        "neutral:standing:wearing: a grey linen apron"
      whose md5 is a8021c6b637b06982bcc4483fb5cabe7, i.e. "a8021c6b637b" at
      12 hex, and the file the job writes is
        <char>/outfits/Torvin_a8021c6b637b.png
      Dropping that file (plus its sidecar) empties the missing list; the
      same file under a name derived from a DIFFERENT outfit text does not
      count, because the outfit text is part of the key.

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
      The stored `max_retries` is 2, NOT the queue's `MAX_RETRIES_DEFAULT`
      of 0 (`app/core/task_queue.py:43`): a `+ New NPC` NPC carries the
      admin's placement in that one job and has no slot that would re-queue
      it, so a single transient backend outage would strand it in the pool
      until some wanderer spawn takes it as "any pooled NPC" and revives it
      somewhere else entirely. Read out of the queue DB, not off the submit
      call.

 [3b] THE POOL ROW IS READABLE. A pooled NPC used to be a bare name in the
      Game-Admin list, and a name an LLM invented says nothing about who
      that is. `list_pool` therefore also delivers `image_url` — the same
      `/characters/<name>/images/<file>` path the living roster builds
      (`character_ops.build_present_characters`), "" when there is no
      portrait, never a broken link — and `description`, the non-empty
      halves of role · standing_task · character_appearance joined with
      " · ". Hand-derived for an NPC created by this file's `make_npc`
      (standing task "sweeping the yard", appearance "a weathered farmhand")
      claimed for the `cook` slot with a portrait on disk:
        image_url   "/characters/Ylva/images/face.png"
        description "cook · sweeping the yard · a weathered farmhand"
      and for `Brenna`, who has no role and no portrait:
        image_url   ""
        description "loading sacks · a thin carter"
      Both fields come out of the profile `list_pool` already reads, so the
      row costs no extra query.

  [4] `revive_from_pool` uses the very same gate — on an NPC that went into
      the pool the real way (`pool_npc`, which is what takes it off the map) —
      and, when the gate holds it back, still returns True: its caller
      (`npc_spawn.spawn_for_slot`) reads False as "the pool did not deliver"
      and would run the three-turn generation pipeline for an NPC that is
      already claimed. It stays pooled, it stands nowhere, one job is queued.

  [5] The handler places what is already complete WITHOUT generating: with all
      four criteria satisfied up front, all four producer stubs stay at 0
      calls, the status goes back to '' and location + room are set.

  [6] The handler produces ONLY what is missing (partial-failure resumption),
      in the order profile image → T-pose → mesh → default expression. The
      expression comes LAST although it needs only the outfit, never the
      mesh: run before the mesh, a dead mesh backend would take the NPC's
      only picture down with it.
      Gate and handler end to end: an NPC with an outfit text but neither
      image nor mesh nor variant is held back with the pool reason "waiting
      for profile_image, model3d, expression", and the handler then calls the
      image stub once, the T-pose stub once, the mesh stub once and the
      expression stub once — call counts (1, 1, 1, 1) — places it and clears
      the reason. An NPC that only lacks the mesh and the variant calls the
      image stub NOT AT ALL: (0, 1, 1, 1) — the T-pose is the mesh's input,
      so it rides on the model3d criterion instead of having one of its own.
      The expression stub is called with EXACTLY the default coordinates —
      `mood=""`, `pose_key=""`, and the currently worn state
      (`equipped_pieces={}`, `equipped_items=[]` for a piece-less NPC), so
      the file it writes is the one the route's default-variant fallback
      (`characters.py:985`, `get_cached_expression(name, "", "", equipped_*)`)
      looks for.

  [7] A missing `outfit_description` is NOT generated. It is a text field the
      generation turn fills (`npc-temporary.json` marks it `required`), so the
      handler returns ok=False without touching a single producer and leaves
      the NPC pooled — a retry would only burn GPU time on the other two.

  [8] A producer that does not deliver leaves the NPC pooled and RAISES, which
      is what hands the task back to the queue's own retry mechanism. Nothing
      is placed: status stays 'pooled', current_location stays "".
      THE PRODUCER'S OWN WORDS TRAVEL. Neither producer raises: the image
      service reports a failure as PROSE ("Fehler: kein Backend") and the
      mesh chain as `{"ok": False, "error": …}`. The queue panel shows the
      EXCEPTION and nothing else, so a message that only says "still
      incomplete: model3d" makes a dead backend look like a mystery. Both
      texts therefore ride in the RuntimeError: the mesh stub's "stub" and
      the image stub's "Fehler: kein Backend". The expression producer is the
      same kind of liar — `generate_expression_image` swallows every failure
      and answers None — so its criterion has to name itself: the error text
      carries "expression".

  [9] A wanderer is sent on its way BY THE HANDLER: with `wanderer` true the
      placement is followed by exactly one `_send_wanderer` call for the
      payload's target. The PAYLOAD is the road — a profile that names a
      target the job does not carry sends nobody, because the payload is
      written by the gate and the gate runs after both placement paths have
      stamped the route (see [11]). A non-wanderer payload sends nobody.

 [10] `npc-temporary.json` marks `outfit_description` required, so
      `validate_npc_fields` demands it in the generation/repair turn — the
      gate's third criterion is enforced at its source, not only here.

 [11] THE ROAD IS STAMPED BEFORE THE PLACEMENT. `apply_npc(..., wanderer=True,
      wander_target=X)` writes `wander_origin`/`wander_target` onto the
      profile BEFORE it asks the gate, so the queued job carries the target
      (`wanderer: True`, `wander_target: X`) and no worker can pick the job up
      in a window where the road is not written yet. Nobody is sent while the
      NPC is held — `_send_wanderer` on a pooled NPC standing nowhere can only
      fail with "no route", which is why `spawn_wanderer` asks
      `is_awaiting_assets` and leaves the journey to the job. The handler then
      places it and sends it off in one go.

 [12] A HELD-BACK NPC IS NOT FREE POOL STOCK. It sits in the pool, so
      `take_from_pool` would otherwise hand the same sheet to a second slot
      while the pending job still carries the FIRST claim's location — the
      second claimer would count its slot filled and leave it empty. Neither
      the role query ("smith") nor a wanderer's "any pooled NPC" query
      ("") returns it. The state lives in the QUEUE, so it heals itself: with
      the job finished the very same query hands the sheet out again.

 [13] A HELD-BACK SLOT NPC HOLDS ITS SLOT. This is the only section that runs
      the slot loop the way a real world runs it — gate armed, cap out of the
      way — because the older spawn smokes switch the gate off. A location
      with one `cook` slot: the first `fill_location_slots` runs the pipeline
      once and the NPC it makes is held back; `held_roles_at` reports `cook`
      anyway (the gate bypasses `pool_npc`, so the slot tags survive on the
      profile), `location_gap` is therefore empty, and the SECOND tick
      generates nothing — without that the pipeline would run again once per
      cooldown for the whole duration of the portrait+mesh render, and N NPCs
      would arrive for a `count 1` slot. The same NPC proves the
      `+ len(list_awaiting_assets())` half of `alive_npc_count`: finishing its
      job drops the count by exactly one while nothing living changed.

 [14] `_place` NEVER TOUCHES A LIVING NPC. The job is re-queued when a temp
      NPC's outfit text is edited, and that NPC is standing in the world, not
      in the pool — so the placement step has to be a no-op unless the
      character is still `status == POOLED_STATUS`. Without the guard the
      re-render job would drag a wandering NPC back to the location the
      ORIGINAL job carried. Checked on an NPC with status '' standing in
      LOC2/nowhere-room: `_place(name, LOC_ID, TAPROOM)` leaves status,
      current_location and current_room exactly as they were.

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

from app.core import (expression_regen, model3d, model_refs,  # noqa: E402
                      npc_assets as na, npc_ops, npc_spawn)
from app.core.npc_ops import apply_npc, validate_npc_fields  # noqa: E402
from app.core.world_ops import update_location_with_extras  # noqa: E402
from app.core.npc_pool import (list_pool, pool_npc,  # noqa: E402
                               revive_from_pool, take_from_pool)
from app.core.task_queue import get_task_queue  # noqa: E402
from app.imagegen import service as imagegen_service  # noqa: E402
from app.models import world  # noqa: E402
from app.models.character import (get_character_current_location,  # noqa: E402
                                  get_character_current_room,
                                  get_character_dir,
                                  get_character_images_dir,
                                  get_character_outfits_dir,
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


def raises(label, exc_type, fn, contains=""):
    """``fn`` must raise ``exc_type``; with ``contains`` the message must also
    carry that text — which is how the producer's own complaint is proven to
    reach the queue panel (the panel shows the exception, nothing else)."""
    global CHECKED
    CHECKED += 1
    try:
        fn()
    except exc_type as e:
        if contains and contains not in str(e):
            print(f"  FAIL {label}: {str(e)[:160]!r} does not carry "
                  f"{contains!r}")
            FAILURES.append(label)
            return
        print(f"  OK  {label}: {exc_type.__name__}({str(e)[:120]!r})")
        return
    except Exception as e:  # noqa: BLE001 — anything else is the defect
        print(f"  FAIL {label}: {type(e).__name__}({e})")
        FAILURES.append(label)
        return
    print(f"  FAIL {label}: no exception")
    FAILURES.append(label)


# ── helpers ─────────────────────────────────────────────────────────────────

def set_npc_config(**values) -> None:
    cfg = config.get_all()
    cfg.setdefault("npc", {}).update(values)
    config.save(cfg, STORAGE / "config.json")


def set_require_assets(value: bool) -> None:
    set_npc_config(require_assets=value)


def tasks_for(name: str):
    """The npc_assets payloads of one NPC, read straight out of the queue DB."""
    conn = sqlite3.connect(f"file:{QUEUE_DB}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT payload FROM tasks WHERE task_type=? AND agent_name=?",
            (na.TASK_TYPE, name)).fetchall()
    finally:
        conn.close()
    return [json.loads(r[0]) for r in rows]


def retries_for(name: str):
    """The ``max_retries`` the queue really stored for this NPC's jobs — asked
    at the consumer (the queue DB), not at the submit call."""
    conn = sqlite3.connect(f"file:{QUEUE_DB}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT max_retries FROM tasks WHERE task_type=? AND agent_name=?",
            (na.TASK_TYPE, name)).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]


def finish_tasks_for(name: str) -> None:
    """Mark this NPC's jobs done — what a worker does when it succeeds."""
    conn = sqlite3.connect(QUEUE_DB)
    try:
        conn.execute("UPDATE tasks SET status='done' WHERE task_type=? "
                     "AND agent_name=?", (na.TASK_TYPE, name))
        conn.commit()
    finally:
        conn.close()


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


def default_variant_key(name: str) -> str:
    """The cache key of the DEFAULT expression variant — mood "", pose "",
    the currently worn state. The same call `npc_assets` makes."""
    pieces, items, _sig = model_refs.current_outfit_state(name)
    return expression_regen._cache_key("", "", name, pieces, items)


def give_expression(name: str) -> Path:
    """Drop the default variant on disk, image plus sidecar — what the real
    generator leaves behind (`expression_regen.py:1133/1176`)."""
    expr_dir = get_character_outfits_dir(name)
    expr_dir.mkdir(parents=True, exist_ok=True)
    path = expr_dir / f"{default_variant_key(name)}.png"
    path.write_bytes(b"\x89PNG fake")
    path.with_suffix(".json").write_text(
        json.dumps({"mood": "", "pose_key": "", "expression_key": "neutral"}),
        encoding="utf-8")
    return path


# ── the producer stubs ──────────────────────────────────────────────────────

CALLS = {"image": 0, "tpose": 0, "mesh": 0, "expression": 0, "send": 0}
SENT = []
EXPR_ARGS = []


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


def install_stubs(*, image_ok=True, mesh_ok=True, expression_ok=True):
    """Replace the four producers plus the wanderer dispatch."""
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

    def fake_expression(name, mood, pose_key, equipped_pieces=None,
                        equipped_items=None, **kwargs):
        CALLS["expression"] += 1
        EXPR_ARGS.append({"name": name, "mood": mood, "pose_key": pose_key,
                          "equipped_pieces": equipped_pieces,
                          "equipped_items": equipped_items})
        if not expression_ok:
            return None
        return give_expression(name)

    def fake_send(name, target_id):
        CALLS["send"] += 1
        SENT.append((name, target_id))
        return True

    model_refs.generate_model_ref_images = fake_tpose
    model3d.generate_for_current_outfit = fake_mesh
    expression_regen.generate_expression_image = fake_expression
    npc_spawn._send_wanderer = fake_send
    for k in CALLS:
        CALLS[k] = 0
    SENT.clear()
    EXPR_ARGS.clear()


# ── [1] the gate matrix, against real files ─────────────────────────────────
print("[1] the gate matrix — real files, exact signature")
A = make_npc("Torvin")
check("a fresh NPC misses all four, in the declared order",
      na.npc_assets_complete(A),
      ["profile_image", "model3d", "outfit_description", "expression"])
give_outfit(A)
check("the outfit text alone leaves three", na.npc_assets_complete(A),
      ["profile_image", "model3d", "expression"])
give_profile_image(A, write_file=False)
check("a profile_image field pointing at nothing is still missing",
      na.npc_assets_complete(A), ["profile_image", "model3d", "expression"])
give_profile_image(A)
check("the file on disk satisfies it", na.npc_assets_complete(A),
      ["model3d", "expression"])
check("the worn signature of a piece-less NPC is md5 of its outfit line",
      model_refs.current_outfit_state(A)[2], "3bdb2ee2463c")
give_mesh(A, "deadbeefcafe")
check("a mesh under a foreign signature does not count",
      na.npc_assets_complete(A), ["model3d", "expression"])
give_mesh(A)
check("the mesh of the WORN signature does",
      na.npc_assets_complete(A), ["expression"])

# The default variant's file name, against the hand-derived key of the
# docstring — the route's fallback looks the file up under exactly this name.
check("the default variant is keyed by name + md5('neutral:standing:<outfit>')",
      default_variant_key(A), "Torvin_a8021c6b637b")
_variant = give_expression(A)
check("and the file the job drops there empties the list",
      na.npc_assets_complete(A), [])
check("it really is that file", _variant.name, "Torvin_a8021c6b637b.png")
# The outfit text is PART of the key: re-dress the NPC and the variant that
# was rendered for the old text no longer answers for the new one.
give_outfit(A, "a patched brown cloak")
check("a new outfit text orphans the old variant",
      na.npc_assets_complete(A), ["model3d", "expression"])
check("and asks for a new key", default_variant_key(A),
      "Torvin_351e41d4e754")
give_outfit(A)
check("dressing it back restores both — nothing was re-rendered",
      na.npc_assets_complete(A), [])

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
give_expression(B)
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
      ["waiting for profile_image, model3d, outfit_description, expression"])
check("the task carries the placement",
      {k: tasks_for(C)[0][k] for k in ("name", "location_id", "room_id")},
      {"name": C, "location_id": LOC_ID, "room_id": TAPROOM})
check("and it is allowed to retry twice", retries_for(C), [2])
apply_npc({"character_name": C, "character_appearance": "a thin carter"},
          LOC_ID, room_id=TAPROOM, template="npc-temporary",
          created_by="smoke_npc_assets")
check("a second apply adds no second task", len(tasks_for(C)), 1)

# ── [3b] the pool row carries a face and a description ──────────────────────
print("[3b] the pool row carries a face and a description")
set_require_assets(True)
P = "Ylva"
apply_npc({"character_name": P,
           "character_appearance": "a weathered farmhand",
           "standing_task": "sweeping the yard"},
          LOC_ID, room_id=TAPROOM, template="npc-temporary",
          slot_role="cook", created_by="smoke_npc_assets")
give_profile_image(P)
check("held back", get_character_status(P), "pooled")
_row = [r for r in list_pool() if r["name"] == P][0]
check("the row points at the profile image the roster would use",
      _row["image_url"], f"/characters/{P}/images/face.png")
check("and the description carries role, task and appearance",
      _row["description"],
      "cook · sweeping the yard · a weathered farmhand")
_bare = [r for r in list_pool() if r["name"] == C][0]
check("an NPC with no profile image gets an empty url, never a broken one",
      _bare["image_url"], "")
check("and its description skips the empty halves",
      _bare["description"], "loading sacks · a thin carter")

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
give_expression(E)
set_character_status(E, "pooled")
set_require_assets(True)
res = na._handle_npc_assets({"name": E, "location_id": LOC_ID,
                             "room_id": TAPROOM})
check("ok", res.get("ok"), True)
check("nothing was produced",
      (CALLS["image"], CALLS["tpose"], CALLS["mesh"], CALLS["expression"]),
      (0, 0, 0, 0))
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
      ["waiting for profile_image, model3d, expression"])
res = na._handle_npc_assets({"name": F, "location_id": LOC_ID})
check("ok", res.get("ok"), True)
check("image once, tpose once, mesh once, expression once",
      (CALLS["image"], CALLS["tpose"], CALLS["mesh"], CALLS["expression"]),
      (1, 1, 1, 1))
check("the expression stub was asked for the DEFAULT coordinates",
      EXPR_ARGS, [{"name": F, "mood": "", "pose_key": "",
                   "equipped_pieces": {}, "equipped_items": []}])
check("and the variant it wrote is the one the route's fallback looks for",
      (get_character_outfits_dir(F) / f"{default_variant_key(F)}.png").exists(),
      True)
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
      (CALLS["image"], CALLS["tpose"], CALLS["mesh"], CALLS["expression"]),
      (0, 1, 1, 1))
check("placed", get_character_current_location(G), LOC_ID)

# ── [7] a missing outfit text is never generated ────────────────────────────
print("[7] a missing outfit_description stops the handler cold")
install_stubs()
H = make_npc("Kettil")
set_character_status(H, "pooled")
res = na._handle_npc_assets({"name": H, "location_id": LOC_ID})
check("not ok", res.get("ok"), False)
check("and nothing was produced",
      (CALLS["image"], CALLS["tpose"], CALLS["mesh"], CALLS["expression"]),
      (0, 0, 0, 0))
check("still pooled", get_character_status(H), "pooled")

# ── [8] a producer that fails leaves it pooled and raises ───────────────────
print("[8] an unfinished attempt raises into the queue retry")
install_stubs(mesh_ok=False)
I_ = make_npc("Ragna", outfit="a felted hat")
set_character_status(I_, "pooled")
raises("the handler raises, carrying the mesh producer's own error",
       RuntimeError,
       lambda: na._handle_npc_assets({"name": I_, "location_id": LOC_ID}),
       contains="stub")
check("still pooled", get_character_status(I_), "pooled")
check("still nowhere", get_character_current_location(I_), "")
check("but the dead mesh did NOT take the NPC's only picture with it — "
      "the expression ran anyway",
      (CALLS["expression"],
       (get_character_outfits_dir(I_) / f"{default_variant_key(I_)}.png"
        ).exists()), (1, True))

# The image service does not raise either — it hands back an error STRING,
# and that string is the only thing that says why there is no portrait.
install_stubs(image_ok=False)
I2 = make_npc("Gunnhild", outfit="a felted hat")
set_character_status(I2, "pooled")
raises("and the image service's error prose too", RuntimeError,
       lambda: na._handle_npc_assets({"name": I2, "location_id": LOC_ID}),
       contains="Fehler: kein Backend")
check("still pooled", get_character_status(I2), "pooled")

# The expression producer lies the same way: generate_expression_image
# swallows everything and answers None, so the criterion has to name itself.
install_stubs(expression_ok=False)
I3 = make_npc("Steinunn", outfit="a felted hat")
set_character_status(I3, "pooled")
raises("an expression that never appears names itself in the error",
       RuntimeError,
       lambda: na._handle_npc_assets({"name": I3, "location_id": LOC_ID}),
       contains="expression")
check("still pooled", get_character_status(I3), "pooled")
check("still nowhere", get_character_current_location(I3), "")

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
check("a payload without a road sends nobody — the payload is the truth",
      SENT, [])

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

# ── [11] the wanderer's road is stamped BEFORE the placement ────────────────
print("[11] the road rides in the gate's payload, nobody is sent early")
install_stubs()
set_require_assets(True)
M = "Torgny"
apply_npc({"character_name": M, "character_appearance": "a lean pedlar",
           "standing_task": "walking the road",
           "outfit_description": "a dusty travelling coat"},
          LOC_ID, template="npc-temporary", wanderer=True,
          wander_target=LOC2_ID, created_by="smoke_npc_assets")
check("held back", get_character_status(M), "pooled")
check("the road is on the profile already",
      (get_character_profile(M).get("wander_origin"),
       get_character_profile(M).get("wander_target")), (LOC_ID, LOC2_ID))
check("and in the job the gate queued",
      {k: tasks_for(M)[0][k] for k in ("wanderer", "wander_target")},
      {"wanderer": True, "wander_target": LOC2_ID})
check("nobody was sent on a journey from nowhere", CALLS["send"], 0)
check("the queue still owes it a placement — spawn_wanderer skips the send",
      na.is_awaiting_assets(M), True)
na._handle_npc_assets(tasks_for(M)[0])
check("the job places it and sends it off", SENT, [(M, LOC2_ID)])

# ── [12] a claimed NPC is not free pool stock ───────────────────────────────
print("[12] a held-back NPC is not handed out a second time")
install_stubs()
N = "Brynja"
apply_npc({"character_name": N, "character_appearance": "a broad smith",
           "standing_task": "hammering"},
          LOC_ID, template="npc-temporary", slot_role="smith",
          created_by="smoke_npc_assets")
check("held back and claimed for the smith slot",
      (get_character_status(N), na.is_awaiting_assets(N)), ("pooled", True))
check("a second claim for the same role gets nothing",
      take_from_pool("smith"), None)
check("and a wanderer asking for ANY pooled NPC does not get it either",
      take_from_pool("") == N, False)
finish_tasks_for(N)
check("once the job is gone the queue owes it nothing",
      na.is_awaiting_assets(N), False)
check("and the sheet is ordinary pool stock again",
      take_from_pool("smith"), N)

# ── [13] a held-back slot NPC HOLDS its slot ────────────────────────────────
print("[13] the slot loop under the production default (require_assets on)")
install_stubs()
# A cap high enough that this section is never refused for the wrong reason,
# and the gate armed — this is the ONLY place that runs the slot loop the way
# a real world runs it (the older spawn smokes switch the gate off).
set_npc_config(require_assets=True, max_alive=50)

LOC3 = world.add_location("Roadside Kitchen", "Smoke and a long bench.",
                          rooms=[{"name": "Hearth", "description": "Soot."}])
LOC3_ID = LOC3["id"]
update_location_with_extras(LOC3_ID, {"npc_slots": [
    {"role": "cook", "count_min": 1, "count_max": 1,
     "briefing": "the cook of this kitchen"}]})

GEN_CALLS = []


def fake_generate(briefing="", location_id="", room_id="", ttl_hours=None,
                  template="", slot_role="", wanderer=False, wander_target="",
                  created_by=""):
    """The pipeline stub — it creates the NPC through the REAL apply path."""
    GEN_CALLS.append(slot_role)
    name = f"Kettilfrid{len(GEN_CALLS)}"
    applied = apply_npc({"character_name": name,
                         "character_appearance": "a soot-streaked cook",
                         "standing_task": "stirring the pot"},
                        location_id, room_id, template=template or "npc-temporary",
                        slot_role=slot_role, created_by="smoke_npc_assets")
    return {"ok": True, "character": name,
            "held_for_assets": bool(applied.get("held_for_assets"))}


npc_ops.generate_npc_blocking = fake_generate

npc_spawn.fill_location_slots(LOC3_ID)
COOK = "Kettilfrid1"
check("the first tick ran the pipeline once", GEN_CALLS, ["cook"])
check("and the NPC it made is held back", get_character_status(COOK), "pooled")
check("the slot is held all the same",
      npc_spawn.held_roles_at(LOC3_ID), ["cook"])
check("so the location has no gap left",
      npc_spawn.location_gap(world.get_location_by_id(LOC3_ID)), [])

_before = npc_spawn.alive_npc_count()
res = npc_spawn.fill_location_slots(LOC3_ID)
check("the second tick generates NOTHING", GEN_CALLS, ["cook"])
check("and reports the slot as filled", res.get("filled"), 0)

check("the cap counts the held NPC", na.is_awaiting_assets(COOK), True)
finish_tasks_for(COOK)
check("and stops counting it when the job is gone",
      npc_spawn.alive_npc_count(), _before - 1)

# ── [14] _place never touches a living NPC ──────────────────────────────────
print("[14] _place is a no-op for an NPC that is not pooled")
install_stubs()
set_require_assets(False)
R = make_npc("Alvhild", outfit="a russet kirtle", location_id=LOC2_ID)
check("it is standing in the world",
      (get_character_status(R), get_character_current_location(R)),
      ("", LOC2_ID))
_before_place = (get_character_status(R), get_character_current_location(R),
                 get_character_current_room(R))
na._place(R, LOC_ID, TAPROOM)
check("_place left the living NPC exactly where it was",
      (get_character_status(R), get_character_current_location(R),
       get_character_current_room(R)), _before_place)
check("and it was really somewhere else than the job's target",
      _before_place[1] == LOC_ID, False)

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    print("FAILED: " + ", ".join(FAILURES))
    sys.exit(1)
print("all green")
