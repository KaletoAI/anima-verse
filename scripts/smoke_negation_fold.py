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
   what ``_generate`` received: with ``supports_negative_prompt=False`` the
   engine must see the folded prompt and an EMPTY negative; with the flag on,
   prompt and negative pass through byte-identically.

Usage:  ./.venv/bin/python scripts/smoke_negation_fold.py
"""
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.imagegen.base import ImageBackend            # noqa: E402
from app.imagegen.negation_fold import fold_negatives  # noqa: E402

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
be.supports_negative_prompt = False
be.generate("A mysterious beach on a secluded lake.", "trees, fog", {})
expect("flag off -> prompt folded", be.seen_prompt,
       "A mysterious beach on a secluded lake. No trees, no fog.")
expect("flag off -> negative emptied", be.seen_negative, "")

be = _FakeBackend()
be.image_family = "keywords"
be.supports_negative_prompt = True
be.generate("beach, lake", "trees, fog", {})
expect("flag on -> prompt untouched", be.seen_prompt, "beach, lake")
expect("flag on -> negative untouched", be.seen_negative, "trees, fog")

be = _FakeBackend()
be.image_family = "keywords"
be.supports_negative_prompt = False
be.generate("beach, lake", "", {})
expect("empty negative -> prompt untouched", be.seen_prompt, "beach, lake")

print("\nBackend flag from the config bridge (env)")
os.environ.pop("SMOKE_FOLD_SUPPORTS_NEGATIVE_PROMPT", None)
expect("missing key -> default True",
       _FakeBackend().supports_negative_prompt, True)
os.environ["SMOKE_FOLD_SUPPORTS_NEGATIVE_PROMPT"] = "false"
expect("'false' -> False", _FakeBackend().supports_negative_prompt, False)
os.environ["SMOKE_FOLD_SUPPORTS_NEGATIVE_PROMPT"] = "true"
expect("'true' -> True", _FakeBackend().supports_negative_prompt, True)
os.environ.pop("SMOKE_FOLD_SUPPORTS_NEGATIVE_PROMPT", None)

print()
if FAILURES:
    print(f"FAILED ({len(FAILURES)}): " + "; ".join(FAILURES))
    sys.exit(1)
print("all checks passed")
