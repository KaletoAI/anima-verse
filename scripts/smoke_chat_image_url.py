#!/usr/bin/env python3
"""Smoke: the chat upload-image URL has all four path segments (DE-23).

Usage:
    ./.venv/bin/python scripts/smoke_chat_image_url.py

Pure SOURCE check: it reads app/routes/chat.py and app/routes/play.py as TEXT
and imports nothing of the app — no server, no world DB, no network. Importing
the route module would pull in FastAPI and the whole route stack for what is a
one-line question about a string literal.

The finding under test (review 2026-09-20, dead_endpoints.md DE-23)
---------------------------------------------------------------------------
``app/routes/chat.py`` built ``f"/chat/upload-image/{image_id}"`` while the
serving route is ``@router.get("/{user_id}/upload-image/{image_id}")`` under
the ``/chat`` prefix — a three-segment path that matches no route, so the
attached image rendered as a broken image. The shared resolver a few hundred
lines earlier had it right all along.

Expected values, derived by hand from the two sources
---------------------------------------------------------------------------
* The serving route is declared as ``"/{user_id}/upload-image/{image_id}"``.
* EVERY ``"/chat/…upload-image…"`` literal in app/routes/chat.py has exactly
  four path segments — chat, <user segment>, upload-image, <id>. Three is the
  bug.
* ``resolve_chat_image`` stays the ONE resolver: the surviving consumer of an
  attached chat image, ``/play/say`` in app/routes/play.py, calls
  ``resolve_chat_image(image_id, image_url)`` instead of assembling a path of
  its own. (Until 2026-09-21 the streaming ``POST /chat/{user_id}`` was the
  second consumer; that route and its hand-written copy are gone.)

Running this against the pre-fix tree reports the three-segment literal.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}{(' — ' + detail) if detail else ''}")
        failures.append(label)


def main() -> int:
    print("smoke_chat_image_url")
    src = (REPO / "app" / "routes" / "chat.py").read_text(encoding="utf-8")
    play = (REPO / "app" / "routes" / "play.py").read_text(encoding="utf-8")

    check("the serving route is declared as /{user_id}/upload-image/{image_id}",
          '"/{user_id}/upload-image/{image_id}"' in src)

    urls = re.findall(r'["\']/chat/[^"\']*upload-image[^"\']*["\']', src)
    check("at least one display URL literal is built here", bool(urls),
          "none found — has the helper moved?")
    bad = [u for u in urls if len(u.strip('"\'').strip("/").split("/")) != 4]
    check(f"all {len(urls)} of them have four segments", not bad, ", ".join(bad))

    check("chat.py still owns the shared resolver",
          "def resolve_chat_image(" in src)
    check("the /play/say path uses it instead of a second resolution",
          "resolve_chat_image(image_id, image_url)" in play)

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
