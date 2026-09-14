#!/usr/bin/env python3
"""Smoke run for the GENDER ROLES of a pair clip (docs/schnittstellen-3d.md § A8a).

Builds a throwaway clip tree and points ANIMATION_CLIPS_DIR at it — the real
``shared/models/clips`` is never read or written. No server, no world DB.
The geometry of a started pair (the anchor yaw after a swap) is checked in
``scripts/smoke_interaction.py`` block [11]; this script covers the rule and
where it is stored.

THE RULE, from which every expectation below is derived by hand:

  * ``clip_role_gender(meta)`` reads the sidecar's ``role_gender``. Only a
    COMPLETE assignment counts — one half "male", the other "female" (case
    and blanks ignored). Anything else is ``{}`` = not assigned.

        {"role_gender": {"a": "male", "b": "female"}}     -> {"a": "male", "b": "female"}
        {"role_gender": {"a": " Female ", "b": "MALE"}}   -> {"a": "female", "b": "male"}
        {"role_gender": {"a": "male", "b": "male"}}       -> {}
        {"role_gender": {"a": "male"}}                    -> {}
        {"role_gender": {"a": "male", "b": "nonbinary"}}  -> {}
        {} / None                                         -> {}

  * ``assign_roles(actor, partner, g_actor, g_partner, rg)`` returns
    ``(plays A, plays B)``. A character FITS a half when its gender equals
    that half's gender. SWAP = (actor fits B or partner fits A) and NOT
    (actor fits A or partner fits B). With rg = {a: male, b: female} and the
    actor always "Ann", the partner always "Bob":

        g_actor     g_partner    fits…                         -> result
        male        female       actor fits A                  -> (Ann, Bob)
        female      male         actor fits B, partner fits A  -> (Bob, Ann)
        female      nonbinary    actor fits B only             -> (Bob, Ann)
        nonbinary   female       partner fits B only           -> (Ann, Bob)
        nonbinary   male         partner fits A only           -> (Bob, Ann)
        male        nonbinary    actor fits A only             -> (Ann, Bob)
        female      female       actor fits B, partner fits B  -> (Ann, Bob)
        male        male         actor fits A, partner fits A  -> (Ann, Bob)
        ""          ""           nothing fits                  -> (Ann, Bob)
        female      male, rg={}  not assigned                  -> (Ann, Bob)

    With the reversed assignment rg = {a: female, b: male}, "female / male"
    gives actor fits A -> (Ann, Bob), "male / female" -> (Bob, Ann).

  * ``set_clip_role_gender(library, rel, rg)`` writes the complete assignment
    into the SHARED ``<kind>.json`` (both halves read it), ``None`` removes the
    key again. The sidecar's other numbers survive. Refused with
    ``ClipLibraryError``: a solo clip, an incomplete/same-gender assignment
    (nothing written), a pair without a sidecar; ``ClipNotFound`` for a file
    that does not exist.

The tree built here (stub files — nothing parses an FBX):

    <root>/hug__a.fbx  hug__b.fbx + hug.json  {"duration_s": 2.0}
    <root>/wave.fbx               + wave.json {"duration_s": 1.0}
    <root>/kiss__a.fbx kiss__b.fbx            (no sidecar)

Derived expectations:

  [1] ``clip_role_gender`` on the six metas above.
  [2] ``assign_roles`` on the twelve rows above.
  [3] Both halves of hug list ``role_gender`` {} before any write; wave (solo)
      lists {} too.
  [4] ``set_clip_role_gender("free", "hug__b.fbx", {a: female, b: male})``
      writes exactly that into hug.json, duration_s stays 2.0, both halves
      now list {a: female, b: male}, the answer names hug__a + hug__b.
  [5] ``None`` removes the key: hug.json has no ``role_gender``, both halves
      list {} again.
  [6] Refusals: wave.fbx (solo), {a: male, b: male} on hug (hug.json still
      without the key), kiss__a.fbx (no sidecar) -> ClipLibraryError;
      nope__a.fbx -> ClipNotFound.

Usage:  ./.venv/bin/python scripts/smoke_pair_role_gender.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CLIPS = Path(tempfile.mkdtemp(prefix="pair-roles-smoke-"))
WORLD = Path(tempfile.mkdtemp(prefix="pair-roles-world-"))
# MUST be set before paths is imported — otherwise the smoke would scan (and
# then WRITE INTO) the repo's real clip library.
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402

paths.init(WORLD)

from app.core import animation_clips as ac  # noqa: E402
from app.core.interaction_engine import assign_roles  # noqa: E402

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


(CLIPS / "hug__a.fbx").write_bytes(b"hug-a")
(CLIPS / "hug__b.fbx").write_bytes(b"hug-b")
write(CLIPS / "hug.json", {"kind": "hug", "pair": True, "duration_s": 2.0})
(CLIPS / "wave.fbx").write_bytes(b"wave")
write(CLIPS / "wave.json", {"kind": "wave", "duration_s": 1.0})
(CLIPS / "kiss__a.fbx").write_bytes(b"kiss-a")
(CLIPS / "kiss__b.fbx").write_bytes(b"kiss-b")


def views() -> dict:
    """``{rel: role_gender}`` of the whole library, as the API delivers it."""
    return {v["rel"]: v["role_gender"] for v in
            (ac.clip_view(e) for e in ac.clip_entries())}


def sidecar(rel: str) -> dict:
    return json.loads((CLIPS / rel).read_text(encoding="utf-8"))


MF = {"a": "male", "b": "female"}
FM = {"a": "female", "b": "male"}

# ── [1] reading ─────────────────────────────────────────────────────────
print("\n[1] clip_role_gender — only one man plus one woman counts")
check("male/female", ac.clip_role_gender({"role_gender": MF}) == MF)
check("case and blanks ignored",
      ac.clip_role_gender({"role_gender": {"a": " Female ", "b": "MALE"}}) == FM)
check("same gender twice is not assigned",
      ac.clip_role_gender({"role_gender": {"a": "male", "b": "male"}}) == {})
check("one half missing is not assigned",
      ac.clip_role_gender({"role_gender": {"a": "male"}}) == {})
check("an unknown word is not assigned",
      ac.clip_role_gender({"role_gender": {"a": "male", "b": "nonbinary"}}) == {})
check("no key / no sidecar", ac.clip_role_gender({}) == {}
      and ac.clip_role_gender(None) == {})

# ── [2] the matching rule ───────────────────────────────────────────────
print("\n[2] assign_roles — gender decides, the initiator only breaks ties")
ROWS = [
    ("male", "female", MF, ("Ann", "Bob")),
    ("female", "male", MF, ("Bob", "Ann")),
    ("female", "nonbinary", MF, ("Bob", "Ann")),
    ("nonbinary", "female", MF, ("Ann", "Bob")),
    ("nonbinary", "male", MF, ("Bob", "Ann")),
    ("male", "nonbinary", MF, ("Ann", "Bob")),
    ("female", "female", MF, ("Ann", "Bob")),
    ("male", "male", MF, ("Ann", "Bob")),
    ("", "", MF, ("Ann", "Bob")),
    ("female", "male", {}, ("Ann", "Bob")),
    ("female", "male", FM, ("Ann", "Bob")),
    ("male", "female", FM, ("Bob", "Ann")),
]
for g_actor, g_partner, rg, want in ROWS:
    got = assign_roles("Ann", "Bob", g_actor, g_partner, rg)
    check(f"Ann={g_actor or '-'} Bob={g_partner or '-'} rg={rg or '{}'} -> A={want[0]}",
          got == want, str(got))

# ── [3] the listing before any write ────────────────────────────────────
print("\n[3] nothing assigned yet")
v = views()
check("both hug halves list {}", v["hug__a.fbx"] == {} and v["hug__b.fbx"] == {}, str(v))
check("the solo clip lists {}", v["wave.fbx"] == {})

# ── [4] writing ─────────────────────────────────────────────────────────
print("\n[4] set_clip_role_gender writes the kind's sidecar")
out = ac.set_clip_role_gender("free", "hug__b.fbx", FM)
check("hug.json carries the assignment", sidecar("hug.json").get("role_gender") == FM,
      str(sidecar("hug.json")))
check("the other numbers survive", sidecar("hug.json")["duration_s"] == 2.0)
v = views()
check("both halves list it", v["hug__a.fbx"] == FM and v["hug__b.fbx"] == FM, str(v))
check("the answer names both halves",
      sorted(c["rel"] for c in out) == ["hug__a.fbx", "hug__b.fbx"],
      str([c["rel"] for c in out]))

# ── [5] clearing ────────────────────────────────────────────────────────
print("\n[5] None removes the assignment")
ac.set_clip_role_gender("free", "hug__a.fbx", None)
check("hug.json has no role_gender", "role_gender" not in sidecar("hug.json"),
      str(sidecar("hug.json")))
v = views()
check("both halves list {} again", v["hug__a.fbx"] == {} and v["hug__b.fbx"] == {})


# ── [6] refusals ────────────────────────────────────────────────────────
print("\n[6] refusals")


def refused(label: str, fn, not_found: bool = False) -> None:
    try:
        fn()
        check(label, False, "no error raised")
    except ac.ClipNotFound as e:
        check(label, not_found, str(e))
    except ac.ClipLibraryError as e:
        check(label, not not_found, str(e))


refused("a solo clip has no halves", lambda: ac.set_clip_role_gender("free", "wave.fbx", MF))
check("… and wave.json is untouched", "role_gender" not in sidecar("wave.json"))
refused("two men is no assignment",
        lambda: ac.set_clip_role_gender("free", "hug__a.fbx", {"a": "male", "b": "male"}))
check("… and nothing was written", "role_gender" not in sidecar("hug.json"))
refused("a pair without a sidecar", lambda: ac.set_clip_role_gender("free", "kiss__a.fbx", MF))
check("… and no sidecar was created", not (CLIPS / "kiss.json").exists())
refused("a missing clip is a 404", lambda: ac.set_clip_role_gender("free", "nope__a.fbx", MF),
        not_found=True)

print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("all checks passed")
