"""The animation studio: clips written as code, built through the clip
pipeline of the main app, published license-free into shared/.

Every entry point calls :func:`bootstrap` BEFORE importing anything from
``app.*`` — the app has no default world, and the studio must never open
the world a running server holds (it gets a throwaway one).
"""
import atexit
import shutil
import sys
import tempfile
from pathlib import Path

STUDIO = Path(__file__).resolve().parents[1]
REPO = STUDIO.parent
ANIMS = STUDIO / "anims"
OUT = STUDIO / "out"

_booted = False


class StudioError(Exception):
    """A problem the author has to fix — printed, never a traceback."""


def bootstrap() -> None:
    """Repo root on sys.path + ``paths.init`` on a throwaway world + the
    installation's instance config (``INSTANCE_DIR``, else ``<repo>/instance``),
    so a studio Blender run counts against the server's
    ``blender_max_concurrent`` slots and uses its binary and switches;
    idempotent."""
    global _booted
    if _booted:
        return
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from app.core import paths
    world = tempfile.mkdtemp(prefix="animstudio-world-")
    atexit.register(shutil.rmtree, world, True)
    paths.init(world)
    from app.blender import runner
    runner.use_instance_config(REPO / "instance")
    _booted = True
