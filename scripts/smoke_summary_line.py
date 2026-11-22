#!/usr/bin/env python3
"""The summary line of a labeled-sections prompt (chat / scene photo, Instagram, story, event on Qwen and Flux).

Usage:
    ./.venv/bin/python scripts/smoke_summary_line.py

No world DB, no server, no network: a throwaway STORAGE_DIR / INSTANCE_DIR (``paths.init`` before any world import);
the styles are the shipped defaults of ``config._DEFAULT_IMAGE_USE_CASES``.

Expected values, derived by hand.

[1] ``prompt_adapters.summary_line(style_word, persons, location)``. ``style_word`` is the first comma token of the
    use-case style. Two kinds:
    ADJECTIVE (no leading article, last word not a picture noun) — the old line, byte for byte:
      ("photorealistic", 0, "")            -> "A photorealistic scene."
      ("photorealistic", 0, "a cafe")      -> "A photorealistic scene in a cafe."
      ("photorealistic", 1, "")            -> "A photorealistic photo of a person."
      ("photorealistic", 3, "a cafe")      -> "A photorealistic group photo of three people in a cafe."
      ("oily", 2, "")                      -> "An oily group photo of two people."   (vowel -> "An")
      ("photorealistic", 12, "")           -> "A photorealistic group photo of 12 people."
    NOUN PHRASE with an article (every shipped natural style) — capitalised, then ", showing <who>":
      ("a candid photograph taken with a 35mm lens", 3, "a cafe")
          -> "A candid photograph taken with a 35mm lens, showing a group of three people in a cafe."
      ("a candid photograph taken with a 35mm lens", 1, "")
          -> "A candid photograph taken with a 35mm lens, showing a person."
      ("a candid photograph taken with a 35mm lens", 2, "")
          -> "A candid photograph taken with a 35mm lens, showing a group of two people."
      ("an atmospheric cinematic scene depicting the event", 0, "the market")
          -> "An atmospheric cinematic scene depicting the event, set in the market."
      ("an atmospheric cinematic scene depicting the event", 0, "")
          -> "An atmospheric cinematic scene depicting the event."
    NOUN PHRASE without an article (keywords-family styles, last word a picture noun) — article added:
      ("RAW photo", 2, "")                 -> "A RAW photo, showing a group of two people."
      ("atmospheric scene", 1, "a cafe")   -> "An atmospheric scene, showing a person in a cafe."
      ("photorealistic portrait", 1, "")   -> "A photorealistic portrait, showing a person."
    No line of the shipped character / profile / instagram / event / story styles (both families, 0..3 persons)
    holds "An a ", "A a ", "An an ", "A an " or two picture nouns ("photograph … photo of").

[2] ``_render_labeled_sections`` uses that line: a PromptVariables with style
    "a candid photograph taken with a 35mm lens, natural light", persons {1: "Kai", 2: "Dario", 3: "Mia"}, location
    "a small cafe" renders first line
    "A candid photograph taken with a 35mm lens, showing a group of three people in a small cafe." and still ends
    with "Style: a candid photograph taken with a 35mm lens, natural light." The default style "" -> line 1
    "A photorealistic photo of a person." for one person (unchanged).

[3] Fails on the old code (commit 3dc6cd390): its ``_render_labeled_sections`` for the [2] fixture starts
    "An a candid photograph taken with a 35mm lens group photo of three people".
"""
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_tmp = tempfile.mkdtemp(prefix="smoke_summary_line_")
os.environ["STORAGE_DIR"] = _tmp
os.environ["INSTANCE_DIR"] = _tmp
from app.core import paths  # noqa: E402

paths.init(_tmp)

from app.core.config import _DEFAULT_IMAGE_USE_CASES as UC  # noqa: E402
from app.core.prompt_adapters import PromptVariables, _render_labeled_sections, summary_line  # noqa: E402

OLD_COMMIT = "3dc6cd390"
fails = 0


def check(label, ok, detail=""):
    global fails
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  -> {detail}"))
    if not ok:
        fails += 1


