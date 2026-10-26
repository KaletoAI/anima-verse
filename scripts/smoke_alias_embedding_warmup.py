#!/usr/bin/env python3
"""Warm alias vectors once; resolution must not reuse a different model's vectors.

Usage: ./.venv/bin/python scripts/smoke_alias_embedding_warmup.py

Temporary storage, deterministic embeddings, no downloads or providers. Unlike
retired global-expression-cache assertions, these checks exercise set-local
matching results and avoid source-text or private cache-layout expectations.
"""
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import types
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
with tempfile.TemporaryDirectory(prefix="alias-warmup-") as temporary:
    os.environ["ANIMATION_CLIPS_DIR"] = str(Path(temporary) / "clips")
    os.environ["ANIMATION_RIG_FILE"] = str(Path(temporary) / "rig.fbx")
    from app.core import paths
    paths.init(temporary)
    paths.init_instance(Path(temporary) / "instance")
    from app.core import db, embedding, pose_catalog
    db.init_schema()

    model = {"id": "demo:A"}
    calls = []
    query = "demo previously unseen expression"
    def embed(text):
        calls.append(text)
        target = "positive" if model["id"] == "demo:A" else "sad"
        return [1.0, 0.0] if text in (query, target) else [-1.0, 0.0]

    with patch.object(embedding, "embed", embed), patch.object(
        embedding, "current_model_id", lambda: model["id"]
    ):
        pose_catalog.reload_catalogs()
        pose_catalog.prewarm_alias_embeddings()
        calls.clear()
        pose_catalog.prewarm_alias_embeddings()
        assert not calls, "Repeated warm-up repeated model inference"
        key, method = pose_catalog.resolve_to_catalog(query, "expression", set_id="humanoid")
        assert (key, method) == ("positive", "embedding")
        assert calls == [query], "Warm matching recomputed alias vectors"
        model["id"] = "demo:B"
        key, method = pose_catalog.resolve_to_catalog(query, "expression", set_id="humanoid")
        assert (key, method) == ("sad", "embedding"), "A new model reused incompatible vectors"
        key, _ = pose_catalog.resolve_to_catalog(query, "expression", set_id="animal")
        from app.core.expression_sets import catalog_snapshot
        assert key in catalog_snapshot().sets["animal"].members, "Matching escaped its anatomy set"

    # Concurrent first callers must share one expensive model session.
    constructed = []
    class Model:
        def __init__(self, model_name, cache_dir=None):
            constructed.append(self)
            time.sleep(0.05)
    results = []
    with patch.dict(sys.modules, {"fastembed": types.SimpleNamespace(TextEmbedding=Model)}):
        threads = [threading.Thread(target=lambda: results.append(
            embedding._get_internal_model("demo-concurrent", "")
        )) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    assert len(constructed) == 1 and len(results) == 4
    assert all(result is constructed[0] for result in results)
print("PASS warmed set-local matching, model transitions and concurrent model loading")
