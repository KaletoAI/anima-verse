"""Authoritative communication sources for the existing RP state extractor.

Source identity and recipients come from persisted delivery, never model text.
The per-turn collector is kept outside JSON tool arguments and explicitly rebound
when work crosses a thread boundary.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from threading import Event, RLock
from typing import Iterator
from uuid import uuid4


@dataclass(frozen=True)
class StatSource:
    event_id: str
    actor: str | None
    content: str
    medium: str
    order: tuple[str, int, str]
    game_ts: str
    allowed_targets: tuple[str, ...]
    avatar_audience: tuple[str, ...]
    avatar_targets: tuple[str, ...] = ()
    location_id: str = ""
    room_id: str = ""


@dataclass(frozen=True)
class ReplyReceipt:
    source: StatSource | None


@dataclass(frozen=True)
class StatExtractionContext:
    sources: tuple[StatSource, ...]
    self_event_id: str
    character: str


class StatSourceCollector:
    """One turn's source set; insertion order is not the application order."""

    def __init__(self) -> None:
        from app.core.timeutils import game_time, utc_now_iso
        self.self_event_id = f"self:{uuid4().hex}"
        self.started_at = utc_now_iso()
        self.game_ts = game_time().canonical()
        self._sources: dict[str, StatSource] = {}
        self._source_work: set[Event] = set()
        self._lock = RLock()

    def add(self, source: StatSource) -> None:
        with self._lock:
            self._sources.setdefault(source.event_id, source)

    def snapshot(self) -> tuple[StatSource, ...]:
        with self._lock:
            return tuple(sorted(self._sources.values(), key=lambda source: source.order))

    def start_source_work(self) -> Event:
        """Register a speech-producing deferred call BEFORE starting its worker."""
        completion = Event()
        with self._lock:
            self._source_work.add(completion)
        return completion

    def finish_source_work(self, completion: Event) -> None:
        """Release a registered call on success, failure or worker-start failure."""
        with self._lock:
            self._source_work.discard(completion)
            completion.set()

    def wait_for_source_work(self) -> None:
        """Wait outside all collector/profile locks before freezing extraction input."""
        while True:
            with self._lock:
                pending = tuple(self._source_work)
            if not pending:
                return
            for completion in pending:
                completion.wait()


_collector: ContextVar[StatSourceCollector | None] = ContextVar("stat_source_collector", default=None)


@contextmanager
def bind_stat_sources(collector: StatSourceCollector | None) -> Iterator[None]:
    """Bind only this collector, without copying unrelated request context."""
    token = _collector.set(collector)
    try:
        yield
    finally:
        _collector.reset(token)


def get_stat_source_collector() -> StatSourceCollector | None:
    """Capture a turn collector explicitly before spawning a worker."""
    return _collector.get()


def collect_stat_source(source: StatSource | None) -> None:
    collector = _collector.get()
    if collector is not None and source is not None:
        collector.add(source)


def _snapshot_names(value: object) -> tuple[str, ...] | None:
    """Reject absent/malformed publication roles instead of consulting live roles."""
    if not isinstance(value, list) or any(not isinstance(name, str) or not name for name in value):
        return None
    if len(set(value)) != len(value):
        return None
    return tuple(sorted(value))


def source_from_utterance(utterance_id: int) -> StatSource | None:
    """Resolve committed delivery only when its complete frozen role snapshot exists."""
    from app.models.perception_store import get_utterance_delivery

    delivery = get_utterance_delivery(utterance_id)
    if delivery is None:
        return None
    from app.core.perception import CONTENTLESS_KINDS

    row, perceptions = delivery
    audience = {perception["perceiver"] for perception in perceptions
                if perception["content"] and perception["kind"] not in CONTENTLESS_KINDS}
    event_id = f"room:{row['id']}"
    metadata = row.get("meta")
    if not isinstance(metadata, dict):
        return None
    avatar_audience = _snapshot_names(metadata.get("stat_avatar_audience"))
    avatars = _snapshot_names(metadata.get("stat_avatar_targets"))
    addressed = set(row.get("addressees") or [])
    if (avatar_audience is None or avatars is None
            or not set(avatar_audience).issubset(audience)
            or not set(avatars).issubset(set(avatar_audience) & addressed)):
        # Old room events did not capture unaddressed avatar roles. They remain
        # readable perceptions, never newly inferred NPC/stat sources.
        return None
    allowed = tuple(sorted(audience))
    return StatSource(
        event_id=event_id,
        actor=row["speaker"] or None,
        content=row["content"],
        medium="in_person",
        order=(row["ts"], int(row["id"]), event_id),
        game_ts=row.get("game_ts") or "",
        allowed_targets=allowed,
        avatar_audience=avatar_audience,
        avatar_targets=avatars,
        location_id=row.get("location_id") or "",
        room_id=row.get("room_id") or "",
    )


