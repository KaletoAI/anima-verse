"""on_load: tables, the expected-present answer of a linked family, the
avatar's phrase intercept, the secrecy lines of the scene state, the
Transformation panel on the character's Skills tab, the reset store and the
expiry tick.

Executed again on every package (re)load, so everything here is idempotent:
``CREATE TABLE IF NOT EXISTS`` (an old table shape is re-created once),
providers replaced under the same owner, the reset handler replaced under the
same key, the event callbacks replaced under the same tags, both caches
dropped.
"""
from contextlib import contextmanager

from app.core import hooks
from app.core.character_panels import panel_capability
from app.core.character_reset import SCOPE_REINIT, register_reset_store
from app.core.linked_characters import EXPECTED_PRESENT_PROVIDER

from plugins.transformation import definitions, engine, intercept, panel, prompt_lines, store

OWNER = "transformation"
#: The /play/say intercept capability (app.routes.play.SAY_INTERCEPT_CAPABILITY).
SAY_INTERCEPT = "play.say_intercept"

store.ensure_schema()
store.invalidate()
definitions.invalidate()

hooks.register_provider(EXPECTED_PRESENT_PROVIDER, engine.expected_present, owner=OWNER)
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


# Only the leader's state: the definitions are world content and survive
# every character reset; the knowers are a secret of the mind.
register_reset_store(
    "transformation", store.delete_character_rows, (SCOPE_REINIT,),
    what="active transformation and transformation cooldowns",
    lock=_invalidate_after_commit)

hooks.register("world_tick", engine.tick, tag="transformation.tick")
