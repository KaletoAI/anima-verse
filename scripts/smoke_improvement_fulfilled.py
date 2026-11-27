#!/usr/bin/env python3
"""Smoke: the improvement step state ``fulfilled`` and the key tokens of the
types that had none (artefact_cleanup, fallback_rerender, fill_missing,
image_rerender, mesh_from_tpose, model_replace, rig_weight_repair,
surface_bake).

Usage:
    ./.venv/bin/python scripts/smoke_improvement_fulfilled.py

Runs without the server, against a temp storage dir (``paths.init`` before any
world-DB import). Subjects are stubs (``unittest.mock.patch`` on the
``subjects`` helpers the types read); the store, the engine's ``scan`` and the
schema migration are real. Expected values, derived by hand from
``store.replace_steps_scan``'s docstring and the types' docstrings; a token
``tok(*parts)`` is the first 12 hex of sha256 over ``json.dumps(list(parts),
sort_keys=True)``:

[1] The store's transitions, one standing entry, key K:
    scan [K] → {"added": 1, "closed": 0}, K pending; the step runs (mark_running,
    mark_result done) → done; scan [K] again (the run did NOT satisfy the
    subject) → {"added": 0, "closed": 0}, K stays done (never re-spent);
    scan [] (subject satisfied) → {"added": 0, "closed": 0}, K fulfilled, its
    duration kept (a number); scan [K] (the SAME reason again) → {"added": 1,
    "closed": 0}, K pending with attempts 0, error "", no stamps.
    A pending step whose subject drops off: scan [] → {"added": 0, "closed": 1},
    fulfilled without a duration; listed again → {"added": 1, ...}, pending.
    A skipped step (given up / cancelled): scan [] then scan [K] → it stays
    skipped both times, {"added": 0, "closed": 0} (dismissed stays dismissed
    for the same token). The counters of ``store.get`` carry ``fulfilled``.
    Before this change (store at f5d0ed9f0) the re-listed key of a satisfied
    subject hit the done row: {"added": 0, "closed": 0}, status "done" — the
    reproduction this smoke's [1] and [3] turn around.
[2] The one-time migration (``db.init_schema``, flag
    ``improvement_steps_fulfilled_v1``): rows a = done, duration NULL (a scan
    closed it), b = done, duration 4.0 (it ran), c = skipped, d = pending. With
    the flag removed, init_schema → a fulfilled, b done, c skipped, d pending;
    the flag is set ("1"); a second init_schema changes nothing (a row set back
    to done with NULL duration stays done — the flag guards it).
[3] End to end through a real type (mesh_from_tpose, standing entry; Mia is
    off the base-body pipeline, an animal — the type lists no one else; the
    T-pose render is a temp file T; key ``Mia:sig1:tok("tpose.png", size,
    mtime_ns)``): due → scan adds 1; the step runs → done; the model now exists
    → scan → fulfilled, nothing offered (the queue holds no step of the entry);
    the model is deleted again with T unchanged (same token) → scan adds 1,
    the step pending again. That step is cancelled (skipped), the model exists,
    scan, the model is gone again, scan → still skipped, added 0. T rendered
    anew (new size → new token) → scan adds 1: a new key, pending.
[4] The tokens (each also moves when its input changes):
    artefact_cleanup ``orphans_token``: orphans b, a and a protected p →
      tok(["a", "b"]); an aborted report → "aborted"; the world key
      ``footwear_sources:tok(["/w/x"])``; old shapes ``character:Mia`` →
      name "Mia", ``footwear_sources`` → world.
    fallback_rerender character_images: portrait "p1.png" marked →
      ``character:Mia:tok("p1.png")``; "p2.png" → another key; ``_split`` of
      the old shape ``character:Mia`` → ("character", "Mia").
    image_rerender character_images: portrait "p1.png" by "hy" →
      ``character:Mia:tok("p1.png")``.
    fill_missing: character model ``character:Mia:tok("sigW")`` (worn
      signature); building ``location:loc1:tok("front.png")``; prop image
      ``prop:chair#0:tok("a red chair", "Chair")``; expressions
      ``character:Mia:tok("Mia_stem")``; clothing ``item:shirt:tok("", "blue
      shirt", "Shirt")``; ``_ident`` of old and new shapes → the ident.
    model_replace character: model {filename "s.glb", created_at "c1", job_id
      "j1"} by "hy" → ``character:Mia:tok("s.glb", "c1", "j1")``; created_at
      "c2" → another key; ``_split`` of old/new → ("character", "Mia").
    rig_weight_repair ``model_token``({created_at "c", job_id "j"}) =
      tok("c", "j"); ``split_key`` of ``character:Mia:sig1`` and
      ``character:Mia:sig1:abc`` → ("Mia", "sig1").
    surface_bake ``surface_token``(file m.glb of 3 bytes, rotation {y: 450})
      = tok(SURFACE_VERSION, {"mtime": int(mtime), "name": "m.glb", "size": 3},
      {"x": 0.0, "y": 90.0, "z": 0.0}); rotation {y: 180} → another token;
      ``_subject_key("room:l/r:abc")`` = "room:l/r", of the old shape "room:l/r"
      itself.
[5] A subject the type could not judge (``base.Listing.withheld``, review
    follow-up of 059b4de8a: a transient omission must not turn a done step
    fulfilled and re-run it at the next scan):
    store: K = ``s:A:t`` ran (done) but its subject is still due (listed →
    stays done); a scan with K unlisted and ``s:A`` withheld → {"added": 0,
    "closed": 0}, K done; listed again → {"added": 0, "closed": 0}, K done —
    zero new runs. The same unlisted scan WITHOUT the withholding (a subject
    genuinely satisfied) → K fulfilled, and the same reason again → {"added":
    1, "closed": 0}, K pending. A pending step under a withheld prefix stays
    pending (closed 0). ``s:A`` does not cover ``s:AB:t`` (pending →
    fulfilled, closed 1), but covers the old token-less shape ``s:A`` itself.
    A listed key ``s:B:t2`` under the withheld ``s:B`` is inserted (added 1)
    while its unlisted sibling ``s:B:t`` stays pending; ``s:A:t`` and ``s:A``
    (pending, ``s:A`` not withheld this time) close → closed 2.
    hair_fill end to end (standing entry, roster ``(["Mia"], [])``, worn
    hairstyle ``hair1`` missing, ``fit_token`` stubbed to "tokA" → key
    ``character:Mia:hair1:tokA``): due → added 1; the step runs → done, the
    hair still missing (still listed → stays done, {0, 0}); a run of the hair
    in flight → withheld ``character:Mia``, not listed → {0, 0}, done; the
    run ended, the hair still missing → listed → {0, 0}, done, the queue holds
    no step of the entry (zero new runs). Then the hair made (``_subject``
    None, nothing in flight → not withheld) → {0, 0}, fulfilled; missing again
    under the same token → {"added": 1, "closed": 0}, pending.
    What each figure type withholds (stubs): the roster ``([], ["Mia"])`` (a
    base model being built) → base_refresh ("base:Mia",), fit_refit
    ("character:Mia",), hair_fill ("character:Mia",), outfit_rebuild
    ("outfit:Mia",), garment_fill kind clothing ("clothing:Mia",) — and no
    candidate. Ready roster ``(["Mia"], [])``: base_refresh with a base render
    running (``_blocker`` "running") → ("base:Mia",); outfit_rebuild with the
    worn outfit sig1 ``outfit_info`` "running" → ("outfit:Mia:sig1",);
    garment_fill with the dress in flight → ("clothing:Mia:dress",).
    ``subjects.pipeline_roster``: Mia ready, Ann running, Bob failed (all on
    the pipeline) → (["Mia"], ["Ann"]); narrowed to "Ann" → ([], ["Ann"]).
    A roster read that fails raises (``list_available_characters`` strict):
    ``subjects.characters()`` raises, and a scan of a mesh_from_tpose entry
    raises and leaves its done step done.
    Fails on 059b4de8a: ``replace_steps_scan`` takes no ``withheld`` (TypeError)
    and the types have no ``list_candidates``.
"""
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="improvement-fulfilled-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="improvement-fulfilled-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core import model_surface  # noqa: E402
from app.core.improvements import engine, registry, store  # noqa: E402
import app.core.improvements.types  # noqa: E402,F401  (registers the types)
from app.core.improvements.types import (artefact_cleanup, fallback_rerender, fill_missing,  # noqa: E402
                                         image_rerender, mesh_from_tpose, model_replace,
                                         rig_weight_repair, subjects, surface_bake)

