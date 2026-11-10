"""The per-item, world-scoped shoe source (plan
``docs/superpowers/plans/2026-11-10-footwear-rigid-shoes.md``, spec
``docs/superpowers/specs/2026-11-10-footwear-rigid-shoes-design.md`` § 5.2,
§ 5.3, § 5.6): one source per item, whoever wears it.

``ssig`` = md5[:12] over the item image's sha256, ``FOOTWEAR_SOURCE_VERSION``
and the seed of a forced Regenerate (0 = never regenerated). Task 1 holds the
signature only; the store and the steps ``source → empty → cutout → mesh``
land in Task 4.
"""
import hashlib
import json
from pathlib import Path
from typing import Any, Dict

#: Bumped when the source steps change what they produce (part of ``ssig``).
FOOTWEAR_SOURCE_VERSION = 1


def _md5(payload: Dict[str, Any]) -> str:
    digest = hashlib.md5(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8"))
    return digest.hexdigest()[:12]


def item_image_sha256(item_id: str) -> str:
    """sha256 of the item's image file, "" without one."""
    from app.core.base_body import file_sha256
    from app.models.inventory import get_item_image_path
    path = get_item_image_path(item_id)
    return file_sha256(Path(path)) if path else ""


def ssig_for(item_id: str, seed: int) -> str:
    """md5[:12] over ``{image, version, seed}`` (module docstring)."""
    return _md5({"image": item_image_sha256(item_id), "version": FOOTWEAR_SOURCE_VERSION, "seed": int(seed)})


def current_ssig(item_id: str) -> str:
    """The ssig of the item's current source: seed 0 until a Regenerate
    exists (Task 4 reads the seed from the item's ``current.json``)."""
    return ssig_for(item_id, 0)