def source_from_dm(event_id: str) -> StatSource | None:
    """Both mirrors must describe one real, server-identified direct message."""
    from app.models.unified_chat import UnifiedChatManager

    event = UnifiedChatManager.get_direct_message_event(event_id)
    if event is None:
        return None
    recipient = event["recipient"]
    metadata = event["metadata"]
    if not isinstance(metadata, dict):
        return None
    avatars = _snapshot_names(metadata.get("stat_avatar_targets"))
    if avatars not in ((), (recipient,)):
        return None
    # A DM has exactly one content-bearing recipient; its existing complete
    # target-role fact is also the complete audience snapshot, not a fallback.
    return StatSource(
        event_id=event_id,
        actor=event["sender"],
        content=event["content"],
        medium="messaging",
        order=(event["ts"], event["row_id"], event_id),
        game_ts=metadata.get("game_ts") or "",
        allowed_targets=(recipient,),
        avatar_audience=avatars,
        avatar_targets=avatars,
    )


def self_source(character: str, content: str, event_id: str, *,
                started_at: str | None = None, game_ts: str | None = None) -> StatSource:
    """Private narrative may change its owner, never an inferred partner."""
    from app.core.timeutils import game_time, utc_now_iso

    return StatSource(
        event_id=event_id,
        actor=None,
        content=content,
        medium="self",
        order=(started_at or utc_now_iso(), 0, event_id),
        game_ts=game_ts or game_time().canonical(),
        allowed_targets=(character,),
        avatar_audience=(),
    )


def extraction_context(character: str, sources: tuple[StatSource, ...], *,
                       narrative: str, self_event_id: str | None = None,
                       started_at: str | None = None, game_ts: str | None = None) -> StatExtractionContext:
    """Keep transmitted sources separate from private, unattributed effects."""
    event_id = self_event_id or f"self:{uuid4().hex}"
    ordered = {source.event_id: source for source in sources}
    if narrative.strip():
        ordered[event_id] = self_source(
            character, narrative, event_id, started_at=started_at, game_ts=game_ts)
    return StatExtractionContext(
        sources=tuple(sorted(ordered.values(), key=lambda source: source.order)),
        self_event_id=event_id,
        character=character,
    )


def source_only_context(character: str, collector: StatSourceCollector | None) -> StatExtractionContext | None:
    """Silent turns evaluate only delivered outgoing speech with eligible avatar stats.

    Incoming/context sources alone never trigger this phase. Use the same
    authority/template/feature/receipt gate as the shared extractor, without
    another model call and without manufacturing a private narrative source.
    """
    if collector is None:
        return None
    collector.wait_for_source_work()
    sources = tuple(source for source in collector.snapshot()
                    if source.actor == character and source.medium != "self"
                    and any(name != character and name in source.allowed_targets
                            and name in source.avatar_audience
                            for name in source.avatar_targets))
    if not sources:
        return None
    context = extraction_context(
        character, sources, narrative="", self_event_id=collector.self_event_id,
        started_at=collector.started_at, game_ts=collector.game_ts)
    from app.core.chat_stat_effects import build_stat_targets
    return context if build_stat_targets(context)["required_stat_pairs"] else None


def stat_source_turn(function):
    """Give a synchronous or asynchronous turn its own collector lifetime."""
    from functools import wraps
    from inspect import iscoroutinefunction

    if iscoroutinefunction(function):
        @wraps(function)
        async def async_turn(*args, **kwargs):
            with bind_stat_sources(StatSourceCollector()):
                return await function(*args, **kwargs)
        return async_turn

    @wraps(function)
    def sync_turn(*args, **kwargs):
        with bind_stat_sources(StatSourceCollector()):
            return function(*args, **kwargs)
    return sync_turn
