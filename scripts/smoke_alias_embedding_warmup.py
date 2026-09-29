#!/usr/bin/env python3
"""Smoke run for the alias-embedding warm-up (plan-befundrunde-2026-09-29 B9b,
incl. the binding review notes).

Usage:  ./.venv/bin/python scripts/smoke_alias_embedding_warmup.py

Offline: throwaway storage (``paths.init`` first), a stub ``embedding.embed``
and a fake ``fastembed`` module in ``sys.modules`` — no model is downloaded,
no endpoint is called.

THE RULE
---------------------------------------------------------------------------
A cold alias-embedding cache cost one embedding call per catalog alias inside
the first chat turn that matched a pose (5 s on the event loop). So:
* ``pose_catalog.prewarm_alias_embeddings()`` embeds every alias of the
  "expression" and the "pose" catalog once; the server lifespan starts it in
  a background thread AFTER the provider manager and BEFORE the AgentLoop —
  and ``reload_catalogs()`` does NOT call it;
* ``_embed_cache`` is keyed by ``(axis, model id)``: vectors of two models
  are not comparable;
* an EMPTY result (no model, endpoint down) is not cached;
* ``embedding._get_internal_model`` loads a model once even when two threads
  ask at the same time (lock).

Hand-derived expectations
---------------------------------------------------------------------------
[1] with ``embedding.embed`` → a constant vector and ``current_model_id`` →
    "internal:A": after the warm-up the cache holds exactly the keys
    ("expression", "internal:A") and ("pose", "internal:A"), each with one
    vector per alias of ``_alias_index(axis)``; the stub was called once per
    alias of both catalogs.
[2] a second warm-up embeds nothing (all cached).
[3] ``current_model_id`` → "internal:B": ``_alias_embeddings("pose", embed)``
    embeds again (len(pose aliases) calls) and adds ("pose", "internal:B");
    the "A" entry stays.
[4] after ``reload_catalogs()``, ``embed`` → None: the warm-up caches NOTHING
    (the cache stays empty); once ``embed`` answers again the next call fills it.
[5] a test double (not ``embedding.embed``) is its own model: its entry is
    keyed ``("pose", "fn:<id>")`` and does not collide with "internal:A".
[6] four threads call ``_get_internal_model("fake-model", "")`` at once with
    a fastembed whose constructor sleeps 0.2 s → exactly ONE construction,
    all four get the same instance.
[7] static, ``app/server.py``: ``initialize_provider_manager()`` <
    ``prewarm_alias_embeddings`` < ``_agent_loop.start()`` in source order,
    and the warm-up is the ``target=`` of a ``threading.Thread``;
    ``pose_catalog.reload_catalogs`` does not call ``prewarm_alias_embeddings``.
"""
import ast
import os
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_TMP = Path(tempfile.mkdtemp(prefix="smoke_alias_warmup_"))
os.environ["ANIMATION_CLIPS_DIR"] = str(_TMP / "clips")
from app.core import paths  # noqa: E402

paths.init(_TMP)

from app.core import embedding  # noqa: E402
from app.core import pose_catalog as pc  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
FAILURES = []
CHECKED = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global CHECKED
    CHECKED += 1
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


CALLS = [0]
ANSWER = {"vec": [1.0, 0.0, 0.0]}


def stub_embed(text):
    CALLS[0] += 1
    return ANSWER["vec"]


MODEL = {"id": "internal:A"}
embedding.embed = stub_embed
embedding.current_model_id = lambda: MODEL["id"]

n_expr = len(pc._alias_index("expression"))
n_pose = len(pc._alias_index("pose"))
print(f"  (catalog aliases: expression={n_expr}, pose={n_pose})")

print("\n[1] warm-up fills both axes for the current model")
pc.reload_catalogs()
pc.prewarm_alias_embeddings()
keys = sorted(pc._embed_cache)
check("cache keys", keys == [("expression", "internal:A"), ("pose", "internal:A")],
      str(keys))
