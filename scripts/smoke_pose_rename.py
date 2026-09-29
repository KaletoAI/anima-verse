#!/usr/bin/env python3
"""Smoke check: renaming a pose catalog key (plan-pose-key-rename.md).

Usage: ./.venv/bin/python scripts/smoke_pose_rename.py

Runs against a throwaway world (``paths.init(<tmp>)`` before any world-DB
import) and a private COPY of the shipped pose catalog, injected through
``pose_catalog.catalog_path`` — the one funnel router and loader share. The
real catalog file is compared byte for byte at the end.

Expectations, derived BY HAND from the design:

Setup — the copy's `seat` group default is pointed at `reading` (a seat pose);
a world group row `seat` does the same; `cooking` gets a world row that
overrides the shared entry (a key in BOTH layers). Characters `demo` (pose
`reading`) and `demo_b` (pose `sitting`, a running interaction on `reading`,
free-text outfit "a red coat"). Invites: one on `reading`, one on `sitting`.
Candidates: pose "buch schmoekern" -> `reading`, pose "leselampe" ->
`sitting`, expression "stirnrunzeln" -> `reading` (other axis), and an open
pose row whose text is "lesen" (the new key).

Variants in demo's outfits dir, all with sidecar pose_key `reading`:
  V1 verified — no pieces, no items, no outfit text, so the outfit part of the
     stem is "" and the stem is "demo_" + md5("neutral:reading:")[:12]; after
     the rename it must sit at "demo_" + md5("neutral:lesen:")[:12] with its
     sidecar, and nothing under the old stem.
  V2 unverifiable — stem "demo_000000000000" matches no hash: kept in place,
     sidecar rewritten (pose_key AND activity `lesen`).
  V3 unrelated — pose_key `sitting`: untouched byte for byte.
  V5 clash — expression `positive`, stem "demo_" + md5("positive:reading:")[:12]
     verifies, but a file already sits at "demo_" + md5("positive:lesen:")[:12]:
     kept under its old stem (sidecar rewritten), the squatter untouched.
and in demo_b's dir:
  V4 free text — stem computed from the outfit text "a red coat"; the text is
     then changed to "a blue coat" BEFORE the rename, so the stem can no longer
     be re-derived: kept (the conservative rule), sidecar rewritten.

Refusals (each writes NOTHING — catalog file bytes unchanged):
  `sleeping` -> 400 (code-named), new == old -> 400, "a/b" -> 400 (slash),
  axis expression -> 400, `nope` -> 404, onto `sitting` -> 409 (a key),
  onto "sitzen" -> 409 (a synonym of `sitting`).

Rename `reading` -> " Lesen " (normalised to `lesen`, one of reading's OWN
synonyms — allowed, and dropped from its synonym list):
  - shared entries: `lesen` at index 2 (where `reading` was), `reading` gone,
    synonyms = the original seven minus "lesen" (six), group `seat`.
  - shared groups.seat.default == `lesen`; world group row seat default `lesen`.
  - demo pose_key `lesen`; demo_b interaction.pose_key `lesen`, its own
    pose_key still `sitting`.
  - invites: the `reading` row -> `lesen`, the `sitting` row unchanged.
  - candidates: "buch schmoekern" -> `lesen`, "leselampe" still `sitting`,
    the expression row still `reading`, the open "lesen" row deleted.
  - response references == {profiles 2, invites 1, candidates 1,
    candidates_closed 1, variants_moved 1, variants_kept 3 (V2, V4, V5),
    failed []}, stores ["shared"].
  - the CACHED catalog sees it without a manual reload (the route drops the
    caches): get_catalog has `lesen`, not `reading`; get_groups seat default
    `lesen`. The same cache check follows the two renames below.
Rename `cooking` -> "am herd kochen" (key in both layers): both the shared
file and the world layer carry the new key, neither the old; stores
["shared", "world"].
A world-only entry `demo world pose` renamed to `demo world pose b`: the world
row moves, the shared file is byte-identical, stores ["world"].
Finally validate_catalog("pose") == [].
"""
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_tmp = tempfile.mkdtemp(prefix="smoke_pose_rename_")
from app.core import paths  # noqa: E402
paths.init(_tmp)

from fastapi import HTTPException  # noqa: E402

from app.core import pose_catalog as pc  # noqa: E402
from app.core.db import get_connection, init_schema, transaction  # noqa: E402

REAL = pc.catalog_path("pose")
REAL_BYTES = REAL.read_bytes()
failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


def md5_12(text):
    return hashlib.md5(text.encode()).hexdigest()[:12]


