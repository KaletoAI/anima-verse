#!/usr/bin/env python3
"""Smoke check: pose/expression catalog integrity + resolution rules.

Usage: ./.venv/bin/python scripts/smoke_pose_catalog.py

Expected values, derived BY HAND from plan-pose-katalog.md:
- pose catalog: 53 entries (50 transferred 1:1 from the 51 curated presets
  + the three partner poses "shaking hands" / "dancing together" (2026-08-20)
  and "comforting" (2026-08-21),
  minus `bending_to_fridge`, removed by the user on 2026-08-17; the set still
  includes the `sleeping` entry Task 3 needs), every entry has
  a non-empty animation kind, exactly one _default (standing).
- expression catalog: 8 entries, exactly one _default (neutral).
- no alias (key or synonym) maps to two different entries.

Stage 2 - resolution rules, derived BY HAND from the catalog files:
- "sitzen" is listed as a synonym of `sitting` -> ("sitting", "exact").
- With the injected 3-axis fake embedding, only the alias "gardening" shares
  the "garden" axis with the query "digging in the garden bed": cosine 1.0 >=
  the 0.60 threshold -> ("gardening", "embedding").
- "quantum flux calibration" sits on its own axis, cosine 0.0 against every
  alias -> default key `standing`, how "fallback", plus one `pose_candidates`
  row with count 1 and distance 1.0 (= 1.0 - 0.0).
- sanitize_flavor: quoted speech removed, first sentence only, hard 120-char
  cap. Character-name removal needs a populated world (empty temp DB here) -
  it is checked manually in Task 6.

Stage 3 - the canonical setter (task 3), derived BY HAND from the setter code
and the catalog files:
- set_pose_intent("sitzen") -> pose_key `sitting` (listed synonym, exact hit),
  pose_flavor "sitzen" (sanitize_flavor keeps it, it differs from the key),
  exactly one profile write.
- the same text again -> key AND flavor unchanged -> ZERO writes.
- "Sitting" -> same key, flavor equals the key case-insensitively and is
  therefore dropped -> one more write.
- is_sleeping=1 -> get_effective_activity "Sleeping",
  get_effective_pose_key "sleeping" (catalog entry), stored fields untouched.
- clear_pose_intent -> pose_key/pose_flavor "".
- sanitize_flavor("demo sits on the bench") -> "sits on the bench": with a
  character row present the name removal (D7) is finally observable.

Stage 4 - the consumers (task 4), derived BY HAND from the catalog files:
- get_pose_prompt("gardening") -> the `gardening` entry's prompt verbatim;
  an unknown key -> the `standing` (=_default) prompt.
- resolve_pose_animation("sitting") == "sit", is_partner_activity("sitting")
  is False (every curated entry is solo:true today).
- resolve_expression_key("happy") == "positive" ("happy" is a listed synonym),
  resolve_expression_key("") == "neutral" (the _default entry). With the
  embedding backend unavailable, unknown text falls back to "neutral" too and
  leaves ONE candidate row (distance NULL - no vector, no distance).
- the cache key has exactly two catalog axes: two moods of the same
  expression key produce the SAME key, an unknown pose key collapses onto the
  default `standing`, and a different expression key changes the key.

Stage 5 - admin surface (task 6), derived BY HAND from the route contract:
- `_axis` accepts exactly "pose"/"expression" (case/whitespace tolerant) and
  answers anything else with HTTP 400, never a KeyError-500.
- `_alias_owner("pose", "sitzen")` == "sitting" (listed synonym), an unclaimed
  text -> "" (that is what the approve conflict check reads).
- the router carries NO `/variants/clear` path any more (pose variants were
  torn out Aug 2026) but DOES carry `/expression-images/clear` — the image
  cache is keyed by the catalog key, so a prompt edit needs that reset.
- `delete_candidate` removes the row for good (approve), while
  `set_candidate_status(..., "dismissed")` keeps it and only takes it out of
  the open list (dismiss).
- approve/new-entry KEEPS the synonyms the admin typed: ["Baking bread",
  " rolling dough ", ""] + raw_text "kneading dough" under the key `kneading`
  -> ["baking bread", "rolling dough", "kneading dough"] (trimmed,
  lowercased, empties dropped, no duplicate, the key never its own synonym),
  and "baking bread" resolves to `kneading` afterwards.
- an alias already owned by another entry ("sitzen" -> `sitting`) is a 409
  naming the owner, and NOTHING is written: no entry, candidate still open.
- the SAME uniqueness rule holds on the plain write paths, not just approve:
  `create_entry` with the synonym "sitzen" (owned by `sitting`) -> 409
  "'sitzen' already belongs to 'sitting'", and the key stays absent from the
  file; `update_entry` re-saving `kneading` with exactly the synonyms it
  already owns -> success (its own key is excluded from the check), while
  `update_entry` adding the foreign "sitzen" to it -> 409 again.
The real catalog FILES are never written: the approve checks run against a
COPY in the throwaway dir, injected through `pose_catalog.catalog_path` (the
one funnel both router and loader use) and restored afterwards.

Stage 6 - the resolver's "never raises" guard, derived BY HAND from
`resolve_to_catalog`: with the alias-embedding cache pre-seeded (module
internals) with ONE alias that the current index does NOT contain, a query
whose fake vector is identical to it scores cosine 1.0 >= the 0.60 threshold
and wins the loop. `index[best_alias]` would be a KeyError, so the guard has
to fall through: expected ("standing", "fallback") plus one candidate row for
the query text with nearest_key "" (the ghost alias resolves to nothing) and
distance 1.0 - 1.0 = 0.0.

Stage 7 - the pose-variant teardown (Aug 2026), derived BY HAND from it:
- `app.core.pose_variants` and `app.core.pose_engine` no longer import, and no
  file under app/ or plugins/ names them - except world_db_schema.py, which
  keeps the retired `character_pose_variants` table because this stream ships
  no DB migrations.
- a pose change still lands in character_state and still drives the expression
  cache key (`gardening` and `sitting` produce different keys), while the
  retired table stays empty.
- `clear_expression_cache` - the surviving per-character reset - runs without
  any variant row and reports 0 for a character that never rendered.

Stage 8 - place types (plan-posen-plaetze.md § 3.1/3.2), derived BY HAND
from the catalog file:
- get_groups() has exactly the five start types seat/bed/floor/counter/stand;
  seat.root_drop == 0.314, bed 0.631, floor 0.051, counter 0, stand 0
  (the numbers scene_recipe.FIGURE_ROOT_DROP still holds today).
- every entry carries a group that exists; group_of("sitting") == "seat",
  group_of("sleeping") == "bed", group_of("standing") == "stand",
  group_of("nope") == "".
- poses_in_group("seat") starts with the group's default "sitting".
- pose_places("sitting") == 1 (solo), pose_places("dancing together") == 2
  (pair default), pose_yaw_offset("dancing together") == 0.0; the stored entry
  says the same as the accessor, so a solo entry carries places 1, not 2.
- the place vocabulary is POSE vocabulary: an expression entry (`neutral`) has
  no group/places/yaw_offset at all.
- validate_catalog("pose") is empty for the shipped file; a private copy with
  a pose in group "sofa" (unknown) and a group whose default is a pose of
  another group reports exactly those two problems.

The stage-2/3/4/5/7 DB work runs against a throwaway storage dir, never the
demo world (the server may hold it).
"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Point every storage path at a temp world BEFORE anything opens the DB.
_tmp_storage = tempfile.mkdtemp(prefix="smoke_pose_catalog_")
from app.core import paths  # noqa: E402
paths.init(_tmp_storage)

from app.core.pose_catalog import (  # noqa: E402
    get_catalog, get_default_key, list_candidates, resolve_to_catalog,
    sanitize_flavor, validate_catalog,
)

failures = []
for axis, expected_count, expected_default in (
        ("pose", 53, "standing"), ("expression", 8, "neutral")):
    catalog = get_catalog(axis)
    if len(catalog) != expected_count:
        failures.append(f"{axis}: {len(catalog)} entries, expected {expected_count}")
    if get_default_key(axis) != expected_default:
        failures.append(f"{axis}: default {get_default_key(axis)!r}, expected {expected_default!r}")
    failures.extend(validate_catalog(axis))

print("FAIL:\n" + "\n".join(failures) if failures else "OK smoke_pose_catalog stage 1")
if failures:
    shutil.rmtree(_tmp_storage, ignore_errors=True)
    sys.exit(1)

# ── Stage 2: resolution rules with an injected embedding function ────────
try:
    from app.core.db import init_schema
    init_schema()

    def fake_embed(text):
        """Three orthogonal axes: gardening, everything else, quantum."""
        if "garden" in text:
            return [1.0, 0.0, 0.0]
        if "quantum" in text:
            return [0.0, 0.0, 1.0]
        return [0.0, 1.0, 0.0]

    k, how = resolve_to_catalog("sitzen", "pose", _embed=fake_embed)
    assert (k, how) == ("sitting", "exact"), (k, how)
    k, how = resolve_to_catalog("", "pose", _embed=fake_embed)
    assert (k, how) == ("standing", "empty"), (k, how)
    k, how = resolve_to_catalog("digging in the garden bed", "pose", _embed=fake_embed)
    assert (k, how) == ("gardening", "embedding"), (k, how)

    k, how = resolve_to_catalog("quantum flux calibration", "pose", _embed=fake_embed)
    assert (k, how) == ("standing", "fallback"), (k, how)
    resolve_to_catalog("Quantum Flux Calibration", "pose", _embed=fake_embed)
    rows = list_candidates("pose")
    assert len(rows) == 1, rows
    assert rows[0]["raw_text"] == "quantum flux calibration", rows[0]
    assert rows[0]["count"] == 2 and rows[0]["distance"] == 1.0, rows[0]
    assert rows[0]["nearest_key"] == "", rows[0]

    # sanitize_flavor: quoted speech + first sentence + 120-char cap.
    flavor = sanitize_flavor('holding a hot mug "so warm!" and glancing at the shelves. Then she waits.')
    assert flavor == "holding a hot mug and glancing at the shelves.", flavor
    # German quotes: „die tasse“ is dropped whole, the doubled space collapses
    # -> 'sie hebt und laechelt' (no sentence end, so nothing else is cut).
    flavor = sanitize_flavor("sie hebt „die tasse“ und laechelt")
    assert flavor == "sie hebt und laechelt", flavor
    assert sanitize_flavor("") == ""
    assert sanitize_flavor('"nothing but speech"') == ""
    assert len(sanitize_flavor("x" * 500)) == 120

    print("OK smoke_pose_catalog stage 2")

    # ── Stage 3: the canonical setter (write path, task 3) ───────────────
    # Runs against the same throwaway world; a single character row is all
    # save_character_profile needs. Only inputs that hit the catalog EXACTLY
    # are used, so no embedding model is ever loaded.
    from app.core import db as _db
    from app.models import character as _ch
    from app.core.timeutils import utc_now_iso as _now

    _ts = _now()
    with _db.transaction() as _conn:
        _conn.execute(
            "INSERT INTO characters (name, template, profile_json, config_json,"
            " created_at, updated_at) VALUES ('demo', '', '{}', '{}', ?, ?)",
            (_ts, _ts))

    def _state(field):
        row = _db.get_connection().execute(
            f"SELECT {field} FROM character_state WHERE character_name='demo'"
        ).fetchone()
        return row[0] if row else None

    def _variant_rows():
        """Retired table — must stay empty, nothing writes it any more."""
        return _db.get_connection().execute(
            "SELECT id, canonical_pose FROM character_pose_variants "
            "WHERE character_name='demo' ORDER BY id").fetchall()

    # Count the profile writes so the no-op branch is observable.
    _saves = {"n": 0}
    _real_save = _ch.save_character_profile

    def _counting_save(name, profile, create_new=False):
        _saves["n"] += 1
        return _real_save(name, profile, create_new=create_new)

    _ch.save_character_profile = _counting_save

    # 1. "sitzen" is a listed synonym of `sitting` -> exact catalog hit.
    #    sanitize_flavor("sitzen") == "sitzen" != the key, so it is KEPT.
    _ch.set_pose_intent("demo", "sitzen")
    assert _state("pose_key") == "sitting", _state("pose_key")
    assert _state("pose_flavor") == "sitzen", _state("pose_flavor")
    assert _variant_rows() == [], _variant_rows()
    assert _saves["n"] == 1, _saves

    # 2. Same text again: key AND flavor unchanged -> no write at all.
    _ch.set_pose_intent("demo", "sitzen")
    assert _saves["n"] == 1, _saves

    # 3. "Sitting" -> same key; the flavor equals the key (case-insensitively)
    #    and is therefore dropped. Flavor changed -> exactly one more write.
    _ch.set_pose_intent("demo", "Sitting")
    assert _state("pose_key") == "sitting", _state("pose_key")
    assert _state("pose_flavor") == "", repr(_state("pose_flavor"))
    assert _saves["n"] == 2, _saves
    assert _variant_rows() == [], _variant_rows()

    # 4. Read API: display text falls back to the key when the flavor is empty.
    assert _ch.get_character_pose_key("demo") == "sitting"
    assert _ch.get_character_pose_flavor("demo") == ""
    assert _ch.get_effective_activity("demo") == "sitting"
    assert _ch.get_effective_pose_key("demo") == "sitting"

    # 5. Sleeping overrides both read APIs (flag = authority, fields untouched).
    with _db.transaction() as _conn:
        _conn.execute("UPDATE character_state SET is_sleeping=1 "
                      "WHERE character_name='demo'")
    assert _ch.get_effective_activity("demo") == "Sleeping"
    assert _ch.get_effective_pose_key("demo") == "sleeping"
    assert _state("pose_key") == "sitting", _state("pose_key")
    with _db.transaction() as _conn:
        _conn.execute("UPDATE character_state SET is_sleeping=0 "
                      "WHERE character_name='demo'")

    # 6. clear_pose_intent empties both fields.
    _ch.clear_pose_intent("demo")
    assert _state("pose_key") == "", repr(_state("pose_key"))
    assert _state("pose_flavor") == "", repr(_state("pose_flavor"))
    assert _ch.get_effective_activity("demo") == ""

    # 7. Empty pose is a reset, not a write, once everything is already empty.
    _n_before = _saves["n"]
    _ch.set_pose_intent("demo", "   ")
    assert _saves["n"] == _n_before, _saves

    # 8. Name removal in the flavor now has a populated world to work with:
    #    the word "demo" is dropped, the rest keeps its wording.
    assert sanitize_flavor("demo sits on the bench") == "sits on the bench", \
        sanitize_flavor("demo sits on the bench")

    _ch.save_character_profile = _real_save
    print("OK smoke_pose_catalog stage 3")

    # ── Stage 4: the consumers (task 4) ──────────────────────────────────
    from app.core.expression_pose_maps import (
        default_pose_prompt, get_pose_prompt, is_partner_activity,
        reload_presets, resolve_expression_key, resolve_pose_animation,
    )
    from app.core.expression_regen import _cache_key

    _GARDENING = ("kneeling on ground, hands in soil, sun hat on, "
                  "looking down at plants")
    _STANDING = ("standing with one hand on hip, weight shifted to one leg, "
                 "shoulder slightly raised, chin up")
    assert get_pose_prompt("gardening") == _GARDENING, get_pose_prompt("gardening")
    # Unknown / empty key -> the default entry's prompt (no admin override set
    # in the temp world, so default_pose_prompt() is the catalog default).
    assert default_pose_prompt() == _STANDING, default_pose_prompt()
    assert get_pose_prompt("digging") == _STANDING, get_pose_prompt("digging")
    assert get_pose_prompt("") == _STANDING, get_pose_prompt("")

    assert resolve_pose_animation("sitting") == "sit", resolve_pose_animation("sitting")
    assert resolve_pose_animation("no_such_pose") == "", resolve_pose_animation("no_such_pose")
    assert is_partner_activity("sitting") is False
    assert is_partner_activity("no_such_pose") is False

    # Expression axis: listed synonym -> exact, empty -> default.
    assert resolve_expression_key("happy") == "positive", resolve_expression_key("happy")
    assert resolve_expression_key("") == "neutral", resolve_expression_key("")
    # Fallback: no embedding backend -> default key + one candidate row.
    import app.core.embedding as _emb
    _real_embed = _emb.embed
    _emb.embed = lambda *_a, **_kw: None
    try:
        reload_presets()          # drop the memo so the patched embed is used
        assert resolve_expression_key("quantum flux calibration") == "neutral"
        _cands = list_candidates("expression")
        assert len(_cands) == 1, _cands
        assert _cands[0]["raw_text"] == "quantum flux calibration", _cands[0]
        assert _cands[0]["distance"] is None, _cands[0]
    finally:
        _emb.embed = _real_embed
        reload_presets()

    # Cache key: exactly two catalog axes (character_name empty -> no DB read).
    _k_happy = _cache_key("happy", "sitting")
    _k_excited = _cache_key("excited", "sitting")      # same expression key
    _k_sad = _cache_key("sad", "sitting")              # different key
    _k_unknown_pose = _cache_key("happy", "no_such_pose")
    _k_default_pose = _cache_key("happy", "standing")
    assert _k_happy == _k_excited, (_k_happy, _k_excited)
    assert _k_happy != _k_sad, (_k_happy, _k_sad)
    assert _k_unknown_pose == _k_default_pose, (_k_unknown_pose, _k_default_pose)
    assert _k_happy != _k_default_pose, (_k_happy, _k_default_pose)

    print("OK smoke_pose_catalog stage 4")

    # ── Stage 5: the admin surface (task 6) ──────────────────────────────
    from fastapi import HTTPException
    from app.core.pose_catalog import delete_candidate, record_candidate, \
        set_candidate_status
    from app.routes.poses import _alias_owner, _axis

    # 1. Axis validation at the boundary: a URL param never becomes a 500.
    assert _axis("pose") == "pose"
    assert _axis(" Expression ") == "expression"
    for _bad in ("", "moods", None):
        try:
            _axis(_bad)
            raise AssertionError(f"axis {_bad!r} was accepted")
        except HTTPException as _e:
            assert _e.status_code == 400, _e.status_code

    # 2. Alias ownership (the approve conflict check).
    assert _alias_owner("pose", "sitzen") == "sitting", _alias_owner("pose", "sitzen")
    assert _alias_owner("pose", "standing") == "standing"
    assert _alias_owner("pose", "quantum flux calibration") == ""

    # 3. The variant-cache reset is gone; what the tab still needs — and the
    #    only reset that heals a prompt edit, since the image cache is keyed by
    #    the catalog KEY — is the world-wide expression-image clear.
    #    (the router carries its own /poses prefix — assert the FULL paths,
    #    an unprefixed needle would pass vacuously)
    from app.routes.poses import router as _poses_router
    _paths = {r.path for r in _poses_router.routes}
    assert "/poses/variants/clear" not in _paths, sorted(_paths)
    assert "/poses/expression-images/clear" in _paths, sorted(_paths)

    # 4. Candidate lifecycle: dismiss keeps the row, approve deletes it.
    #    (stage 2 already left the 'quantum flux calibration' row behind)
    _base = {c["raw_text"] for c in list_candidates("pose")}
    record_candidate("pose", "juggling knives", "standing", 0.7)
    record_candidate("pose", "counting stars", "", None)
    _open = {c["raw_text"] for c in list_candidates("pose")}
    assert _open - _base == {"juggling knives", "counting stars"}, _open
    assert set_candidate_status("pose", "counting stars", "dismissed") is True
    assert "counting stars" not in {c["raw_text"] for c in list_candidates("pose")}
    assert [c["raw_text"] for c in list_candidates("pose", status="dismissed")] \
        == ["counting stars"]
    assert delete_candidate("pose", "juggling knives") is True
    assert {c["raw_text"] for c in list_candidates("pose")} == _base
    assert delete_candidate("pose", "juggling knives") is False

    # 5. approve (new entry): the admin's synonyms are KEPT, the candidate text
    #    is merged in, and an alias already owned elsewhere is a 409 that
    #    writes nothing. The handler writes catalog FILES, so it runs against a
    #    COPY of the real pose catalog in the throwaway dir — `catalog_path` is
    #    the single funnel both the router and the loader go through.
    import asyncio
    import json as _json
    import shutil as _shutil
    from app.core import pose_catalog as _pc
    from app.core.expression_pose_maps import reload_presets as _reload
    from app.routes.poses import approve_candidate, create_entry, update_entry

    _real_path = _pc.catalog_path
    _tmp_cat = Path(_tmp_storage) / "pose_catalog_copy.json"
    _shutil.copyfile(_real_path("pose"), _tmp_cat)
    _pc.catalog_path = lambda a: _tmp_cat if a == "pose" else _real_path(a)
    _reload()

    class _Req:
        """Minimal stand-in for the parts of Request the handler touches."""
        def __init__(self, body):
            self._body = body

        async def json(self):
            return self._body

    def _entries():
        return _json.loads(_tmp_cat.read_text(encoding="utf-8"))["entries"]

    try:
        record_candidate("pose", "kneading dough", "standing", 0.5)
        asyncio.run(approve_candidate(_Req({
            "axis": "pose", "raw_text": "kneading dough", "key": "kneading",
            "prompt": "leaning over a table, pressing dough with both hands",
            "animation": "idle", "solo": True,
            "synonyms": ["Baking bread", " rolling dough ", ""],
        }), _={}))
        _new = _entries()["kneading"]
        # typed synonyms first (trimmed + lowercased, empties dropped), the
        # candidate text appended once, the key itself never a synonym
        assert _new["synonyms"] == ["baking bread", "rolling dough",
                                    "kneading dough"], _new["synonyms"]
        assert _new["animation"] == "idle" and _new["solo"] is True, _new
        assert "kneading dough" not in {c["raw_text"] for c in list_candidates("pose")}
        # the freshly approved aliases resolve now — that is the point of it
        assert resolve_to_catalog("baking bread", "pose")[0] == "kneading"

        # A synonym owned by another entry: 409, nothing written, candidate stays.
        record_candidate("pose", "perching on a stool", "sitting", 0.5)
        try:
            asyncio.run(approve_candidate(_Req({
                "axis": "pose", "raw_text": "perching on a stool",
                "key": "perching", "prompt": "perched on a stool",
                "animation": "idle", "synonyms": ["sitzen"],
            }), _={}))
            raise AssertionError("collision was accepted")
        except HTTPException as _e:
            assert _e.status_code == 409, _e.status_code
            assert "sitting" in _e.detail, _e.detail
        assert "perching" not in _entries(), sorted(_entries())
        assert "perching on a stool" in {c["raw_text"] for c in list_candidates("pose")}

        # 6. create (POST): the same uniqueness rule as approve — "sitzen"
        #    belongs to `sitting`, so the whole create is refused and the file
        #    never grows the key.
        try:
            asyncio.run(create_entry(_Req({
                "axis": "pose", "key": "perching",
                "prompt": "perched on a stool", "animation": "idle",
                "synonyms": ["sitzen"],
            }), _={}))
            raise AssertionError("create collision was accepted")
        except HTTPException as _e:
            assert _e.status_code == 409, _e.status_code
            assert _e.detail == "'sitzen' already belongs to 'sitting'", _e.detail
        assert "perching" not in _entries(), sorted(_entries())
        # a free key + free synonym still goes through (the check is not a wall)
        asyncio.run(create_entry(_Req({
            "axis": "pose", "key": "perching",
            "prompt": "perched on a stool", "animation": "idle",
            "synonyms": ["Stool Sitting "],
        }), _={}))
        assert _entries()["perching"]["synonyms"] == ["stool sitting"], _entries()["perching"]

        # 7. update (PUT): re-saving an entry with the synonyms it ALREADY owns
        #    must stay legal — its own key is excluded from the check.
        _own = _entries()["kneading"]["synonyms"]
        assert _own == ["baking bread", "rolling dough", "kneading dough"], _own
        asyncio.run(update_entry("kneading", _Req({"synonyms": _own}), axis="pose", _={}))
        assert _entries()["kneading"]["synonyms"] == _own, _entries()["kneading"]
        # ...but a FOREIGN alias is still a 409, and nothing is written.
        try:
            asyncio.run(update_entry("kneading", _Req({
                "prompt": "clobbered", "synonyms": _own + ["sitzen"],
            }), axis="pose", _={}))
            raise AssertionError("update collision was accepted")
        except HTTPException as _e:
            assert _e.status_code == 409, _e.status_code
            assert _e.detail == "'sitzen' already belongs to 'sitting'", _e.detail
        assert _entries()["kneading"]["synonyms"] == _own, _entries()["kneading"]
        assert _entries()["kneading"]["prompt"] != "clobbered", _entries()["kneading"]
    finally:
        _pc.catalog_path = _real_path
        _reload()
    # the real catalog file is untouched: back to the 50 curated entries
    assert len(get_catalog("pose")) == 53, len(get_catalog("pose"))
    assert "kneading" not in get_catalog("pose")

    print("OK smoke_pose_catalog stage 5")

    # ── Stage 6: the resolver survives a catalog edit under it ───────────
    # `_alias_embeddings` returns the CACHE verbatim when one exists, so a
    # pre-seeded cache holding an alias the current index does not know is
    # exactly the state a catalog edit racing the warm-up leaves behind.
    # The ghost wins the loop (cosine 1.0 against an identical query vector),
    # `index[best_alias]` would raise -> the guard must fall through instead.
    with _pc._lock:
        _pc._embed_cache["pose"] = {"ghost alias": [0.0, 1.0, 0.0]}
    try:
        # fake_embed("phantom drift") -> [0,1,0] (the "everything else" axis)
        k, how = resolve_to_catalog("phantom drift", "pose", _embed=fake_embed)
        assert (k, how) == ("standing", "fallback"), (k, how)
        _ghosted = [c for c in list_candidates("pose")
                    if c["raw_text"] == "phantom drift"]
        assert len(_ghosted) == 1, list_candidates("pose")
        assert _ghosted[0]["nearest_key"] == "", _ghosted[0]
        assert _ghosted[0]["distance"] == 0.0, _ghosted[0]
    finally:
        _pc.reload_catalogs()

    print("OK smoke_pose_catalog stage 6")

    # ── Stage 7: pose + expression still work WITHOUT pose variants ──────
    # Derived BY HAND from the teardown (Aug 2026): the pose write path and
    # the expression cache key never touch the variant cache any more.
    # 1. Source guard: no module imports the deleted modules.
    import importlib
    for _gone in ("app.core.pose_variants", "app.core.pose_engine"):
        try:
            importlib.import_module(_gone)
            raise AssertionError(f"{_gone} is back — the teardown regressed")
        except ModuleNotFoundError:
            pass
    _repo = Path(__file__).resolve().parents[1]
    _hits = [str(p.relative_to(_repo))
             for p in list((_repo / "app").rglob("*.py"))
             + list((_repo / "plugins").rglob("*.py"))
             if "pose_variants" in p.read_text(encoding="utf-8")
             or "pose_engine" in p.read_text(encoding="utf-8")]
    # world_db_schema keeps the retired TABLE (no DB migrations in this stream)
    assert _hits == ["app/core/world_db_schema.py"], _hits

    # 2. Round trip: a pose change lands in the state AND drives the
    #    expression cache key, with the retired table untouched.
    _ch.set_pose_intent("demo", "gardening")
    assert _state("pose_key") == "gardening", _state("pose_key")
    assert _ch.get_effective_pose_key("demo") == "gardening"
    _k_garden = _cache_key("happy", _ch.get_effective_pose_key("demo"))
    _ch.set_pose_intent("demo", "sitzen")
    _k_sit = _cache_key("happy", _ch.get_effective_pose_key("demo"))
    assert _k_garden != _k_sit, (_k_garden, _k_sit)
    assert _variant_rows() == [], _variant_rows()

    # 3. The surviving cache reset is per character and needs no variant row:
    #    a character that never rendered anything reports 0 deletions.
    from app.core.expression_regen import clear_expression_cache
    assert clear_expression_cache("demo") == 0

    _ch.clear_pose_intent("demo")
    print("OK smoke_pose_catalog stage 7")

    # ── Stage 8: place types (the groups a marker names) ─────────────────
    print("\nStage 8 - place types")
    from app.core import pose_catalog as pc
    _FAILURES = []

    def check(name, ok, detail=""):
        """Records a failed expectation instead of aborting the stage, so one
        broken group does not hide the rest."""
        if not ok:
            _FAILURES.append(name)
            print(f"  ✗ {name} {detail}".rstrip())

    pc.reload_catalogs()
    groups = pc.get_groups()
    check("five start types", sorted(groups) == ["bed", "counter", "floor", "seat", "stand"], str(sorted(groups)))
    check("seat root_drop 0.314", groups["seat"]["root_drop"] == 0.314)
    check("bed root_drop 0.631", groups["bed"]["root_drop"] == 0.631)
    check("floor root_drop 0.051", groups["floor"]["root_drop"] == 0.051)
    check("stand/counter drop 0", groups["stand"]["root_drop"] == 0 and groups["counter"]["root_drop"] == 0)
    cat = pc.get_catalog("pose")
    check("every pose has a known group", all(e["group"] in groups for e in cat.values()),
          str([k for k, e in cat.items() if e["group"] not in groups]))
    check("group_of sitting/sleeping/standing", (pc.group_of("sitting"), pc.group_of("sleeping"),
          pc.group_of("standing"), pc.group_of("nope")) == ("seat", "bed", "stand", ""))
    check("poses_in_group(seat) starts with default", pc.poses_in_group("seat")[0] == "sitting")
    check("pose_places solo 1 / pair 2", (pc.pose_places("sitting"), pc.pose_places("dancing together")) == (1, 2))
    check("solo entry stores 1 place", cat["sitting"]["places"] == 1, str(cat["sitting"]))
    _expr = pc.get_catalog("expression")["neutral"]
    check("expression entry has no place fields",
          not ({"group", "places", "yaw_offset"} & set(_expr)), str(sorted(_expr)))
    check("pose_yaw_offset pair 0.0", pc.pose_yaw_offset("dancing together") == 0.0)
    check("shipped catalog validates", pc.validate_catalog("pose") == [], str(pc.validate_catalog("pose")))
    # private copy with two deliberate faults
    import json as _json
    import tempfile as _tf
    from pathlib import Path as _P
    _bad = _P(_tf.mkdtemp(prefix="pose-groups-")) / "pose_catalog.json"
    _bad.write_text(_json.dumps({
        "groups": {"seat": {"label": "Seat", "root_drop": 0.3, "default": "standing"},
                   "stand": {"label": "Stand", "root_drop": 0, "default": "standing"}},
        "entries": {"standing": {"prompt": "p", "animation": "idle", "group": "stand", "_default": True},
                    "sitting": {"prompt": "p", "animation": "sit", "group": "sofa"}}}), encoding="utf-8")
    _orig = pc.catalog_path
    pc.catalog_path = lambda axis: _bad if axis == "pose" else _orig(axis)
    try:
        pc.reload_catalogs()
        _problems = pc.validate_catalog("pose")
        check("unknown group reported", any("sofa" in p for p in _problems), str(_problems))
        check("foreign default reported", any("default" in p and "seat" in p for p in _problems), str(_problems))
        check("exactly two problems", len(_problems) == 2, str(_problems))
    finally:
        pc.catalog_path = _orig
        shutil.rmtree(_bad.parent, ignore_errors=True)
        pc.reload_catalogs()

    if _FAILURES:
        raise AssertionError(f"stage 8: {len(_FAILURES)} failed check(s): {_FAILURES}")
    print("OK smoke_pose_catalog stage 8")
finally:
    shutil.rmtree(_tmp_storage, ignore_errors=True)
