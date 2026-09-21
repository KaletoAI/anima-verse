#!/usr/bin/env python3
"""Smoke run: the per-chunk tool detection in the stream must stay EXACT and
must stop scaling with the answer length (LLM-5).

Usage:
    ./.venv/bin/python scripts/smoke_stream_tool_scan.py

Runs WITHOUT the server, without a world DB and without a network — it only
imports ``app.core.tool_formats`` and calls one pure function.

The finding
---------------------------------------------------------------------------
``StreamingAgent._stream_*`` calls ``find_stream_tool_call`` once per chunk,
with the WHOLE accumulated answer. The function ran up to three format
regexes plus a fallback over that text, so chunk n re-scanned the n-1 chunks
before it: quadratic, and on the event loop, where it delays every other SSE
stream. Measured on this machine with the pre-fix code (12 tools, German RP
prose, 4 characters per chunk): 17 ms / 113 ms / 434 ms for 1500 / 4000 /
8000 characters.

The fix is a cheap gate: every ``stream_pattern`` of every format AND the
known-tool fallback need one of a handful of literal markers (``<tool``,
``for:``, ``für:``, ``fuer:`` — the formats carry them as ``stream_markers``),
so a text containing none of them cannot contain a tool call. The C-level
substring test decides that in a fraction of the time, and it can only skip
work that could not have matched.

What is checked, and why these are the expected values
---------------------------------------------------------------------------
1. EQUIVALENCE, derived from the fix being a pure prefilter: for every text
   below and for EVERY prefix of it — i.e. every possible position a stream
   could be split at — the new function must return exactly what the OLD one
   returns: both ``None``, or the same span and the same groups. The old
   implementation is kept verbatim in ``_old_find_stream_tool_call`` below as
   the oracle; it is not imported, so a later edit of the real function
   cannot quietly move the target.
2. CHUNKED FEEDING: replaying each text in chunks of 1, 3, 7 and 13
   characters must report the tool call at the same accumulated length as the
   oracle does, with the same span — a marker split across a chunk boundary
   must not be lost (the gate looks at the whole accumulated text, so it
   cannot be).
3. COST: the new function must need well under a tenth of the old one on the
   8000-character case. The table is printed; the assertion is the 10x, which
   is far below the ~87x measured, so a slower machine does not turn this
   into a flaky check.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# Throwaway storage before the first app import (repo rule) — nothing here
# opens a DB, but the lint is about the import, not about the intent.
_TMP = Path(tempfile.mkdtemp(prefix="smoke_stream_tool_"))
os.environ["ANIMATION_CLIPS_DIR"] = str(_TMP / "clips")
from app.core import paths  # noqa: E402

paths.init(_TMP)

from app.core.tool_formats import (TOOL_FORMATS,  # noqa: E402
                                   find_stream_tool_call, get_format)

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}{(' — ' + detail) if detail else ''}")
        failures.append(label)


def _old_find_stream_tool_call(format_name: str, text: str, known_tools=None):
    """The implementation before the fix — the oracle, kept verbatim.

    Configured format first, then every other format, then the universal
    fallback over the known tool names.
    """
    fmt = get_format(format_name)
    match = re.search(fmt["stream_pattern"], text, re.IGNORECASE)
    if match:
        return match
    for other_name, other_fmt in TOOL_FORMATS.items():
        if other_name == format_name:
            continue
        match = re.search(other_fmt["stream_pattern"], text, re.IGNORECASE)
        if match:
            return match
    if known_tools:
        names = "|".join(re.escape(n) for n in known_tools.keys())
        fallback = (rf"(?:[Nn]utze|[Uu]se)\s+({names})\s+"
                    rf"(?:f(?:ü|ue)r|for):\s*(.*?)(?:\n|$)")
        match = re.search(fallback, text, re.IGNORECASE)
        if match:
            return match
    return None


TOOLS = {name: object() for name in (
    "TakePhoto", "TalkTo", "SetLocation", "WebSearch", "SearchKnowledge",
    "ChangeOutfit", "Announce", "SendMessage", "CastSpell", "Remember",
    "InviteToParty", "LeaveParty")}

_PROSE = ("Sie lehnte sich zurueck und sah ihn lange an, bevor sie antwortete. "
          "Das Licht der Lampe fiel warm auf den Tisch zwischen ihnen. ")

# Texts chosen so every branch of the function is exercised: no call at all,
# each of the three formats, the known-tool fallback, a marker that never
# completes, a false-positive marker in prose, and mixed casing.
TEXTS = {
    "no call at all": _PROSE * 3,
    "tag format": _PROSE + '<tool name="TakePhoto">a photo of the room</tool>' + _PROSE,
    "tag, uppercase attribute": _PROSE + '<TOOL NAME="TalkTo">hello</TOOL>',
    "english natural": _PROSE + "Use TakePhoto for: a photo of the room\n" + _PROSE,
    "german natural": _PROSE + "Ich nutze TakePhoto für: ein Foto\n" + _PROSE,
    "german natural, ue spelling": _PROSE + "Ich nutze TakePhoto fuer: ein Foto\n",
    "fallback on a known tool": _PROSE + "Also nutze SearchKnowledge für: alte Karten\n",
    "opening marker that never closes": _PROSE + '<tool name="TakePhoto">and then',
    "marker-like prose, no call": _PROSE + "Sie sorgte für: Ruhe im Raum. " + _PROSE,
    "call right at the start": '<tool name="Announce">now</tool>' + _PROSE,
    "two calls, the first one counts": (
        _PROSE + '<tool name="TakePhoto">one</tool> und <tool name="TalkTo">two</tool>'),
}


def _same(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return (a.span() == b.span()) and (a.groups() == b.groups())


def part_equivalence() -> None:
    print("\n1. Every prefix of every text gives the SAME result as before")
    for fmt_name in ("tag", "natural_en", "natural_de"):
        bad = []
        for label, text in TEXTS.items():
            for i in range(len(text) + 1):
                prefix = text[:i]
                if not _same(find_stream_tool_call(fmt_name, prefix, TOOLS),
                             _old_find_stream_tool_call(fmt_name, prefix, TOOLS)):
                    bad.append(f"{label}@{i}")
                    break
        total = sum(len(t) + 1 for t in TEXTS.values())
        check(f"format {fmt_name}: {total} prefixes identical to the oracle",
              not bad, ", ".join(bad[:5]))

    # Without known_tools the fallback branch is off — the gate must not
    # change that either.
    bad = [label for label, text in TEXTS.items()
           if not _same(find_stream_tool_call("tag", text, None),
                        _old_find_stream_tool_call("tag", text, None))]
    check("known_tools=None behaves as before", not bad, ", ".join(bad))


def part_chunked() -> None:
    print("\n2. Chunked replay finds the call at the same position")
    for size in (1, 3, 7, 13):
        bad = []
        for label, text in TEXTS.items():
            want_at = None
            want_span = None
            got_at = None
            got_span = None
            acc = ""
            for i in range(0, len(text), size):
                acc += text[i:i + size]
                if got_at is None:
                    m = find_stream_tool_call("tag", acc, TOOLS)
                    if m:
                        got_at, got_span = len(acc), m.span()
                if want_at is None:
                    m = _old_find_stream_tool_call("tag", acc, TOOLS)
                    if m:
                        want_at, want_span = len(acc), m.span()
                if got_at is not None and want_at is not None:
                    break
            if (got_at, got_span) != (want_at, want_span):
                bad.append(f"{label}: {got_at}/{got_span} != {want_at}/{want_span}")
        check(f"chunk size {size}: same detection point for all "
              f"{len(TEXTS)} texts", not bad, "; ".join(bad[:3]))


def part_cost() -> None:
    print("\n3. Cost per streamed answer (4 characters per chunk, 12 tools)")
    long_prose = (_PROSE * 200)
    worst = 0.0
    for n in (1500, 4000, 8000):
        text = long_prose[:n]
        times = {}
        for label, fn in (("old", _old_find_stream_tool_call),
                          ("new", find_stream_tool_call)):
            t0 = time.perf_counter()
            for i in range(4, n + 1, 4):
                fn("tag", text[:i], TOOLS)
            times[label] = time.perf_counter() - t0
        print(f"       {n:5d} chars, {n // 4:4d} chunks: "
              f"old {times['old'] * 1000:7.1f} ms   "
              f"new {times['new'] * 1000:7.1f} ms   "
              f"({times['old'] / max(times['new'], 1e-9):5.1f}x)")
        if n == 8000:
            worst = times["new"] / max(times["old"], 1e-9)
    check("8000-character answer costs less than a tenth of before",
          worst < 0.1, f"ratio {worst:.3f}")


def part_markers() -> None:
    print("\n4. Every format declares the marker its pattern needs")
    for name, fmt in TOOL_FORMATS.items():
        markers = fmt.get("stream_markers")
        check(f"format {name} has non-empty stream_markers",
              bool(markers) and all(m == m.casefold() for m in markers),
              repr(markers))


def main() -> int:
    print("smoke_stream_tool_scan")
    try:
        part_equivalence()
        part_chunked()
        part_cost()
        part_markers()
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)

    print()
    if failures:
        print(f"FAILED ({len(failures)}):")
        for f in failures:
            print(f"  {f}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
