"""Game audio assets — music and ambience for the 3D client (stage 4, task 2).

The files are USER data, not repo content: they live in ``<repo>/audio/``,
which is gitignored exactly like ``voices/`` (the TTS speaker references) and
``shared/models/clips/``. Nothing here generates or manages audio — the
directory is the interface, dropping a file in is the whole workflow.

Layout, one level of category and one of sub::

    audio/music/day/*.mp3        music while the world is in daylight
    audio/music/night/*.mp3      music at night
    audio/ambient/<terrain>/*    ambience per worldmap ``terrain``

``day``/``night`` is a closed pair — those are the two states the client's
day/night factor has. ``<terrain>`` is an OPEN vocabulary: it is whatever the
worldmap locations carry (grass, forest, water, …), so a new terrain is just a
new directory, nothing is listed in code. Only ``.mp3``/``.ogg``/``.wav`` are
picked up; a missing ``audio/`` directory is the normal state and yields empty
lists, never an error. Symlinks — a whole terrain folder or a single track —
count as content: linking an existing music library in is the natural way to
fill this folder.

Public like the rest of ``/assets`` (animation clips, surface textures): these
are the media the running game needs, and the client fetches them exactly like
a clip file.
"""
import mimetypes
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app.core import paths
from app.core.http_files import etag_file_response

router = APIRouter(prefix="/assets", tags=["assets"])

AUDIO_EXTS = {".mp3", ".ogg", ".wav"}
"""What browsers decode without a plugin — everything else in the folder is
ignored (a README, a stray .flac, the cover art)."""

MUSIC_SUBS = ("day", "night")
"""The two music buckets. Closed on purpose: the client picks by daylight."""


def get_audio_dir() -> Path:
    """``<repo>/audio`` — the drop folder for music and ambience.

    Delegates to ``paths.get_game_audio_dir()`` (one place owns storage paths);
    the indirection stays because the standalone check in ``scripts/`` replaces
    THIS function so it never touches the real, user-owned folder.
    """
    return paths.get_game_audio_dir()


def _listable(name: str) -> bool:
    """Whether a directory entry may appear in the listing at all.

    The same rule the serve route enforces, so the two can never disagree:
    a dotfile is not content (.DS_Store, an editor swap file, a .git folder
    someone linked in), and a name carrying a separator or a NUL byte could
    not be addressed by a URL anyway.
    """
    return (bool(name) and not name.startswith(".")
            and "/" not in name and "\\" not in name and "\x00" not in name)


def _tracks(directory: Path, category: str, sub: str) -> List[str]:
    """The playable files of one directory as ready-made URLs, sorted by name
    so every client gets the same playlist order.

    ``is_file()`` follows symlinks on purpose — a track linked in from a music
    library is a track (see ``resolve_audio_path``).
    """
    if not directory.is_dir():
        return []
    urls = []
    for f in sorted(directory.iterdir()):
        if f.is_file() and _listable(f.name) and f.suffix.lower() in AUDIO_EXTS:
            urls.append(f"/assets/audio/{category}/{sub}/{quote(f.name)}")
    return urls


@router.get("/audio")
def list_game_audio() -> Dict[str, Dict[str, List[str]]]:
    """Lists what is on disk: ``{"music": {"day": [...], "night": [...]},
    "ambient": {"<terrain>": [...]}}``.

    Music always carries both keys (empty lists when nothing is there);
    ``ambient`` carries one key per terrain directory that actually holds
    playable files — an empty world of sound is an empty object, not an error.
    The client takes the URLs opaquely, it never builds one from a name.
    """
    base = get_audio_dir()
    music = {sub: _tracks(base / "music" / sub, "music", sub)
             for sub in MUSIC_SUBS}
    ambient: Dict[str, List[str]] = {}
    ambient_dir = base / "ambient"
    if ambient_dir.is_dir():
        for d in sorted(ambient_dir.iterdir()):
            # A symlinked terrain directory counts — see resolve_audio_path.
            if not d.is_dir() or not _listable(d.name):
                continue
            urls = _tracks(d, "ambient", d.name)
            if urls:
                ambient[d.name] = urls
    return {"music": music, "ambient": ambient}


def resolve_audio_path(category: str, sub: str, filename: str) -> Optional[Path]:
    """``<category>/<sub>/<file>`` → the audio file, or None when the request
    is not a legal reference.

    Safety here is LEXICAL, and deliberately so. Each of the three segments
    must be a plain name: not empty, no leading dot (a dotfile is not content),
    no ``/``, ``\\`` or NUL byte — a NUL would otherwise reach the filesystem
    and raise, i.e. answer 500 where 400 belongs. On top of that the category
    comes from the two known ones, the music sub from the closed day/night pair
    and the ambient sub must be a directory that actually exists, and the file
    needs a playable extension. Three plain names cannot leave the folder, so
    that is the whole traversal defence.

    SYMLINKS ARE FOLLOWED. ``audio/`` is the user's own territory, exactly like
    ``voices/``, and linking a music library into it is the natural way to fill
    it — the earlier containment check on the RESOLVED path only produced a
    split where a linked terrain was listed but then refused. Nothing here
    takes a path from the client, so following a link the user placed himself
    adds no reach that he did not already have.
    """
    if category not in ("music", "ambient"):
        return None
    for seg in (category, sub, filename):
        if not _listable(seg):    # the leading-dot rule also kills "." and ".."
            return None
    if category == "music" and sub not in MUSIC_SUBS:
        return None
    base = get_audio_dir()
    if category == "ambient" and not (base / "ambient" / sub).is_dir():
        return None
    path = base / category / sub / filename
    if path.suffix.lower() not in AUDIO_EXTS:
        return None
    return path


@router.get("/audio/{category}/{sub}/{filename}")
def get_game_audio(category: str, sub: str, filename: str, request: Request):
    """Serves one music or ambience file. ETag + If-None-Match; these files
    change only when the user replaces them, so they may be cached hard."""
    path = resolve_audio_path(category, sub, filename)
    if path is None:
        raise HTTPException(status_code=400, detail="Invalid audio path")
    if not path.is_file():
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    media_type, _ = mimetypes.guess_type(str(path))
    return etag_file_response(path, request,
                              media_type or "application/octet-stream",
                              cache_control="public, max-age=86400")
