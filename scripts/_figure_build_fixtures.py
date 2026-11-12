"""Shared smoke helpers for the automatic Build (plan
docs/superpowers/plans/2026-11-12-unified-worn-pieces.md Task 8).

Since Task 8 every automatic trigger of the figure pipeline — the outfit
change, ``garments.after_base_model`` (body change),
``base_body.after_mesh_item_ready`` (piece ready),
``base_body.after_piece_detail_change``, ``model3d.maybe_auto_generate_for_outfit``
— is a ``figure_build.request``: an automatic Build in its own worker thread.
A smoke that measures a producer (chain, outfit model, views) must not have
such a Build running beside it, and a smoke that tested what a trigger used to
do directly now runs the Build's own step for it:

* ``record_requests()`` — ``figure_build.request`` becomes a recorder; returns
  the list it appends ``(character, trigger)`` to. The trigger itself (that a
  hook asks the Build) is covered by ``scripts/smoke_figure_auto_build.py``.
* ``build_chains(name)`` — the Build's garment steps after a body change: the
  ``pieces`` / ``hair`` steps of ``figure_build.plan`` that are not cached
  failures, each run by ``figure_build._RUNNERS`` (``garments.run_queued``, an
  automatic run), blocking. True when one ran.
"""
from typing import List, Tuple


def record_requests() -> List[Tuple[str, str]]:
    from app.core import figure_build
    calls: List[Tuple[str, str]] = []

    def request(character_name, trigger):
        calls.append((character_name, trigger))
        return True
    figure_build.request = request
    return calls


def build_chains(name: str) -> bool:
    from app.core import figure_build
    steps = [s for s in figure_build.plan(name) if s.name in ("pieces", "hair") and not s.failed]
    for step in steps:
        figure_build._RUNNERS[step.name](name, step, False)
    return bool(steps)
