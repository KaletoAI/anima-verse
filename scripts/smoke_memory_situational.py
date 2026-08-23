#!/usr/bin/env python3
"""Checks the situational memory block: selection, cache, rendering, placement.

Usage:
    ./.venv/bin/python scripts/smoke_memory_situational.py

Runs without the server, without a world DB and without an embedding backend:
the selection takes its embedding function, its vector cache and its
candidates as arguments, so all three are stubbed here. The stub returns
pre-declared 2-D unit vectors, which makes every expected cosine value a hand
calculation and not a recording of current output.

THE VECTORS AND WHAT THEY IMPLY

The query sits at (1, 0). For a unit vector (x, y) the cosine similarity
against it is simply x — so the x-coordinate below IS the expected score:

    m01 fact "Bogen"        (1.00, 0.00)  -> 1.00   above 0.75, rank 1
    m02 commitment          (0.96, 0.28)  -> 0.96   above 0.75, rank 2   (7-24-25)
    m03 fact                (0.80, 0.60)  -> 0.80   above 0.75, rank 3   (3-4-5)
    m04 fact                (0.75, 0.6614)-> 0.75   exactly at the threshold
    m05..m12                (0.60, 0.80) and below -> under the threshold

The off-topic message sits at (-1, 0), the opposite direction: its best match
among the twelve is m12 at 0.20 — nothing comes near the threshold.

With max_entries = 3 (the shipped default) the block is m01, m02, m03 — m04
is above the bar but loses the third seat to a better match, m05..m12 never
qualify. That is the whole ranking rule: similarity, nothing else.

WHY these expectations (derived from the decisions in
plan-memory-facts-and-commitments.md, section "Situativer Memory-Block"):

1. A fact about the thing being asked about must come FIRST. That is the
   entire point of the feature — the system prompt already ranks by
   importance and age, and by that ranking the Bogen fact never surfaced.

2. Below the threshold there is NO block. Not an empty header, not a "no
   relevant memories" line: nothing is appended to the user turn at all.
   An always-present block would train the model to expect one.

3. A missing embedding backend is silence, not a failure. `embed` returning
   None is the normal state of a world without fastembed and without a routed
   embedding model — same rule as the pose catalog.

4. The cache must actually cache. The second lookup for the same character
   may embed the MESSAGE only; embedding twelve memory rows on every single
   chat turn is what the `memory_embeddings` table exists to prevent. The
   stub counts its calls: 13 on the first lookup, 1 on the second.

5. The batch cap holds. A store larger than the per-turn budget fills over
   several turns instead of embedding everything at once on the first
   message.

6. The template renders under StrictUndefined with EXACTLY the kwargs of its
   production call site (`memory_situational.render_block`), and a commitment
   carries its due state the way the thought block writes it.

7. The block lands in the USER turn. `compose_messages` is the function the
   provider list is built with, so this is checked at the consumer: the block
   must be in the last message, that message must have role "user", and the
   system content must be byte-identical to what it was without the block —
   the cached prefix is the reason the whole feature is not in the system
   prompt.

Exit code 0 = all checks passed, 1 = at least one failed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import memory_situational as ms  # noqa: E402
from app.core.streaming import compose_messages  # noqa: E402
from app.core.prompt_templates import render  # noqa: E402

failures = []


def check(name, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name}"
          f"{'' if ok else f'  — got {got!r}, want {want!r}'}")
    if not ok:
        failures.append(name)


def close(name, got, want, tol=1e-4):
    ok = abs(got - want) <= tol
    print(f"  {'PASS' if ok else 'FAIL'}  {name}"
          f"{'' if ok else f'  — got {got!r}, want {want!r}'}")
    if not ok:
        failures.append(name)


# ── the synthetic world ────────────────────────────────────────────────────

QUERY = "Wo ist eigentlich mein Bogen?"
OFF_TOPIC = "Wie war das Wetter gestern?"

# text -> unit vector. The query is the reference direction (1, 0).
VECTORS = {
    QUERY: (1.0, 0.0),
    # The opposite direction: its best match among the twelve is m12 at 0.20,
    # so nothing comes close to the threshold.
    OFF_TOPIC: (-1.0, 0.0),
}

MEMORIES = [
    # id, type, content, vector, timestamp
    (1, "semantic", "Der Bogen des Jaegers steht in der Kammer", (1.00, 0.00), "2026-08-01T10:00:00"),
    (2, "commitment", "Ich bringe dir deinen Bogen zurueck", (0.96, 0.28), "2026-08-02T10:00:00"),
    (3, "semantic", "Pfeile lagern neben der Truhe", (0.80, 0.60), "2026-08-03T10:00:00"),
    (4, "semantic", "Die Sehne muss neu gewachst werden", (0.75, 0.6614), "2026-08-04T10:00:00"),
    (5, "semantic", "Das Brot wird morgens gebacken", (0.60, 0.80), "2026-08-05T10:00:00"),
    (6, "semantic", "Der Fluss fuehrt Hochwasser", (0.50, 0.866), "2026-08-06T10:00:00"),
    (7, "commitment", "Ich helfe beim Dach", (0.40, 0.917), "2026-08-07T10:00:00"),
    (8, "semantic", "Die Muehle steht still", (0.30, 0.954), "2026-08-08T10:00:00"),
    (9, "semantic", "Der Markt ist am Wochenende", (0.20, 0.980), "2026-08-09T10:00:00"),
    (10, "semantic", "Das Pferd heisst Nebel", (0.10, 0.995), "2026-08-10T10:00:00"),
    (11, "semantic", "Der Schmied hat einen neuen Lehrling", (0.00, 1.00), "2026-08-11T10:00:00"),
    (12, "semantic", "Im Keller riecht es feucht", (-0.20, 0.980), "2026-08-12T10:00:00"),
]


def candidates():
    out = []
    for mem_id, mtype, content, vec, ts in MEMORIES:
        VECTORS[content] = vec
        out.append({"id": mem_id, "memory_type": mtype, "content": content,
                    "timestamp": ts, "game_ts": "", "tags": []})
    # load_candidates hands them over newest first (load_memories: ts DESC).
    return list(reversed(out))


class CountingEmbed:
    """The embedding entry point, stubbed. Counts every call."""

    def __init__(self, answers=VECTORS, always_none=False):
        self.answers = answers
        self.always_none = always_none
        self.calls = 0

    def __call__(self, text):
        self.calls += 1
        if self.always_none:
            return None
        vec = self.answers.get(text)
        return list(vec) if vec else None


class DictCache:
    """The vector cache, stubbed — same two methods as DbVectorCache."""

    def __init__(self):
        self.store = {}
        self.writes = 0

    def get_many(self, memory_ids, model_id):
        return {i: v for (i, m), v in self.store.items()
                if m == model_id and i in set(memory_ids)}

    def put_many(self, model_id, vectors):
        self.writes += 1
        for memory_id, vec in vectors.items():
            self.store[(memory_id, model_id)] = list(vec)


MODEL = "internal:test-model"


def run(message, cache, embed, max_results=3, threshold=0.75, budget=64):
    return ms.select_situational(
        message, candidates(), cache, embed=embed, model_id=MODEL,
        max_results=max_results, threshold=threshold, embed_budget=budget)


print("1) the fact about the thing being asked about ranks first")
cache = DictCache()
embed = CountingEmbed()
picked = run(QUERY, cache, embed)
check("three entries attached", len(picked), 3)
check("rank 1 is the Bogen fact", picked[0]["id"] if picked else None, 1)
check("rank 2 is the commitment", picked[1]["id"] if len(picked) > 1 else None, 2)
check("rank 3 is the third-best match", picked[2]["id"] if len(picked) > 2 else None, 3)
if picked:
    close("rank 1 score is the x coordinate", picked[0]["score"], 1.00)
    close("rank 2 score is the x coordinate", picked[1]["score"], 0.96)
    close("rank 3 score is the x coordinate", picked[2]["score"], 0.80)
check("the at-threshold entry lost the last seat, not the threshold",
      [p["id"] for p in picked].count(4), 0)

print("2) below the threshold there is no block at all")
picked_off = run(OFF_TOPIC, DictCache(), CountingEmbed())
check("nothing selected", picked_off, [])
check("and nothing rendered", ms.render_block(picked_off), "")

print("3) no embedding backend = silence, not an exception")
none_embed = CountingEmbed(always_none=True)
check("empty selection", run(QUERY, DictCache(), none_embed), [])
check("it asked exactly once (the message) and gave up",
      none_embed.calls, 1)
check("an unembeddable message is not an error",
      run("", DictCache(), CountingEmbed()), [])

print("4) the cache spares the memory rows on the next turn")
cache2 = DictCache()
first = CountingEmbed()
run(QUERY, cache2, first)
check("first lookup: 1 message + 12 memories", first.calls, 13)
check("twelve vectors persisted", len(cache2.store), 12)
check("in ONE batched write, not twelve", cache2.writes, 1)
second = CountingEmbed()
run(QUERY, cache2, second)
check("second lookup: the message only", second.calls, 1)
third = CountingEmbed()
run(QUERY, cache2, third, threshold=0.75)
check("a third lookup stays at one", third.calls, 1)
check("a model change invalidates every vector",
      len(cache2.get_many([m[0] for m in MEMORIES], "internal:other")), 0)

print("5) the per-turn embedding budget holds")
cache3 = DictCache()
capped = CountingEmbed()
run(QUERY, cache3, capped, budget=2)
check("1 message + 2 memories", capped.calls, 3)
check("only two vectors cached", len(cache3.store), 2)

print("6) a tie falls to the more recent memory")
tied = [
    {"id": 20, "memory_type": "semantic", "content": "alt", "timestamp": "2026-08-01T00:00:00", "tags": []},
    {"id": 21, "memory_type": "semantic", "content": "neu", "timestamp": "2026-08-09T00:00:00", "tags": []},
]
tie_vecs = {QUERY: (1.0, 0.0), "alt": (1.0, 0.0), "neu": (1.0, 0.0)}
tie_pick = ms.select_situational(
    QUERY, tied, DictCache(), embed=CountingEmbed(tie_vecs), model_id=MODEL,
    max_results=2, threshold=0.75)
check("identical scores", [round(p["score"], 6) for p in tie_pick], [1.0, 1.0])
check("newer first", [p["id"] for p in tie_pick], [21, 20])

print("7) the template renders with exactly the call-site kwargs")
# render_block calls render(TEMPLATE, memories=[{content, due, is_commitment}]).
block = render(ms.TEMPLATE, memories=[
    {"content": "Der Bogen steht in der Kammer", "due": "", "is_commitment": False},
    {"content": "Ich bringe dir deinen Bogen zurueck", "due": "in 20 min", "is_commitment": True},
])
check("the fact is in the block", "Der Bogen steht in der Kammer" in block, True)
check("the commitment is marked as a promise",
      "You promised: Ich bringe dir deinen Bogen zurueck" in block, True)
check("the due state is rendered like the thought block",
      "(due: in 20 min)" in block, True)
check("a plain fact carries no due suffix",
      "Der Bogen steht in der Kammer (due" in block, False)
check("the header names it as memory, not as user speech",
      block.splitlines()[0].startswith("[You remember"), True)

print("8) render_block is the production path and skips empties")
rendered = ms.render_block(picked)
check("all three contents present",
      all(p["content"] in rendered for p in picked), True)
check("no entries, no block", ms.render_block([]), "")
check("only blank contents, no block",
      ms.render_block([{"content": "  ", "memory_type": "semantic"}]), "")

print("9) the block lands in the USER turn, never in the system prompt")
SYSTEM = "You are Alpha. Never break character."
HISTORY = [{"role": "user", "content": "Hallo"},
           {"role": "assistant", "content": "Hallo!"}]
plain = compose_messages(SYSTEM, HISTORY, QUERY)
withblock = compose_messages(SYSTEM, HISTORY, QUERY, rendered)
check("system prompt is byte-identical with and without the block",
      withblock[0]["content"], plain[0]["content"])
check("nothing of the block leaked into the system prompt",
      "You remember" in withblock[0]["content"], False)
check("history is untouched", withblock[1:-1], plain[1:-1])
check("the last message is the user turn", withblock[-1]["role"], "user")
check("the block is in the user turn",
      rendered in withblock[-1]["content"], True)
check("the user's own words come first",
      withblock[-1]["content"].startswith(QUERY), True)
check("no suffix = the old message list", plain[-1]["content"], QUERY)
check("message count unchanged", len(withblock), len(plain))

print("10) only facts and open commitments are candidates")
from app.models import memory as mem_mod  # noqa: E402
store = [
    {"id": 1, "memory_type": "semantic", "content": "a fact", "tags": []},
    {"id": 2, "memory_type": "commitment", "content": "an open promise", "tags": []},
    {"id": 3, "memory_type": "commitment", "content": "a kept promise", "tags": ["completed"]},
    {"id": 4, "memory_type": "episodic", "content": "something that happened", "tags": []},
    {"id": 5, "memory_type": "semantic", "content": "   ", "tags": []},
]
_orig_load = mem_mod.load_memories
mem_mod.load_memories = lambda name: store
try:
    ids = [c["id"] for c in ms.load_candidates("Alpha")]
finally:
    mem_mod.load_memories = _orig_load
check("fact and open commitment only", ids, [1, 2])

print("11) the vector blob survives the round trip")
vec = [0.5, -0.25, 0.125]
back = ms.unpack_vector(ms.pack_vector(vec))
check("same length", len(back), 3)
close("value 0 preserved", back[0], 0.5)
close("value 1 preserved", back[1], -0.25)
close("value 2 preserved", back[2], 0.125)
check("a truncated blob yields nothing", ms.unpack_vector(b"\x00\x00\x00"), [])

print("12) the code defaults match the admin schema defaults")
from app.core.config_schema import SECTIONS  # noqa: E402
_f = SECTIONS["memory"]["fields"]
check("enabled", _f["situational_enabled"]["default"], ms.DEFAULT_ENABLED)
check("max entries", _f["situational_max_entries"]["default"], ms.DEFAULT_MAX_ENTRIES)
check("threshold", _f["situational_min_similarity"]["default"], ms.DEFAULT_MIN_SIMILARITY)
check("an unsaved config reads the schema default", ms.max_entries(), 3)
close("threshold too", ms.min_similarity(), 0.75)
check("and the feature is on", ms.is_enabled(), True)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
    sys.exit(1)
print("all checks passed")
