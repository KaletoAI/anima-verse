#!/usr/bin/env python3
"""Alias embeddings are batched, single-flight and never block a poll.

Usage: ./.venv/bin/python scripts/smoke_alias_embedding_batch.py

Background (thread dump 2026-11-08): after a restart ``GET /play/scene`` and
``GET /play/self`` hung ~18 minutes — every expression alias (~381) was embedded
ONE request at a time against a gateway answering in ~3 s, and the warm-up
thread plus every waiting request computed the same maps in parallel.

Temporary storage, no world DB of the running server, no real provider:
``httpx.post`` and the external route are replaced by in-process fakes, the
other embedders are counting doubles. Expectations, derived by hand:

A  embed_many, external backend, chunk = EXTERNAL_BATCH_SIZE = 64.
   150 texts "t000".."t149" -> ceil(150/64) = 3 requests carrying 64, 64 and
   150 - 128 = 22 inputs, every input prefixed with the world prefix "p: ",
   the entry's extra_params (dimensions = 8) merged into each body. The fake
   answers ``data`` in REVERSED order with the ``index`` field, vector [i]
   for "t<i>" -> out[i] == [float(i)] for all 150 despite the order.
   An empty text in the input is not sent and comes back None.
A2 the 2nd of 3 requests raises -> entries 64..127 are None, 0..63 and
   128..149 still filled, nothing raises.
B  embed_map with a custom function WITHOUT ``embed_many`` -> one call per
   unique text (5 texts, one duplicate -> 4 calls); WITH ``embed_many`` -> 1.
C  Pose alias map through the REAL embed path (external, fake endpoint),
   6 threads asking at once on a cold cache: N = number of pose aliases
   (read from the catalog) -> exactly ceil(N/64) requests in total, all six
   threads hold the SAME map object; a later lookup makes 0 requests.
D  Expression set map, 8 threads + the warm-up asking at once with a slow
   batch double -> exactly 1 ``embed_many`` call, one shared map object.
E  wait=False on a cold map (the batch double is held on a gate):
   an unknown text returns (set default, "cold") within 0.5 s, an exact alias
   still returns (key, "exact"), no candidate row is recorded, the map warms
   in the background once the gate opens, and the next resolve with
   wait=True answers ("positive", "embedding").
F  resolve_expression_key(wait=False) with a cold map: answers the set
   default at once and memoises NOTHING; once the background resolution is
   done the memo holds the real key and the next poll answers "positive".
G  SingleFlight failure cooldown: an empty result blocks a new ``kick`` for
   ``retry_after_s``; a blocking ``do`` still runs.
H  the warm-up logs its result at INFO with a duration ("in <x> s").
I  the polled routes ask for the non-blocking path: play._expr_version calls
   expression_snapshot(..., wait=False); the GET expression-status and
   outfit-expression routes call _expression_request(..., wait=False).
"""
import logging
import math
import os
import sys
import tempfile
import threading
import time
import types
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FAIL: list = []


def check(label, got, want):
    ok = got == want
    print(f"  [{'OK  ' if ok else 'FAIL'}] {label}" + ("" if ok else f" — got {got!r}, want {want!r}"))
    if not ok:
        FAIL.append(label)


def wait_until(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.01)
    return pred()


