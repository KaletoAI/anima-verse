#!/usr/bin/env python3
"""Smoke run for the negative-prompt fold (backends without a negative input).

Two halves, both without a world, a config or a network:

1. The pure function ``app.imagegen.negation_fold.fold_negatives`` — expected
   values derived by hand from the format rule:
     * family "natural"  -> one sentence appended: "No a, no b." (leading
       capital, ", no " between the items, a full stop at the end; the prompt
       gets a terminator first when it lacks one).
     * family "keywords" (and anything else) -> ", no a, no b" appended to the
       tag list.
     * items are split on commas, trimmed, de-duplicated case-insensitively
       (order kept), and every item the prompt ALREADY negates ("no fog" /
       "without fog") is skipped. An empty negative changes nothing.

2. The handoff in ``ImageBackend.generate`` with a fake backend that records
   what ``_generate`` received: with the backend resolved to "no negative
   input" the engine must see the folded prompt and an EMPTY negative; with a
   negative input, prompt and negative pass through byte-identically.

3. ``backend_supports_negative`` — the tri-state resolution the config field
   (auto/yes/no), the handoff and the option payloads all share. Expected
   values derived by hand from the rule: yes/true/1/on -> True,
   no/false/0/off -> False, everything else (auto, "", None) -> the prompt
   family decides, natural -> False, keywords -> True.

Usage:  ./.venv/bin/python scripts/smoke_negation_fold.py
"""
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.imagegen.base import ImageBackend            # noqa: E402
from app.imagegen.negation_fold import (               # noqa: E402
    backend_supports_negative, fold_negatives)

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def expect(label: str, got, want) -> None:
    check(label, got == want, f"got {got!r}, want {want!r}")


print("fold_negatives — family 'natural' (prose sentence)")
got, items = fold_negatives(
    "A mysterious beach on a secluded lake.", "trees, fog", "natural")
expect("sentence appended",
       got, "A mysterious beach on a secluded lake. No trees, no fog.")
expect("folded items", items, ["trees", "fog"])

got, items = fold_negatives("A quiet beach at dawn", "fog", "natural")
expect("missing terminator gets a full stop",
       got, "A quiet beach at dawn. No fog.")

print("\nfold_negatives — family 'keywords' (comma tags)")
got, items = fold_negatives("beach, lake, photo", "trees, fog, blurry",
                            "keywords")
expect("tags appended", got, "beach, lake, photo, no trees, no fog, no blurry")
expect("folded items", items, ["trees", "fog", "blurry"])

got, items = fold_negatives("beach, lake, photo", "trees", "")
expect("unknown family behaves like keywords", got,
       "beach, lake, photo, no trees")

print("\nfold_negatives — skipping and de-duplication")
got, items = fold_negatives("wide shore, no fog", "trees, fog", "keywords")
expect("item the prompt already negates is skipped", items, ["trees"])
expect("only the new item lands in the prompt",
       got, "wide shore, no fog, no trees")

got, items = fold_negatives("casino fog lights", "fog", "keywords")
expect("'no fog' inside 'casino fog' is NOT a negation", items, ["fog"])

got, items = fold_negatives("beach", "fog, Fog, fog", "keywords")
expect("case-insensitive de-duplication", items, ["fog"])
expect("de-duplicated prompt", got, "beach, no fog")

got, items = fold_negatives("beach", "no fog, without trees", "keywords")
expect("negation words already in the negative are not doubled",
       got, "beach, no fog, no trees")

print("\nfold_negatives — nothing to do")
expect("empty negative", fold_negatives("beach, lake", "", "keywords"),
       ("beach, lake", []))
expect("whitespace-only negative",
       fold_negatives("beach, lake", " ,  , ", "natural"), ("beach, lake", []))
expect("every item already negated",
       fold_negatives("A shore without fog.", "fog", "natural"),
       ("A shore without fog.", []))

print("\nfold_negatives — folding twice changes nothing (preview + handoff)")
# The dialog preview folds, the handoff folds again on the same negative
# (the use-case default it falls back to). The second pass must be a no-op —
# every item is already negated in the prompt.
for _fam, _p, _n in (
        ("natural", "A mysterious beach on a secluded lake.", "trees, fog"),
        ("keywords", "beach, lake, photo", "trees, fog, blurry"),
        ("natural", "A quiet shore", "no fog, without trees")):
    once, _ = fold_negatives(_p, _n, _fam)
    twice, again = fold_negatives(once, _n, _fam)
    expect(f"idempotent ({_fam}, {_n!r})", twice, once)
    expect(f"second pass folds nothing ({_fam})", again, [])


