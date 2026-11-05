"""on_load: tables, the four identity providers, the avatar's phrase
intercept, the identity lines of the scene state, the Transformation panel on
the character's Skills tab, the reset store and the expiry tick.

Executed again on every package (re)load, so everything here is idempotent:
``CREATE TABLE IF NOT EXISTS``, providers replaced under the same owner, the
reset handler replaced under the same key, the event callbacks replaced
under the same tags, both caches dropped.
"""
import copy
from contextlib import contextmanager

from app.core import hooks
from app.core.character_panels import panel_capability
from app.core.character_reset import SCOPE_REINIT, register_reset_store
from app.core.identity_view import (PROVIDER_ACTIVE, PROVIDER_COSTUME, PROVIDER_KNOWS,
                                    PROVIDER_NAMES)
from app.models.inventory import get_item

from plugins.transformation import (definitions, engine, intercept, knowers, panel,
                                    prompt_lines, store)

OWNER = "transformation"
#: The /play/say intercept capability (app.routes.play.SAY_INTERCEPT_CAPABILITY).
SAY_INTERCEPT = "play.say_intercept"

store.ensure_schema()
store.invalidate()
definitions.invalidate()


def active_persona(subject):
    """``identity.active_persona``: the persona ``subject`` wears, or None.

    A row whose persona is no longer configured answers None (real name).
    Besides the identity keys the answer carries the persona's settings —
    ``field_overrides`` (character prompt fields it replaces), ``pause_routine``,
    ``imagegen`` (backends + LoRAs) and ``suit_items`` — as copies, so a
    caller cannot change the cached definition."""
    row = store.get_active(subject)
    if row is None:
        return None
    d = definitions.load().get(row.persona_id)
    if d is None:
        return None
    item = get_item(d.item_id)
    portrait = f"/inventory/items/{d.item_id}/image" if item and item.get("image") else ""
    return {"persona_id": d.id, "alias": d.alias, "description": d.description,
            "portrait_url": portrait,
            "field_overrides": dict(d.prompt_overrides),
            "pause_routine": d.pause_routine,
            "imagegen": copy.deepcopy(d.imagegen),
            "suit_items": list(d.suit_items)}


def knows(observer, subject):
    """``identity.knows``: whether ``observer`` is in on ``subject``'s persona."""
    row = store.get_active(subject)
    if row is None:
        return False
    return knowers.knows(observer, subject, row.persona_id)


def persona_names():
    """``identity.persona_names``: every usable alias, worn or not."""
    return [d.alias for d in definitions.load().values()]


def costume_items():
    """``identity.costume_items``: ``{suit item id: persona id}`` over every
    usable persona (disabled or unusable ones lock nothing). An item in two
    suits belongs to the older persona (creation order)."""
    out = {}
    for d in definitions.load().values():
        for item_id in d.suit_items:
            out.setdefault(item_id, d.id)
    return out


hooks.register_provider(PROVIDER_ACTIVE, active_persona, owner=OWNER)
hooks.register_provider(PROVIDER_KNOWS, knows, owner=OWNER)
hooks.register_provider(PROVIDER_NAMES, persona_names, owner=OWNER)
hooks.register_provider(PROVIDER_COSTUME, costume_items, owner=OWNER)
hooks.register_provider(SAY_INTERCEPT, intercept.say_intercept, owner=OWNER, multiple=True)
hooks.register_provider(panel_capability(OWNER), panel, owner=OWNER)
hooks.register("character.prompt_context", prompt_lines.on_prompt_context,
               tag="transformation.lines")
hooks.register("character.thought_context", prompt_lines.on_thought_context,
               tag="transformation.thought_lines")


@contextmanager
def _invalidate_after_commit(name):
    """Reset guard: held around the handler's transaction, so the cache is
    dropped only once the delete is committed."""
    try:
        yield
    finally:
        store.invalidate()


# Only the per-character state: the persona definitions are world content and
# survive every character reset.
register_reset_store(
    "transformation", store.delete_character_rows, (SCOPE_REINIT,),
    what="active transformation and persona cooldowns",
    lock=_invalidate_after_commit)

hooks.register("world_tick", engine.tick, tag="transformation.tick")