FAILS = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok ' if ok else 'FAIL'} {label}" + ("" if ok else f"\n       got:  {got!r}\n       want: {want!r}"))
    if not ok:
        FAILS.append(label)


def tok(*parts):
    return hashlib.sha256(json.dumps(list(parts), sort_keys=True).encode("utf-8")).hexdigest()[:12]


def step(entry, key):
    return next(s for s in store.list_steps(entry) if s["candidate_key"] == key)


def part1():
    print("[1] the store's transitions")
    entry = store.create("fake", "T", {}, "standing")["id"]
    K = "character:Mia:t1"
    listed = [(K, "Mia", 1, "")]
    check("due: added", store.replace_steps_scan(entry, listed), {"added": 1, "closed": 0})
    store.mark_running(entry, K)
    store.mark_result(entry, K, status="done", count_attempt=False)
    check("still listed after the run: nothing re-offered", store.replace_steps_scan(entry, listed),
          {"added": 0, "closed": 0})
    check("…the step stays done", step(entry, K)["status"], "done")
    check("satisfied: no closure counted", store.replace_steps_scan(entry, []), {"added": 0, "closed": 0})
    row = step(entry, K)
    check("…the step is fulfilled, its run's duration kept",
          (row["status"], isinstance(row["duration_s"], float)), ("fulfilled", True))
    check("the counters carry fulfilled", (store.get(entry)["fulfilled"], store.get(entry)["done"]), (1, 0))
    check("not listed again: still fulfilled", (store.replace_steps_scan(entry, []), step(entry, K)["status"]),
          ({"added": 0, "closed": 0}, "fulfilled"))
    check("the same reason again: offered again", store.replace_steps_scan(entry, listed),
          {"added": 1, "closed": 0})
    row = step(entry, K)
    check("…pending with a clean slate",
          (row["status"], row["attempts"], row["error"], row["started_at"], row["finished_at"], row["duration_s"]),
          ("pending", 0, "", None, None, None))

    P = "character:Ann:t1"
    check("a pending step whose subject drops off is closed",
          store.replace_steps_scan(entry, [(P, "Ann", 0, "")] + listed), {"added": 1, "closed": 0})
    check("…closed", store.replace_steps_scan(entry, listed), {"added": 0, "closed": 1})
    check("…as fulfilled without a duration", (step(entry, P)["status"], step(entry, P)["duration_s"]),
          ("fulfilled", None))
    check("…and offered again when listed again",
          (store.replace_steps_scan(entry, [(P, "Ann", 0, "")] + listed), step(entry, P)["status"]),
          ({"added": 1, "closed": 0}, "pending"))

    S = "character:Bob:t1"
    store.replace_steps_scan(entry, [(S, "Bob", 0, "")])
    store.mark_result(entry, S, status="skipped", error="cancelled", count_attempt=False)
    check("a skipped step, subject satisfied: stays skipped",
          (store.replace_steps_scan(entry, []), step(entry, S)["status"]), ({"added": 0, "closed": 0}, "skipped"))
    check("…and listed again with the same token: still skipped",
          (store.replace_steps_scan(entry, [(S, "Bob", 0, "")]), step(entry, S)["status"]),
          ({"added": 0, "closed": 0}, "skipped"))
    store.delete(entry)


