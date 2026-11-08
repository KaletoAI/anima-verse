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
import hashlib
import json
import threading
import time
from typing import Callable, Dict, Hashable, Iterable, List, Optional

from app.core import config
from app.core.llm_client import merge_extra_params
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
_MODEL_LOCK = threading.Lock()
_FASTEMBED_MISSING_LOGGED = False
_LANGUAGE_MISMATCH_CHECKED = False

#: Texts per ``/embeddings`` request of :func:`embed_many`. The catalog warm-up
#: embeds a few hundred aliases; one request per alias cost ~19 minutes against
#: a slow gateway (3 s per call), one request per chunk costs a handful.
EXTERNAL_BATCH_SIZE = 64


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


#: The genuine :func:`embed` — a check script may patch the module attribute
#: with a double, and that double must then be called, not bypassed.
_REAL_EMBED = embed


def embed_many(texts: Iterable[str]) -> List[Optional[List[float]]]:
    """Embeddings of ``texts`` via the configured backend, in BATCHES.

    Returns one entry per input text, in input order; an entry is ``None``
    for an empty text or a text whose embedding failed. Never raises.

    The external backend sends ``input`` as a list, ``EXTERNAL_BATCH_SIZE``
    texts per request (OpenAI-compatible ``/embeddings``); the internal model
    embeds the whole list in one call. ``auto`` falls back to the internal
    model only when the external route answered NOTHING — a partial answer is
    kept as it is, because mixing two models' vectors in one map would make
    them silently incomparable.
    """
    cleaned = [(t or "").strip() for t in texts]
    out: List[Optional[List[float]]] = [None] * len(cleaned)
    todo = [i for i, t in enumerate(cleaned) if t]
    if not todo:
        return out
    cfg = config.get("embedding", {}) or {}
    backend = (cfg.get("backend") or "auto").strip().lower()
    if effective_backend(cfg) == "external":
        vecs = _embed_external_many([cleaned[i] for i in todo])
        for i, vec in zip(todo, vecs):
            out[i] = vec
        if backend == "external" or any(v is not None for v in vecs):
            return out
    vecs = _embed_internal_many([cleaned[i] for i in todo])
    for i, vec in zip(todo, vecs):
        out[i] = vec
    return out


def embed_map(texts: Iterable[str], embed_fn=None) -> Dict[str, List[float]]:
    """``{text: vector}`` for every text that got a vector — the shape the
    catalog alias maps keep.

    ``embed_fn`` is ``None`` or :func:`embed` for the real backend (batched
    through :func:`embed_many`). Any other function is a test double or a
    custom embedder: when it carries an ``embed_many`` attribute (a callable
    taking a list and answering a list of the same length) that is used,
    otherwise the texts are embedded one by one through ``embed_fn`` itself.
    A double patched over ``embedding.embed`` counts as such a function —
    the comparison is with the original :func:`embed`.
    """
    unique = list(dict.fromkeys(t for t in texts if t))
    if not unique:
        return {}
    if embed_fn is None or embed_fn is _REAL_EMBED:
        vecs = embed_many(unique)
    else:
        many = getattr(embed_fn, "embed_many", None)
        if callable(many):
            try:
                vecs = list(many(unique))
            except Exception as e:
                logger.debug("custom batch embedding failed (%s): %s",
                             type(e).__name__, e)
                vecs = []
            if len(vecs) != len(unique):
                vecs = [None] * len(unique)
        else:
            vecs = [embed_fn(t) for t in unique]
    return {t: v for t, v in zip(unique, vecs) if v}


