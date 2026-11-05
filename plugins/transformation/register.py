"""on_load: tables, the avatar's phrase intercept, the Transformation panel on
the character's Skills tab, the reset store and the expiry tick.

Executed again on every package (re)load, so everything here is idempotent:
``CREATE TABLE IF NOT EXISTS``, providers replaced under the same owner, the
reset handler replaced under the same key, the event callback replaced under
the same tag, both caches dropped.
"""
from contextlib import contextmanager

from app.core import hooks
from app.core.character_panels import panel_capability
from app.core.character_reset import SCOPE_REINIT, register_reset_store

from plugins.transformation import definitions, engine, intercept, panel, store

OWNER = "transformation"
#: The /play/say intercept capability (app.routes.play.SAY_INTERCEPT_CAPABILITY).
SAY_INTERCEPT = "play.say_intercept"

store.ensure_schema()
store.invalidate()
definitions.invalidate()

hooks.register_provider(SAY_INTERCEPT, intercept.say_intercept, owner=OWNER, multiple=True)
hooks.register_provider(panel_capability(OWNER), panel, owner=OWNER)


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
