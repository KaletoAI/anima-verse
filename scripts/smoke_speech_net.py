"""Smoke check: B-lite speech net — the filter drops false positives and keeps real speech.

Usage:
    ./.venv/bin/python scripts/smoke_speech_net.py

Runs without a server and without a world DB — the storage directory is a
throwaway temp dir set BEFORE the first ``app`` import, so ``worlds/`` is never
touched.

Expected values, derived by hand from the filter spec
(plan-log-befunde-2026-09-11 § 3.8) and from the 2026-09-11 log analysis, in
which 40 of 40 B-lite warnings were false positives (10x a JSON `detail`
value out of the activity verb, 14x written text / caption, 11x a remembered
quote or inner voice, 4x another character's line, 0x real loss).

The base rule is unchanged: a segment counts only when it is at least 2
characters long AND (contains a space OR ends in sentence punctuation) — so
name/emphasis quotes never were candidates.

Three deterministic exclusions on top, checked one class per case:

[1] JSON context — an unclosed `{` in front of the quote on the same line, or
    a `"<key>":` right before it, or a `:` right behind it. The activity
    verb's own example produced exactly this: only `sketching in a notebook`
    survives the base rule (the other values have no space and no final
    punctuation), and it is a JSON value. Expected: [].
[2] Writing verb in the 60 characters in front of the quote -> written, not
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

[14] MANDATORY SURVIVORS — the risk direction of § 5 („the filter discards
     real speech"). Two failure modes cost real dialogue once and must stay
     covered by a case each:

     (a) A writing STEM inside an everyday NOUN is not a writing verb, and
         neither is a verb form that an everyday NOUN or ADJECTIVE happens to
         share. `Schreibtisch`, `Schreibmaschine`, `Schreibblock`, `Notiz`,
         `Notizen`, `Notizbuch`, `Notizblock`, `Notizheft`, `Notierung`,
         `Tipp`, `Tippfehler`, `Post`, `Postkarte`, `Postbote`, `Posten`,
         `Kritzelei`, `Skizze`, `Skizzierung` and the English `note`,
         `notes`, `notebook`, `type`, `types`, `writing desk`, `writing
         style`, `writer`, `a noted author` are furniture, objects, people
         and properties — none of them says anything about the quote next to
         them. The spec asks for conjugated verb forms, so every one of these
         sentences keeps its dialogue. `Notiz` is the case that slipped
         through the first pass: the singular is as much an object as the
         plural, and the verb is already covered by `notier…`.
         The same holds for the `ge…schrieben` family: `vorgeschrieben`,
         `zugeschrieben`, `eingeschrieben` and `festgeschrieben` are not
         about writing at all, so only the writing prefixes count.
     (b) A first-person pronoun at the start of a sentence is capitalised and
         therefore matches the NAME pattern of rule 3 („Ich sagte:", "I
         said:"). § 3.8 rule 3 exempts `ich`/`I` explicitly — the quote is
         the speaker's own line and survives, in German and in English, in
         front of and behind the quote.

[15] The exclusions must NOT be given up to reach [14]: the same sentences
     with a real conjugated writing verb, and a real foreign name, still
     drop. `Ich notiere mir:`, `Ich kritzele:`, `Ich poste:`, `I wrote:`,
     `She typed:`, `taking notes:` -> []; `Tom sagte:` -> []. The writing
     prefixes of `geschrieben` (`aufgeschrieben`, `vollgeschrieben` — the
     latter straight out of the 2026-09 logs) keep dropping too.

[16] `notes` and `types` are nouns as bare words (`my notes`, `two types`)
     and verbs of a written introduction with a colon behind them
     (`She notes:`, `He types:`). The colon is what decides — both
     directions get a case. `noted` needs no colon (it is only a verb), but
     the attributive `a noted author` / `the noted author` is an adjective
     and keeps its dialogue.

[17] The lookbehind of the writing rule ends at the SENTENCE boundary. A
     character window alone runs across sentence borders, so a writing verb
     of the previous sentence swallowed the next sentence's dialogue
     („Ich schreibe den Brief zu Ende. „Komm her", sage ich." and
     „Ich tippe die Nachricht. „Komm her", sage ich." both lost their line).
     A verb governs a quote only inside the same sentence.

     Sentence end = `.` `!` `?` `…` followed by whitespace or closing the
     lookbehind — punctuation alone, no abbreviation list, no capital-letter
     test. Consequences, all of them checked here:

     (a) The dot of `z.B.` or of a decimal (`3.5`) is followed by a letter or
         a digit, never by whitespace, so it does not cut. The final dot of
         `z.B.`, `usw.` or `Dr.` DOES cut although it ends no sentence — that
         error only shortens the lookbehind, so it can cost a suppression but
         never a line of dialogue, which is the cheap direction of § 5.
     (b) A colon and a comma are NOT sentence ends, on purpose: they bind the
         writing verb to the quote behind them (`Ich notierte: „Milch
         kaufen"`, `Ich schreibe, „Komm her"`) — exactly the case the rule
         must catch. Both keep dropping.
     (c) `!` and `?` end a sentence like `.` does.
     (d) The foreign-speaker rule needs no cut of its own: its BEFORE pattern
         is anchored to the end of the lookbehind and tolerates only
         whitespace and a colon in between, so an attribution of the previous
         sentence cannot reach across. `Tom sagte etwas. „Komm her", sage
         ich.` survives, `Tom sagte: „Komm her."` still drops.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Throwaway storage BEFORE the first app import — the smoke never writes into
# a real world.
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="speech-net-clips-")

from app.core import paths  # noqa: E402
paths.init(Path(tempfile.mkdtemp(prefix="speech-net-storage-")))

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


def survives(label: str, text: str, want_quote: str) -> None:
    """A line that MUST keep its dialogue — the regression direction of § 5."""
    got = _speech_candidates(text, "Luisa")
    check(label, got == [want_quote], f"got={got!r} want=[{want_quote!r}]")


def drops(label: str, text: str) -> None:
    """A line the filter must still discard — the false-alarm suppression."""
    got = _speech_candidates(text, "Luisa")
    check(label, got == [], f"got={got!r} want=[]")


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

    print("[14a] MANDATORY SURVIVORS — a writing stem inside a noun is scenery")
    survives("Schreibtisch",
             'Ich setze mich an den Schreibtisch. „Setz dich zu mir", sage ich.',
             "Setz dich zu mir")
    survives("Notizbuch",
             'Ich klappe mein Notizbuch zu. „Komm, wir gehen", sage ich.',
             "Komm, wir gehen")
    survives("Tipp",
             'Ich gebe ihm einen Tipp. „Nimm den linken Weg", sage ich.',
             "Nimm den linken Weg")
    survives("Post",
             'Die Post ist da. „Schau, ein Brief für dich", sage ich.',
             "Schau, ein Brief für dich")
    survives("notes (EN)",
             'I look up from my notes. "Come sit with me," I say.',
             "Come sit with me,")
    survives("Schreibmaschine",
             'Ich lehne mich an die Schreibmaschine. „Komm her", sage ich.',
             "Komm her")
    survives("Schreibblock",
             'Der Schreibblock liegt auf dem Tisch. „Nimm ihn dir", sage ich.',
             "Nimm ihn dir")
    survives("Notizblock",
             'Ich lege den Notizblock weg. „Jetzt du", sage ich.',
             "Jetzt du")
    survives("Notizheft",
             'Ich blättere durch mein Notizheft. „Warte kurz", sage ich.',
             "Warte kurz")
    survives("Schreiberin",
             'Sie ist eine gute Schreiberin. „Setz dich", sage ich.',
             "Setz dich")
    survives("Tippfehler",
             'Ein Tippfehler, mehr nicht. „Nicht so schlimm", sage ich.',
             "Nicht so schlimm")
    survives("Postkarte",
             'Ich hole die Postkarte aus der Tasche. „Lies mal", sage ich.',
             "Lies mal")
    survives("Postbote",
             'Der Postbote klingelt. „Ich gehe schon", sage ich.',
             "Ich gehe schon")
    survives("Posten",
             'Ich beziehe meinen Posten am Tor. „Bleib hinter mir", sage ich.',
             "Bleib hinter mir")
    survives("Kritzelei",
             'Eine alte Kritzelei an der Wand. „Sieh dir das an", sage ich.',
             "Sieh dir das an")
    survives("Skizze",
             'Die Skizze gefällt mir. „Zeig sie mir", sage ich.',
             "Zeig sie mir")
    survives("writing desk (EN)",
             'I sit at the writing desk. "Come sit with me," I say.',
             "Come sit with me,")
    survives("writer (EN)",
             'He is a great writer. "Sit down," I say.',
             "Sit down,")
    survives("type (EN noun)",
             'What type of tea is this? "Try it," I say.',
             "Try it,")
    survives("notebook (EN)",
             'I put the notebook away. "Let us go," I say.',
             "Let us go,")
    survives("post (EN noun)",
             'The post arrived today. "Look, a letter for you," I say.',
             "Look, a letter for you,")
    survives("Notiz (reported regression)",
             'Eine Notiz liegt auf dem Tisch. „Lies sie", sage ich.',
             "Lies sie")
    survives("Notiz (reported regression, verb reading of lesen)",
             'Ich lese die Notiz. „Komm her", sage ich.',
             "Komm her")
    survives("Notizen",
             'Ich blättere durch die Notizen. „Setz dich", sage ich.',
             "Setz dich")
    survives("Notizzettel",
             'Der Notizzettel klebt am Spiegel. „Sieh mal", sage ich.',
             "Sieh mal")
    survives("Notierung",
             'Die Notierung steht fest. „Sieh her", sage ich.',
             "Sieh her")
    survives("Skizzierung",
             'Die Skizzierung ist fertig. „Schau es dir an", sage ich.',
             "Schau es dir an")
    survives("vorgeschrieben",
             'Die Uniform ist vorgeschrieben. „Zieh sie an", sage ich.',
             "Zieh sie an")
    survives("zugeschrieben",
             'Man hat mir das zugeschrieben. „Egal jetzt", sage ich.',
             "Egal jetzt")
    survives("eingeschrieben",
             'Ich bin an der Uni eingeschrieben. „Komm mit", sage ich.',
             "Komm mit")
    survives("festgeschrieben",
             'Die Regel ist festgeschrieben. „Halt dich dran", sage ich.',
             "Halt dich dran")
    survives("note (EN noun)",
             'I read the note. "Come here," I say.',
             "Come here,")
    survives("types (EN noun)",
             'There are two types of tea. "Try this one," I say.',
             "Try this one,")
    survives("a noted author (EN adjective)",
             'He is a noted author. "Sit down," I say.',
             "Sit down,")
    survives("writing style (EN noun phrase)",
             'Her writing style is odd. "Sit down," I say.',
             "Sit down,")

    print("[14b] MANDATORY SURVIVORS — a first-person pronoun is not a name")
    survives("Ich sagte:",
             'Ich sagte: „Setz dich zu mir."',
             "Setz dich zu mir.")
    survives("Ich flüsterte:",
             'Ich flüsterte: „Bleib noch."',
             "Bleib noch.")
    survives("I said:",
             'I said: "Come sit with me."',
             "Come sit with me.")
    survives("Wir sagten:",
             'Wir sagten: „Wir kommen mit."',
             "Wir kommen mit.")

    print("[15] the false-alarm suppression is still in force")
    drops("notieren", 'Ich notiere mir: „Morgen einkaufen."')
    drops("kritzeln", 'Ich kritzele an den Rand: „Nie wieder."')
    drops("posten", 'Ich poste: „Heute war ein guter Tag."')
    drops("geschrieben", 'Ich habe ihm geschrieben: „Komm vorbei."')
    drops("skizzieren", 'Ich skizziere daneben: „So sieht es aus."')
    drops("wrote (EN)", 'I wrote: "See you tomorrow."')
    drops("typed (EN)", 'She typed: "I am on my way."')
    drops("taking notes (EN)", 'I was taking notes: "remember the key."')
    drops("aufgeschrieben", 'Ich habe es aufgeschrieben: „Milch kaufen."')
    drops("vollgeschrieben", 'Die Seite ist vollgeschrieben: „Kais Kaffeekunst."')
    drops("notierte", 'Ich notierte: „Morgen einkaufen."')
    drops("skizzierte", 'Ich skizzierte daneben: „So sieht es aus."')
    drops("foreign name in front", 'Tom sagte: „Ich bin morgen weg."')

    print("[16] notes / types / noted — the colon decides")
    drops("noted (EN verb)", 'I noted: "Come sit with me."')
    drops("notes: (EN verb)", 'She notes: "Come here."')
    drops("types: (EN verb)", 'He types: "Hello."')
    drops("Notes: as a written heading", 'Notes: "Bring milk tomorrow."')
    survives("notes without a colon stays a noun",
             'I look through my notes. "Come sit with me," I say.',
             "Come sit with me,")
    survives("types without a colon stays a noun",
             'She knows both types well. "Pick one," I say.',
             "Pick one,")

    print("[17] the writing lookbehind stops at the sentence boundary")
    survives("writing verb one sentence earlier (reported regression)",
             'Ich schreibe den Brief zu Ende. „Komm her", sage ich.',
             "Komm her")
    survives("tippen one sentence earlier (reported regression)",
             'Ich tippe die Nachricht. „Komm her", sage ich.',
             "Komm her")
    survives("the next sentence may start with anything",
             'Ich schreibe den Brief. Dann „Komm her", sage ich.',
             "Komm her")
    survives("! ends a sentence too",
             'Ich schreibe das auf! „Komm her", sage ich.',
             "Komm her")
    survives("? ends a sentence too",
             'Schreibe ich das auf? „Komm her", sage ich.',
             "Komm her")
    survives("… ends a sentence too",
             'Ich habe ihm geschrieben… „Komm her", sage ich.',
             "Komm her")
    drops("a colon binds the verb to the quote",
          'Ich notierte: „Milch kaufen."')
    drops("a comma binds the verb to the quote",
          'Ich schreibe, „Milch kaufen."')
    drops("a decimal point does not end a sentence",
          'Ich habe 3.5 Seiten geschrieben: „Milch kaufen."')
    drops("no boundary, no cut",
          'Ich schreibe mit ruhiger Hand „Milch kaufen" auf den Zettel.')
    survives("foreign attribution one sentence earlier",
             'Tom sagte etwas. „Komm her", sage ich.',
             "Komm her")
    drops("foreign attribution with a colon still binds",
          'Tom sagte: „Komm her."')

    ok = all(CHECKS)
    print(f"\n{'ALL OK' if ok else 'FAILURES'} ({sum(CHECKS)}/{len(CHECKS)} checks)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
