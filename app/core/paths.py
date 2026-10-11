"""Centralized path module — single source of truth for all storage paths.

Every file that needs a storage path imports from here instead of
defining its own ``STORAGE_DIR = Path("./storage")``.

Initialization order (in server.py):
    1. paths.init(storage_dir)          # from CLI / env
    2. paths.init_instance(instance_dir)  # from CLI / env (INSTANCE_DIR)
    3. config.load(paths.get_config_path(), paths.get_instance_config_path())
       # world config.json lives inside storage, instance config.json inside
       # the instance directory

THERE IS NO DEFAULT WORLD.  ``init`` takes the explicit argument, else the
``STORAGE_DIR`` environment variable, and raises ``StorageNotInitialised``
when it has neither; ``get_storage_dir()`` raises the same when nothing was
initialised at all.  The old silent fallback to ``./worlds/demo`` made every
script that reached world data before initialising — even lazily, e.g.
``game_time()`` -> world_kv -> a world-DB connection — write into the demo
world, which is TRACKED in git.  The default now lives where the server is
started (``start.sh``, ``docker/docker-entrypoint.sh``), not in this module.

Paths under ``shared/`` (templates, languages, schemas, clips, rig) are
repo-relative and deliberately need NO storage: a pure-shared script works
without a world.

THERE IS NO DEFAULT INSTANCE either.  The instance directory holds the
per-installation server config (``<instance>/config.json``) — everything that
belongs to the installation rather than to one world.  ``init_instance``
takes the explicit argument, else the ``INSTANCE_DIR`` environment variable,
and raises ``InstanceNotInitialised`` when it has neither.  The default
``<repo>/instance`` is set by ``start.sh``; Docker sets ``/app/instance``;
CLI tools pass ``--instance`` explicitly.
"""

import os
from pathlib import Path
from typing import Optional, Union

_storage_dir: Optional[Path] = None
_project_root: Path = Path(__file__).resolve().parent.parent.parent

_NOT_INITIALISED = (
    "storage not initialised — call app.core.paths.init(<dir>) or set "
    "STORAGE_DIR before touching world data"
)


class StorageNotInitialised(RuntimeError):
    """No storage root was chosen before world data was touched."""


_instance_dir: Optional[Path] = None

_INSTANCE_NOT_INITIALISED = (
    "instance not initialised — call app.core.paths.init_instance(<dir>) or "
    "set INSTANCE_DIR before touching the server config"
)


class InstanceNotInitialised(RuntimeError):
    """No instance directory was chosen before the server config was touched."""


def init(storage_dir: Optional[Union[str, Path]] = None) -> Path:
    """Set the storage root.  Called once by whoever starts server or script.

    Resolution order:
        1. Explicit *storage_dir* argument  (from CLI ``--storage`` / ``--world``)
        2. ``STORAGE_DIR`` environment variable

    No third step: without either, this raises ``StorageNotInitialised``
    instead of quietly picking the tracked demo world.
    """
    global _storage_dir

    if storage_dir:
        _storage_dir = Path(storage_dir).resolve()
    else:
        env = os.environ.get("STORAGE_DIR", "").strip()
        if not env:
            raise StorageNotInitialised(_NOT_INITIALISED)
        _storage_dir = Path(env).resolve()

    _storage_dir.mkdir(parents=True, exist_ok=True)
    return _storage_dir


def get_storage_dir() -> Path:
    """Return the base storage directory.

    Raises ``StorageNotInitialised`` when no world was selected — every other
    storage-derived accessor inherits that.
    """
    if _storage_dir is None:
        raise StorageNotInitialised(_NOT_INITIALISED)
    return _storage_dir


def make_private_dir(directory: Union[str, Path]) -> bool:
    """Create ``directory`` as 0700 when it is missing; returns True if it
    was created here.

    The parents come with the usual umask permissions. The chmod after the
    mkdir makes the mode independent of the umask — and it touches only a
    directory this call created: an existing one (the user's own choice of
    permissions) is left alone.
    """
    directory = Path(directory)
    directory.parent.mkdir(parents=True, exist_ok=True)
    try:
        directory.mkdir(mode=0o700)
    except FileExistsError:
        if not directory.is_dir():
            raise
        return False
    os.chmod(directory, 0o700)
    return True


def init_instance(instance_dir: Optional[Union[str, Path]] = None) -> Path:
    """Set the instance directory.  Called once by whoever starts server or tool.

    Resolution order:
        1. Explicit *instance_dir* argument  (from CLI ``--instance``)
        2. ``INSTANCE_DIR`` environment variable

    No third step: without either, this raises ``InstanceNotInitialised``.
    There is no default instance — ``start.sh`` / Docker set it.
    The directory is created when missing, private (0700): it holds the
    installation's keys and passwords. An existing directory keeps the
    permissions its owner gave it.
    """
    global _instance_dir

    if instance_dir:
        resolved = Path(instance_dir).resolve()
    else:
        env = os.environ.get("INSTANCE_DIR", "").strip()
        if not env:
            raise InstanceNotInitialised(_INSTANCE_NOT_INITIALISED)
        resolved = Path(env).resolve()

    make_private_dir(resolved)
    _instance_dir = resolved
    return _instance_dir


def get_instance_dir() -> Path:
    """Return the instance directory.

    Raises ``InstanceNotInitialised`` when none was selected — every other
    instance-derived accessor inherits that.
    """
    if _instance_dir is None:
        raise InstanceNotInitialised(_INSTANCE_NOT_INITIALISED)
    return _instance_dir


