"""Centralized path module — single source of truth for all storage paths.

Every file that needs a storage path imports from here instead of
defining its own ``STORAGE_DIR = Path("./storage")``.

Initialization order (in server.py):
    1. paths.init(storage_dir)          # from CLI / env
    2. config.load(paths.get_config_path())  # config.json lives inside storage
"""

import os
from pathlib import Path
from typing import Optional, Union

_storage_dir: Optional[Path] = None
_project_root: Path = Path(__file__).resolve().parent.parent.parent


def init(storage_dir: Optional[Union[str, Path]] = None) -> Path:
    """Set the storage root.  Called once at server startup.

    Resolution order:
        1. Explicit *storage_dir* argument  (from CLI ``--storage`` / ``--world``)
        2. ``STORAGE_DIR`` environment variable
        3. ``./storage`` (default, backward-compatible)
    """
    global _storage_dir

    if storage_dir:
        _storage_dir = Path(storage_dir).resolve()
    else:
        _storage_dir = Path(os.environ.get("STORAGE_DIR", "./worlds/demo")).resolve()

    _storage_dir.mkdir(parents=True, exist_ok=True)
    return _storage_dir


def get_storage_dir() -> Path:
    """Return the base storage directory.  Auto-initializes on first call."""
    if _storage_dir is None:
        init()
    return _storage_dir


def get_account_path() -> Path:
    """Return the path to the account profile (login, settings)."""
    return get_storage_dir() / "account.json"


def get_shared_dir() -> Path:
    """Return the shared directory for cross-world files (templates, schemas)."""
    return _project_root / "shared"


def get_animation_clips_dir() -> Path:
    """Shared 3D animation clips (Mixamo FBX, "Without Skin") — world-independent,
    consumed by every 3D client. See the README in that folder for the hard
    requirements (same rig source, no mesh).

    ``ANIMATION_CLIPS_DIR`` overrides the location. Tests MUST set it: the real
    folder holds user-provided binaries that exist nowhere else (they are
    gitignored), so a test must never write into — or clean up — that path.
    """
    override = os.environ.get("ANIMATION_CLIPS_DIR", "").strip()
    if override:
        return Path(override)
    return get_shared_dir() / "models" / "clips"


def get_licensed_clips_dir() -> Path:
    """The LICENSED clip library — Mixamo downloads, bought mocap packs:
    usable in the game, but not redistributable, so it is gitignored and
    lives per installation. ``shared/models/clips`` is the redistributable
    one (CMU-derived, tracked). Both are scanned (``animation_clips``); the
    same file name in both → the licensed one wins.

    ``ANIMATION_CLIPS_LICENSED_DIR`` overrides the location (tests). With only
    ``ANIMATION_CLIPS_DIR`` set, the licensed directory is ``<that>-licensed``
    — a test that sets the one never reads the real other.
    """
    override = os.environ.get("ANIMATION_CLIPS_LICENSED_DIR", "").strip()
    if override:
        return Path(override)
    free = os.environ.get("ANIMATION_CLIPS_DIR", "").strip()
    if free:
        return Path(free + "-licensed")
    return get_shared_dir() / "models" / "clips-licensed"


def get_trial_clips_dir() -> Path:
    """The TRIAL clip archive — the whole CMU database converted to browsable
    FBX clips plus ``_catalog.json`` / ``_index.json``.

    It is NOT a clip library: nothing here is served to the game, and
    ``animation_clips`` never scans it. It is the pool the catalog browser
    picks from; a take becomes a real clip only by being imported (re-cut,
    named) into ``shared/models/clips``. Gitignored, per installation.

    ``ANIMATION_CLIPS_TRIAL_DIR`` overrides the location — tests must set it,
    same rule as ANIMATION_CLIPS_DIR.
    """
    override = os.environ.get("ANIMATION_CLIPS_TRIAL_DIR", "").strip()
    if override:
        return Path(override)
    return get_shared_dir() / "models" / "clips-trial"


def get_mocap_source_dir() -> Path:
    """The downloaded ORIGINAL mocap recordings (``cmu/<subject>/*.asf|amc``).

    ``MOCAP_SOURCE_DIR`` overrides it; without the originals an import falls
    back to fetching the take from mocap.cs.cmu.edu.
    """
    override = os.environ.get("MOCAP_SOURCE_DIR", "").strip()
    if override:
        return Path(override)
    return get_shared_dir() / "models" / "mocap-src"


def get_animation_clips_dirs() -> list:
    """Both clip libraries, free first: ``[(dir, source)]`` with source
    ``"free"`` / ``"licensed"``."""
    return [(get_animation_clips_dir(), "free"), (get_licensed_clips_dir(), "licensed")]


def get_game_audio_dir() -> Path:
    """Music and ambience for the 3D client — world-independent user data in
    ``<repo>/audio/`` (``music/day|night/*``, ``ambient/<terrain>/*``).

    Gitignored like the animation clips and ``voices/``: the directory IS the
    interface, dropping a file in is the whole workflow. Served by
    ``app/routes/game_audio.py``; a missing directory is the normal state.
    """
    return _project_root / "audio"


def get_test_figure_dir() -> Path:
    """Shared neutral TEST FIGURE (a Mixamo standard character like X Bot) —
    world-independent, used by the admin previews for marker/scale figures.
    User-provided binary like the clips (gitignored); see the README there.

    ``TEST_FIGURE_DIR`` overrides the location — tests must set it (same
    rule as ANIMATION_CLIPS_DIR: never touch the real user files).
    """
    override = os.environ.get("TEST_FIGURE_DIR", "").strip()
    if override:
        return Path(override)
    return get_shared_dir() / "models" / "figure"


def get_templates_dir() -> Path:
    """Character templates directory (shared across all worlds).

    Seit der Reorganisation gibt es Unterordner fuer Character/User/Expression/Pose —
    diese Funktion zeigt explizit auf `character/`, damit Listing kein Type-Filter
    mehr braucht. Expression/Pose-Presets haben eigene Helfer (get_expression_dir, etc.).
    """
    return get_shared_dir() / "templates" / "character"


def get_config_dir() -> Path:
    """Shared JSON-Config-Dateien (languages, etc.)."""
    return get_shared_dir() / "config"


def get_languages_dir() -> Path:
    """UI translation files (one JSON per language code)."""
    return get_shared_dir() / "languages"


def get_expression_presets_dir() -> Path:
    """Expression-Presets fuer Bild-Generierung."""
    return get_shared_dir() / "templates" / "expression"


def get_schemas_dir() -> Path:
    """World-dev schemas are shared across all worlds."""
    return get_shared_dir() / "world_dev_schemas"


def get_config_path() -> Path:
    return get_storage_dir() / "config.json"


def get_secrets_path() -> Path:
    """Sensitive overlay (api keys, passwords) — gitignored, merged on top of config.json at load time."""
    return get_storage_dir() / "secrets.json"