def part2():
    print("[2] the one-time migration")
    entry = store.create("fake", "M", {}, "standing")["id"]
    conn = db.get_connection()
    rows = [("a", "done", None), ("b", "done", 4.0), ("c", "skipped", 1.0), ("d", "pending", None)]
    for key, status, duration in rows:
        conn.execute("INSERT INTO improvement_steps (improvement_id, candidate_key, status, duration_s) "
                     "VALUES (?, ?, ?, ?)", (entry, key, status, duration))
    conn.execute("DELETE FROM schema_meta WHERE key='improvement_steps_fulfilled_v1'")
    conn.commit()
    db.init_schema()
    statuses = {s["candidate_key"]: s["status"] for s in store.list_steps(entry)}
    check("scan-closed done → fulfilled, a run stays done",
          statuses, {"a": "fulfilled", "b": "done", "c": "skipped", "d": "pending"})
    flag = conn.execute("SELECT value FROM schema_meta WHERE key='improvement_steps_fulfilled_v1'").fetchone()
    check("the flag is set", flag["value"] if flag else None, "1")
    conn.execute("UPDATE improvement_steps SET status='done' WHERE improvement_id=? AND candidate_key='a'",
                 (entry,))
    conn.commit()
    db.init_schema()
    check("a second boot changes nothing", step(entry, "a")["status"], "done")
    store.delete(entry)


