"""Embedding generation — internal (fastembed/ONNX) or external (routed model).

Two consumers: the pose/expression catalog resolver
(``pose_catalog.resolve_to_catalog``) and the situational memory block
(``memory_situational``). Returns a vector or ``None`` — on ``None`` the
catalog falls back to plain alias equality and the memory block is simply
omitted; no crash, no queue block, ever.

Backend choice via ``config.embedding.backend``:
  - ``auto`` (default): the external model when the ``pose_embedding`` task is
    routed, otherwise the built-in ONNX model. That makes catalog matching work
    out of the box without an external embedding endpoint.
  - ``internal``: always the built-in fastembed/ONNX model (CPU).
  - ``external``: only the routed ``/v1/embeddings`` provider.

The built-in model runs via ``fastembed`` (reuses the ``onnxruntime`` that is
already present, no torch). It is downloaded into ``cache_dir`` on first use
(~130 MB for bge-small). Catalog aliases are short English phrases, so a small
EN model is enough.
"""
from typing import List, Optional

from app.core import config
from app.core.log import get_logger

logger = get_logger("embedding")

DEFAULT_INTERNAL_MODEL = "BAAI/bge-small-en-v1.5"
DEFAULT_CACHE_DIR = "./models/fastembed"

# Kuratierte fastembed-Modelle (klein, CPU-tauglich). Schluessel = fastembed
# model_name, Wert = UI-Label. Wird vom config_schema fuer das Dropdown genutzt.
INTERNAL_MODELS = {
    "BAAI/bge-small-en-v1.5": "bge-small-en (384d, ~130 MB) — Default",
    "BAAI/bge-base-en-v1.5": "bge-base-en (768d, ~440 MB)",
    "sentence-transformers/all-MiniLM-L6-v2": "all-MiniLM-L6 (384d, ~90 MB)",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2":
        "paraphrase-multilingual-MiniLM-L12 (384d, multilingual)",
}

# model_id -> fastembed.TextEmbedding | None (None = Laden fehlgeschlagen)
_MODEL_CACHE: dict = {}
_FASTEMBED_MISSING_LOGGED = False


def embed(text: str) -> Optional[List[float]]:
    """Erzeugt ein Embedding fuer ``text`` gemaess Config-Backend.

    Returns ``None`` wenn kein Modell verfuegbar/konfiguriert ist oder der
    Aufruf fehlschlaegt.
    """
    text = (text or "").strip()
    if not text:
        return None
    cfg = config.get("embedding", {}) or {}
    backend = (cfg.get("backend") or "auto").strip().lower()
    if backend == "internal":
        return _embed_internal(text)
    if backend == "external":
        return _embed_external(text)
    # auto: prefer the external model when routed, otherwise the internal one
    if _external_configured():
        vec = _embed_external(text)
        if vec is not None:
            return vec
    return _embed_internal(text)


def current_model_id() -> str:
    """Identifier of the model ``embed()`` would use right now.

    Vectors from two different models are not comparable, so every persisted
    vector is stamped with this string and a mismatch means "re-embed". Shape:
    ``internal:<model>`` / ``external:<model>``. Returns ``""`` when no model
    can be resolved at all — the caller then skips the feature, exactly as it
    does for a ``None`` vector.
    """
    cfg = config.get("embedding", {}) or {}
    backend = (cfg.get("backend") or "auto").strip().lower()
    internal_id = "internal:" + (
        (cfg.get("internal_model") or DEFAULT_INTERNAL_MODEL).strip())
    if backend == "internal":
        return internal_id
    inst, prov = _resolve_external()
    external_id = f"external:{inst.model}" if (inst and prov) else ""
    if backend == "external":
        return external_id
    return external_id or internal_id


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Cosine similarity of two vectors. Returns 0.0 on any inconsistency.

    Lives next to ``embed`` because every consumer of a vector needs it — the
    catalog resolver and the situational memory selection both compare what
    this module produced.
    """
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# ── intern (fastembed/ONNX) ──────────────────────────────────────────────

def _get_internal_model(model_id: str, cache_dir: str):
    """Lazy-laedt + cached eine fastembed-TextEmbedding-Instanz pro model_id."""
    global _FASTEMBED_MISSING_LOGGED
    if model_id in _MODEL_CACHE:
        return _MODEL_CACHE[model_id]
    try:
        from fastembed import TextEmbedding
    except ImportError:
        if not _FASTEMBED_MISSING_LOGGED:
            logger.warning(
                "fastembed nicht installiert — internes Embedding deaktiviert "
                "(Pose-Matching faellt auf String-Vergleich zurueck). "
                "Installation: pip install fastembed"
            )
            _FASTEMBED_MISSING_LOGGED = True
        _MODEL_CACHE[model_id] = None
        return None
    try:
        logger.info("Lade internes Embedding-Modell %r (cache: %s) …",
                    model_id, cache_dir)
        model = TextEmbedding(model_name=model_id, cache_dir=cache_dir or None)
        _MODEL_CACHE[model_id] = model
        return model
    except Exception as e:
        logger.warning("Internes Embedding-Modell %r konnte nicht geladen "
                       "werden: %s", model_id, e)
        _MODEL_CACHE[model_id] = None
        return None


def _embed_internal(text: str) -> Optional[List[float]]:
    cfg = config.get("embedding", {}) or {}
    model_id = (cfg.get("internal_model") or DEFAULT_INTERNAL_MODEL).strip()
    cache_dir = (cfg.get("cache_dir") or DEFAULT_CACHE_DIR).strip()
    model = _get_internal_model(model_id, cache_dir)
    if model is None:
        return None
    try:
        vecs = list(model.embed([text]))
        if not vecs:
            return None
        return [float(x) for x in vecs[0]]
    except Exception as e:
        logger.debug("internes Embedding fehlgeschlagen (%s): %s",
                     type(e).__name__, e)
        return None


# ── extern (gerouteter /v1/embeddings-Provider) ──────────────────────────

def _resolve_external():
    """Liefert (inst, provider) fuer den Task ``pose_embedding`` oder (None, None)."""
    try:
        from app.core.llm_router import resolve_llm
        inst = resolve_llm("pose_embedding")
        if inst is None:
            return None, None
        prov = inst._provider
        if prov is None:
            from app.core.provider_manager import get_provider_manager
            prov = get_provider_manager().get_provider(inst.provider_name)
        if not prov or not (prov.api_base or "").strip():
            return None, None
        return inst, prov
    except Exception as e:
        logger.debug("resolve_external fehlgeschlagen (%s): %s",
                     type(e).__name__, e)
        return None, None


def _external_configured() -> bool:
    inst, prov = _resolve_external()
    return inst is not None and prov is not None


def _embed_external(text: str) -> Optional[List[float]]:
    inst, prov = _resolve_external()
    if inst is None or prov is None:
        return None
    try:
        api_base = prov.api_base.rstrip("/")
        api_key = (prov.api_key or "not-needed").strip()
        from app.models.world import get_world_setting
        prefix = get_world_setting("pose.embedding_input_prefix", "") or ""
        import httpx
        resp = httpx.post(
            f"{api_base}/embeddings",
            json={"model": inst.model, "input": prefix + text},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=float(prov.timeout or 30),
        )
        resp.raise_for_status()
        payload = resp.json()
        vec = (payload.get("data") or [{}])[0].get("embedding")
        if not vec:
            return None
        return [float(x) for x in vec]
    except Exception as e:
        logger.debug("externes Embedding fehlgeschlagen (%s): %s",
                     type(e).__name__, e)
        return None
