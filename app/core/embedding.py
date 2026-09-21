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
EN model is enough for the catalog — but the situational memory block embeds
free world text (messages, facts, promises) in the language the world is
played in, and an English-only model cannot rank that. That combination is
reported by ``english_model_language_mismatch`` (admin validation) and logged
once per process the first time the internal model is used.
"""
from typing import List, Optional

from app.core import config
from app.core.log import get_logger

logger = get_logger("embedding")

DEFAULT_INTERNAL_MODEL = "BAAI/bge-small-en-v1.5"
DEFAULT_CACHE_DIR = "./models/fastembed"

# Curated fastembed models (small, CPU-friendly). Key = fastembed model_name,
# value = UI label. config_schema feeds its dropdown from this.
INTERNAL_MODELS = {
    "BAAI/bge-small-en-v1.5": "bge-small-en (384d, ~130 MB) — Default",
    "BAAI/bge-base-en-v1.5": "bge-base-en (768d, ~440 MB)",
    "sentence-transformers/all-MiniLM-L6-v2": "all-MiniLM-L6 (384d, ~90 MB)",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2":
        "paraphrase-multilingual-MiniLM-L12 (384d, multilingual, ~220 MB)",
    "sentence-transformers/paraphrase-multilingual-mpnet-base-v2":
        "paraphrase-multilingual-mpnet-base (768d, multilingual, ~1 GB) — "
        "recommended for German pose aliases",
}

# Which of the models above measure ENGLISH text only — the one place that
# knowledge lives, so no caller has to string-match "-en-" in a model id.
# The bge-* pair and all-MiniLM-L6 are English-trained; both
# paraphrase-multilingual-* models cover ~50 languages.
ENGLISH_ONLY_INTERNAL_MODELS = {
    "BAAI/bge-small-en-v1.5",
    "BAAI/bge-base-en-v1.5",
    "sentence-transformers/all-MiniLM-L6-v2",
}

# What to point a non-English world at: MiniLM-L12 is multilingual but
# measures short non-English phrases poorly (same note as the schema
# description of ``internal_model``).
RECOMMENDED_MULTILINGUAL_MODEL = (
    "sentence-transformers/paraphrase-multilingual-mpnet-base-v2")

# model_id -> fastembed.TextEmbedding | None (None = loading failed)
_MODEL_CACHE: dict = {}
_FASTEMBED_MISSING_LOGGED = False
_LANGUAGE_MISMATCH_CHECKED = False


def embed(text: str) -> Optional[List[float]]:
    """Embedding of ``text`` via the configured backend.

    Returns ``None`` when no model is available/configured or the call
    fails.
    """
    text = (text or "").strip()
    if not text:
        return None
    cfg = config.get("embedding", {}) or {}
    backend = (cfg.get("backend") or "auto").strip().lower()
    if effective_backend(cfg) == "external":
        vec = _embed_external(text)
        # auto falls back to the internal model when the external one is
        # unreachable; an explicit "external" does not.
        if vec is not None or backend == "external":
            return vec
    return _embed_internal(text)


def _section(full_config: Optional[dict], name: str) -> dict:
    """One config section — from ``full_config`` or, for ``None``, live."""
    if full_config is None:
        return config.get(name, {}) or {}
    if not isinstance(full_config, dict):
        return {}
    return full_config.get(name) or {}


def internal_model_id(embedding_cfg: Optional[dict] = None) -> str:
    """The built-in model id in effect. ``None`` = read the live config."""
    cfg = (config.get("embedding", {}) or {}) if embedding_cfg is None \
        else (embedding_cfg or {})
    return (cfg.get("internal_model") or DEFAULT_INTERNAL_MODEL).strip()


def effective_backend(embedding_cfg: Optional[dict] = None) -> str:
    """Which path ``embed()`` takes right now: ``internal`` or ``external``.

    The ONE place the three-way rule of ``config.embedding.backend`` is
    resolved — ``auto`` means external when the ``pose_embedding`` task is
    routed and reachable, internal otherwise. ``embedding_cfg`` is the
    ``embedding`` section (the admin form validates an unsaved one);
    ``None`` reads the live config.
    """
    cfg = (config.get("embedding", {}) or {}) if embedding_cfg is None \
        else (embedding_cfg or {})
    backend = (cfg.get("backend") or "auto").strip().lower()
    if backend == "internal":
        return "internal"
    if backend == "external":
        return "external"
    return "external" if _external_configured() else "internal"


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
    internal_id = "internal:" + internal_model_id(cfg)
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


# ── language fit of the built-in model ───────────────────────────────────

def english_model_language_mismatch(full_config: Optional[dict] = None):
    """``(model_id, language_code)`` when the built-in ENGLISH-only model has
    to rank text this world is not written in — otherwise ``None``.

    All four conditions must hold: the effective backend is the internal one,
    its model is one of ``ENGLISH_ONLY_INTERNAL_MODELS``, the one consumer
    that embeds free world text is switched on (``memory.situational_enabled``
    — the pose catalog alone is NOT a reason, its aliases are English by
    design), and the account's ``system_language`` is not English.

    ``full_config`` is a whole config dict (the admin form validates an
    unsaved one); ``None`` reads the live config. The function never raises:
    an unreadable account row — no world DB in this process, no row yet —
    means "no finding", so this can only ever produce a warning.
    """
    try:
        emb = _section(full_config, "embedding")
        if effective_backend(emb) != "internal":
            return None
        model = internal_model_id(emb)
        if model not in ENGLISH_ONLY_INTERNAL_MODELS:
            return None
        from app.core.memory_situational import DEFAULT_ENABLED
        raw = _section(full_config, "memory").get(
            "situational_enabled", DEFAULT_ENABLED)
        if raw in (None, ""):
            raw = DEFAULT_ENABLED
        if not bool(raw):
            return None
        from app.models.account import get_language_settings
        lang = (get_language_settings().get("system_language")
                or "").strip().lower()
        if not lang or lang == "en":
            return None
        return model, lang
    except Exception as e:
        logger.debug("language fit check skipped (%s): %s",
                     type(e).__name__, e)
        return None


def language_mismatch_message(model: str, lang: str) -> str:
    """The one wording of that finding — admin validation and server log."""
    from app.core.i18n import language_name
    return (
        f"Internal embedding model '{model}' only measures English text, but "
        f"this world's language is {language_name(lang)} — situational "
        f"memories will pick unrelated memories or miss the fitting ones. "
        f"Either choose '{RECOMMENDED_MULTILINGUAL_MODEL}' as the Internal "
        f"Model under Embedding, or switch the situational memory block off "
        f"under Memory."
    )


def _maybe_log_language_mismatch() -> None:
    """Log that finding ONCE per process, when the internal model is first
    used — most users never open the admin validation panel."""
    global _LANGUAGE_MISMATCH_CHECKED
    if _LANGUAGE_MISMATCH_CHECKED:
        return
    _LANGUAGE_MISMATCH_CHECKED = True
    found = english_model_language_mismatch()
    if found:
        logger.warning("%s", language_mismatch_message(*found))


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
                "fastembed not installed — internal embedding disabled "
                "(pose matching falls back to string comparison). "
                "Install: pip install fastembed"
            )
            _FASTEMBED_MISSING_LOGGED = True
        _MODEL_CACHE[model_id] = None
        return None
    try:
        logger.info("Loading internal embedding model %r (cache: %s) …",
                    model_id, cache_dir)
        model = TextEmbedding(model_name=model_id, cache_dir=cache_dir or None)
        _MODEL_CACHE[model_id] = model
        return model
    except Exception as e:
        logger.warning("Internal embedding model %r could not be loaded: %s",
                       model_id, e)
        _MODEL_CACHE[model_id] = None
        return None


def _embed_internal(text: str) -> Optional[List[float]]:
    _maybe_log_language_mismatch()
    cfg = config.get("embedding", {}) or {}
    model_id = internal_model_id(cfg)
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
        logger.debug("internal embedding failed (%s): %s",
                     type(e).__name__, e)
        return None


# ── external (routed /v1/embeddings provider) ────────────────────────────

def _resolve_external():
    """(inst, provider) for the ``pose_embedding`` task, or (None, None)."""
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
