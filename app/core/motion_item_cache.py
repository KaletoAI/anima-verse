"""World-scoped item snapshot for motion and passive bonuses; shared edits reload it."""
from threading import RLock

_lock = RLock()
_key = None
_items = None
_carried_bonus_ids = frozenset()
_strict_snapshot = False


def invalidate():
    """Called after item writes; readers rebuild once for all characters."""
    global _items
    with _lock:
        _items = None


def item_snapshot(*, strict: bool = False):
    """Read definitions once per world/write/shared-file version and trust level."""
    global _key, _items, _carried_bonus_ids, _strict_snapshot
    from app.core.paths import get_storage_dir
    from app.models import inventory
    with _lock:
        path = inventory._get_shared_items_file()
        try:
            stat = path.stat()
            stamp = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
        except FileNotFoundError:
            stamp = None
        key = (get_storage_dir(), path, stamp)
        if _items is None or key != _key or (strict and not _strict_snapshot):
            shared = {item["id"]: item for item in inventory._load_shared_items(strict=strict)}
            shared.update({item["id"]: item for item in inventory._load_items(strict=strict)})
            _carried_bonus_ids = frozenset(
                iid for iid, item in shared.items()
                if (item.get("properties") or {}).get("bonus_when") == "carried"
                and (item.get("properties") or {}).get("stat_bonuses"))
            _items = shared
            _key = key
            _strict_snapshot = strict
        return _items


def passive_bonus_snapshot(*, strict: bool = False):
    """Return definitions and carried bonus IDs from the same cached version."""
    with _lock:
        return item_snapshot(strict=strict), _carried_bonus_ids