def part3():
    print("[3] end to end through mesh_from_tpose")
    typ = registry.get("mesh_from_tpose")
    tpose = STORAGE / "tpose.png"
    tpose.write_bytes(b"12345")
    state = {"model": False}

    def key_now():
        st = tpose.stat()
        return f"Mia:sig1:{tok('tpose.png', st.st_size, st.st_mtime_ns)}"

    with patch.object(subjects, "characters", lambda: ["Mia"]), \
         patch.object(mesh_from_tpose, "_on_figure_pipeline", lambda name: False), \
         patch.object(subjects, "character_tpose_signatures", lambda name: {"sig1"}), \
         patch.object(subjects, "character_model_signatures", lambda name: {"sig1"} if state["model"] else set()), \
         patch.object(subjects, "character_model_exists", lambda name, sig: state["model"]), \
         patch("app.core.model_refs.find_ref_image", lambda name, kind, sig=None: tpose):
        entry = store.create(typ.id, "Meshes", {"backend": "hy"}, "standing")["id"]
        k1 = key_now()
        check("the key carries the T-pose token", [c.key for c in typ.find_candidates({"backend": "hy"})], [k1])
        check("due: a step", engine.scan(entry), {"added": 1, "closed": 0})
        store.mark_running(entry, k1)
        store.mark_result(entry, k1, status="done", count_attempt=False)
        state["model"] = True
        check("the model exists: nothing offered", engine.scan(entry), {"added": 0, "closed": 0})
        check("…the step is fulfilled", step(entry, k1)["status"], "fulfilled")
        check("…and the queue holds no step of the entry",
              [r["candidate_key"] for r in engine.ordered_queue() if r["improvement_id"] == entry], [])
        state["model"] = False
        check("the model gone again, T unchanged: offered again", engine.scan(entry), {"added": 1, "closed": 0})
        check("…the same key, pending", (key_now(), step(entry, k1)["status"]), (k1, "pending"))

        store.mark_result(entry, k1, status="skipped", error="cancelled", count_attempt=False)
        state["model"] = True
        engine.scan(entry)
        state["model"] = False
        check("a dismissed step stays dismissed for the same token", engine.scan(entry), {"added": 0, "closed": 0})
        check("…skipped", step(entry, k1)["status"], "skipped")

        tpose.write_bytes(b"123456")
        k2 = key_now()
        check("a new T-pose render is a new key", k2 != k1, True)
        check("…a new step", engine.scan(entry), {"added": 1, "closed": 0})
        check("…pending, the old one still skipped",
              (step(entry, k2)["status"], step(entry, k1)["status"]), ("pending", "skipped"))
        store.delete(entry)
    check("mesh_from_tpose split_key: old and new shapes",
          (mesh_from_tpose.split_key("Mia:sig1"), mesh_from_tpose.split_key("Mia:sig1:abc")),
          (("Mia", "sig1"), ("Mia", "sig1")))


