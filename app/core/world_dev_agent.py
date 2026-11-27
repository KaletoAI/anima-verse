"""World Dev free mode — the agent loop and the run manager.

Plan docs/superpowers/plans/2026-11-22-world-dev-free-mode.md, Task 7 (the
"Run state machine" table there is binding); spec
docs/superpowers/specs/2026-11-22-world-dev-free-mode-design.md.

A RUN is one task the admin gave a model. `RunManager.start` resolves the
LLM, claims the one open run (`world_dev_runs.create_run`), records whether
the world was already frozen and freezes it, then runs TURN 1 as an asyncio
task. A turn is a text tool loop: the model answers, the FIRST
`<tool name="...">{json}</tool>` of the answer is executed through
`world_dev_tools.run_tool` (journaled there), its one-line result goes back
as `[result <tool>] <line>`, and so on until a reply carries no tool call.

Turn ends:
* no tool call (turn >= 2, or turn 1 after at least one tool call) ->
  `awaiting_review`, note = the final reply;
* budget reached (the tool-call or token budget OF THIS TURN, see below) ->
  `awaiting_review` WITHOUT any undo: the turn's work is kept, the note
  starts "budget reached (" and asks for a follow-up, and the history gets
  one assistant line saying the turn was cut off, so the next turn continues
  where it stopped. Exception: turn 1 that hit a budget before its first
  tool call has nothing to keep and is a hard failure;
* hard failure (LLM error, 3 unparseable calls in a row, turn 1 without any
  tool call, a tool raising a non-refusal exception) or Stop -> the turn's
  writes are undone (`world_dev_undo.undo(run, turn)`); turn 1 then ends
  terminal (`rolled_back` / `rollback_incomplete`), a later turn returns
  to `awaiting_review` with the error as note.

Budgets are PER TURN: `max_steps` / `max_tokens_total` of the run row
bound each turn on its own (start and every follow-up get the full
budget); the run row keeps the run TOTALS (steps, tokens, cost).
max_steps = tool calls per turn: the run's `steps` counts every model tool
call once (`world_dev_runs.count_call`, taken by `_loop` only) — executed
or refused, however many journal rows it writes; the media lane's rows are
no model calls and are not counted. The budget notes print tokens in
thousands (`_k`) — raw counts when the limit is under 1,000 tokens, where
"0k of 0k" would hide why the turn was cut. The
per-turn counters are measured against the totals at the turn's start and
live in memory only — a turn never survives a restart. A follow-up may
raise the budgets for itself and every later turn, never lower them.
Each turn's outcome (`kept` / `cut_by_budget` / `rolled_back`) is
remembered per process; `turn_summaries` merges it with the journal for
the run detail (writes and undone writes per turn).
From `awaiting_review` a follow-up `message` starts the next turn;
`accept` / `discard` (also from `interrupted`) end the run. `_close` is
the ONE terminal transition: status + ended_at, then the freeze state the
world had before the run.

Media (plan docs/superpowers/plans/2026-11-25-world-dev-free-media.md,
Task 9): a follow-up turn's start cancels the run's queued media rows
(`world_dev_media.cancel_queued`, "turn N started"); every turn end that
leaves the run in review (final, budget cut, a rolled-back later turn)
releases the turn's deferral WITHOUT a replay and queues the media of every
touched element (`world_dev_media.schedule`, which re-plans what a cancel
left open). An interrupted run renders nothing before Accept (F1): its
turn end only releases the deferral, its Accept schedules once
(`schedule(run, accepting=True)`) before the close, a Discard drops the
plan. Discard closes and removes the run's media BEFORE
the journal undo (`close_run_media`: the run's characters deferred again,
a running render waited for at most `DISCARD_WAIT_S`, then `pending`),
and after it sweeps the orphan dirs and replays the triggers the undo
suppressed (`finish_closed_run`); the report gains `media` {removed,
kept, pending, swept} — media never make the rollback incomplete. Accept
cancels nothing (`finish_accepted_run`: the lane keeps rendering).

A rolled-back later turn leaves the in-memory history truthful: every
entry of that turn after its user message is dropped and one note says the
turn was rolled back (and which steps could not be reversed), so the next
turn never builds on writes that are gone.

Concurrency: every state transition of a run runs under its own
`asyncio.Lock`. Tools, the undo and the store calls run in the thread pool
and are ALWAYS awaited to completion — Stop is a flag (plus an event the
stream races against, so a provider that sends nothing can still be
stopped) checked before each LLM call, while streaming and after each tool;
it aborts a stream, never a running tool. If ending a turn itself fails,
the run falls back to `interrupted` (accept / discard work from there)
rather than staying `running` without a task. The
LLM-queue registration wraps each LLM call alone (never a tool). A
cancelled turn task (process shutdown) makes no transition at all: the next
boot's `mark_interrupted_on_boot` marks the run `interrupted` and writes
nothing else.
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple

from app.core import world_dev_media as wdm
from app.core import world_dev_runs as wr
from app.core import world_dev_tools as wt
from app.core import world_dev_undo as wu
from app.core.log import get_logger

logger = get_logger("world_dev_agent")

#: Per-TURN budgets (each turn of a run gets them in full).
DEFAULT_MAX_STEPS = 200  # tool calls per turn
DEFAULT_MAX_TOKENS_TOTAL = 2_000_000
#: Start of the note of a turn cut off by its budget (work kept).
BUDGET_NOTE_PREFIX = "budget reached ("


def _k(n: int) -> str:
    """Tokens in thousands for the budget notes, rounded half up (the panel
    prints the note raw and shows its own counters the same way)."""
    return f"{(int(n) + 500) // 1000:,}k"


#: Consecutive replies with an unparseable tool call that fail the turn.
MAX_BAD_CALLS = 3
#: Read results kept whole in the history; older ones become a stub (pinned
#: reference reads excepted — they stay whole until the same read repeats).
KEEP_RESULTS = 4
#: Longest pinned read kept in the history. Every shipped manual stays
#: whole (smoke_world_dev_pinned.py (i) checks each one); a longer pinned
#: result (a world override of a manual, a huge template schema) is cut
#: with a closing note so it cannot fill every later turn's prompt. The
#: step row / panel line keeps the whole text — only the history is capped.
MAX_PINNED_CHARS = 16000
BAD_BODY_LINE = "error: body is not a JSON object"
# The fix a model needs most often: an unescaped quote or a raw line break
# inside a string. The escapes are the literal two-character sequences the
# model must type (backslash + quote, backslash + n), never the characters.
BAD_JSON_HINT = (" — inside a string write a double quote as \\\" and a line break "
                 "as \\n; split a very long text into several calls")
REPAIR_NOTE = ("note: the closing brackets of your call were wrong and were "
               "repaired — count { [ ] } carefully")
UNCLOSED_NOTE = ("note: your tool call was not closed with </tool> — it ran "
                 "anyway; always end it with </tool>")
CUT_OFF_LINE = ("error: your reply hit the model's output limit after {n} characters and "
                "was cut off before </tool> — the call did not run. Make it smaller: split "
                "the change into several calls (update_location: change one room per call "
                "and send the other kept rooms as {{\"id\": …}} alone, they stay as they "
                "are), shorter texts, fewer fields per call")


def _excerpt(body: str, pos: int, radius: int = 20) -> str:
    """Short single-line snippet of body around pos with ellipses when clipped."""
    start = max(0, pos - radius)
    end = min(len(body), pos + radius)
    frag = body[start:end].replace("\n", "\\n").replace("\r", "\\r")
    return ("…" if start > 0 else "") + frag + ("…" if end < len(body) else "")


def _repair_closers(body: str) -> Optional[str]:
    """Repair a JSON object body whose ONLY problem is its trailing run of
    closing brackets/braces (extra closer, missing closer, or swapped }] / ]}).

    Strips the maximal suffix made only of '}', ']' and whitespace, scans the
    remaining prefix with a JSON-aware string/bracket scanner, and appends the
    exact closers required by the open bracket stack. Returns the repaired text
    only when the prefix has no structural mismatch, ends outside a string, and
    json.loads produces a dict; else None. Never alters anything before the
    trailing closer run."""
    end = len(body)
    while end > 0 and (body[end - 1] in "}]" or body[end - 1].isspace()):
        end -= 1
    prefix = body[:end]
    if not prefix:
        return None
    in_string = False
    escape = False
    stack: List[str] = []
    for ch in prefix:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch in "{[":
                stack.append(ch)
            elif ch in "}]":
                expected = "{" if ch == "}" else "["
                if not stack or stack[-1] != expected:
                    return None
                stack.pop()
    if in_string or not stack:
        return None
    repaired = prefix + "".join("}" if c == "{" else "]" for c in reversed(stack))
    try:
        parsed = json.loads(repaired)
    except ValueError:
        return None
    return repaired if isinstance(parsed, dict) else None


def _structural_hint(body: str) -> Optional[str]:
    """If body has a bracket/brace structural problem outside strings (extra
    closer, mismatched closer, or unclosed brackets at EOF), return a precise
    hint naming the position and an excerpt; else None."""
    if not body:
        return None
    in_string = False
    escape = False
    stack: List[str] = []
    prev_non_ws = ""
    for i, ch in enumerate(body):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            prev_non_ws = ch
            continue
        if ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            col = i - body.rfind("\n", 0, i)
            excerpt = _excerpt(body, i)
            expected = "{" if ch == "}" else "["
            if not stack:
                what = "object" if ch == "}" else "array"
                return (f' — one "{ch}" too many at column {col}: {excerpt}'
                        f' — the {what} was already closed')
            if stack[-1] != expected:
                if ch == "}" and prev_non_ws == "}":
                    return (f' — one "}}" too many at column {col}: {excerpt}'
                            f' — the object was already closed')
                return f' — "{ch}" closes a "{stack[-1]}" at column {col}: {excerpt}'
            stack.pop()
        if not ch.isspace():
            prev_non_ws = ch
    if not in_string and stack:
        need = "".join("}" if c == "{" else "]" for c in reversed(stack))
        noun = "bracket" if len(stack) == 1 else "brackets"
        return f' — {len(stack)} {noun} not closed at the end (need "{need}")'
    return None


def _bad_json_line(e: json.JSONDecodeError, body: str = "") -> str:
    """The refused line for an unparseable body: BAD_BODY_LINE stays the exact
    prefix (panel and smokes key on it), then where json stopped and how to fix it."""
    hint = _structural_hint(body) or BAD_JSON_HINT
    return (f"{BAD_BODY_LINE} (JSON error: {e.msg} at line {e.lineno} column {e.colno})"
            + hint)
SYSTEM_TEMPLATE = "world_dev_free/system.md"


class RunStateError(RuntimeError):
    """The action is not allowed in the run's current status (HTTP 409)."""

    def __init__(self, message: str, run_id: str = ""):
        super().__init__(message)
        self.run_id = run_id


