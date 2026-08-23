"""The few memories that fit THIS message — attached to the user turn.

Why it is not in the system prompt (plan-memory-facts-and-commitments.md,
Task 5): the memory section of the full system prompt is only rebuilt every
``SYSTEM_PROMPT_CACHE_TIMEOUT`` seconds, so a message-driven selection there
would answer the message that happened to trigger the rebuild — up to five
minutes stale — and it would break the byte-identical cached prefix. This
block therefore hangs on the CURRENT user turn instead: it is composed fresh
per message, and the prefix above it never changes.

Selection is similarity, nothing else: the current message is embedded, every
candidate memory (facts + open commitments) is compared by cosine similarity
against its cached vector, and the best ``max_entries`` above the threshold
are attached. Ties fall to the more recent memory. No importance, no decay, no
type bonus — that ranking already runs in the system prompt, and mixing the
two would just reproduce it.

Failure is always silence: no embedding backend, no vectors, nothing above the
threshold — then there is NO block at all, never an empty header and never an
exception into the chat turn.

Vectors are cached per memory row in ``memory_embeddings`` (one row per
memory, stamped with the model that produced it). They are filled lazily —
a bounded batch per lookup — and by ``add_memory`` in the background.
"""
from array import array
from typing import Any, Dict, Iterable, List

from app.core import config
from app.core.log import get_logger

logger = get_logger("memory_situational")

# Only these two types are candidates. Episodics are the bulk of the store and
# are what the day/scene summaries already carry into the prompt; facts and
# promises are the sorts that go missing when nobody asks the right question.
CANDIDATE_TYPES = ("semantic", "commitment")

# How many missing vectors one lookup may compute. A character with hundreds
# of memories would otherwise embed the whole store on its first situational
# message; instead the cache fills over the next few turns.
EMBED_BATCH_LIMIT = 64

# Schema defaults (app/core/config_schema.py, section "memory"). Kept in sync
# by hand — a config that was never saved must behave like the admin UI shows.
DEFAULT_ENABLED = True
DEFAULT_MAX_ENTRIES = 3
DEFAULT_MIN_SIMILARITY = 0.75

TEMPLATE = "chat/situational_memories.md"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def is_enabled() -> bool:
    value = config.get("memory.situational_enabled", DEFAULT_ENABLED)
    return DEFAULT_ENABLED if value in (None, "") else bool(value)


def max_entries() -> int:
    try:
        value = int(config.get("memory.situational_max_entries")
                    or DEFAULT_MAX_ENTRIES)
    except (TypeError, ValueError):
        return DEFAULT_MAX_ENTRIES
    return value if value > 0 else DEFAULT_MAX_ENTRIES


def min_similarity() -> float:
    raw = config.get("memory.situational_min_similarity")
    if raw in (None, ""):
        return DEFAULT_MIN_SIMILARITY
    try:
        return float(raw)
    except (TypeError, ValueError):
        return DEFAULT_MIN_SIMILARITY


# ---------------------------------------------------------------------------
# Vector cache
# ---------------------------------------------------------------------------

def pack_vector(vec: Iterable[float]) -> bytes:
    """float list -> raw float32 blob (what the DB column holds)."""
    return array("f", [float(x) for x in vec]).tobytes()


def unpack_vector(blob: bytes) -> List[float]:
    """Raw float32 blob -> float list. Empty list on a truncated blob."""
    if not blob or len(blob) % 4:
        return []
    arr = array("f")
    arr.frombytes(blob)
    return list(arr)


