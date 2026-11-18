"""Shared fixture of the image-routing smokes (smoke_image_routing_resolve, smoke_image_routing_runtime,
smoke_image_service_facade) — not a smoke itself: the leading underscore keeps it out of run_smokes.py's
``smoke_*`` glob.

What it holds is what those smokes had three to five copies of: the throwaway storage set-up, the house
``check(label, got, expected)`` and one fake backend that never touches a network.

    from _smoke_image_routing import scratch
    os.environ["ANIMATION_CLIPS_DIR"] = scratch("routing-x-clips-")
    from app.core import paths
    paths.init(scratch("routing-x-storage-"))     # in the smoke itself: smoke_scripts_storage_lint sees it there
    from _smoke_image_routing import FAILS, Fake, check

``scratch`` makes a directory removed at exit. ``Fake`` is built on first import, so importing ``scratch`` imports
nothing of ``app`` before the storage redirect. The façade smoke (its own config + instance set-up) only imports
``check`` / ``Fake``.
"""
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FAILS = []


def scratch(prefix):
    p = tempfile.mkdtemp(prefix=prefix)
    atexit.register(shutil.rmtree, p, ignore_errors=True)
    return p


def check(label, got, expected):
    ok = got == expected
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {got!r}"
          + ("" if ok else f" (expected {expected!r})"))
    if not ok:
        FAILS.append(label)


def _make_fake():
    from app.imagegen.base import ImageBackend

    class Fake(ImageBackend):
        """A backend that renders locally (``result``) or refuses to render (``result=None`` -> AssertionError).

        Defaults are the img2img fake of the runtime smokes; the resolution smoke passes media / category / cost /
        ref / enabled per backend. ``probes`` counts availability checks."""

        def __init__(self, name, cost=1, *, media="image", category="img2img", ref=1, enabled=True,
                     available=True, result=(b"img",), env_prefix="FAKE_ROUTING_"):
            super().__init__(name, "http://localhost", float(cost), "fake", env_prefix)
            self.MEDIA_TYPE = media
            self.category = category
            self.ref_slot_count = ref
            self.instance_enabled = enabled
            self._available = available
            self._result = None if result is None else list(result)
            self.probes = 0

        def check_availability(self):
            self.probes += 1
            return self.available

        def _generate(self, prompt, negative_prompt, params):
            if self._result is None:
                raise AssertionError("no real generate in this smoke")
            return list(self._result)

    return Fake


def __getattr__(name):
    """``Fake`` is built on first import, so importing ``init_storage`` imports nothing of ``app`` yet."""
    if name == "Fake":
        globals()["Fake"] = cls = _make_fake()
        return cls
    raise AttributeError(name)