class _Stopped(Exception):
    """Stop was requested while the model was streaming."""


# ── LLM plumbing (module level so a test can replace it) ─────────────────

#: Effort levels of the Anthropic Messages API (`output_config.effort`).
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
#: Completion budget for a Claude model when neither the request nor the LLM
#: routing names one: thinking and reply share max_tokens (Anthropic's
#: suggested start; 32768 left a map JSON ~600 tokens, 2026-11-23).
ANTHROPIC_DEFAULT_MAX_TOKENS = 65536


def anthropic_budget(is_anthropic: bool, requested: Optional[int],
                     routed: Optional[int]) -> Optional[int]:
    """The per-reply max_tokens: the cap the user sent wins; else the
    routing entry's; else ANTHROPIC_DEFAULT_MAX_TOKENS for a Claude model
    and None (the provider's default) for any other."""
    if requested:
        return int(requested)
    if routed:
        return int(routed)
    return ANTHROPIC_DEFAULT_MAX_TOKENS if is_anthropic else None


def apply_effort(llm: Any, effort: str) -> None:
    """Set the Effort level on a Claude client (`output_config.effort`).
    '' = the model's default; other providers ignore it. ValueError for a
    level not in EFFORT_LEVELS."""
    from app.core.llm_client import AnthropicLLMClient, merge_extra_params
    effort = (effort or "").strip().lower()
    if not effort:
        return
    if effort not in EFFORT_LEVELS:
        raise ValueError(f"unknown effort {effort!r} (allowed: {', '.join(EFFORT_LEVELS)})")
    if isinstance(llm, AnthropicLLMClient):
        llm.extra_params = merge_extra_params(
            llm.extra_params, {"output_config": {"effort": effort}})


def _default_llm_factory(model: str, provider: str,
                         max_tokens: Optional[int]) -> Optional[Tuple[Any, Any]]:
    """(LLM client, LLMInstance) for the World Dev model, or None.

    The per-reply budget follows `anthropic_budget`: `create_llm_instance`
    keeps the routing entry's max_tokens when called with None, so that value
    is the routed one; the result is written to the client AND the instance
    (the instance is what the queue tracking reports)."""
    from app.core.llm_client import AnthropicLLMClient
    from app.core.llm_router import create_llm_instance
    instance = create_llm_instance(task="chat", model=model, provider_name=provider or "",
                                   max_tokens=max_tokens)
    if instance is None:
        return None
    routed = getattr(instance, "max_tokens", None) if max_tokens is None else None
    llm = instance.create_llm()
    if llm is None:
        return None
    budget = anthropic_budget(isinstance(llm, AnthropicLLMClient), max_tokens, routed)
    llm.max_tokens = budget
    instance.max_tokens = budget
    logger.info("world-dev LLM: %s/%s max_tokens=%s", provider or "?", model, budget)
    return llm, instance


async def _chat_active(llm_instance: Any) -> Any:
    from app.core.llm_queue import get_llm_queue
    return await get_llm_queue().register_chat_active_async(
        "WorldDev", llm_instance=llm_instance, task_type="world_dev",
        label="World Dev free mode")


def _chat_done(task_id: Any) -> None:
    if not task_id:
        return
    from app.core.llm_queue import get_llm_queue
    get_llm_queue().register_chat_done(task_id)


def _render_system(building_models: str = "hull") -> str:
    from app.core import prompt_templates
    from app.core.layout_prompt import world_setup_block
    return prompt_templates.render(
        SYSTEM_TEMPLATE,
        world_setup_block=world_setup_block(),
        tool_list="\n".join(f"- {line}" for line in wt.tool_list()),
        manual_sections=", ".join(wt.MANUAL_SECTIONS),
        building_models=building_models)


