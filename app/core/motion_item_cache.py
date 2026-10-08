"""World-scoped item snapshot for motion polls; shared file changes reload it."""
from threading import RLock

_lock = RLock()
_key = None
_items = None


def invalidate():
    """Called after item writes; readers rebuild once for all characters."""
    global _items
    with _lock:
        _items = None


def item_snapshot():
    """Read definitions once per world/write/shared-file version."""
    global _key, _items
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
        if _items is None or key != _key:
            shared = {item["id"]: item for item in inventory._load_shared_items()}
            shared.update({item["id"]: item for item in inventory._load_items()})
            _items = shared
            _key = key
        return _items
