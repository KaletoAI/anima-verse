#!/usr/bin/env python3
"""Smoke run for the 📷 SCENE PHOTO and running pair interactions
(``app/core/scene_photo.py``).

Throwaway storage — never touches a real world. No server, and no LLM: with
an empty room stream ``prepare_scene_photo`` takes its deterministic
fallback branch, which is exactly the branch whose wording this checks.

The interaction records are stamped onto the profiles the way
``interaction_engine.start_interaction`` writes them (id/kind/role/partner/
pose_key/started_at_game). No clip library is needed: the photo path reads
the record, never the clip.

World: one location "Photo Room" with the single room "salon"; Ann is the
AVATAR, Bob and Cid are present with her.

Hand-derived expectations:

  [1] ``_pairs_among`` reports each pair ONCE, in the order the names come
      in, as (a, b, pose_key) — and only when BOTH halves are in the set.
      Ann+Bob paired, asked for ["Ann", "Bob", "Cid"] → one entry
      ("Ann", "Bob", "dancing"); asked for ["Bob", "Cid"] → none, because
      Bob's partner Ann is not in the frame.

  [2] Subjects. The photographer stays out of frame: with Bob and Cid
      present and NO interaction, subjects == ["Bob", "Cid"]. Alone in the
      room it is a selfie, subjects == ["Ann"]. But once Ann is IN a pair
      she is part of what is being photographed: subjects ==
      ["Bob", "Cid", "Ann"] — everyone present PLUS the avatar, appended
      last (the user's ruling: all present stay in the frame, the pair does
      not narrow it).

  [3] The fallback prompt names a pair ONCE as a shared action and does not
      repeat it per person: with Ann+Bob dancing and Cid on his own the
      prompt lists exactly TWO entries, not three:
      ["Bob and Ann (dancing together)", "Cid"] — neither half of the pair
      also stands on its own, and Cid still appears separately. BOB comes first because the pair is read in subject order
      and the avatar is appended last — the naming order carries no meaning
      here, only its predictability does. Without any pair, every subject is
      listed individually as before.

  [4] The ``pairs`` string handed to the LLM template reads
      "Bob and Ann are dancing together" (same order as [3]) and is empty
      when nobody is paired — the template hides its whole rule block on the
      empty value, so an unpaired photo is worded exactly as it was before.

Usage:  ./.venv/bin/python scripts/smoke_scene_photo_pair.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="scene-photo-smoke-"))

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import scene_photo  # noqa: E402
from app.core.prompt_templates import render_task  # noqa: E402
from app.models.character import (  # noqa: E402
    get_character_profile, save_character_current_location,
    save_character_current_room, save_character_profile)
from app.models.world import add_location, update_location_position  # noqa: E402

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


# ── fixtures ────────────────────────────────────────────────────────────
ROOM = add_location(name="Photo Room", description="scene photo smoke",
                    rooms=[{"id": "salon", "name": "Salon"}])["id"]
update_location_position(ROOM, 0.0, 0.0)


def new_character(name: str) -> None:
    save_character_profile(name, {"current_location": "", "language": "en"},
                           create_new=True)
    save_character_current_location(name, ROOM)
    save_character_current_room(name, "salon")


for _n in ("Ann", "Bob", "Cid"):
    new_character(_n)


def pair(a: str, b: str, pose: str) -> None:
    """Stamp the record start_interaction writes, on both halves."""
    for name, role, other in ((a, "a", b), (b, "b", a)):
        prof = get_character_profile(name) or {}
        prof["interaction"] = {"id": "smoke", "kind": pose, "role": role,
                               "partner": other, "pose_key": pose,
                               "started_at_game": "Y0001-D001T00:00:00"}
        save_character_profile(name, prof)


def unpair(*names: str) -> None:
    for name in names:
        prof = get_character_profile(name) or {}
        if prof.pop("interaction", None) is not None:
            save_character_profile(name, prof)


# ── [1] which pairs are inside a set of names ───────────────────────────
print("[1] _pairs_among")
check("nobody paired -> no pairs",
      scene_photo._pairs_among(["Ann", "Bob", "Cid"]) == [])
pair("Ann", "Bob", "dancing")
check("a pair is reported ONCE, not per half",
      scene_photo._pairs_among(["Ann", "Bob", "Cid"]) == [("Ann", "Bob", "dancing")],
      str(scene_photo._pairs_among(["Ann", "Bob", "Cid"])))
check("a partner outside the frame is not a pair here",
      scene_photo._pairs_among(["Bob", "Cid"]) == [],
      str(scene_photo._pairs_among(["Bob", "Cid"])))
check("order follows the names given",
      scene_photo._pairs_among(["Bob", "Ann"]) == [("Bob", "Ann", "dancing")],
      str(scene_photo._pairs_among(["Bob", "Ann"])))

# ── [2] who is in the frame ─────────────────────────────────────────────
print("\n[2] subjects")
unpair("Ann", "Bob")
prep = scene_photo.prepare_scene_photo("Ann")
check("unpaired: the photographer stays out of frame",
      prep["subjects"] == ["Bob", "Cid"], str(prep["subjects"]))

pair("Ann", "Bob", "dancing")
prep = scene_photo.prepare_scene_photo("Ann")
check("in a pair: everyone present PLUS the avatar, avatar last",
      prep["subjects"] == ["Bob", "Cid", "Ann"], str(prep["subjects"]))
check("a pair does not narrow the frame — Cid stays in",
      "Cid" in prep["subjects"])

unpair("Ann", "Bob")
save_character_current_room("Bob", "elsewhere")
save_character_current_room("Cid", "elsewhere")
prep = scene_photo.prepare_scene_photo("Ann")
check("alone in the room: a selfie", prep["subjects"] == ["Ann"],
      str(prep["subjects"]))
save_character_current_room("Bob", "salon")
save_character_current_room("Cid", "salon")

# ── [3] the deterministic prompt ────────────────────────────────────────
print("\n[3] the fallback prompt")
prep = scene_photo.prepare_scene_photo("Ann")
p = prep["prompt"]
check("unpaired: every subject on its own", "Bob (" in p or "Bob;" in p or "Bob\n" in p, p[:120])
check("… and the avatar is not in it", "Ann" not in p.split("People in the frame:")[0],
      p.split("People in the frame:")[0][:160])

pair("Ann", "Bob", "dancing")
prep = scene_photo.prepare_scene_photo("Ann")
head = prep["prompt"].split("People in the frame:")[0].strip()
_PREFIX = "Candid photograph of the current moment: "
entries = head[len(_PREFIX):].split("; ") if head.startswith(_PREFIX) else []
# The whole point in one assertion: TWO entries, not three. The pair is one
# of them; neither half also stands on its own.
check("paired: exactly two entries — the pair and Cid",
      entries == ["Bob and Ann (dancing together)", "Cid"], str(entries))

# ── [4] what the LLM template is told ───────────────────────────────────
print("\n[4] the pairs line")
pairs_text = "; ".join(f"{a} and {b} are {pose} together"
                       for a, b, pose in scene_photo._pairs_among(prep["subjects"]))
check("the pairs line names the shared action",
      pairs_text == "Bob and Ann are dancing together", pairs_text)
sys_p, _ = render_task("scene_photo", photographer="Ann",
                       subjects=", ".join(prep["subjects"]),
                       pairs=pairs_text, transcript="Ann: hello")
check("the template carries the rule", "ONE shared action between the two" in sys_p)
check("… and knows the photographer is in the frame",
      "selfie — they ARE in the frame" in sys_p)
sys_p2, _ = render_task("scene_photo", photographer="Ann", subjects="Bob, Cid",
                        pairs="", transcript="Ann: hello")
check("no pair -> the rule block is absent",
      "ONE shared action between the two" not in sys_p2)
check("… and the photographer is out of frame again",
      "is NOT in the frame" in sys_p2)


print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s): " + "; ".join(FAILURES))
    sys.exit(1)
print("all checks passed")
