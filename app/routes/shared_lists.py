"""Read-only shared seed lists the admin UI renders its option pickers from.

One route per list under ``shared/config/``. The point is that a list the UI
offers exists exactly ONCE — in the repo's shared seed — instead of being
re-typed in every component that offers it. The mood list used to live in
``shared/config/moods.json`` plus two hand-maintained React copies, and the
copies had already drifted apart (``chatting`` was missing from one of them).

Mounted under ``/admin`` because these are option lists for the Game-Admin
surfaces (character placement, item effects), which makes them admin-only
through the blanket prefix rule of the auth gate — the explicit
``require_admin`` below says the same thing at the route.
"""
import json
from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from app.core.auth_dependency import require_admin
from app.core.log import get_logger
from app.core.paths import get_config_dir

logger = get_logger("shared_lists")

router = APIRouter(prefix="/admin/shared-lists", tags=["shared_lists"])


def load_moods() -> List[str]:
    """The mood ids from ``shared/config/moods.json``, in file order.

    Order is the file's — it is a hand-curated suggestion order, not
    alphabetical. A malformed or missing file yields an empty list: a mood is
    free text, so an empty suggestion list costs suggestions, never the
    ability to set a mood.
    """
    path = get_config_dir() / "moods.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("moods.json not readable (%s): %s", path, e)
        return []
    out: List[str] = []
    for entry in data.get("moods") or []:
        mood_id = (entry.get("id") or "").strip() if isinstance(entry, dict) else ""
        if mood_id and mood_id not in out:
            out.append(mood_id)
    return out


@router.get("/moods")
def get_moods(_user: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Mood ids the UI offers as suggestions.

    A mood is FREE TEXT in the backend — ``current_feeling`` is never
    validated against this list and ``mood_influence`` is stored verbatim.
    These are the curated suggestions, not a vocabulary. Localized labels come
    from ``shared/languages/<lang>.json``, where the ids are the keys verbatim.
    """
    return {"moods": load_moods()}