try:
    init_schema()
    cat = Path(_tmp) / "pose_catalog.json"
    doc = json.loads(REAL_BYTES)
    doc["groups"]["seat"]["default"] = "reading"
    cat.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    _orig_path = pc.catalog_path
    pc.catalog_path = lambda a: cat if a == "pose" else _orig_path(a)
    pc.reload_catalogs()

    from app.routes import poses as R
    from app.models import character as ch
    from app.core.model_refs import outfit_signature_raw

    orig_reading_syn = list(doc["entries"]["reading"]["synonyms"])
    pc.replace_world_groups({"seat": dict(doc["groups"]["seat"])})
    cooking_world = dict(doc["entries"]["cooking"], prompt="world cooking")
    pc.replace_world_entries("pose", {"cooking": cooking_world})
    pc.reload_catalogs()

    now = "2026-09-29T00:00:00Z"
    with transaction() as conn:
        for name in ("demo", "demo_b"):
            conn.execute(
                "INSERT INTO characters (name, template, profile_json, config_json,"
                " created_at, updated_at) VALUES (?, '', '{}', '{}', ?, ?)",
                (name, now, now))
        conn.execute("INSERT INTO interaction_invites (invite_id, inviter, invitee,"
                     " pose_key, created_at, status) VALUES"
                     " ('i1','demo','demo_b','reading',?,'pending'),"
                     " ('i2','demo_b','demo','sitting',?,'pending')", (now, now))
        for axis, text, near in (("pose", "buch schmoekern", "reading"),
                                 ("pose", "leselampe", "sitting"),
                                 ("expression", "stirnrunzeln", "reading"),
                                 ("pose", "lesen", "")):
            conn.execute("INSERT INTO pose_candidates (axis, raw_text, nearest_key,"
                         " first_seen, last_seen) VALUES (?,?,?,?,?)",
                         (axis, text, near, now, now))

    p = ch.get_character_profile("demo")
    p["pose_key"] = "reading"
    assert ch.save_character_profile("demo", p)
    p = ch.get_character_profile("demo_b")
    p["pose_key"] = "sitting"
    p["outfit_description"] = "a red coat"
    p["interaction"] = {"id": "x", "pose_key": "reading", "role": "b", "partner": "demo"}
    assert ch.save_character_profile("demo_b", p)

    def outfits(name):
        d = ch.get_character_dir(name, create=True) / "outfits"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def variant(folder, stem, pose, **extra):
        meta = {"expression_key": "neutral", "pose_key": pose, "activity": pose,
                "equipped_pieces": {}, "equipped_items": [], "state_fingerprint": ""}
        meta.update(extra)
        (folder / f"{stem}.png").write_bytes(b"png:" + stem.encode())
        (folder / f"{stem}.json").write_text(json.dumps(meta), encoding="utf-8")

    d_demo, d_b = outfits("demo"), outfits("demo_b")
    check(outfit_signature_raw({}, [], "demo") == "", "demo outfit signature not empty")
    v1_old = "demo_" + md5_12("neutral:reading:")
    v1_new = "demo_" + md5_12("neutral:lesen:")
    variant(d_demo, v1_old, "reading")
    variant(d_demo, "demo_000000000000", "reading")
    v3 = "demo_" + md5_12("neutral:sitting:")
    variant(d_demo, v3, "sitting")
    v3_bytes = (d_demo / f"{v3}.json").read_bytes()
    red = outfit_signature_raw({}, [], "demo_b")
    check(red != "", "free-text outfit signature is empty - V4 would not test the text branch")
    v5_old = "demo_" + md5_12("positive:reading:")
    v5_new = "demo_" + md5_12("positive:lesen:")
    variant(d_demo, v5_old, "reading", expression_key="positive")
    (d_demo / f"{v5_new}.png").write_bytes(b"squatter")
    v4 = "demo_b_" + md5_12(f"neutral:reading:{red}")
    variant(d_b, v4, "reading")
    p = ch.get_character_profile("demo_b")
    p["outfit_description"] = "a blue coat"
    assert ch.save_character_profile("demo_b", p)

    # ── refusals ─────────────────────────────────────────────────────────
    before = cat.read_bytes()
    for key, axis, new, status in (("sleeping", "pose", "schlafend", 400),
                                   ("reading", "pose", "reading", 400),
                                   ("reading", "pose", "a/b", 400),
                                   ("reading", "expression", "lesen", 400),
                                   ("nope", "pose", "neu", 404),
                                   ("reading", "pose", "sitting", 409),
                                   ("reading", "pose", "sitzen", 409)):
        try:
            R._rename_entry_sync(key, axis, {"new_key": new})
            failures.append(f"refusal {key}->{new} ({axis}) went through")
        except HTTPException as e:
            check(e.status_code == status, f"{key}->{new}: {e.status_code} != {status}")
    check(cat.read_bytes() == before, "a refused rename wrote the catalog")

    # ── the rename ───────────────────────────────────────────────────────
    res = R._rename_entry_sync("reading", "pose", {"new_key": " Lesen "})
    check(res["key"] == "lesen" and res["stores"] == ["shared"], f"response {res}")
    check(res["references"] == {"profiles": 2, "invites": 1, "candidates": 1,
                                "candidates_closed": 1, "variants_moved": 1,
                                "variants_kept": 3, "failed": []},
          f"references {res['references']}")
    cached = pc.get_catalog("pose")
    check("lesen" in cached and "reading" not in cached, "cache not dropped after rename")
    check(pc.get_groups()["seat"]["default"] == "lesen", "cached seat default")
    after = json.loads(cat.read_text(encoding="utf-8"))
    keys = list(after["entries"])
    check("reading" not in keys and keys.index("lesen") == 2, f"order {keys[:4]}")
    check(after["entries"]["lesen"]["synonyms"] == [s for s in orig_reading_syn if s != "lesen"],
          f"synonyms {after['entries']['lesen']['synonyms']}")
    check(after["groups"]["seat"]["default"] == "lesen", "shared seat default")
    check(pc.world_groups()["seat"]["default"] == "lesen", "world seat default")
    check(ch.get_character_profile("demo").get("pose_key") == "lesen", "demo pose_key")
    pb = ch.get_character_profile("demo_b")
    check(pb.get("pose_key") == "sitting", "demo_b pose_key changed")
    check((pb.get("interaction") or {}).get("pose_key") == "lesen", "demo_b interaction")
    conn = get_connection()
    inv = dict(conn.execute("SELECT invite_id, pose_key FROM interaction_invites").fetchall())
    check(inv == {"i1": "lesen", "i2": "sitting"}, f"invites {inv}")
    cand = {(a, t): n for a, t, n in conn.execute(
        "SELECT axis, raw_text, nearest_key FROM pose_candidates").fetchall()}
    check(cand == {("pose", "buch schmoekern"): "lesen", ("pose", "leselampe"): "sitting",
                   ("expression", "stirnrunzeln"): "reading"}, f"candidates {cand}")
    check((d_demo / f"{v1_new}.png").exists() and (d_demo / f"{v1_new}.json").exists()
          and not (d_demo / f"{v1_old}.png").exists()
          and not (d_demo / f"{v1_old}.json").exists(), "V1 not moved")
    v1_meta = json.loads((d_demo / f"{v1_new}.json").read_text())
    check(v1_meta["pose_key"] == "lesen" and v1_meta["activity"] == "lesen", "V1 sidecar")
    v2 = json.loads((d_demo / "demo_000000000000.json").read_text())
    check((d_demo / "demo_000000000000.png").exists()
          and v2["pose_key"] == "lesen" and v2["activity"] == "lesen", "V2 not kept+rewritten")
    check((d_demo / f"{v3}.json").read_bytes() == v3_bytes, "V3 touched")
    v4m = json.loads((d_b / f"{v4}.json").read_text())
    check((d_b / f"{v4}.png").exists() and v4m["pose_key"] == "lesen", "V4 not kept+rewritten")
    v5m = json.loads((d_demo / f"{v5_old}.json").read_text())
    check((d_demo / f"{v5_old}.png").exists() and v5m["pose_key"] == "lesen"
          and (d_demo / f"{v5_new}.png").read_bytes() == b"squatter"
          and not (d_demo / f"{v5_new}.json").exists(), "V5 clash not kept")

    # ── key in both layers ───────────────────────────────────────────────
    res = R._rename_entry_sync("cooking", "pose", {"new_key": "am herd kochen"})
    check(res["stores"] == ["shared", "world"], f"cooking stores {res['stores']}")
    after = json.loads(cat.read_text(encoding="utf-8"))
    world = pc.world_entries("pose")
    check("am herd kochen" in after["entries"] and "cooking" not in after["entries"],
          "cooking shared")
    check(set(world) == {"am herd kochen"} and world["am herd kochen"]["prompt"] == "world cooking",
          f"cooking world {set(world)}")
    cached = pc.get_catalog("pose")
    check("am herd kochen" in cached and "cooking" not in cached
          and cached["am herd kochen"]["prompt"] == "world cooking", "cooking cache")

    # ── world-only entry ─────────────────────────────────────────────────
    R._create_entry_sync({}, {"axis": "pose", "key": "demo world pose", "prompt": "x",
                              "animation": "idle", "group": "stand", "store": "world"})
    before = cat.read_bytes()
    res = R._rename_entry_sync("demo world pose", "pose", {"new_key": "demo world pose b"})
    check(res["stores"] == ["world"], f"world-only stores {res['stores']}")
    check(cat.read_bytes() == before, "world-only rename wrote the shared file")
    check("demo world pose b" in pc.world_entries("pose")
          and "demo world pose" not in pc.world_entries("pose"), "world-only row")
    cached = pc.get_catalog("pose")
    check("demo world pose b" in cached and "demo world pose" not in cached,
          "world-only cache not dropped")

    check(pc.validate_catalog("pose") == [], f"problems {pc.validate_catalog('pose')}")
    pc.catalog_path = _orig_path
except Exception as e:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    failures.append(f"crashed: {e!r}")
finally:
    if REAL.read_bytes() != REAL_BYTES:
        failures.append("the REAL catalog file was modified")
    shutil.rmtree(_tmp, ignore_errors=True)

print("FAIL:\n" + "\n".join(failures) if failures else "OK smoke_pose_rename")
sys.exit(1 if failures else 0)