class SingleFlight:
    """At most ONE computation per key at a time, shared by every caller.

    ``do(key, fn)`` runs ``fn`` unless a computation of the same key is
    already in flight — then it waits for that one and returns its result.
    ``kick(key, fn)`` starts the computation on a daemon thread and returns
    at once (False when one is already running, or when the last attempt
    for the key came back empty less than ``retry_after_s`` ago — a dead
    endpoint must not get a new background thread per poll).

    The cache itself stays with the caller: ``fn`` checks it, fills it and
    returns the value; an empty/falsy result counts as a failure.
    """

    def __init__(self, name: str, retry_after_s: float = 30.0):
        self._name = name
        self._retry_after_s = retry_after_s
        self._lock = threading.Lock()
        self._flights: Dict[Hashable, dict] = {}
        self._failed_at: Dict[Hashable, float] = {}

    def do(self, key: Hashable, fn: Callable[[], object]):
        with self._lock:
            flight = self._flights.get(key)
            owner = flight is None
            if owner:
                flight = self._flights[key] = {
                    "done": threading.Event(), "result": None}
        if not owner:
            flight["done"].wait()
            return flight["result"]
        result = None
        try:
            result = fn()
        except Exception as e:
            logger.warning("%s computation failed for %r: %s",
                           self._name, key, e)
        finally:
            with self._lock:
                if result:
                    self._failed_at.pop(key, None)
                else:
                    self._failed_at[key] = time.monotonic()
                self._flights.pop(key, None)
            flight["result"] = result
            flight["done"].set()
        return result

    def running(self, key: Hashable) -> bool:
        with self._lock:
            return key in self._flights

    def kick(self, key: Hashable, fn: Callable[[], object]) -> bool:
        with self._lock:
            if key in self._flights:
                return False
            failed = self._failed_at.get(key)
            if failed is not None and \
                    time.monotonic() - failed < self._retry_after_s:
                return False
        threading.Thread(target=self.do, args=(key, fn), daemon=True,
                         name=f"{self._name}-warm").start()
        return True


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

    Vectors from two different models or request-body variants are not
    comparable, so every persisted vector is stamped with this string and a
    mismatch means "re-embed". Shape: ``internal:<model>`` or
    ``external:<model>[:<extra_params digest>]``. Returns ``""`` when no
    model can be resolved at all — the caller then skips the feature, exactly
    as it does for a ``None`` vector.
    """
    cfg = config.get("embedding", {}) or {}
    backend = (cfg.get("backend") or "auto").strip().lower()
    internal_id = "internal:" + internal_model_id(cfg)
    if backend == "internal":
        return internal_id
    inst, prov = _resolve_external()
    external_id = f"external:{inst.model}" if (inst and prov) else ""
    if external_id and inst.extra_params:
        canonical = json.dumps(inst.extra_params, sort_keys=True, separators=(",", ":"))
        external_id += ":" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
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


# ── internal (fastembed/ONNX) ──────────────────────────────────────────────

def _get_internal_model(model_id: str, cache_dir: str):
    """Lazily loads and caches one fastembed ``TextEmbedding`` per model_id.

    Under ``_MODEL_LOCK``: the start-up warm-up thread and a first request can
    ask at the same moment, and loading the model twice costs seconds and
    hundreds of MB. Once cached, the lookup does not take the lock.
    """
    global _FASTEMBED_MISSING_LOGGED
    if model_id in _MODEL_CACHE:
        return _MODEL_CACHE[model_id]
    with _MODEL_LOCK:
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
    return _embed_internal_many([text])[0]


def _embed_internal_many(texts: List[str]) -> List[Optional[List[float]]]:
    """The built-in model over the whole list in ONE ``embed`` call
    (fastembed batches internally)."""
    out: List[Optional[List[float]]] = [None] * len(texts)
    if not texts:
        return out
    _maybe_log_language_mismatch()
    cfg = config.get("embedding", {}) or {}
    model_id = internal_model_id(cfg)
    cache_dir = (cfg.get("cache_dir") or DEFAULT_CACHE_DIR).strip()
    model = _get_internal_model(model_id, cache_dir)
    if model is None:
        return out
    try:
        vecs = list(model.embed(list(texts)))
        for i, vec in enumerate(vecs[:len(texts)]):
            if vec is not None and len(vec):
                out[i] = [float(x) for x in vec]
    except Exception as e:
        logger.debug("internal embedding failed (%s): %s",
                     type(e).__name__, e)
    return out


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
        logger.debug("resolve_external failed (%s): %s",
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
            json=merge_extra_params(
                {"model": inst.model, "input": prefix + text}, inst.extra_params),
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
        logger.debug("external embedding failed (%s): %s",
                     type(e).__name__, e)
        return None


def _embed_external_many(texts: List[str]) -> List[Optional[List[float]]]:
    """The routed ``/embeddings`` endpoint, ``EXTERNAL_BATCH_SIZE`` texts per
    request with ``input`` as a list. Results are mapped back by their
    ``index`` (the order of ``data`` is not guaranteed); an answer without
    indexes is taken in order. A failed chunk leaves its entries ``None``
    and the next chunk is still tried. Never raises."""
    out: List[Optional[List[float]]] = [None] * len(texts)
    if not texts:
        return out
    inst, prov = _resolve_external()
    if inst is None or prov is None:
        return out
    try:
        api_base = prov.api_base.rstrip("/")
        api_key = (prov.api_key or "not-needed").strip()
        from app.models.world import get_world_setting
        prefix = get_world_setting("pose.embedding_input_prefix", "") or ""
        timeout = float(prov.timeout or 30)
        import httpx
    except Exception as e:
        logger.debug("external batch embedding not possible (%s): %s",
                     type(e).__name__, e)
        return out
    size = max(1, int(EXTERNAL_BATCH_SIZE))
    for start in range(0, len(texts), size):
        chunk = texts[start:start + size]
        try:
            resp = httpx.post(
                f"{api_base}/embeddings",
                json=merge_extra_params(
                    {"model": inst.model, "input": [prefix + t for t in chunk]},
                    inst.extra_params),
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=timeout,
            )
            resp.raise_for_status()
            data = resp.json().get("data") or []
            for pos, item in enumerate(data):
                if not isinstance(item, dict):
                    continue
                idx = item.get("index", pos)
                vec = item.get("embedding")
                if not isinstance(idx, int) or not 0 <= idx < len(chunk) or not vec:
                    continue
                out[start + idx] = [float(x) for x in vec]
        except Exception as e:
            logger.debug("external batch embedding failed for texts %d-%d "
                         "(%s): %s", start, start + len(chunk) - 1,
                         type(e).__name__, e)
    return out