def _tag_pattern() -> "re.Pattern[str]":
    from app.core.tool_formats import get_format
    return re.compile(get_format("tag")["pattern"])


_TOOL_OPEN = re.compile(r'<tool\s+name="(\w+)"')


def _display_cut(text: str) -> int:
    """How much of a streamed reply the UI may see: everything before a
    (possibly still partial) tool tag."""
    cut = text.find("<tool")
    if cut >= 0:
        return cut
    lt = text.rfind("<")
    if lt >= 0 and "<tool".startswith(text[lt:]):
        return lt
    return len(text)


def _seq_of(item: Any) -> int:
    """The journal seq of a skip record (its `seq`) or of a reversed entry
    (a bare number); 0 when it names none or cannot be read — never raises
    (used in the discard's `finally`)."""
    raw = item.get("seq") if isinstance(item, dict) else item
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


def _tokens(run: Dict[str, Any]) -> int:
    return int(run["tokens_in"] or 0) + int(run["tokens_out"] or 0)


def turn_summaries(run: Dict[str, Any], steps: List[Dict[str, Any]],
                   known: Optional[Dict[int, Dict[str, str]]] = None) -> List[Dict[str, Any]]:
    """One row per turn of the run: {turn, status, reason, writes, undone}.

    `writes` / `undone` count the turn's WRITE journal rows and those of
    them already undone. `status`: `running` for the working turn of a
    running run; else the outcome this process recorded (`known`, from
    `RunManager.turn_outcomes`); without one (after a restart) it is
    derived — undone writes in a run that was not discarded = `rolled_back`,
    the newest turn whose note starts with BUDGET_NOTE_PREFIX =
    `cut_by_budget`, otherwise `kept`. The reason of a derived row is the
    run note for the newest turn, else empty. A discarded run's turns keep
    their own outcome (the discard is the run's status)."""
    known = known or {}
    last = int(run.get("turn") or 0)
    note = str(run.get("note") or "")
    discarded = run.get("status") in ("rolled_back", "rollback_incomplete")
    out: List[Dict[str, Any]] = []
    for turn in range(1, last + 1):
        rows = [s for s in steps
                if int(s.get("turn") or 0) == turn and s.get("kind") == "write"]
        writes = len(rows)
        undone = sum(1 for s in rows if s.get("undone_at"))
        o = known.get(turn)
        if turn == last and run.get("status") == "running":
            status, reason = "running", ""
        elif o:
            status, reason = o.get("status") or "kept", o.get("reason") or ""
        elif undone and not discarded:
            status, reason = "rolled_back", note if turn == last else ""
        elif turn == last and note.startswith(BUDGET_NOTE_PREFIX):
            status, reason = "cut_by_budget", note
        else:
            status, reason = "kept", ""
        out.append({"turn": turn, "status": status, "reason": reason,
                    "writes": writes, "undone": undone})
    return out


# ── Per-run in-memory state ──────────────────────────────────────────────

@dataclass
class _RunState:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    cond: asyncio.Condition = field(default_factory=asyncio.Condition)
    events: List[Dict[str, Any]] = field(default_factory=list)
    history: List[Dict[str, Any]] = field(default_factory=list)
    task: Optional[asyncio.Task] = None
    busy: bool = False
    stop: bool = False
    stop_ev: asyncio.Event = field(default_factory=asyncio.Event)
    llm: Any = None
    llm_instance: Any = None
    system: str = ""
    pricing: Dict[str, float] = field(default_factory=dict)
    #: the run totals at the start of the current turn (per-turn budgets)
    base: Dict[str, int] = field(default_factory=dict)
    last_finish: Optional[str] = None