# ── Handoff: ImageBackend.generate ────────────────────────────────────────
class _FakeBackend(ImageBackend):
    """Records what the engine step received. No network, no files."""

    def __init__(self, env_prefix: str = "SMOKE_FOLD_") -> None:
        super().__init__(name="fake", api_url="http://localhost",
                         cost=0, api_type="localai", env_prefix=env_prefix)
        self.seen_prompt = ""
        self.seen_negative = ""

    def check_availability(self) -> bool:
        self._available = True
        return True

    def _generate(self, prompt: str, negative_prompt: str,
                  params: Dict[str, Any]) -> List[bytes]:
        self.seen_prompt = prompt
        self.seen_negative = negative_prompt
        return [b"PNG"]


print("\nHandoff ImageBackend.generate")
be = _FakeBackend()
be.image_family = "natural"
be.negative_prompt_setting = "no"
be.generate("A mysterious beach on a secluded lake.", "trees, fog", {})
expect("no negative input -> prompt folded", be.seen_prompt,
       "A mysterious beach on a secluded lake. No trees, no fog.")
expect("no negative input -> negative emptied", be.seen_negative, "")

be = _FakeBackend()
be.image_family = "keywords"
be.negative_prompt_setting = "yes"
be.generate("beach, lake", "trees, fog", {})
expect("negative input -> prompt untouched", be.seen_prompt, "beach, lake")
expect("negative input -> negative untouched", be.seen_negative, "trees, fog")

be = _FakeBackend()
be.image_family = "keywords"
be.negative_prompt_setting = "no"
be.generate("beach, lake", "", {})
expect("empty negative -> prompt untouched", be.seen_prompt, "beach, lake")

# The preview folds and the handoff folds again (the generate path falls back
# to the use-case negative when the dialog sends none) — nothing doubles.
be = _FakeBackend()
be.image_family = "natural"
be.negative_prompt_setting = "no"
pre_folded, _ = fold_negatives(
    "A mysterious beach on a secluded lake.", "trees, fog", "natural")
be.generate(pre_folded, "trees, fog", {})
expect("preview-folded prompt + same negative -> no doubling",
       be.seen_prompt,
       "A mysterious beach on a secluded lake. No trees, no fog.")

print("\nbackend_supports_negative — the tri-state rule")
expect("auto + natural family -> no negative input",
       backend_supports_negative("auto", "natural", ""), False)
expect("auto + keywords family -> negative input",
       backend_supports_negative("auto", "keywords", ""), True)
expect("auto + Flux model name -> no negative input",
       backend_supports_negative("auto", "", "Flux2-9B"), False)
expect("auto + Qwen-Image model name -> no negative input",
       backend_supports_negative("auto", "", "Qwen/Qwen-Image-2.0"), False)
# Documented blind spot: Z-Image models are KEYWORD family, so auto grants
# them a negative input — right for Z-Image with CFG > 1, WRONG for Z-Image
# Turbo (distilled, guidance-free). Only the explicit "no" fixes that one;
# the model name carries no "turbo" marker to key on reliably.
expect("auto + Z-Image model name -> negative input (Turbo needs 'no')",
       backend_supports_negative("auto", "", "Z-Image-Turbo"), True)
expect("explicit 'no' overrides the family",
       backend_supports_negative("no", "keywords", "Z-Image-Turbo"), False)
expect("explicit 'yes' overrides the family",
       backend_supports_negative("yes", "natural", "Flux2-9B"), True)

print("\nbackend_supports_negative — tolerant values")
for value, want in (("true", True), ("false", False), ("1", True),
                    ("0", False), ("on", True), ("off", False),
                    (True, True), (False, False),
                    ("YES", True), (" no ", False)):
    expect(f"{value!r} (natural family)",
           backend_supports_negative(value, "natural", ""), want)
expect("None -> auto (natural family)",
       backend_supports_negative(None, "natural", ""), False)
expect("'' -> auto (keywords family)",
       backend_supports_negative("", "keywords", ""), True)
expect("unknown word -> auto (natural family)",
       backend_supports_negative("maybe", "natural", ""), False)

print("\nBackend setting from the config bridge (env)")
os.environ.pop("SMOKE_FOLD_SUPPORTS_NEGATIVE_PROMPT", None)
_be = _FakeBackend()
_be.image_family = "natural"
expect("missing key -> auto -> natural family has none",
       _be.supports_negative_prompt, False)
_be = _FakeBackend()
_be.image_family = "keywords"
expect("missing key -> auto -> keyword family has one",
       _be.supports_negative_prompt, True)
for env_value, family, want in (("no", "keywords", False),
                                ("yes", "natural", True),
                                ("false", "keywords", False),
                                ("true", "natural", True),
                                ("auto", "natural", False)):
    os.environ["SMOKE_FOLD_SUPPORTS_NEGATIVE_PROMPT"] = env_value
    _be = _FakeBackend()
    _be.image_family = family
    expect(f"env {env_value!r} + {family}", _be.supports_negative_prompt, want)
os.environ.pop("SMOKE_FOLD_SUPPORTS_NEGATIVE_PROMPT", None)

print()
if FAILURES:
    print(f"FAILED ({len(FAILURES)}): " + "; ".join(FAILURES))
    sys.exit(1)
print("all checks passed")