def get_instance_config_path() -> Path:
    """The per-installation server config: ``<instance>/config.json``."""
    return get_instance_dir() / "config.json"


def instance_initialised() -> bool:
    """True once ``init_instance`` has chosen a directory."""
    return _instance_dir is not None


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


def get_clips_inbox_dir() -> Path:
    """The INBOX for foreign animation files waiting to be imported.

    Whatever lies here (``*.fbx`` today) is offered in the Poses tab as "to be
    imported": probed for its skeleton family, cut to a window and retargeted
    onto the library rig (``app/core/fbx_import.py``). It is NOT a clip
    library — nothing scans it, nothing plays from it — and it is gitignored:
    the files a user drops in are almost always licensed material.

    ``ANIMATION_CLIPS_INBOX_DIR`` overrides the location — tests must set it,
    same rule as ANIMATION_CLIPS_DIR.
    """
    override = os.environ.get("ANIMATION_CLIPS_INBOX_DIR", "").strip()
    if override:
        return Path(override)
    return get_shared_dir() / "models" / "clips-inbox"


def get_rig_file() -> Path:
    """The RETARGET REFERENCE skeleton — ``shared/models/rig/reference.fbx``.

    One FBX with the project's ``mixamorig:`` armature and nothing else: no
    mesh, no animation. Every clip conversion is driven onto it
    (``app.core.cmu_import.default_rig()``), so all clips share one skeleton
    and one standing hip height — the height the client normalises against.

    It lives OUTSIDE the clip libraries on purpose: the libraries are content
    that may be emptied, replaced or deleted, and the importer's reference must
    not go with them. Tracked in git (CMU-derived, redistributable); see the
    README next to it for how to rebuild it.

    ``ANIMATION_RIG_FILE`` overrides the location — tests must set it, same
    rule as ANIMATION_CLIPS_DIR (never touch the real file).
    """
    override = os.environ.get("ANIMATION_RIG_FILE", "").strip()
    if override:
        return Path(override)
    return get_shared_dir() / "models" / "rig" / "reference.fbx"


def get_puppet_file() -> Path:
    """The UniMate PUPPET — ``shared/models/rig/puppet.glb``.

    One rigged GLB of a neutral humanoid (Mixamo rig, no textures) that every
    generated pose animation is computed on: the gateway alias animates the
    rig it is sent, and the result is retargeted onto ``reference.fbx`` like
    any foreign clip. It is never a character of a world. Tracked in git; the
    README next to it says where it comes from.

    ``ANIMATION_PUPPET_FILE`` overrides the location — tests must set it, same
    rule as ANIMATION_RIG_FILE. No existence check here: the caller reports a
    missing puppet.
    """
    override = os.environ.get("ANIMATION_PUPPET_FILE", "").strip()
    if override:
        return Path(override)
    return get_shared_dir() / "models" / "rig" / "puppet.glb"


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
    """The shared REFERENCE FIGURE — ``shared/models/figure/default.fbx``
    (or ``.glb``): THE figure wherever a body stands in for a body, i.e. the
    admin previews' marker and scale figures and the measurement smokes.
    World-independent, rigged on the project's skeleton, user-provided binary
    like the clips (gitignored); see the README there for the fallback chain.

    ``TEST_FIGURE_DIR`` overrides the location — tests must set it (same
    rule as ANIMATION_CLIPS_DIR: never touch the real user files).
    """
    override = os.environ.get("TEST_FIGURE_DIR", "").strip()
    if override:
        return Path(override)
    return get_shared_dir() / "models" / "figure"


def get_templates_dir() -> Path:
    """Character templates directory (shared across all worlds).

    Since the reorganisation there are subfolders for Character/User/Expression/
    Pose — this function points explicitly at `character/`, so listing needs no
    type filter any more. Expression/pose presets have their own helpers
    (get_expression_dir, etc.).
    """
    return get_shared_dir() / "templates" / "character"


def get_config_dir() -> Path:
    """Shared JSON config files (languages, etc.)."""
    return get_shared_dir() / "config"


def get_model_capabilities_path() -> Path:
    """Model capabilities + suitability test results.

    Shared across every world and tracked in git: a model's tool-calling /
    vision ability and its measured test scores describe the MODEL and the
    hardware behind it, not the world it happened to be tested from.
    Consolidated out of the old per-world files by
    ``model_capabilities_migration.migrate_model_capabilities_once``.
    """
    return get_config_dir() / "model_capabilities.json"


def get_model_capabilities_outputs_path() -> Path:
    """Raw model answers from the suitability test — LOCAL, never committed.

    The test replays REAL logged prompts, so the answers quote characters,
    places and plots from the world it was run against. That is study material
    for prompt tuning, not a result, and it has no place in a shared repo — so
    it is split off ``get_model_capabilities_path()`` and gitignored.
    """
    return get_config_dir() / "model_capabilities_outputs.json"


def get_languages_dir() -> Path:
    """UI translation files (one JSON per language code)."""
    return get_shared_dir() / "languages"


def get_schemas_dir() -> Path:
    """World-dev schemas are shared across all worlds."""
    return get_shared_dir() / "world_dev_schemas"


def get_config_path() -> Path:
    return get_storage_dir() / "config.json"