class DbVectorCache:
    """``memory_embeddings`` as a two-method cache (``get_many``/``put_many``).

    A row whose ``model_id`` differs from the current one counts as missing —
    vectors from two models are not comparable, so it gets re-embedded on
    touch and overwrites the stale row (memory_id is the primary key).
    """

    def get_many(self, memory_ids: List[int], model_id: str) -> Dict[int, List[float]]:
        ids: List[int] = []
        for raw in memory_ids:
            try:
                ids.append(int(raw))
            except (TypeError, ValueError):
                continue  # legacy hex id ("mem_ab12…") — no row to key on
        if not ids or not model_id:
            return {}
        from app.core.db import get_connection
        out: Dict[int, List[float]] = {}
        # Chunked so a character with a big store cannot blow the SQLite
        # variable limit (999 by default).
        for start in range(0, len(ids), 400):
            chunk = ids[start:start + 400]
            placeholders = ",".join("?" * len(chunk))
            rows = get_connection().execute(
                f"SELECT memory_id, vector FROM memory_embeddings "
                f"WHERE model_id=? AND memory_id IN ({placeholders})",
                [model_id] + chunk).fetchall()
            for row in rows:
                vec = unpack_vector(row[1])
                if vec:
                    out[int(row[0])] = vec
        return out

    def put_many(self, model_id: str, vectors: Dict[int, List[float]]) -> None:
        """One transaction for a whole batch — the lazy backfill writes up to
        ``EMBED_BATCH_LIMIT`` rows at once and must not commit that many
        times into a DB other threads are using."""
        if not model_id or not vectors:
            return
        from app.core.db import transaction
        from app.core.timeutils import utc_now_iso
        now = utc_now_iso()
        rows = [(int(mem_id), model_id, pack_vector(vec), now)
                for mem_id, vec in vectors.items() if vec]
        if not rows:
            return
        with transaction() as conn:
            conn.executemany(
                "INSERT INTO memory_embeddings (memory_id, model_id, vector, ts) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(memory_id) DO UPDATE SET "
                "model_id=excluded.model_id, vector=excluded.vector, ts=excluded.ts",
                rows)


# ---------------------------------------------------------------------------
# Selection — pure: no DB, no config, no clock
# ---------------------------------------------------------------------------

def select_situational(message: str,
                       candidates: List[Dict[str, Any]],
                       cache,
                       *,
                       embed,
                       model_id: str,
                       max_results: int,
                       threshold: float,
                       embed_budget: int = EMBED_BATCH_LIMIT) -> List[Dict[str, Any]]:
    """The memories of ``candidates`` that fit ``message``, best first.

    ``candidates`` are memory entries (``id``, ``content``, ``memory_type``,
    ``timestamp``, ...); ``cache`` supplies ``get_many``/``put``; ``embed`` is
    the text -> vector function. Everything the caller injects, so this can be
    checked without a world DB and without an embedding backend.

    Returns entries copied with an added ``score``. Empty list means "attach
    nothing" — including when the embedding backend has no answer at all.
    """
    text = (message or "").strip()
    if not text or not candidates or max_results <= 0:
        return []

    query = embed(text)
    if not query:
        # No embedding backend (or it failed). Same rule as the pose catalog:
        # fall silent, never block and never guess.
        return []

    ids = [c.get("id") for c in candidates if c.get("id") is not None]
    vectors = dict(cache.get_many(ids, model_id) or {})

    # Lazy fill, bounded. Newest first, because that is the order the
    # candidates arrive in and the recent ones are the likelier hits.
    budget = max(0, int(embed_budget))
    fresh: Dict[int, List[float]] = {}
    for cand in candidates:
        if budget <= 0:
            break
        mem_id = cand.get("id")
        if mem_id is None or mem_id in vectors:
            continue
        content = (cand.get("content") or "").strip()
        if not content:
            continue
        vec = embed(content)
        budget -= 1
        if not vec:
            continue
        vectors[mem_id] = vec
        fresh[mem_id] = vec
    if fresh:
        try:
            cache.put_many(model_id, fresh)
        except Exception as e:
            # A cache that cannot be written costs the next turn the same
            # embeddings — it must never cost this turn its answer.
            logger.debug("vector cache write failed (%d rows): %s", len(fresh), e)

    from app.core.embedding import cosine_similarity
    scored: List[Dict[str, Any]] = []
    for cand in candidates:
        vec = vectors.get(cand.get("id"))
        if not vec:
            continue
        score = cosine_similarity(query, vec)
        if score < threshold:
            continue
        entry = dict(cand)
        entry["score"] = score
        scored.append(entry)

    # Similarity decides; a tie falls to the more recent memory (the timestamp
    # is an ISO string, so the same descending sort covers both keys).
    scored.sort(key=lambda e: (e["score"], e.get("timestamp") or ""), reverse=True)
    return scored[:max_results]


# ---------------------------------------------------------------------------
# DB-backed wiring
# ---------------------------------------------------------------------------

