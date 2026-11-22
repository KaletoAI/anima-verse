"""Boot migration (pair scene spec 2026-11-22): pre-fill the lead role of
multi-person poses.

The core decides nothing itself. For every multi-person pose that stores no
``lead_role`` it asks the package provider
``pose.lead_role_default(pose_key, roles, role_gender) -> role`` once, with
the role assignment of the pose's own ``animation`` clip (its sidecar), and
stores a valid answer in the store the entry came from — the world layer for a
world entry, the shared file for a shared one, as the Poses editor writes it.
No provider, an empty or invalid answer: nothing is stored, and
``pose_catalog.lead_role_of`` falls back to role "a". A pose that already
carries the field is never asked again, so repeated boots change nothing.
"""
from typing import Dict

from app.core.log import get_logger

logger = get_logger(__name__)


def migrate_lead_role_once() -> int:
    """Ask the provider for each multi-person pose without a lead role;
    returns the entries written."""
    from app.core.hooks import get_provider
    provider = get_provider("pose.lead_role_default")
    if not provider:
        return 0
    from app.core import animation_clips, pose_catalog
    from app.core.pose_catalog_edit import catalog_txn, read_store, write_store
    written = 0
    with catalog_txn("pose"):
        docs: Dict[str, dict] = {}
        changed = set()
        for key, entry in pose_catalog.get_catalog("pose").items():
            people = int(entry.get("participants") or 1)
            if people < 2:
                continue
            store = entry.get("_store") or "shared"
            if store not in docs:
                docs[store] = read_store("pose", store)
            raw = docs[store]["entries"].get(key)
            if not isinstance(raw, dict) or "lead_role" in raw:
                continue
            roles = list(pose_catalog.ROLES[:people])
            gender = animation_clips.clip_role_gender(
                animation_clips.clip_meta(entry.get("animation") or ""))
            try:
                answer = str(provider(pose_key=key, roles=roles, role_gender=gender) or "").strip().lower()
            except Exception:
                logger.exception("pose.lead_role_default provider failed for %s", key)
                continue
            if answer not in roles:
                continue
            raw["lead_role"] = answer
            changed.add(store)
            written += 1
        for store in changed:
            write_store("pose", docs[store], store)
    return written
