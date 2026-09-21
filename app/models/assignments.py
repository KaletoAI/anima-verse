"""Assignment text tags — the last living remnant of the old task feature.

The assignment feature itself is gone; its data model moved to
``app/models/intents.py``. What remains is the Tool-LLM marker syntax: the
thought prompt still offers ``[NEW_ASSIGNMENT: ...]`` (and characters
occasionally echo ``[ASSIGNMENT_UPDATE: ...]`` / ``[ASSIGNMENT_DONE: ...]``),
so a reply on its way to a user has to be cleaned of those tags.

``strip_assignment_tags`` is the only public name here.
"""
import re


def strip_assignment_tags(text: str) -> str:
    """Remove all assignment marker tags from display text."""
    text = re.sub(r'\n?\[ASSIGNMENT_(?:UPDATE|DONE):\s*[^\]]+\]', '', text)
    text = re.sub(r'\n?\[NEW_ASSIGNMENT:\s*[^\]]+\]', '', text)
    return text.strip()