with tempfile.TemporaryDirectory(prefix="alias-batch-") as temporary:
    os.environ["ANIMATION_CLIPS_DIR"] = str(Path(temporary) / "clips")
    os.environ["ANIMATION_RIG_FILE"] = str(Path(temporary) / "rig.fbx")
    os.environ["STORAGE_DIR"] = temporary
    os.environ["INSTANCE_DIR"] = str(Path(temporary) / "instance")
    from app.core import paths
    paths.init(temporary)
    paths.init_instance(Path(temporary) / "instance")
    from app.core import db, embedding, pose_catalog
    db.init_schema()
    from app.core import expression_sets, expression_pose_maps
    import app.models.world as world_model

    # ── fake external route ──────────────────────────────────────────────
    prov = types.SimpleNamespace(api_base="http://fake-gateway/v1", api_key="k", timeout=5)
    inst = types.SimpleNamespace(model="emb-m", extra_params={"dimensions": 8},
                                 provider_name="fake", _provider=prov)
    cfg_stub = types.SimpleNamespace(
        get=lambda key, default=None: {"backend": "external"} if key == "embedding" else default)
    posts: list = []
    posts_lock = threading.Lock()
    behaviour = {"fail_call": None, "delay": 0.0}

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def vector_for(text):
        body = text[len("p: "):] if text.startswith("p: ") else text
        if body.startswith("t") and body[1:].isdigit():
            return [float(int(body[1:]))]
        return [1.0, float(len(body))]

    def fake_post(url, json=None, headers=None, timeout=None):
        with posts_lock:
            posts.append(json)
            number = len(posts)
        if behaviour["delay"]:
            time.sleep(behaviour["delay"])
        if behaviour["fail_call"] == number:
            raise RuntimeError("gateway hiccup")
        inputs = json["input"]
        data = [{"index": i, "embedding": vector_for(t)} for i, t in enumerate(inputs)]
        return _Resp({"data": list(reversed(data))})

    import httpx
    external = [
        patch.object(embedding, "_resolve_external", lambda: (inst, prov)),
        patch.object(embedding, "config", cfg_stub),
        patch.object(world_model, "get_world_setting", lambda key, default="": "p: "),
        patch.object(httpx, "post", fake_post),
    ]
    for p in external:
        p.start()

    print("A — embed_many batches the external route")
    texts = [f"t{i:03d}" for i in range(150)]
    out = embedding.embed_many(texts)
    check("A1 requests = ceil(150/64)", len(posts), 3)
    check("A2 chunk sizes", [len(p["input"]) for p in posts], [64, 64, 22])
    check("A3 prefix on every input", all(t.startswith("p: ") for p in posts for t in p["input"]), True)
    check("A4 extra_params merged", [p.get("dimensions") for p in posts], [8, 8, 8])
    check("A5 mapped by index despite reversed order", out, [[float(i)] for i in range(150)])
    posts.clear()
    check("A6 empty text not sent, comes back None",
          (embedding.embed_many(["", "t007"]), [p["input"] for p in posts]),
          ([None, [7.0]], [["p: t007"]]))
    posts.clear()
    behaviour["fail_call"] = 2
    out = embedding.embed_many(texts)
    behaviour["fail_call"] = None
    check("A7 failed chunk -> None, others filled",
          ([o is None for o in out[64:128]] == [True] * 64,
           out[:64] == [[float(i)] for i in range(64)],
           out[128:] == [[float(i)] for i in range(128, 150)]),
          (True, True, True))
    posts.clear()

    print("B — embed_map: per item without batch support, one call with it")
    single_calls = []
    def single(text):
        single_calls.append(text)
        return [1.0]
    embedding.embed_map(["a", "b", "a", "c", "d"], single)
    check("B1 per-item calls (4 unique)", len(single_calls), 4)
    batch_calls = []
    def batched(text):
        raise AssertionError("per-item path used despite embed_many")
    batched.embed_many = lambda items: batch_calls.append(list(items)) or [[1.0] for _ in items]
    got = embedding.embed_map(["a", "b", "a", "c", "d"], batched)
    check("B2 one batch call", (len(batch_calls), sorted(got)), (1, ["a", "b", "c", "d"]))

    print("C — pose alias map: real embed path, 6 concurrent cold callers")
    pose_catalog.reload_catalogs()
    n_pose = len(pose_catalog._alias_index("pose"))
    behaviour["delay"] = 0.1
    maps: list = []
    threads = [threading.Thread(target=lambda: maps.append(
        pose_catalog._alias_embeddings("pose", embedding.embed))) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    behaviour["delay"] = 0.0
    check("C1 requests = ceil(N/64)", len(posts), math.ceil(n_pose / 64))
    check("C2 every caller holds the same map", len({id(m) for m in maps}), 1)
    check("C3 map covers every alias", len(maps[0]) if maps else 0, n_pose)
    posts.clear()
    pose_catalog._alias_embeddings("pose", embedding.embed)
    check("C4 warm lookup makes no request", len(posts), 0)

    for p in external:
        p.stop()

    # ── doubles for the expression side ──────────────────────────────────
    from app.core.expression_sets import catalog_snapshot
    cat = catalog_snapshot()
    spec = cat.sets["humanoid"]
    target = "positive"
    query = "demo glowing with quiet delight"

    def make_double(gate=None, delay=0.0):
        calls = []
        def fn(text):
            return [1.0, 0.0] if text in (query, target) else [-1.0, 0.0]
        def many(items):
            calls.append(len(items))
            if gate is not None:
                gate.wait(10)
            if delay:
                time.sleep(delay)
            return [fn(t) for t in items]
        fn.embed_many = many
        fn.calls = calls
        return fn

    print("D — expression set map: 8 requests + warm-up share one computation")
    slow = make_double(delay=0.3)
    results: list = []
    workers = [threading.Thread(target=lambda: results.append(
        expression_sets.alias_embeddings(cat, spec, slow))) for _ in range(9)]
    for w in workers:
        w.start()
    for w in workers:
        w.join(30)
    check("D1 one batch computation", slow.calls, [len({a for k in spec.members
                                                         for a in (k, *cat.entries[k]["synonyms"])})])
    check("D2 one shared map object", len({id(r) for r in results}), 1)

    print("E — wait=False on a cold map")
    gate = threading.Event()
    held = make_double(gate=gate)
    started = time.monotonic()
    got = pose_catalog.resolve_to_catalog(query, "expression", held, set_id="humanoid", wait=False)
    elapsed = time.monotonic() - started
    check("E1 cold -> set default", got, (spec.default, "cold"))
    check("E2 answered within 0.5 s", elapsed < 0.5, True)
    exact_alias = spec.members[0]
    check("E3 exact alias still answers",
          pose_catalog.resolve_to_catalog(exact_alias, "expression", held, set_id="humanoid", wait=False),
          (exact_alias, "exact"))
    check("E4 no candidate for the cold result",
          [c for c in pose_catalog.list_candidates("expression", set_id="humanoid")
           if c["raw_text"] == query], [])
    gate.set()
    check("E5 background warm finished",
          wait_until(lambda: expression_sets.alias_embeddings(cat, spec, held, wait=False) is not None),
          True)
    check("E6 one background computation", len(held.calls), 1)
    check("E7 warm -> real match",
          pose_catalog.resolve_to_catalog(query, "expression", held, set_id="humanoid"),
          (target, "embedding"))

    print("F — resolve_expression_key(wait=False) never memoises a cold result")
    gate_f = threading.Event()
    real_double = make_double(gate=gate_f)
    with patch.object(embedding, "embed", real_double), \
            patch.object(embedding, "current_model_id", lambda: "smoke:F"):
        expression_pose_maps._EXPRESSION_KEY_MEMO.clear()
        memo_key = (catalog_snapshot().revision, "humanoid", query)
        started = time.monotonic()
        first = expression_pose_maps.resolve_expression_key(query, set_id="humanoid", wait=False)
        check("F1 cold poll -> default at once",
              (first, time.monotonic() - started < 0.5), (spec.default, True))
        check("F2 nothing memoised", memo_key in expression_pose_maps._EXPRESSION_KEY_MEMO, False)
        gate_f.set()
        check("F3 background resolution fills the memo",
              wait_until(lambda: memo_key in expression_pose_maps._EXPRESSION_KEY_MEMO), True)
        check("F4 next poll answers the real key",
              expression_pose_maps.resolve_expression_key(query, set_id="humanoid", wait=False), target)

    print("G — failure cooldown of a background kick")
    flight = embedding.SingleFlight("smoke", retry_after_s=60.0)
    runs = []
    def empty():
        runs.append(1)
        return {}
    check("G1 first kick starts", flight.kick("k", empty), True)
    wait_until(lambda: not flight.running("k"))
    check("G2 kick inside the cooldown is skipped", flight.kick("k", empty), False)
    flight.do("k", empty)
    check("G3 blocking do still runs", len(runs), 2)

    print("H — warm-up logs at INFO with a duration")
    records = []
    class Grab(logging.Handler):
        def emit(self, record):
            records.append(record)
    handler = Grab(level=logging.INFO)
    logging.getLogger("pose_catalog").addHandler(handler)
    with patch.object(embedding, "embed", make_double()), \
            patch.object(embedding, "current_model_id", lambda: "smoke:H"):
        pose_catalog.prewarm_alias_embeddings()
    logging.getLogger("pose_catalog").removeHandler(handler)
    lines = [r.getMessage() for r in records if r.levelno == logging.INFO]
    check("H1 pose line with duration",
          any(m.startswith("Alias embeddings warmed: pose (") and m.endswith(" s") for m in lines), True)
    check("H2 finished line", any(m.startswith("Alias embedding warm-up finished in ") for m in lines), True)

    print("I — polled play routes take the non-blocking path")
    from app.core import expression_regen
    import app.models.character as character_model
    asked = {}
    def capture(name, mood="", **kw):
        asked.update(kw)
        raise ValueError("stop here")
    with patch.object(expression_regen, "expression_snapshot", capture), \
            patch.object(character_model, "get_character_current_feeling", lambda n: "x"):
        from app.routes import play
        play._expr_version("demo")
    check("I1 _expr_version asks wait=False", asked.get("wait"), False)

    from fastapi import HTTPException
    from app.routes import characters as char_routes
    route_asked = []
    def capture_request(*args, **kw):
        route_asked.append(kw.get("wait", True))
        raise HTTPException(418, "stop here")
    with patch.object(char_routes, "_expression_owner", lambda *a: {}), \
            patch.object(char_routes, "_expression_request", capture_request):
        for route in (char_routes.expression_status_route, char_routes.get_outfit_expression):
            try:
                route("demo", types.SimpleNamespace(query_params={}))
            except HTTPException:
                pass
    check("I2 expression-status + outfit-expression GETs ask wait=False",
          route_asked, [False, False])

print()
if FAIL:
    print(f"{len(FAIL)} CHECK(S) FAILED: {', '.join(FAIL)}")
    sys.exit(1)
print("OK smoke_alias_embedding_batch")
