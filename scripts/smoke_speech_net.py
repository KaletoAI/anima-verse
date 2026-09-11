"""Smoke check: B-lite speech net — the filter drops false positives and keeps real speech.

Usage:
    ./.venv/bin/python scripts/smoke_speech_net.py

Runs without a server and without a world DB.

Expected values, derived by hand from the filter spec
(plan-log-befunde-2026-09-11 § 3.8) and from the 2026-09-11 log analysis, in
which 40 of 40 B-lite warnings were false positives (10x a JSON `detail`
value out of the activity verb, 14x written text / caption, 11x a remembered
quote or inner voice, 4x another character's line, 0x real loss).

The base rule is unchanged: a segment counts only when it is at least 2
characters long AND (contains a space OR ends in sentence punctuation) — so
name/emphasis quotes never were candidates.

Three deterministic exclusions on top, checked one class per case:

[1] JSON context — a quote that sits inside a `{…}` of the same line, or right
    behind a `"<key>":`. The activity verb's own example produced exactly
    this: only `sketching in a notebook` survives the base rule (the other
    values have no space and no final punctuation), and it is a JSON value.
    Expected: [].
[2] Writing verb in the 90 characters in front of the quote -> written, not
    spoken. Expected: [].
[3] Caption wording in front of the quote -> written. Expected: [].
[4] A third-person speech attribution with a FOREIGN name behind the quote
    -> somebody else's line. Expected: [].
[5] `<Name> hat gesagt:` in front of the quote -> quoted, not spoken now.
    Expected: [].
[6] MANDATORY SURVIVOR — the character's own line with a first-person
    attribution (`sage ich`). `sage` is not in the attribution verb list
    (which has `sagt`/`sagte`), so no rule fires. Expected: the quote.
[7] MANDATORY SURVIVOR — a third-person attribution naming the SPEAKER
    (a model narrating its own character). Name == speaker -> kept.
    Expected: the quote.
[8] A remembered quote is NOT filtered deterministically — no rule separates
    memory from speech, that judgement belongs to the retry prompt.
    Expected: the inner quote survives.
[9] A pronoun attribution (`sagt sie`) counts as a foreign speaker
    (decision E1: thought prose is first person). Expected: [].
[10] Hashtag inside the segment -> social-post caption. Expected: [].
[11] Content-tool delivery, as a pure function: a call whose `caption` field
    carries the quote means the line has a delivery path -> True; the same
    call when the tool is NOT a content tool -> False.
[12] The counters name the rule that dropped each quote (json/written/
     foreign), so the next log analysis can measure the filter.
[13] The template `tasks/speech_retry.md` renders with StrictUndefined: the
     user part lists every quote, the system part carries the syntax shell of
     the tag format, and the appendix pattern is gone — no `respond with
     NONE` from the decision prompt.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core import prompt_templates  # noqa: E402
from app.core.streaming import (  # noqa: E402
    _delivered_by_content_tool,
    _scan_speech_candidates,
    _speech_candidates,
)

CHECKS = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(ok)
    print(f"  {'OK ' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail and not ok else ""))


def case(n: str, text: str, want: list) -> None:
    got = _speech_candidates(text, "Luisa")
    check(n, got == want, f"got={got!r} want={want!r}")


def main() -> int:
    print("Filter cases (speaker = Luisa)")
    case("[1] JSON value out of the activity verb",
         'Ich setze mich. {"pose": "sitting", "detail": "sketching in a notebook"}',
         [])
    case("[2] writing verb in front",
         'Ich schreibe auf den Zettel: „Bin gleich zurück."',
         [])
    case("[3] caption wording in front",
         'Die Caption lautet "Sunset over the bay, finally."',
         [])
    case("[4] foreign name behind the quote",
         '„Komm später wieder", sagt Tom und geht.',
         [])
    case("[5] attribution in front of the quote",
         'Tom hat gesagt: „Ich bin morgen weg."',
         [])
    case("[6] MANDATORY: own line, first person",
         '„Setz dich zu mir", sage ich leise.',
         ["Setz dich zu mir"])
    case("[7] MANDATORY: own name in third person",
         '„Setz dich zu mir", sagt Luisa.',
         ["Setz dich zu mir"])
    case("[8] remembered quote is not filtered here",
         'Ich erinnere mich an ihre Worte: „Geh nie allein."',
         ["Geh nie allein."])
    case("[9] pronoun attribution (E1)",
         '„Komm her", sagt sie und dreht sich weg.',
         [])
    case("[10] hashtag = caption",
         'Der Post: "Selbst im Regen wachsen wir. #Mut #WachseMitUns"',
         [])

    print("[11] content tool as a delivery path")
    calls = [("Post", '{"caption": "Sunset over the bay, finally."}')]
    check("delivered when the tool is a content tool",
          _delivered_by_content_tool("Sunset over the bay, finally.",
                                     calls, {"Post"}) is True)
    check("not delivered when it is not a content tool",
          _delivered_by_content_tool("Sunset over the bay, finally.",
                                     calls, set()) is False)
    check("a different line is not delivered",
          _delivered_by_content_tool("Komm später wieder",
                                     calls, {"Post"}) is False)

    print("[12] drop counters per rule")
    text = ('Ich schreibe: „Bin gleich zurück."\n'
            '{"pose": "sitting", "detail": "sketching in a notebook"}\n'
            '„Komm her", sagt Tom.\n'
            '„Setz dich zu mir", sage ich.')
    quotes, counts = _scan_speech_candidates(text, "Luisa")
    check("one survivor", quotes == ["Setz dich zu mir"], f"got={quotes!r}")
    check("counters json=1 written=1 foreign=1",
          counts == {"json": 1, "written": 1, "foreign": 1}, f"got={counts!r}")

    print("[13] speech_retry template")
    system, user = prompt_templates.render_task(
        "speech_retry",
        character="Luisa",
        quotes=["Setz dich zu mir", "Gute Nacht."],
        present=["Kai"],
        tools=[{"name": "TalkTo", "description": "Speak to someone present."}],
        example='<tool name="TalkTo"><JSON input exactly as the tool '
                'description specifies></tool>')
    check("system non-empty", bool(system.strip()))
    check("user non-empty", bool(user.strip()))
    check("user lists every quote",
          "Setz dich zu mir" in user and "Gute Nacht." in user)
    check("user names the present character", "Kai" in user)
    check("system carries the syntax shell", '<tool name="' in system)
    check("no decision-prompt appendix", "respond with NONE" not in system
          and "respond with NONE" not in user)

    ok = all(CHECKS)
    print(f"\n{'ALL OK' if ok else 'FAILURES'} ({sum(CHECKS)}/{len(CHECKS)} checks)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
