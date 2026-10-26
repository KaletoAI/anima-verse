#!/usr/bin/env python3
"""Regression: embedding request variants must not reuse persisted vectors.

Usage: ./.venv/bin/python scripts/smoke_embedding_extra_identity.py

Only an in-memory SQLite table is used; no provider or world DB is accessed.
"""
import sqlite3
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import paths  # noqa: E402

with tempfile.TemporaryDirectory(prefix="embedding-identity-") as storage:
    paths.init(storage)

    from app.core import db, embedding, memory_situational  # noqa: E402

    settings = {"backend": "external"}
    instance = SimpleNamespace(model="demo-embed", extra_params={})
    provider = SimpleNamespace(api_base="https://example.invalid/v1")

    def live_config(key, default=None):
        return settings if key == "embedding" else default

    with patch.object(embedding.config, "get", side_effect=live_config), \
         patch.object(embedding, "_resolve_external", return_value=(instance, provider)):
        assert embedding.current_model_id() == "external:demo-embed"

        instance.extra_params = {"dimensions": 512, "options": {"normalize": True, "scale": 2},
                                 "metadata": {"secret": "private-canary-value"}}
        original = embedding.current_model_id()
        assert original.startswith("external:demo-embed:")
        assert "private-canary-value" not in original
        assert embedding.current_model_id() == original

        # JSON object key order does not change the request body or its identity.
        instance.extra_params = {"metadata": {"secret": "private-canary-value"},
                                 "options": {"scale": 2, "normalize": True}, "dimensions": 512}
        assert embedding.current_model_id() == original

        instance.extra_params = {"dimensions": 1024, "options": {"normalize": True, "scale": 2},
                                 "metadata": {"secret": "private-canary-value"}}
        bigger = embedding.current_model_id()
        assert bigger != original

        # A non-dimension parameter also changes the embedding variant.
        instance.extra_params = {"dimensions": 512, "options": {"normalize": False, "scale": 2},
                                 "metadata": {"secret": "private-canary-value"}}
        assert embedding.current_model_id() not in (original, bigger)

        # The real persisted-vector reader ignores the old row under the new ID.
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("CREATE TABLE memory_embeddings (memory_id INTEGER, model_id TEXT, vector BLOB)")
            conn.execute("INSERT INTO memory_embeddings VALUES (?, ?, ?)",
                         (17, original, memory_situational.pack_vector([1.0, 0.0])))
            with patch.object(db, "get_connection", return_value=conn):
                cache = memory_situational.DbVectorCache()
                assert cache.get_many([17], original) == {17: [1.0, 0.0]}
                assert cache.get_many([17], bigger) == {}
        finally:
            conn.close()

        settings["backend"] = "internal"
        assert embedding.current_model_id() == "internal:BAAI/bge-small-en-v1.5"

print("Embedding extra_params identity and stale-vector rejection OK")