class RunManager:
    """Drives the free-mode runs of this process (one open run per world)."""

    def __init__(self) -> None:
        #: (model, provider, max_tokens) -> (llm, llm_instance) | None
        self.llm_factory: Callable[[str, str, Optional[int]], Any] = _default_llm_factory
        self._states: Dict[str, _RunState] = {}
        #: run id -> {turn: {"status", "reason"}} of the turns this process ended
        self._outcomes: Dict[str, Dict[int, Dict[str, str]]] = {}
        #: run id -> {"turn", "steps", "tokens"} of the newest turn this process ran
        self._turn_usage: Dict[str, Dict[str, int]] = {}

    # ── helpers ──
    def _state(self, run_id: str) -> _RunState:
        st = self._states.get(run_id)
        if st is None:
            st = self._states[run_id] = _RunState()
        return st

    def _drop_if_idle(self, run_id: str, st: _RunState) -> None:
        """Forget a state an action created for nothing (no events, no turn)."""
        if not st.events and not st.busy and st.llm is None \
                and self._states.get(run_id) is st:
            self._states.pop(run_id, None)

    def is_busy(self, run_id: str) -> bool:
        """True while a turn task of this run is working."""
        st = self._states.get(run_id)
        return bool(st and st.busy)

    def turn_outcomes(self, run_id: str) -> Dict[int, Dict[str, str]]:
        """The outcomes of the turns this process ended (empty after a restart)."""
        return dict(self._outcomes.get(run_id) or {})

    def turn_usage(self, run_id: str) -> Optional[Dict[str, int]]:
        """Per-turn counters of the newest turn this process ran, or None."""
        u = self._turn_usage.get(run_id)
        return dict(u) if u else None

    def _set_outcome(self, run_id: str, turn: int, status: str, reason: str) -> None:
        if turn > 0:
            self._outcomes.setdefault(run_id, {})[turn] = {"status": status,
                                                           "reason": reason}

    async def _emit(self, st: _RunState, ev: Dict[str, Any]) -> None:
        async with st.cond:
            ev = {"ev": len(st.events) + 1, **ev}
            st.events.append(ev)
            st.cond.notify_all()

    async def _resolve(self, model: str, provider: str, max_tokens: Optional[int],
                       effort: str = "", building_models: str = "hull") -> Tuple[Any, Any, str, Dict[str, float]]:
        from app.core.llm_cost import resolve_pricing
        resolved = await asyncio.to_thread(self.llm_factory, model, provider, max_tokens)
        if not resolved or resolved[0] is None:
            raise ValueError(f"no provider for model {model!r}")
        # Here, not in the factory: the factory seam keeps its 3 arguments.
        apply_effort(resolved[0], effort)
        system = await asyncio.to_thread(_render_system, building_models)
        pricing = await resolve_pricing(model, provider)
        return resolved[0], resolved[1], system, pricing

    def _get(self, run_id: str) -> Dict[str, Any]:
        run = wr.get_run(run_id)
        if run is None:
            raise KeyError(f"unknown world-dev run: {run_id}")
        return run

    async def _close(self, run_id: str, status: str, note: Optional[str] = None,
                     restore_freeze: bool = True,
                     media_closed: bool = False) -> Dict[str, List]:
        """THE terminal transition: status + ended_at, then the world's
        pre-run freeze state (skipped with `restore_freeze=False`: a start
        that failed before it recorded that state), then the run's media
        (`_close_media`; `media_closed` = the caller already ran
        `world_dev_media.close_run_media` before its journal undo). Returns
        the orphan sweep of a non-accepted close (`{"removed", "kept"}`)."""
        from app.models.world import set_world_frozen
        run = await asyncio.to_thread(self._get, run_id)
        await asyncio.to_thread(wr.set_status, run_id, status, note)
        if restore_freeze:
            try:
                await asyncio.to_thread(set_world_frozen, bool(run.get("was_frozen")))
            except Exception as e:  # noqa: BLE001 — the run is closed either way
                logger.error("world-dev %s: restoring the freeze state failed: %s",
                             run_id, e, exc_info=True)
        logger.info("world-dev run %s closed: %s", run_id, status)
        swept = await self._close_media(run_id, status, media_closed)
        st = self._state(run_id)
        await self._emit(st, {"type": "status", "status": status,
                              "note": note if note is not None else run.get("note") or ""})
        # A closed run keeps nothing in memory: subscribers already holding
        # the state still get the final event; later ones read the store.
        st.history, st.llm, st.llm_instance, st.system = [], None, None, ""
        if self._states.get(run_id) is st:
            self._states.pop(run_id, None)
        return swept

    async def _release_media(self, run_id: str) -> None:
        """Lift the turn's deferral of automatic renders (``world_dev_media``,
        plan 2026-11-25-world-dev-free-media Tasks 2/9) at every turn end —
        without a replay: the turn-end `_schedule_media` renders instead.
        Never raises — the run's transition stands either way."""
        try:
            await asyncio.to_thread(wdm.release_turn, run_id)
        except Exception as e:  # noqa: BLE001
            logger.error("world-dev %s: releasing the media deferral failed: %s",
                         run_id, e, exc_info=True)

    async def _schedule_media(self, run_id: str, st: _RunState, *,
                              accepting: bool = False) -> None:
        """A turn returned the run to review — or an interrupted run is being
        accepted (`accepting`, F1): queue the media of every element the run
        touched (``world_dev_media.schedule`` re-plans ALL of them, so rows a
        turn start cancelled come back by themselves). A failure is logged and
        shown as one text event; the turn's outcome (the Accept) stands."""
        try:
            if accepting:
                await asyncio.to_thread(wdm.schedule, run_id, accepting=True)
            else:
                await asyncio.to_thread(wdm.schedule, run_id)
        except Exception as e:  # noqa: BLE001
            logger.error("world-dev %s: scheduling the media failed: %s", run_id, e,
                         exc_info=True)
            await self._emit(st, {"type": "text", "text": f"[media scheduling failed: {e}]"})

    @staticmethod
    async def _media_closing(run_id: str) -> Dict[str, List]:
        """Discard / terminal rollback before the journal undo
        (``world_dev_media.close_run_media``). Never raises: a failure is one
        `kept` record — media are derived, they never make a rollback
        incomplete (M9). `defer_run` runs first in its own try, so the
        journal undo's automatic triggers are still recorded (and replayed
        by the close) when `close_run_media` fails before its own
        `defer_run` (e.g. in `set_media_state`); a second `defer_run`
        inside it is a no-op."""
        try:
            await asyncio.to_thread(wdm.defer_run, run_id)
        except Exception as e:  # noqa: BLE001 — close_run_media tries again
            logger.error("world-dev %s: deferring the run's characters failed: %s",
                         run_id, e, exc_info=True)
        try:
            return await asyncio.to_thread(wdm.close_run_media, run_id)
        except Exception as e:  # noqa: BLE001
            logger.error("world-dev %s: removing the run's media failed: %s", run_id, e,
                         exc_info=True)
            return {"removed": [], "pending": [],
                    "kept": [{"item": "media", "reason": f"could not be removed ({e})"}]}

    async def _close_media(self, run_id: str, status: str,
                           media_closed: bool) -> Dict[str, List]:
        """The media side of `_close` (Task 9). Accepted: media state
        ``accepted``, the deferral released without a replay, the lane keeps
        running. Otherwise (discard, terminal rollback, a failed start): the
        run's media are closed and removed first unless the caller did it
        before its undo (`media_closed`), then the orphan dirs are swept and
        the deferral released WITH the replay of the triggers the undo
        suppressed. Never raises; returns the sweep (`{"removed", "kept"}`)."""
        try:
            if status == "accepted":
                await asyncio.to_thread(wdm.finish_accepted_run, run_id)
                return {"removed": [], "kept": []}
            if not media_closed:
                closed = await self._media_closing(run_id)
                if closed.get("pending") or closed.get("kept"):
                    logger.info("world-dev %s: media closed with %s", run_id, closed)
            return await asyncio.to_thread(wdm.finish_closed_run, run_id)
        except Exception as e:  # noqa: BLE001
            logger.error("world-dev %s: closing the run's media failed: %s", run_id, e,
                         exc_info=True)
            return {"removed": [], "kept": [{"item": "media", "reason": f"could not be swept ({e})"}]}

    def _spawn(self, run_id: str, st: _RunState, text: str) -> None:
        st.stop = False
        st.stop_ev = asyncio.Event()
        st.busy = True
        st.task = asyncio.create_task(self._run_turn(run_id, st, text))

    # ── public API ──
    async def start(self, task: str, model: str, provider: str, user_id: str,
                    max_tokens: Optional[int] = None,
                    max_steps: int = DEFAULT_MAX_STEPS,
                    max_tokens_total: int = DEFAULT_MAX_TOKENS_TOTAL,
                    effort: str = "", media_enabled: bool = True,
                    building_models: str = "hull") -> str:
        """Start a run; ValueError (nothing changed) when the task is empty,
        the effort or building_models unknown, or the model cannot be resolved;
        RunOpenError when a run is open. `effort` is stored on the run
        (EFFORT_LEVELS, '' = the model's default), `media_enabled` is the run's
        media switch (world_dev_media), `building_models` is 'hull' or 'mesh'."""
        from app.models.world import is_world_frozen, set_world_frozen
        task = (task or "").strip()
        if not task:
            raise ValueError("the task is empty")
        effort = (effort or "").strip().lower()
        if effort and effort not in EFFORT_LEVELS:
            raise ValueError(f"unknown effort {effort!r} (allowed: {', '.join(EFFORT_LEVELS)})")
        bm = (building_models or "").strip().lower()
        if bm not in wr.BUILDING_MODELS:
            raise ValueError(f"unknown building_models {building_models!r} "
                             f"(allowed: {', '.join(wr.BUILDING_MODELS)})")
        llm, instance, system, pricing = await self._resolve(model, provider, max_tokens,
                                                             effort, bm)
        run_id = await asyncio.to_thread(
            wr.create_run, task, model, provider, user_id,
            int(max_steps or DEFAULT_MAX_STEPS),
            int(max_tokens_total or DEFAULT_MAX_TOKENS_TOTAL), max_tokens, effort,
            bool(media_enabled), bm)
        st = self._state(run_id)
        async with st.lock:
            recorded = False  # was_frozen holds the world's real pre-run state
            try:
                was = await asyncio.to_thread(is_world_frozen)
                await asyncio.to_thread(wr.set_was_frozen, run_id, was)
                recorded = True
                await asyncio.to_thread(set_world_frozen, True)
            except Exception as e:
                # No write exists yet: close the run so it does not block
                # every new run until a restart, then report the error.
                logger.error("world-dev %s: start failed: %s", run_id, e, exc_info=True)
                try:
                    await self._close(run_id, "rolled_back", f"start failed: {e}",
                                      restore_freeze=recorded)
                except Exception as e2:  # noqa: BLE001 — the original error wins
                    logger.error("world-dev %s: closing the failed start failed: %s",
                                 run_id, e2, exc_info=True)
                raise
            st.llm, st.llm_instance, st.system, st.pricing = llm, instance, system, pricing
            await self._emit(st, {"type": "status", "status": "running", "note": ""})
            self._spawn(run_id, st, task)
        return run_id

    async def message(self, run_id: str, text: str, max_steps: Optional[int] = None,
                      max_tokens_total: Optional[int] = None) -> None:
        """A follow-up turn; only from `awaiting_review`. The budgets given
        apply per turn to this turn and every later one; they may only be
        raised: each stored budget becomes max(stored, requested)."""
        text = (text or "").strip()
        if not text:
            raise ValueError("the message is empty")
        st = self._state(run_id)
        try:
            await self._message(run_id, st, text, max_steps, max_tokens_total)
        finally:
            self._drop_if_idle(run_id, st)

    async def _message(self, run_id: str, st: _RunState, text: str,
                       max_steps: Optional[int], max_tokens_total: Optional[int]) -> None:
        async with st.lock:
            run = await asyncio.to_thread(self._get, run_id)
            if run["status"] != "awaiting_review":
                raise RunStateError(f"run is {run['status']}, not awaiting_review", run_id)
            steps = max(int(run["max_steps"] or 0), int(max_steps or 0))
            tokens = max(int(run["max_tokens_total"] or 0), int(max_tokens_total or 0))
            if (steps, tokens) != (run["max_steps"], run["max_tokens_total"]):
                await asyncio.to_thread(wr.set_budgets, run_id, steps, tokens)
            if st.llm is None:
                # This process did not start the run (server restart while it
                # waited for review): resolve again with the run's own
                # per-reply cap and effort, rebuild the context.
                (st.llm, st.llm_instance, st.system,
                 st.pricing) = await self._resolve(run["model"], run["provider"],
                                                   run.get("max_tokens"),
                                                   run.get("effort") or "",
                                                   run.get("building_models") or "hull")
                st.history = await asyncio.to_thread(self._rebuilt_history, run)
            await asyncio.to_thread(wr.set_status, run_id, "running", "")
            # The rows still queued would render a state the new turn may
            # change: cancelled (a running row finishes its current step);
            # the turn end re-plans every touched element (Task 9).
            try:
                await asyncio.to_thread(wdm.cancel_queued, run_id,
                                        f"turn {int(run.get('turn') or 0) + 1} started")
            except Exception as e:  # noqa: BLE001 — the turn starts either way
                logger.error("world-dev %s: cancelling the queued media failed: %s",
                             run_id, e, exc_info=True)
            await self._emit(st, {"type": "status", "status": "running", "note": ""})
            self._spawn(run_id, st, text)

    async def stop(self, run_id: str) -> None:
        """Ask the running turn to stop (it finishes a running tool first)."""
        st = self._state(run_id)
        try:
            async with st.lock:
                run = await asyncio.to_thread(self._get, run_id)
                if run["status"] != "running" or not st.busy:
                    raise RunStateError(f"run is {run['status']}, nothing to stop", run_id)
                st.stop = True
                st.stop_ev.set()
        finally:
            self._drop_if_idle(run_id, st)

    async def accept(self, run_id: str) -> None:
        st = self._state(run_id)
        try:
            async with st.lock:
                run = await asyncio.to_thread(self._get, run_id)
                if run["status"] not in ("awaiting_review", "interrupted"):
                    raise RunStateError(f"run is {run['status']}, cannot accept", run_id)
                if run["status"] == "interrupted":
                    # F1: an interrupted run rendered nothing so far; its
                    # Accept queues what plan() lists, before the close
                    # turns the media state to accepted.
                    await self._schedule_media(run_id, st, accepting=True)
                await self._close(run_id, "accepted")
        finally:
            self._drop_if_idle(run_id, st)

    async def discard(self, run_id: str) -> Dict[str, Any]:
        """Undo the whole run newest-first and close it (ALWAYS, also when
        the undo fails). Returns the undo report."""
        st = self._state(run_id)
        try:
            return await self._discard(run_id, st)
        finally:
            self._drop_if_idle(run_id, st)

    async def _discard(self, run_id: str, st: _RunState) -> Dict[str, Any]:
        async with st.lock:
            run = await asyncio.to_thread(self._get, run_id)
            if run["status"] not in ("awaiting_review", "interrupted"):
                raise RunStateError(f"run is {run['status']}, cannot discard", run_id)
            report: Dict[str, Any] = {"reversed": [], "skipped": [], "complete": False}
            # Media first (Task 9): closed, the run's characters deferred
            # again, every produced artefact removed (bounded wait for a
            # running row) — then the journal undo.
            media = await self._media_closing(run_id)
            try:
                report = await asyncio.to_thread(wu.undo, run_id)
            except Exception as e:  # noqa: BLE001 — close the run anyway
                logger.error("world-dev %s: discard undo failed: %s", run_id, e,
                             exc_info=True)
                report["skipped"] = [{"seq": 0, "line": "undo", "reason": f"undo failed: {e}"}]
            finally:
                # F7: an earlier skip record (a failed turn rollback) survives
                # only when its seq is 0 (a crashed undo) or this undo neither
                # reversed nor re-skipped that seq — a re-skipped seq keeps the
                # fresh record only (one record per seq).
                fresh = list(report.get("skipped") or [])
                done = {_seq_of(s) for s in report.get("reversed") or []}
                done |= {_seq_of(s) for s in fresh}
                done.discard(0)
                earlier = [s for s in run.get("skipped") or []
                           if _seq_of(s) == 0 or _seq_of(s) not in done]
                skipped = earlier + fresh
                complete = bool(report.get("complete")) and wu.is_complete(earlier)
                if skipped != list(run.get("skipped") or []):
                    try:
                        await asyncio.to_thread(wr.set_skipped, run_id, skipped)
                    except Exception as e:  # noqa: BLE001 — the close must still run
                        logger.error("world-dev %s: recording the skipped steps failed: %s",
                                     run_id, e, exc_info=True)
                swept = await self._close(run_id,
                                          "rolled_back" if complete else "rollback_incomplete",
                                          media_closed=True)
                # Media never make the rollback incomplete (M9): own key.
                report["media"] = {
                    "removed": list(media.get("removed") or []),
                    "kept": list(media.get("kept") or []) + list(swept.get("kept") or []),
                    "pending": list(media.get("pending") or []),
                    "swept": list(swept.get("removed") or [])}
            return report

    async def subscribe(self, run_id: str, after: int = 0) -> AsyncIterator[Dict[str, Any]]:
        """Events with `ev` > after: {"ev", "type": text|step|status|usage, ...};
        a "step" event carries the journal `seq` of its row (None only for a
        tool that raised, which ends the turn).
        Ends once the run's turn is no longer working and everything was
        delivered. A run this process holds no events for (never started
        here, or closed and forgotten) yields its stored status once, as ev 1.
        An `after` beyond this process's buffer (a counter from before a
        server restart) first yields {"ev": 0, "type": "reset"} — the client
        drops its view — and then the whole buffer from its start."""
        st = self._states.get(run_id)
        if st is None or (not st.events and not st.busy):
            run = await asyncio.to_thread(self._get, run_id)
            if after > 1:
                yield {"ev": 0, "type": "reset"}
            if after != 1:
                yield {"ev": 1, "type": "status", "status": run["status"],
                       "note": run.get("note") or ""}
            return
        async with st.cond:
            beyond = after > len(st.events)
        if beyond:
            after = 0
            yield {"ev": 0, "type": "reset"}
        while True:
            async with st.cond:
                await st.cond.wait_for(lambda: len(st.events) > after or not st.busy)
                new = st.events[after:]
                busy = st.busy
            for ev in new:
                yield ev
            if new:
                after = new[-1]["ev"]
            if not busy and len(st.events) <= after:
                return

    def mark_interrupted_on_boot(self) -> Optional[str]:
        """Boot: a run left `running` becomes `interrupted` — nothing else
        is written (no undo, no freeze change)."""
        run = wr.open_run()
        if run and run["status"] == "running":
            wr.set_status(run["id"], "interrupted")
            logger.warning("world-dev run %s was running at shutdown -> interrupted",
                           run["id"])
            return run["id"]
        return None

    # ── the turn ──
    @staticmethod
    def _rebuilt_history(run: Dict[str, Any]) -> List[Dict[str, Any]]:
        lines = [f"#{s['seq']} {s['tool']}: {s.get('line') or ''}"
                 + (" (undone)" if s.get("undone_at") else "")
                 for s in wr.steps(run["id"])]
        return [{"role": "user", "content": run.get("task") or ""},
                {"role": "assistant", "content":
                 "(Earlier turns of this run, from the journal:)\n"
                 + ("\n".join(lines[-60:]) or "(no steps)")
                 + (f"\n{run.get('note')}" if run.get("note") else "")}]

    async def _run_turn(self, run_id: str, st: _RunState, text: str) -> None:
        turn = 0  # 0 = the turn number itself could not be taken
        mark = len(st.history)  # where this turn's history begins
        try:
            try:
                turn = await asyncio.to_thread(wr.next_turn, run_id)
                st.history.append({"role": "user", "content": text})
                outcome, note = await self._loop(run_id, st, turn)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — any crash is a hard failure
                logger.error("world-dev %s turn %s crashed: %s", run_id, turn, e,
                             exc_info=True)
                outcome, note = "fail", f"internal error: {e}"
            try:
                async with st.lock:
                    if outcome == "final":
                        await asyncio.to_thread(wr.set_status, run_id,
                                                "awaiting_review", note)
                        self._set_outcome(run_id, turn, "kept", "")
                        status_ev = {"type": "status", "status": "awaiting_review",
                                     "note": note}
                    elif outcome == "budget":
                        status_ev = await self._cut_by_budget(run_id, st, turn, note)
                    else:
                        status_ev = await self._fail(run_id, st, turn, note, mark)
                    # After the turn's undo (a failed turn), before the status
                    # event: release the deferral (no replay), then queue the
                    # media of the run's elements when the run is back in
                    # review (status_ev None = _fail closed the run).
                    await self._release_media(run_id)
                    if status_ev is not None:
                        await self._schedule_media(run_id, st)
                    st.busy = False
                    if status_ev:
                        await self._emit(st, status_ev)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — never leave it running without a task
                await self._interrupt(run_id, st, f"ending the turn failed: {e}", e)
        except asyncio.CancelledError:
            # Process shutdown: no transition; the next boot marks it.
            raise
        finally:
            # Unconditional: an end path that cleared busy without an emit
            # (_interrupt whose store call failed) must still wake subscribers.
            st.busy = False
            async with st.cond:
                st.cond.notify_all()

    async def _interrupt(self, run_id: str, st: _RunState, note: str,
                         exc: BaseException) -> None:
        """Last resort when the end-of-turn transition raised: a run still
        `running` becomes `interrupted` (accept / discard work from there)."""
        logger.error("world-dev %s: %s", run_id, note, exc_info=exc)
        st.busy = False
        await self._release_media(run_id)
        try:
            run = await asyncio.to_thread(wr.get_run, run_id)
            if run is not None and run["status"] == "running":
                # No media scheduling (F1): an interrupted run renders
                # nothing before Accept.
                await asyncio.to_thread(wr.set_status, run_id, "interrupted", note)
                await self._emit(st, {"type": "status", "status": "interrupted",
                                      "note": note})
        except Exception as e:  # noqa: BLE001 — the boot sweep is the backstop
            logger.error("world-dev %s: marking interrupted failed: %s", run_id, e,
                         exc_info=True)

    async def _cut_by_budget(self, run_id: str, st: _RunState, turn: int,
                             note: str) -> Dict[str, Any]:
        """The turn reached its budget: NO undo — its work stays, the run
        waits for review, and the history says the turn was cut off so a
        follow-up continues where it stopped."""
        logger.info("world-dev %s turn %s cut off: %s", run_id, turn, note)
        st.history.append({"role": "assistant", "content":
                           f"[turn {turn} was cut off: {note}. Every write of that turn "
                           "is kept — continue where it stopped, do not redo it.]"})
        await asyncio.to_thread(wr.set_status, run_id, "awaiting_review", note)
        self._set_outcome(run_id, turn, "cut_by_budget", note)
        return {"type": "status", "status": "awaiting_review", "note": note}

    async def _fail(self, run_id: str, st: _RunState, turn: int, note: str,
                    mark: int) -> Optional[Dict[str, Any]]:
        """Hard failure / Stop: undo the turn. Turn 1 ends terminal; a later
        turn returns to review with its history cut back to its user message
        plus a rollback note. Returns the status event still to emit (None
        when _close emitted it)."""
        logger.warning("world-dev %s turn %s failed: %s", run_id, turn, note)
        self._set_outcome(run_id, turn, "rolled_back", note)
        try:
            report = await asyncio.to_thread(wu.undo, run_id, turn)
        except Exception as e:  # noqa: BLE001
            logger.error("world-dev %s: undo of turn %s failed: %s", run_id, turn, e,
                         exc_info=True)
            report = {"reversed": [], "complete": False,
                      "skipped": [{"seq": 0, "line": "undo", "reason": f"undo failed: {e}"}]}
        run = await asyncio.to_thread(self._get, run_id)
        new_skips = list(report.get("skipped") or [])
        if new_skips:
            await asyncio.to_thread(wr.set_skipped, run_id,
                                    list(run.get("skipped") or []) + new_skips)
        # An occupant record (key "occupant") is informational: its step WAS
        # reversed, the character only has to be placed anew.
        not_reversed = [s for s in new_skips if s.get("reason") != wu.REASON_GONE
                        and "occupant" not in s]
        if turn == 1 or (turn == 0 and int(run.get("turn") or 0) == 0):
            status = "rolled_back" if report.get("complete") else "rollback_incomplete"
            await self._close(run_id, status, note)
            return None
        full = (f"{note} — turn {turn} was rolled back"
                + (f"; {len(not_reversed)} step(s) could not be reversed"
                   if not_reversed else ""))
        # Truthful history: drop what this turn added after its user message
        # (results of writes that are gone) and say so once.
        del st.history[mark + (1 if turn else 0):]
        self._restore_superseded(st)
        hist = (f"[turn {turn} was rolled back: {note} — every write of that turn "
                "was undone")
        if not_reversed:
            hist += (f"; {len(not_reversed)} step(s) could not be reversed: "
                     + "; ".join(f"{s.get('line') or s.get('seq')} ({s.get('reason')})"
                                 for s in not_reversed))
        st.history.append({"role": "assistant", "content": hist + "]"})
        await asyncio.to_thread(wr.set_status, run_id, "awaiting_review", full)
        return {"type": "status", "status": "awaiting_review", "note": full}

    def _messages(self, st: _RunState) -> List[Dict[str, str]]:
        return ([{"role": "system", "content": st.system}]
                + [{"role": m["role"], "content": m["content"]} for m in st.history])

    def _add_result(self, st: _RunState, tool: str, line: str,
                    args: Optional[Dict[str, Any]] = None, ok: bool = True) -> None:
        """Append one tool result to the history and shrink older reads.

        A pinned reference read is never shrunk; only a newer result of the
        same tool with the same args (`_key`) turns its older copy into a
        stub (its text kept in `_orig` for _restore_superseded). Only an ok
        result is pinned — a refused one follows the normal rule. Pinned
        results still count among the newest KEEP_RESULTS; one longer than
        MAX_PINNED_CHARS is stored cut, with a note naming the cut."""
        spec = wt.TOOLS.get(tool)
        pinned = bool(spec is not None and spec.pinned and ok)
        key = tool + json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
        if pinned and len(line) > MAX_PINNED_CHARS:
            line = (line[:MAX_PINNED_CHARS]
                    + f"\n[cut — {MAX_PINNED_CHARS} of {len(line)} characters kept]")
        if pinned:
            for m in st.history:
                if m.get("_pinned") and m.get("_key") == key and not m.get("_superseded"):
                    m["_orig"] = m["content"]
                    m["content"] = f"[result {tool}] (superseded — see the later copy)"
                    m["_superseded"] = True
        st.history.append({"role": "user", "content": f"[result {tool}] {line}",
                           "_result": True, "_tool": tool, "_pinned": pinned, "_key": key,
                           "_read": bool(spec is not None and not spec.write)})
        results = [m for m in st.history if m.get("_result")]
        for m in results[:-KEEP_RESULTS]:
            if m.get("_read") and not m.get("_pinned") and not m.get("_shrunk"):
                m["content"] = f"[result {m['_tool']}] (shrunk — call again if needed)"
                m["_shrunk"] = True

    @staticmethod
    def _restore_superseded(st: _RunState) -> None:
        """After a rollback cut the history: a superseded pinned copy whose
        newer copy was cut away gets its whole text back. The history is
        walked newest first, so in a chain of copies the NEWEST surviving
        one is restored and the older ones stay stubs."""
        live = {m.get("_key") for m in st.history
                if m.get("_pinned") and not m.get("_superseded")}
        for m in reversed(st.history):
            if m.get("_superseded") and m.get("_key") not in live:
                m["content"] = m.pop("_orig", m["content"])
                m["_superseded"] = False
                live.add(m.get("_key"))

    async def _call_llm(self, run_id: str, st: _RunState, pattern) -> str:
        """One streamed LLM call; returns the reply up to the end of its first
        tool call (the rest is never read). Counts usage with the text
        estimate (llm_cost.estimate_cost, ~4 characters a token) for EVERY
        call: the provider's usage report is the last chunk, which a reply
        cut at its tool call never reaches, so it is not used at all — one
        measure for the whole budget. Each next chunk races the stop event."""
        from app.core.llm_cost import estimate_cost
        st.last_finish = None
        messages = self._messages(st)
        reply, shown = "", 0
        task_id = await _chat_active(st.llm_instance)
        try:
            stream = st.llm.astream(messages)
            it = stream.__aiter__()
            stop_wait = asyncio.ensure_future(st.stop_ev.wait())
            nxt: Optional[asyncio.Future] = None
            try:
                while True:
                    if st.stop:
                        raise _Stopped()
                    nxt = asyncio.ensure_future(it.__anext__())
                    await asyncio.wait({nxt, stop_wait},
                                       return_when=asyncio.FIRST_COMPLETED)
                    if not nxt.done():
                        nxt.cancel()
                        await asyncio.wait({nxt})
                        raise _Stopped()
                    try:
                        chunk = nxt.result()
                    except StopAsyncIteration:
                        break
                    if st.stop:
                        raise _Stopped()
                    finish = getattr(chunk, "finish_reason", None)
                    if finish:
                        st.last_finish = finish
                    if not getattr(chunk, "content", None):
                        continue
                    reply += chunk.content
                    m = pattern.search(reply)
                    if m:
                        reply = reply[:m.end()]
                    cut = _display_cut(reply)
                    if cut > shown:
                        await self._emit(st, {"type": "text", "text": reply[shown:cut]})
                        shown = cut
                    if m:
                        break
            finally:
                stop_wait.cancel()
                if nxt is not None and not nxt.done():
                    nxt.cancel()
                    await asyncio.wait({nxt})
                aclose = getattr(stream, "aclose", None)
                if aclose is not None:
                    try:
                        await aclose()
                    except Exception:  # noqa: BLE001
                        pass
        finally:
            _chat_done(task_id)
        if shown < len(reply) and not pattern.search(reply) and "<tool" not in reply:
            await self._emit(st, {"type": "text", "text": reply[shown:]})
        t_in, t_out, cost = estimate_cost(
            "\n".join(m["content"] for m in messages), reply, st.pricing)
        await asyncio.to_thread(wr.add_usage, run_id, t_in, t_out, cost)
        run = await asyncio.to_thread(self._get, run_id)
        await self._emit(st, {"type": "usage", **self._usage(run_id, run, st.base)})
        return reply

    def _usage(self, run_id: str, run: Dict[str, Any],
               base: Dict[str, int]) -> Dict[str, Any]:
        """Run totals plus this turn's counters (remembered for the detail)."""
        turn = {"turn": int(base.get("turn") or 0),
                "steps": int(run["steps"] or 0) - int(base.get("steps") or 0),
                "tokens": _tokens(run) - int(base.get("tokens") or 0)}
        self._turn_usage[run_id] = turn
        return {"tokens_in": run["tokens_in"], "tokens_out": run["tokens_out"],
                "cost": run["cost_total"], "steps": run["steps"],
                "max_steps": run["max_steps"],
                "max_tokens_total": run["max_tokens_total"],
                "turn": turn["turn"], "turn_steps": turn["steps"],
                "turn_tokens": turn["tokens"]}

    @staticmethod
    def _over_budget(run: Dict[str, Any], base: Dict[str, int],
                     steps_too: bool) -> Optional[Tuple[str, int, int]]:
        """(kind, used, budget) when THIS TURN has used up its tokens (or,
        with `steps_too`, its tool calls), else None."""
        used = _tokens(run) - int(base.get("tokens") or 0)
        if used >= int(run["max_tokens_total"] or 0):
            return "tokens", used, int(run["max_tokens_total"] or 0)
        steps = int(run["steps"] or 0) - int(base.get("steps") or 0)
        if steps_too and steps >= int(run["max_steps"] or 0):
            return "steps", steps, int(run["max_steps"] or 0)
        return None

    async def _loop(self, run_id: str, st: _RunState, turn: int) -> Tuple[str, str]:
        """("final", reply), ("budget", note) or ("fail", note). A budget hit
        in turn 1 before its first tool call is a failure: nothing to keep.
        Every reply that asks for a tool is counted once (`wr.count_call`)
        after the budget check and before the call runs or is refused."""
        pattern = _tag_pattern()
        ctx = wt.ToolCtx(run_id=run_id, turn=turn)
        bad = 0
        run = await asyncio.to_thread(self._get, run_id)
        base = st.base = {"turn": turn, "steps": int(run["steps"] or 0),
                          "tokens": _tokens(run)}
        self._turn_usage[run_id] = {"turn": turn, "steps": 0, "tokens": 0}

        def budget(hit: Tuple[str, int, int]) -> Tuple[str, str]:
            kind, used, limit = hit
            fmt = _k if int(limit) >= 1000 else str
            first = turn == 1 and int(run["steps"] or 0) == base["steps"]
            if kind == "tokens":
                if first:
                    return "fail", ("token budget exhausted before the first tool call "
                                    f"({fmt(used)} of {fmt(limit)} tokens)")
                what = f"tokens: {fmt(used)} of {fmt(limit)}"
            else:
                if first:
                    return "fail", ("tool-call budget exhausted before the first tool "
                                    f"call ({used} of {limit} tool calls)")
                what = f"tool calls: {used} of {limit}"
            return "budget", (f"{BUDGET_NOTE_PREFIX}{what} this turn) "
                              "— the turn's work is kept; send a follow-up to continue")

        while True:
            if st.stop:
                return "fail", "stopped by the admin"
            run = await asyncio.to_thread(self._get, run_id)
            over = self._over_budget(run, base, steps_too=False)
            if over:
                return budget(over)
            try:
                reply = await self._call_llm(run_id, st, pattern)
            except _Stopped:
                return "fail", "stopped by the admin"
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — provider error
                return "fail", f"LLM error: {e}"
            run = await asyncio.to_thread(self._get, run_id)
            m = pattern.search(reply)
            if m is None and "<tool" not in reply:
                if turn == 1 and int(run["steps"] or 0) == 0:
                    return "fail", ("model made no tool call — is it tool-capable? "
                                    "Pick another model.")
                st.history.append({"role": "assistant", "content": reply})
                return "final", reply.strip()
            # Only a reply that asks for more work is held to the budgets
            # after the call: a final reply has finished the turn (the check
            # at the top of the loop blocks any further call anyway). The
            # reply that asked is NOT kept in the history: its tool never ran.
            over = self._over_budget(run, base, steps_too=True)
            if over:
                return budget(over)
            # One model tool call, counted once whatever follows: executed,
            # refused by the tool, unparseable or unclosed.
            await asyncio.to_thread(wr.count_call, run_id)
            # Tell the panel at once: its per-turn tool-call counter would
            # otherwise lag one LLM call behind (the budget reads the row).
            counted = await asyncio.to_thread(self._get, run_id)
            await self._emit(st, {"type": "usage", **self._usage(run_id, counted, base)})
            notes: List[str] = []
            if m is None:
                # A tool tag that never closed: run it if the text right after
                # the opening tag starts with a complete JSON object, else refuse.
                opened = _TOOL_OPEN.search(reply)
                name = opened.group(1) if opened else "tool"
                st.history.append({"role": "assistant", "content": reply})
                args, line = None, (f'error: tool call not closed — write <tool name="{name}">'
                                    '{...}</tool>')
                if opened is not None:
                    gt = reply.find(">", opened.end())
                    tail = reply[gt + 1:].lstrip() if gt >= 0 else ""
                    if tail:
                        try:
                            decoded, _ = json.JSONDecoder().raw_decode(tail)
                        except json.JSONDecodeError:
                            decoded = None
                        if isinstance(decoded, dict):
                            args = decoded
                            notes.append(UNCLOSED_NOTE)
                if not isinstance(args, dict) and st.last_finish == "length":
                    line = CUT_OFF_LINE.format(n=len(reply))
            else:
                name, body = m.group(1), m.group(2).strip()
                st.history.append({"role": "assistant", "content": reply})
                line = BAD_BODY_LINE
                try:
                    args = json.loads(body) if body else {}
                except json.JSONDecodeError as e:
                    repaired = _repair_closers(body)
                    if repaired is not None:
                        args = json.loads(repaired)
                        notes.append(REPAIR_NOTE)
                    else:
                        args = None
                        line = _bad_json_line(e, body)
                except ValueError:
                    args = None
                else:
                    if not isinstance(args, dict):
                        line = f"{BAD_BODY_LINE} (got {type(args).__name__})"
            if not isinstance(args, dict):
                bad += 1
                seq = await asyncio.to_thread(self._journal_refused, ctx, name,
                                              body if m else reply, line)
                await self._emit(st, {"type": "step", "tool": name, "ok": False,
                                      "line": line, "kind": "refused", "seq": seq})
                self._add_result(st, name, line, args if isinstance(args, dict) else None,
                                 ok=False)
                if bad >= MAX_BAD_CALLS:
                    return "fail", (f"{MAX_BAD_CALLS} tool calls in a row had a body that is "
                                    "not a JSON object")
                continue
            bad = 0
            try:
                res = await asyncio.to_thread(wt.run_tool, ctx, name, args)
            except Exception as e:  # noqa: BLE001 — a non-refusal is a hard failure
                logger.error("world-dev %s: tool %s raised: %s", run_id, name, e,
                             exc_info=True)
                spec = wt.TOOLS.get(name)
                await self._emit(st, {"type": "step", "tool": name, "ok": False,
                                      "line": f"failed: {e}",
                                      "kind": "write" if spec and spec.write else "read"})
                return "fail", f"tool {name} failed: {e}"
            result_line = "\n".join([res.line, *notes]) if notes else res.line
            await self._emit(st, {"type": "step", "tool": name, "ok": res.ok,
                                  "line": result_line, "wrote": res.wrote, "seq": res.seq})
            self._add_result(st, name, result_line, args, ok=res.ok)
            if st.stop:
                return "fail", "stopped by the admin"

    @staticmethod
    def _journal_refused(ctx: "wt.ToolCtx", tool: str, raw: str, line: str) -> int:
        seq = wr.begin(ctx.run_id, ctx.turn, "refused", tool, {"_raw": raw})
        wr.complete(ctx.run_id, seq, None, line)
        return seq


_MANAGER: Optional[RunManager] = None


def get_run_manager() -> RunManager:
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = RunManager()
    return _MANAGER


def mark_interrupted_on_boot() -> Optional[str]:
    """Server lifespan hook (first statement): see RunManager."""
    return get_run_manager().mark_interrupted_on_boot()
