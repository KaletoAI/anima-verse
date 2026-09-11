"""Smoke check: deferred tool order — attachment sends run after the image tools.

Usage:
    ./.venv/bin/python scripts/smoke_deferred_order.py

Runs without a server and without a world DB.

Expected values, derived by hand from the contract of
``streaming._attachment_sends_last``:

The helper is a STABLE sort with the key "1 if the call defers for an
attachment, else 0". Python's ``sorted`` is stable, so:

[1] With ``_defers_for_attachment`` patched to "the tool is called Attach",
    the input
        [("Attach","a"), ("Img","b"), ("Other","c"), ("Attach","d")]
    has keys        [1, 0, 0, 1]
    -> the key-0 group keeps its order (("Img","b"), ("Other","c")) and is
    followed by the key-1 group in its original order (("Attach","a"),
    ("Attach","d")):
        [("Img","b"), ("Other","c"), ("Attach","a"), ("Attach","d")]
[2] Nothing defers -> the list comes back byte-identical (all keys 0).
[3] Everything defers -> the list comes back byte-identical (all keys 1);
    a "sort" that reversed equal keys would break the image-before-send
    contract for two attachment sends of the same turn.
[4] The empty list stays empty (the caller returns early, but the helper
    must not raise).
[5] The helper consults the declaration, never a tool name: with the patch
    keying on the INPUT text instead of the name, the same reordering
    happens for a differently named tool — i.e. the sort has no knowledge
    of any skill (R1).
[6] Text check: ``_sendmessage_wants_attachment`` — the helper name removed
    in 6ea60f69 — must not occur in app/core/streaming.py. It survived only
    inside the sort lambda, where it raised NameError and aborted the whole
    turn. Expected count: 0. (No pyflakes/ruff in the venv; F821 would have
    caught this statically.)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core import streaming  # noqa: E402

CHECKS = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(ok)
    print(f"  {'OK ' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail and not ok else ""))


def with_defers(fn, pending):
    """Run the sort with a patched ``_defers_for_attachment``."""
    original = streaming._defers_for_attachment
    streaming._defers_for_attachment = fn
    try:
        return streaming._attachment_sends_last(pending)
    finally:
        streaming._defers_for_attachment = original


def main() -> int:
    by_name = lambda n, i: n == "Attach"  # noqa: E731

    print("[1] attachment sends move to the end, stable within groups")
    got = with_defers(by_name, [("Attach", "a"), ("Img", "b"),
                                ("Other", "c"), ("Attach", "d")])
    want = [("Img", "b"), ("Other", "c"), ("Attach", "a"), ("Attach", "d")]
    check("order", got == want, f"got={got!r}")

    print("[2] nothing defers -> unchanged")
    src = [("Img", "b"), ("Other", "c")]
    got = with_defers(lambda n, i: False, list(src))
    check("unchanged", got == src, f"got={got!r}")

    print("[3] everything defers -> unchanged (stability)")
    src = [("Attach", "a"), ("Attach", "d")]
    got = with_defers(lambda n, i: True, list(src))
    check("unchanged", got == src, f"got={got!r}")

    print("[4] empty list")
    got = with_defers(by_name, [])
    check("empty", got == [], f"got={got!r}")

    print("[5] the declaration decides, not the name")
    got = with_defers(lambda n, i: "attachment" in i,
                      [("Whatever", "use the attachment"), ("Img", "plain")])
    want = [("Img", "plain"), ("Whatever", "use the attachment")]
    check("keyed by declaration", got == want, f"got={got!r}")

    print("[6] the dead helper name is gone from streaming.py")
    text = (ROOT / "app" / "core" / "streaming.py").read_text(encoding="utf-8")
    n = text.count("_sendmessage_wants_attachment")
    check("no _sendmessage_wants_attachment", n == 0, f"count={n}")

    ok = all(CHECKS)
    print(f"\n{'ALL OK' if ok else 'FAILURES'} ({sum(CHECKS)}/{len(CHECKS)} checks)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