def load_candidates(character_name: str) -> List[Dict[str, Any]]:
    """Facts and OPEN commitments of a character, newest first.

    Same two exclusions the prompt sections apply: a completed commitment is
    done with, and a memory about a character that no longer exists in the
    world stays in storage but out of any prompt.
    """
    from app.models.memory import load_memories
    try:
        from app.models.character import character_exists
    except Exception:
        character_exists = None  # type: ignore

    out: List[Dict[str, Any]] = []
    for mem in load_memories(character_name):
        if mem.get("memory_type") not in CANDIDATE_TYPES:
            continue
        if "completed" in (mem.get("tags") or []):
            continue
        if not (mem.get("content") or "").strip():
            continue
        related = mem.get("related_character") or ""
        if related and character_exists is not None and not character_exists(related):
            continue
        out.append(mem)
    return out


def situational_memories(character_name: str, message: str,
                         embed=None) -> List[Dict[str, Any]]:
    """Selection for one character and one message (DB + config + embedding)."""
    if not is_enabled():
        return []
    from app.core import embedding as embedding_mod
    model_id = embedding_mod.current_model_id()
    if not model_id:
        return []
    return select_situational(
        message,
        load_candidates(character_name),
        DbVectorCache(),
        embed=embed or embedding_mod.embed,
        model_id=model_id,
        max_results=max_entries(),
        threshold=min_similarity())


def _due_state(entry: Dict[str, Any]) -> str:
    """Due hint of a commitment, rendered exactly like the thought block does.

    One implementation, so the two blocks can never say different things about
    the same promise. Anything but a commitment with a readable delay yields
    "" and the entry renders bare.
    """
    if entry.get("memory_type") != "commitment":
        return ""
    try:
        minutes = int(entry.get("delay_minutes") or 0)
    except (TypeError, ValueError):
        return ""
    if minutes <= 0:
        return ""
    from app.core.thought_context import _due_hint
    return _due_hint(entry.get("game_ts", "") or "", minutes)


def render_block(entries: List[Dict[str, Any]]) -> str:
    """Renders the selected entries into the user-turn fragment ("" if none)."""
    if not entries:
        return ""
    from app.core.prompt_templates import render
    memories = [
        {
            "content": (e.get("content") or "").strip(),
            "due": _due_state(e),
            "is_commitment": e.get("memory_type") == "commitment",
        }
        for e in entries if (e.get("content") or "").strip()
    ]
    if not memories:
        return ""
    return render(TEMPLATE, memories=memories).strip()


def build_situational_block(character_name: str, message: str) -> str:
    """The finished fragment for the user turn — "" when nothing fits.

    Never raises: the chat turn must not fail because a memory lookup did.
    """
    try:
        entries = situational_memories(character_name, message)
        if not entries:
            return ""
        block = render_block(entries)
        if block:
            logger.info("[%s] situational memories: %d attached (best %.2f)",
                        character_name, len(entries), entries[0].get("score", 0.0))
        return block
    except Exception as e:
        logger.debug("[%s] situational memory block failed: %s",
                     character_name, e)
        return ""


# ---------------------------------------------------------------------------
# Write path — keep the cache warm without ever blocking a turn
# ---------------------------------------------------------------------------

def embed_memory(memory_id: int, content: str) -> None:
    """Computes and stores the vector for ONE memory row. Never raises."""
    try:
        if not is_enabled() or not memory_id or not (content or "").strip():
            return
        from app.core import embedding as embedding_mod
        model_id = embedding_mod.current_model_id()
        if not model_id:
            return
        vec = embedding_mod.embed(content)
        if vec:
            DbVectorCache().put_many(model_id, {int(memory_id): vec})
    except Exception as e:
        logger.debug("embedding memory %s failed: %s", memory_id, e)


def schedule_embedding(memory_id: int, content: str) -> None:
    """Fire-and-forget version of :func:`embed_memory`.

    Called from ``add_memory``, which runs inside chat, thought and skill
    turns — the first internal embedding loads an ONNX model, so this must
    never happen on the caller's thread. Same shape as the background
    extraction in ``chat_engine``: the running loop's executor when there is
    one, a daemon thread otherwise (``add_memory`` is often already in a pool
    thread, where there is no loop to hand the work to).
    """
    if not memory_id or not (content or "").strip():
        return
    if not is_enabled():
        return

    def _run():
        embed_memory(memory_id, content)

    try:
        import asyncio
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    try:
        if loop is not None:
            from app.core.turn_trace import bind_trace
            loop.run_in_executor(None, bind_trace(_run))
        else:
            import threading
            threading.Thread(target=_run, daemon=True,
                             name=f"embed-memory-{memory_id}").start()
    except Exception as e:
        logger.debug("scheduling embedding for memory %s failed: %s",
                     memory_id, e)
