#!/usr/bin/env python3
"""``base_body._stored_base_for`` (behind ``base_signature`` whenever the current identity has no stored front: a
carried-over A74a base, a legacy base, none) parses the base front sidecars once per change, not on every call
(review 08b#7 — the Figure tab's poll asks ``base_signature`` four times a tick).

Usage:
    ./.venv/bin/python scripts/smoke_stored_base_memo.py

No server, no world DB: a throwaway storage dir, the character's ``model_refs`` made by hand, ``_stored_base_for``
called with explicit arguments (identity ``baseaaaaaaaa``, profile image ``Demo_1.png``, appearance "a").
``base_body._front_sidecar`` is wrapped by a counter.

Fixture, three base front sidecars with their pictures:
  base00000001 — no ``base_identity`` (legacy), first reference ``Demo_1.png``, created_at "2026-01-01" -> legacy pool;
  base00000002 — ``base_identity`` "baseffffffff" with ``prompt_rules`` (not carried) -> no pool;
  base00000003 — legacy, first reference ``Other.png`` -> no pool.

Expected, by hand:
  [1] first call: 3 sidecars parsed, answer base00000001 (the only pool entry).
  [2] the same call again: 0 parsed, the same answer (the old code parsed 3 every time -> FAILS on it).
  [3] base00000003's sidecar rewritten atomically (os.replace: new inode) with first reference ``Demo_1.png`` and
      created_at "2026-02-01": the key changed -> 3 parsed, answer base00000003 (the newer legacy stamp wins).
  [4] base00000003's picture removed (the listing changed) -> 3 parsed, answer base00000001.
  [5] another identity asked -> the key differs: 3 parsed (answer base00000001: legacy goes by the picture alone).
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="smoke-stored-base-"))
    try:
        os.environ["STORAGE_DIR"] = str(tmp / "world")
        from app.core import paths
        paths.init(tmp / "world")
        from app.core import base_body, model_refs
        from app.models.character import get_character_dir
        get_character_dir("Demo").mkdir(parents=True, exist_ok=True)
        refs = model_refs.get_model_refs_dir("Demo")

        def write(sig, meta, *, atomic=False):
            target = refs / f"tpose_{sig}.json"
            if atomic:
                staged = refs / f".staged_{sig}.json"
                staged.write_text(json.dumps(meta))
                os.replace(staged, target)
            else:
                target.write_text(json.dumps(meta))
            (refs / f"tpose_{sig}.png").write_bytes(b"png")

        write("base00000001", {"created_at": "2026-01-01",
                               "reference_images": {"input_reference_image_1": "Demo_1.png"}})
        write("base00000002", {"created_at": "2026-03-01", "base_identity": "baseffffffff", "prompt_rules": "a74a"})
        write("base00000003", {"created_at": "2026-01-15",
                               "reference_images": {"input_reference_image_1": "Other.png"}})
        parsed = []
        real = base_body._front_sidecar

        def counting(character_name, signature):
            parsed.append(signature)
            return real(character_name, signature)

        base_body._front_sidecar = counting
        try:
            def ask(identity="baseaaaaaaaa"):
                parsed.clear()
                return base_body._stored_base_for("Demo", identity, "Demo_1.png", "a"), len(parsed)

            check("[1] first call", ask(), ("base00000001", 3))
            check("[2] again: nothing parsed", ask(), ("base00000001", 0))
            write("base00000003", {"created_at": "2026-02-01",
                                   "reference_images": {"input_reference_image_1": "Demo_1.png"}}, atomic=True)
            check("[3] a sidecar rewritten", ask(), ("base00000003", 3))
            (refs / "tpose_base00000003.png").unlink()
            check("[4] its picture gone", ask(), ("base00000001", 3))
            check("[5] another identity", ask("basebbbbbbbb"), ("base00000001", 3))
        finally:
            base_body._front_sidecar = real
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILS:
        print(f"{len(FAILS)} failure(s): {', '.join(FAILS)}")
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
