"""Garment assembly — the served 3D model = bare outfit model + grafted
garment meshes (plan 2026-11-09-base-body-phase4-hair R11).

Placeholder until the assembly layer lands (task 7 of that plan): the
inventory already calls ``schedule`` whenever a mesh-only garment is equipped
or taken off, so the hook point exists before the builder does.
"""
from typing import Optional


def schedule(character_name: str, signature: Optional[str] = None) -> bool:
    """Ask for a background rebuild of the character's assembled model
    (``signature=None`` = the current outfit). No-op for now: returns False,
    nothing is scheduled."""
    return False