def part4():
    print("[4] the tokens")
    report = {"orphans": [{"key": "b"}, {"key": "a"}, {"key": "p", "protected": "grace"}]}
    check("artefact_cleanup: over the deletable orphan keys", artefact_cleanup.orphans_token(report),
          tok(["a", "b"]))
    check("artefact_cleanup: another set, another token",
          artefact_cleanup.orphans_token({"orphans": [{"key": "a"}]}) != tok(["a", "b"]), True)
    check("artefact_cleanup: aborted", artefact_cleanup.orphans_token({"aborted": "over budget"}), "aborted")
    with patch("app.core.footwear_source.collect", lambda dry_run=False: {"removed": ["/w/x"]}), \
         patch.object(artefact_cleanup, "_tree_size", lambda path: 0):
        check("artefact_cleanup: the world key", [c.key for c in artefact_cleanup._world_candidate()],
              [f"footwear_sources:{tok(['/w/x'])}"])
    check("artefact_cleanup: old shapes parse",
          (artefact_cleanup._name("character:Mia"), artefact_cleanup._name("character:Mia:abc"),
           artefact_cleanup._is_world("footwear_sources"), artefact_cleanup._is_world("footwear_sources:abc")),
          ("Mia", "Mia", True, True))

    portrait = {"filename": "p1.png", "prompt": "x", "backend": "hy", "source_file": "",
                "fallback_from": {"occasion": "photo", "intended_spec": "Big*"}}
    with patch.object(subjects, "characters", lambda: ["Mia"]), \
         patch.object(subjects, "character_profile", lambda name: dict(portrait)):
        fr = registry.get("fallback_rerender")
        check("fallback_rerender: the portrait's file name",
              [c.key for c in fr.find_candidates({"subject": "character_images"})], [f"character:Mia:{tok('p1.png')}"])
        ir = registry.get("image_rerender")
        params = {"subject": "character_images", "source_backend": "hy", "target_backend": "tr"}
        check("image_rerender: the portrait's file name",
              [c.key for c in ir.find_candidates(params)], [f"character:Mia:{tok('p1.png')}"])
        portrait["filename"] = "p2.png"
        check("fallback_rerender: a new portrait, a new key",
              [c.key for c in fr.find_candidates({"subject": "character_images"})], [f"character:Mia:{tok('p2.png')}"])
    check("fallback/image_rerender: old shapes parse",
          (fallback_rerender._split("character:Mia"), image_rerender._split(f"character:Mia:{tok('p1.png')}"),
           image_rerender._split("location:loc1:a.png")),
          (("character", "Mia"), ("character", "Mia"), ("location", "loc1:a.png")))

    fm = registry.get("fill_missing")
    with patch.object(subjects, "characters", lambda: ["Mia"]), \
         patch.object(subjects, "character_model", lambda name: None), \
         patch("app.core.model_refs.current_outfit_state", lambda name: ({}, [], "sigW")):
        check("fill_missing character model: the worn signature",
              [c.key for c in fm.find_candidates({"subject": "character_model"})], [f"character:Mia:{tok('sigW')}"])
    with patch.object(subjects, "locations", lambda: [{"id": "loc1", "name": "Inn"}]), \
         patch.object(subjects, "building_model", lambda loc: None), \
         patch.object(subjects, "building_source_image", lambda loc: "front.png"):
        check("fill_missing building: the source image",
              [c.key for c in fm.find_candidates({"subject": "building_model"})], [f"location:loc1:{tok('front.png')}"])
    with patch.object(subjects, "props", lambda: [{"id": "chair", "name": "Chair"}]), \
         patch.object(subjects, "prop_variants", lambda pid: [{"index": 0, "description": "a red chair"}]), \
         patch.object(subjects, "prop_has_source", lambda ident: False):
        check("fill_missing prop image: description and name",
              [c.key for c in fm.find_candidates({"subject": "prop_images"})],
              [f"prop:chair#0:{tok('a red chair', 'Chair')}"])
    with patch.object(subjects, "characters", lambda: ["Mia"]), \
         patch.object(subjects, "expression_missing_stem", lambda name: "Mia_stem"):
        check("fill_missing expressions: the wanted stem",
              [c.key for c in fm.find_candidates({"subject": "character_expressions"})],
              [f"character:Mia:{tok('Mia_stem')}"])
    with patch.object(subjects, "clothing_items",
                      lambda: [{"id": "shirt", "name": "Shirt", "prompt_fragment": "blue shirt"}]), \
         patch.object(subjects, "clothing_image_done", lambda iid: False):
        check("fill_missing clothing: prompt, fragment, name",
              [c.key for c in fm.find_candidates({"subject": "clothing_images"})],
              [f"item:shirt:{tok('', 'blue shirt', 'Shirt')}"])
    check("fill_missing: old and new shapes parse",
          (fill_missing._ident("character:Mia"), fill_missing._ident("prop:chair#0:abc")), ("Mia", "chair#0"))

    mr = registry.get("model_replace")
    model = {"backend": "hy", "filename": "s.glb", "created_at": "c1", "job_id": "j1"}
    params = {"subject": "character", "source_backend": "hy", "target_backend": "tr"}
    with patch.object(subjects, "characters", lambda: ["Mia"]), \
         patch.object(subjects, "character_model", lambda name: dict(model)):
        check("model_replace: the active model's generation",
              [c.key for c in mr.find_candidates(params)], [f"character:Mia:{tok('s.glb', 'c1', 'j1')}"])
        model["created_at"] = "c2"
        check("model_replace: a new model, a new key",
              [c.key for c in mr.find_candidates(params)], [f"character:Mia:{tok('s.glb', 'c2', 'j1')}"])
    check("model_replace: old and new shapes parse",
          (model_replace._split("character:Mia"), model_replace._split("prop:chair#0:abc")),
          (("character", "Mia"), ("prop", "chair#0")))

    check("rig_weight_repair: the model's generation",
          rig_weight_repair.model_token({"created_at": "c", "job_id": "j"}), tok("c", "j"))
    check("rig_weight_repair: old and new shapes parse",
          (rig_weight_repair.split_key("character:Mia:sig1"), rig_weight_repair.split_key("character:Mia:sig1:abc")),
          (("Mia", "sig1"), ("Mia", "sig1")))

    model_file = STORAGE / "m.glb"
    model_file.write_bytes(b"abc")
    mtime = int(model_file.stat().st_mtime)
    check("surface_bake: version, file, fix", surface_bake.surface_token(model_file, {"y": 450}),
          tok(model_surface.SURFACE_VERSION, {"mtime": mtime, "name": "m.glb", "size": 3},
              {"x": 0.0, "y": 90.0, "z": 0.0}))
    check("surface_bake: another fix, another token",
          surface_bake.surface_token(model_file, {"y": 180}) != surface_bake.surface_token(model_file, {"y": 450}),
          True)
    check("surface_bake: the subject key of old and new shapes",
          (surface_bake._subject_key("room:l/r:abc"), surface_bake._subject_key("room:l/r")), ("room:l/r", "room:l/r"))


