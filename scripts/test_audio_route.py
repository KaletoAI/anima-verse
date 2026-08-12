#!/usr/bin/env python3
"""Standalone check for the game-audio asset route (stage 4, task 2).

Runs against a THROWAWAY audio directory with fake files — no real audio, and
the real ``<repo>/audio/`` (user data) is never touched: the check overrides
``game_audio.get_audio_dir``. No server needed; the router is mounted on a
bare FastAPI app.

What is checked is the contract, derived by hand from the task brief:
  - the listing shape ``{music: {day, night}, ambient: {<terrain>}}``, sorted,
    only mp3/ogg/wav, URLs pointing back at this route
  - an absent directory gives empty lists instead of an error
  - path traversal and unknown categories/subs are refused (400/404)
  - a real file comes back with its bytes, an ETag and a 304 on revalidation

Usage:  ./.venv/bin/python scripts/test_audio_route.py
"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="audio-route-check-"))

from app.core import paths  # noqa: E402

paths.init(STORAGE / "world")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.routes import game_audio  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global CHECKED
    CHECKED += 1
    print(f"  {'OK  ' if ok else 'FAIL'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def equals(label: str, actual, expected) -> None:
    check(label, actual == expected, "" if actual == expected
          else f"expected {expected!r}, got {actual!r}")


AUDIO = STORAGE / "audio"
game_audio.get_audio_dir = lambda: AUDIO          # never the real folder
client = TestClient(FastAPI())
client.app.include_router(game_audio.router)


def make_files() -> None:
    """Two music buckets, two terrains, plus the things that must be ignored:
    a non-audio file, a loose file directly under ``ambient/`` and an empty
    terrain directory."""
    for rel in ("music/day", "music/night", "ambient/forest", "ambient/water",
                "ambient/desert"):
        (AUDIO / rel).mkdir(parents=True, exist_ok=True)
    (AUDIO / "music/day/morning walk.mp3").write_bytes(b"ID3day")
    (AUDIO / "music/day/afternoon.ogg").write_bytes(b"OggS")
    (AUDIO / "music/day/notes.txt").write_text("not audio")
    (AUDIO / "music/night/dark.wav").write_bytes(b"RIFFnight")
    (AUDIO / "ambient/forest/birds.mp3").write_bytes(b"ID3birds")
    (AUDIO / "ambient/forest/wind.mp3").write_bytes(b"ID3wind")
    (AUDIO / "ambient/water/waves.ogg").write_bytes(b"OggSwaves")
    (AUDIO / "ambient/loose.mp3").write_bytes(b"ID3loose")
    # ambient/desert stays empty on purpose.


def main() -> int:
    print("empty world — no audio directory at all")
    r = client.get("/assets/audio")
    equals("listing answers 200", r.status_code, 200)
    equals("music buckets exist but are empty", r.json()["music"],
           {"day": [], "night": []})
    equals("ambient is an empty object", r.json()["ambient"], {})

    make_files()

    print("\nlisting — what is on disk, sorted, as URLs")
    body = client.get("/assets/audio").json()
    equals("day: the two playable files, .txt ignored, spaces encoded",
           body["music"]["day"],
           ["/assets/audio/music/day/afternoon.ogg",
            "/assets/audio/music/day/morning%20walk.mp3"])
    equals("night", body["music"]["night"],
           ["/assets/audio/music/night/dark.wav"])
    equals("ambient carries one key per NON-EMPTY terrain",
           sorted(body["ambient"].keys()), ["forest", "water"])
    equals("forest, sorted", body["ambient"]["forest"],
           ["/assets/audio/ambient/forest/birds.mp3",
            "/assets/audio/ambient/forest/wind.mp3"])
    equals("water", body["ambient"]["water"],
           ["/assets/audio/ambient/water/waves.ogg"])

    print("\nserving — every listed URL resolves to its bytes")
    served = []
    for urls in (body["music"]["day"], body["music"]["night"],
                 *body["ambient"].values()):
        served.extend(urls)
    for url in served:
        rr = client.get(url)
        check(f"200 for {url}", rr.status_code == 200, f"got {rr.status_code}")
    r = client.get("/assets/audio/music/day/afternoon.ogg")
    equals("bytes come back unchanged", r.content, b"OggS")
    etag = r.headers.get("etag")
    check("an ETag is sent", bool(etag), repr(etag))
    r304 = client.get("/assets/audio/music/day/afternoon.ogg",
                      headers={"If-None-Match": etag or ""})
    equals("revalidation gives 304", r304.status_code, 304)

    print("\nrefusals — the route takes three segments from the client")
    for label, url in [
        ("traversal out of the audio dir",
         "/assets/audio/music/day/..%2f..%2f..%2fsecrets.json"),
        ("encoded traversal in the sub", "/assets/audio/ambient/..%2f..%2fetc/x.mp3"),
        ("backslash smuggled in", "/assets/audio/music/day/..%5c..%5cx.mp3"),
        ("unknown category", "/assets/audio/voices/day/afternoon.ogg"),
        ("unknown music bucket", "/assets/audio/music/evening/afternoon.ogg"),
        ("terrain that is not on disk", "/assets/audio/ambient/lava/x.mp3"),
        ("a file that is not audio", "/assets/audio/music/day/notes.txt"),
        ("a file loose under ambient/", "/assets/audio/ambient/loose.mp3"),
        ("a missing file in a real bucket", "/assets/audio/music/day/nope.mp3"),
        # A NUL byte in a segment must be refused like any other illegal
        # character — reaching the filesystem with it raises ValueError, i.e.
        # a 500 where a 400 belongs.
        ("a NUL byte in the filename", "/assets/audio/music/day/a%00.mp3"),
        ("a NUL byte in the sub", "/assets/audio/ambient/fo%00rest/birds.mp3"),
        # Dotfiles are not content — the folder is user territory and may hold
        # a .DS_Store or an editor swap file.
        ("a dotfile", "/assets/audio/music/day/.hidden.mp3"),
    ]:
        rr = client.get(url)
        check(f"{label} -> {rr.status_code}", rr.status_code in (400, 404, 405),
              f"got {rr.status_code}")
    check("secrets.json was not served",
          b"secret" not in client.get(
              "/assets/audio/music/day/..%2f..%2f..%2fsecrets.json").content.lower())

    # A plain `..` between real segments never reaches the server: HTTP clients
    # normalise the URL first (`/assets/audio/music/../music/day/x.ogg` is sent
    # as `/assets/audio/music/day/x.ogg`, and answering that with the file is
    # correct). So the guard itself is checked directly, segment by segment —
    # that is where a hostile value would land if a client did NOT normalise.
    print("\nresolve_audio_path — the guard, called directly")
    resolve = game_audio.resolve_audio_path
    equals("a legal reference resolves",
           resolve("music", "day", "afternoon.ogg"),
           AUDIO / "music/day/afternoon.ogg")
    for label, args in [
        ("'..' as the sub", ("music", "..", "afternoon.ogg")),
        ("'..' as the filename", ("ambient", "forest", "..")),
        ("'.' as the sub", ("ambient", ".", "birds.mp3")),
        ("an empty sub", ("music", "", "afternoon.ogg")),
        ("a separator inside the sub", ("ambient", "forest/..", "birds.mp3")),
        ("a separator inside the filename", ("music", "day", "../night/dark.wav")),
        ("a backslash inside the filename", ("music", "day", "..\\dark.wav")),
        ("an absolute path as the filename", ("music", "day", "/etc/passwd")),
        ("a NUL byte in the filename", ("music", "day", "afternoon\x00.ogg")),
        ("a leading dot in the filename", ("music", "day", ".hidden.mp3")),
        ("a leading dot in the sub", ("ambient", ".git", "x.mp3")),
        ("an unknown category", ("voices", "day", "afternoon.ogg")),
    ]:
        check(f"{label} -> refused", resolve(*args) is None,
              f"got {resolve(*args)!r}")

    # SYMLINKS ARE ALLOWED. `audio/` is user territory like `voices/`, and
    # linking a music library into it is the natural way to fill the folder.
    # URL safety is enforced LEXICALLY above; the file access then simply
    # follows the link. What matters is that there is no split: what is listed
    # is what is served.
    print("\nsymlinks — a linked library is content, not an attack")
    outside = STORAGE / "outside"
    outside.mkdir(exist_ok=True)
    (outside / "leak.mp3").write_bytes(b"ID3leak")
    (outside / "linked-single.mp3").write_bytes(b"ID3single")
    (AUDIO / "ambient" / "linked").symlink_to(outside, target_is_directory=True)
    (AUDIO / "music" / "day" / "from-library.mp3").symlink_to(
        outside / "linked-single.mp3")
    listing = client.get("/assets/audio").json()
    equals("a symlinked terrain directory is listed",
           sorted(listing["ambient"].keys()), ["forest", "linked", "water"])
    equals("with its files", listing["ambient"]["linked"],
           ["/assets/audio/ambient/linked/leak.mp3",
            "/assets/audio/ambient/linked/linked-single.mp3"])
    r = client.get("/assets/audio/ambient/linked/leak.mp3")
    equals("and it serves", r.status_code, 200)
    equals("with the linked bytes", r.content, b"ID3leak")
    check("a symlinked FILE is listed too",
          "/assets/audio/music/day/from-library.mp3" in listing["music"]["day"],
          str(listing["music"]["day"]))
    rf = client.get("/assets/audio/music/day/from-library.mp3")
    equals("and serves its target", (rf.status_code, rf.content),
           (200, b"ID3single"))

    # The one invariant that has to hold for the whole listing.
    print("\nno split — every listed URL answers 200")
    listed = [u for u in listing["music"]["day"] + listing["music"]["night"]]
    for urls in listing["ambient"].values():
        listed.extend(urls)
    bad = [u for u in listed if client.get(u).status_code != 200]
    check("nothing is advertised that the route then refuses", not bad, str(bad))

    print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
    if FAILURES:
        print("FAILED: " + "; ".join(FAILURES))
    return 1 if FAILURES else 0


try:
    code = main()
finally:
    shutil.rmtree(STORAGE, ignore_errors=True)
sys.exit(code)
