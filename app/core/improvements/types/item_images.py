"""Improvement type: generate the image of every item that has none.

The clothing images of ``fill_missing`` cover the world's outfit pieces; this
type covers everything else an item can be — tools, keys, food, documents,
gifts, spells — and the shared-library items this world reaches
(``subjects.world_item_ids``: held by a character, placed in a room, or a part
one of those links). Not a subject (``subjects.item_image_exclusion``): a
hairstyle and every other mesh-only ``garment`` item (no image on purpose), and
a world outfit piece (the clothing images' subject, so nothing runs twice).

Key ``item:<id>:<t>``, <t> = ``key_token(image_prompt, prompt_fragment, name)``
— the item producer's subject text, as for the clothing images: an item whose
text changed is a new step.

The step renders through the item producer
(``item_images.generate_item_image_sync``), routed on the ``item`` occasion
unless an explicit image backend is picked. It is satisfied once the item's
selected image exists, and wrong once the item is deleted or excluded.
"""
from typing import Any, Dict, List

from app.core.improvements.base import Candidate, ImprovementType, ParamField
from app.core.improvements.types import subjects


def _item_id(key: str) -> str:
    """``item:<id>:<token>`` → ``<id>``; "" for a key of another shape."""
    head, _sep, rest = str(key or "").partition(":")
    return rest.split(":", 1)[0] if head == "item" else ""


def _key(item: Dict[str, Any]) -> str:
    return f"item:{item['id']}:" + subjects.key_token(item.get("image_prompt") or "",
                                                      item.get("prompt_fragment") or "",
                                                      item.get("name") or "")


class ItemImages(ImprovementType):
    id = "item_images"
    label = "Generate missing item images"
    description = ("Every item without an image — tools, keys, food, documents, spells and the shared items this "
                   "world uses. Clothing has its own subject under “Generate missing assets”; hairstyles get none.")

    @property
    def params_schema(self) -> List[ParamField]:
        auto = [{"value": "", "label": "Auto (routing)"}]
        return [ParamField("image_backend", "Image backend", "image_backend",
                           auto + subjects.image_backend_options(), required=False)]

    def find_candidates(self, params: Dict[str, Any]) -> List[Candidate]:
        out = [Candidate(_key(item), str(item.get("name") or item["id"]))
               for item in subjects.item_image_items()
               if not subjects.item_image_done(item["id"])]
        return sorted(out, key=lambda c: (c.label.lower(), c.key))

    def is_done(self, candidate: Candidate, params: Dict[str, Any]) -> bool:
        return subjects.item_image_done(_item_id(candidate.key))

    def invalid_reason(self, key: str, params: Dict[str, Any]) -> str:
        item_id = _item_id(key)
        if not item_id:
            return "not an item key"
        from app.models.inventory import get_item
        # strict: an unreadable item table raises — it must not read as "deleted".
        return subjects.item_image_exclusion(get_item(item_id, strict=True))

    def apply(self, candidate: Candidate, params: Dict[str, Any], task_id: str) -> None:
        subjects.generate_item_image(_item_id(candidate.key), params.get("image_backend", ""))