print("[1] summary_line")
CASES = [
    (("photorealistic", 0, ""), "A photorealistic scene."),
    (("photorealistic", 0, "a cafe"), "A photorealistic scene in a cafe."),
    (("photorealistic", 1, ""), "A photorealistic photo of a person."),
    (("photorealistic", 3, "a cafe"), "A photorealistic group photo of three people in a cafe."),
    (("oily", 2, ""), "An oily group photo of two people."),
    (("photorealistic", 12, ""), "A photorealistic group photo of 12 people."),
    (("a candid photograph taken with a 35mm lens", 3, "a cafe"),
     "A candid photograph taken with a 35mm lens, showing a group of three people in a cafe."),
    (("a candid photograph taken with a 35mm lens", 1, ""),
     "A candid photograph taken with a 35mm lens, showing a person."),
    (("a candid photograph taken with a 35mm lens", 2, ""),
     "A candid photograph taken with a 35mm lens, showing a group of two people."),
    (("an atmospheric cinematic scene depicting the event", 0, "the market"),
     "An atmospheric cinematic scene depicting the event, set in the market."),
    (("an atmospheric cinematic scene depicting the event", 0, ""),
     "An atmospheric cinematic scene depicting the event."),
    (("RAW photo", 2, ""), "A RAW photo, showing a group of two people."),
    (("atmospheric scene", 1, "a cafe"), "An atmospheric scene, showing a person in a cafe."),
    (("photorealistic portrait", 1, ""), "A photorealistic portrait, showing a person."),
]
for args, want in CASES:
    got = summary_line(*args)
    check(f"{args} -> {want!r}", got == want, repr(got))

BAD = ("An a ", "A a ", "An an ", "A an ", "An the ", "A the ")
for uc in ("character", "profile", "instagram", "event", "story"):
    for fam in ("keywords", "natural"):
        word = UC[uc][fam]["prompt_style"].split(",", 1)[0].strip()
        for n in range(4):
            line = summary_line(word, n, "a cafe")
            bad = [b for b in BAD if line.startswith(b)]
            stacked = " photo of " in line and word.split()[-1].lower() in ("photo", "photograph", "portrait")
            check(f"{uc}/{fam} n={n}: {line[:70]!r}", not bad and not stacked, line)

print("[2] labeled sections")


def pv_of(style, persons, location):
    pv = PromptVariables()
    pv.prompt_style = style
    pv.prompt_persons = dict(enumerate(persons, 1))
    pv.prompt_location = location
    return pv


FIXTURE = ("a candid photograph taken with a 35mm lens, natural light", ["Kai", "Dario", "Mia"], "a small cafe")
full = _render_labeled_sections(pv_of(*FIXTURE))["input_prompt_positiv"]
check("first line names the group after the style noun phrase",
      full.split("\n", 1)[0] == "A candid photograph taken with a 35mm lens, showing a group of three people in a "
                                 "small cafe.", full.split("\n", 1)[0])
check("style line unchanged", full.rstrip().endswith("Style: a candid photograph taken with a 35mm lens, natural "
                                                      "light."), full[-120:])
one = _render_labeled_sections(pv_of("", ["Kai"], ""))["input_prompt_positiv"]
check("default style, one person unchanged", one.split("\n", 1)[0] == "A photorealistic photo of a person.",
      one.split("\n", 1)[0])

print(f"[3] fails on the old code ({OLD_COMMIT})")


def old_module(rel, name):
    src = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD_COMMIT}:{rel}"], capture_output=True, text=True,
                         check=True).stdout
    mod = types.ModuleType(name)
    mod.__file__ = str(ROOT / rel)
    exec(compile(src, rel, "exec"), mod.__dict__)
    return mod


old_pa = old_module("app/core/prompt_adapters.py", "old_prompt_adapters")
old_pv = old_pa.PromptVariables()
old_pv.prompt_style, old_pv.prompt_persons, old_pv.prompt_location = FIXTURE[0], dict(enumerate(FIXTURE[1], 1)), FIXTURE[2]
old_line = old_pa._render_labeled_sections(old_pv)["input_prompt_positiv"].split("\n", 1)[0]
check("old summary is the broken one",
      old_line.startswith("An a candid photograph taken with a 35mm lens group photo of three people"), old_line)

print("\nFAILED: %d" % fails if fails else "\nall ok")
sys.exit(1 if fails else 0)