check("one vector per alias",
      len(pc._embed_cache.get(("expression", "internal:A"), {})) == n_expr
      and len(pc._embed_cache.get(("pose", "internal:A"), {})) == n_pose)
check("embed called once per alias", CALLS[0] == n_expr + n_pose,
      f"{CALLS[0]} vs {n_expr + n_pose}")

print("\n[2] second warm-up embeds nothing")
CALLS[0] = 0
pc.prewarm_alias_embeddings()
check("no embed calls", CALLS[0] == 0, str(CALLS[0]))

print("\n[3] another model is another cache entry")
MODEL["id"] = "internal:B"
pc._alias_embeddings("pose", embedding.embed)
check("embedded again for B", CALLS[0] == n_pose, str(CALLS[0]))
check("B added, A kept",
      ("pose", "internal:B") in pc._embed_cache and ("pose", "internal:A") in pc._embed_cache,
      str(sorted(pc._embed_cache)))
MODEL["id"] = "internal:A"

print("\n[4] empty results are not cached")
pc.reload_catalogs()
ANSWER["vec"] = None
pc.prewarm_alias_embeddings()
check("cache stays empty", pc._embed_cache == {}, str(sorted(pc._embed_cache)))
ANSWER["vec"] = [0.0, 1.0, 0.0]
got = pc._alias_embeddings("pose", embedding.embed)
check("the next call with a working model fills it",
      len(got) == n_pose and ("pose", "internal:A") in pc._embed_cache, str(len(got)))

print("\n[5] a test double is its own model")


def other_embed(text):
    return [0.5, 0.5, 0.0]


pc._alias_embeddings("pose", other_embed)
check("keyed fn:<id>", ("pose", f"fn:{id(other_embed)}") in pc._embed_cache,
      str(sorted(pc._embed_cache)))
check("does not replace the model entry",
      next(iter(pc._embed_cache[("pose", "internal:A")].values())) == [0.0, 1.0, 0.0])

print("\n[6] the internal model loads once under concurrency")
CONSTRUCTED = [0]


class FakeTextEmbedding:
    def __init__(self, model_name, cache_dir=None):
        CONSTRUCTED[0] += 1
        time.sleep(0.2)
        self.model_name = model_name


sys.modules["fastembed"] = types.SimpleNamespace(TextEmbedding=FakeTextEmbedding)
embedding._MODEL_CACHE.pop("fake-model", None)
results = []
threads = [threading.Thread(target=lambda: results.append(
    embedding._get_internal_model("fake-model", ""))) for _ in range(4)]
for t in threads:
    t.start()
for t in threads:
    t.join()
check("exactly one construction", CONSTRUCTED[0] == 1, str(CONSTRUCTED[0]))
check("all four got the same instance",
      len(results) == 4 and all(r is results[0] for r in results) and results[0] is not None)
sys.modules.pop("fastembed", None)

print("\n[7] lifespan order + no warm-up in reload_catalogs")
src = (REPO / "app/server.py").read_text(encoding="utf-8")
i_pm = src.find("initialize_provider_manager()")
i_warm = src.find("prewarm_alias_embeddings")
i_loop = src.find("_agent_loop.start()")
check("provider manager < warm-up < AgentLoop start",
      0 <= i_pm < i_warm < i_loop, f"{i_pm} {i_warm} {i_loop}")
check("started as a Thread target",
      "target=prewarm_alias_embeddings" in src)
tree = ast.parse((REPO / "app/core/pose_catalog.py").read_text(encoding="utf-8"))
reload_fn = next(n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "reload_catalogs")
called = {getattr(n.func, "id", getattr(n.func, "attr", "")) for n in ast.walk(reload_fn)
          if isinstance(n, ast.Call)}
check("reload_catalogs does not warm", "prewarm_alias_embeddings" not in called, str(called))

print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAILED: " + "; ".join(FAILURES))
sys.exit(1 if FAILURES else 0)