def part5():
    print("[5] withheld subjects")
    entry = store.create("fake", "W", {}, "standing")["id"]
    K = "s:A:t"
    listed = [(K, "A", 2, "")]
    store.replace_steps_scan(entry, listed)
    store.mark_running(entry, K)
    store.mark_result(entry, K, status="done", count_attempt=False)
    check("ran, still due: stays done", store.replace_steps_scan(entry, listed), {"added": 0, "closed": 0})
    check("withheld and unlisted: untouched", store.replace_steps_scan(entry, [], withheld=["s:A"]),
          {"added": 0, "closed": 0})
    check("…still done", step(entry, K)["status"], "done")
    check("listed again: not re-offered", store.replace_steps_scan(entry, listed), {"added": 0, "closed": 0})
    check("…still done, attempts unchanged", (step(entry, K)["status"], step(entry, K)["attempts"]), ("done", 0))
    store.replace_steps_scan(entry, [])
    check("genuinely satisfied (not withheld): fulfilled", step(entry, K)["status"], "fulfilled")
    check("…and offered again when the reason recurs", store.replace_steps_scan(entry, listed),
          {"added": 1, "closed": 0})
    P, AB, OLD = "s:B:t", "s:AB:t", "s:A"
    store.replace_steps_scan(entry, listed + [(P, "B", 0, ""), (AB, "AB", 0, ""), (OLD, "A old", 0, "")])
    check("withheld s:A and s:B: only s:AB closes", store.replace_steps_scan(entry, [], withheld=["s:A", "s:B"]),
          {"added": 0, "closed": 1})
    check("…statuses", {k: step(entry, k)["status"] for k in (K, P, AB, OLD)},
          {K: "pending", P: "pending", AB: "fulfilled", OLD: "pending"})
    check("a listed key under a withheld prefix is inserted",
          store.replace_steps_scan(entry, [("s:B:t2", "B", 0, "")], withheld=["s:B"]), {"added": 1, "closed": 2})
    check("…its unlisted sibling stays", (step(entry, P)["status"], step(entry, "s:B:t2")["status"]),
          ("pending", "pending"))
    store.delete(entry)

    from app.core import base_body
    from app.core.improvements.types import base_refresh, garment_fill, hair_fill, outfit_rebuild
    hf = registry.get("hair_fill")
    hair = {"subject": ("hair1", "Bob cut"), "in_flight": False}
    HK = "character:Mia:hair1:tokA"
    with patch.object(subjects, "pipeline_roster", lambda wanted="": (["Mia"], [])), \
         patch.object(hair_fill, "_profile", lambda name: {}), \
         patch.object(hair_fill, "_subject", lambda name, profile: hair["subject"]), \
         patch.object(hair_fill, "_in_flight", lambda name, item: hair["in_flight"]), \
         patch.object(hair_fill, "fit_token", lambda name, profile, item: "tokA"), \
         patch("app.core.garments.run_estimate", lambda name, item, profile=None: {"hub_jobs": 1, "note": ""}):
        entry = store.create(hf.id, "Hair", {}, "standing")["id"]
        check("hair_fill: due", engine.scan(entry), {"added": 1, "closed": 0})
        check("…the key", [s["candidate_key"] for s in store.list_steps(entry)], [HK])
        store.mark_running(entry, HK)
        store.mark_result(entry, HK, status="done", count_attempt=False)
        check("…ran, the hair still missing", engine.scan(entry), {"added": 0, "closed": 0})
        hair["in_flight"] = True
        check("…a hair run in flight: withheld", hf.list_candidates({}).withheld, ("character:Mia",))
        check("…the scan leaves the step", engine.scan(entry), {"added": 0, "closed": 0})
        check("…done", step(entry, HK)["status"], "done")
        hair["in_flight"] = False
        check("…the run ended, still missing: nothing re-offered", engine.scan(entry), {"added": 0, "closed": 0})
        check("…done, no step queued", (step(entry, HK)["status"],
                                        [r["candidate_key"] for r in engine.ordered_queue()
                                         if r["improvement_id"] == entry]), ("done", []))
        hair["subject"] = None
        check("…the hair made: nothing new (a done step closes uncounted)", engine.scan(entry), {"added": 0, "closed": 0})
        check("…fulfilled", step(entry, HK)["status"], "fulfilled")
        hair["subject"] = ("hair1", "Bob cut")
        check("…missing again, the same token: offered again", engine.scan(entry), {"added": 1, "closed": 0})
        check("…pending", step(entry, HK)["status"], "pending")
        store.delete(entry)

    def withheld(typ, params):
        listing = typ.list_candidates(params)
        return listing.withheld, [c.key for c in listing.candidates]

    with patch.object(subjects, "pipeline_roster", lambda wanted="": ([], ["Mia"])):
        check("a base model being built: each figure type withholds the character",
              [withheld(registry.get(t), p) for t, p in
               (("base_refresh", {}), ("fit_refit", {}), ("hair_fill", {}), ("outfit_rebuild", {}),
                ("garment_fill", {"kind": "clothing"}))],
              [(("base:Mia",), []), (("character:Mia",), []), (("character:Mia",), []), (("outfit:Mia",), []),
               (("clothing:Mia",), [])])
    with patch.object(subjects, "pipeline_roster", lambda wanted="": (["Mia"], [])), \
         patch.object(base_refresh, "_profile", lambda name: {}), \
         patch.object(base_refresh, "_blocker", lambda name: ("running", "a base render is running")):
        check("base_refresh: a base render running", withheld(registry.get("base_refresh"), {}),
              (("base:Mia",), []))
    with patch.object(subjects, "pipeline_roster", lambda wanted="": (["Mia"], [])), \
         patch.object(outfit_rebuild, "_profile", lambda name: {}), \
         patch.object(outfit_rebuild, "_outfits", lambda name, scope: [("sig1", "")]), \
         patch.object(base_body, "outfit_info", lambda name, signature=None: {"status": "running"}):
        check("outfit_rebuild: the outfit model being built", withheld(registry.get("outfit_rebuild"), {}),
              (("outfit:Mia:sig1",), []))
    with patch.object(subjects, "pipeline_roster", lambda wanted="": (["Mia"], [])), \
         patch.object(garment_fill, "_profile", lambda name: {}), \
         patch.object(garment_fill, "_pieces", lambda name, profile, scope: {"dress": "clothing"}), \
         patch.object(garment_fill, "_in_flight", lambda name, item: True):
        check("garment_fill: the dress in flight", withheld(registry.get("garment_fill"), {"kind": "clothing"}),
              (("clothing:Mia:dress",), []))

    status = {"Mia": "ready", "Ann": "running", "Bob": "failed"}
    with patch.object(subjects, "characters", lambda: ["Ann", "Bob", "Mia"]), \
         patch("app.models.character.get_character_profile", lambda name: {}), \
         patch.object(base_body, "is_base_pipeline", lambda name, profile=None: True), \
         patch.object(base_body, "base_model_info", lambda name, signature=None: {"status": status[name]}):
        check("pipeline_roster: ready and building", subjects.pipeline_roster(), (["Mia"], ["Ann"]))
        check("…narrowed", subjects.pipeline_roster("Ann"), ([], ["Ann"]))

    def broken(*_a, strict=False, **_k):
        if strict:
            raise RuntimeError("roster unreadable")
        return []
    mt = registry.get("mesh_from_tpose")
    entry = store.create(mt.id, "Meshes", {"backend": "hy"}, "standing")["id"]
    store.replace_steps_scan(entry, [("Mia:sig1:t", "Mia", 0, "")])
    store.mark_running(entry, "Mia:sig1:t")
    store.mark_result(entry, "Mia:sig1:t", status="done", count_attempt=False)
    with patch("app.models.character.list_available_characters", broken):
        try:
            subjects.characters()
            got = "returned"
        except RuntimeError:
            got = "raised"
        check("a failing roster read raises", got, "raised")
        try:
            engine.scan(entry)
            got = "returned"
        except RuntimeError:
            got = "raised"
        check("…the scan raises", got, "raised")
    check("…and the done step stays done", step(entry, "Mia:sig1:t")["status"], "done")
    store.delete(entry)


def main() -> int:
    part1()
    part2()
    part3()
    part4()
    part5()
    print("\nOK" if not FAILS else f"\nFAILED ({len(FAILS)}): {', '.join(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
