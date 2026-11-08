"""A pair action started WITHOUT asking (consent "react") and the partner's
reaction to it — shared by the two pair flows:

* ``prop_action`` — a furniture pair run (``prop_action_engine``, the
  reference is its ``execution_id``);
* ``interaction`` — a free pair pose (``interaction_engine``, the reference
  is the ``invite_id`` of its ``reacting`` row).

Both ask the ``pair_reaction`` provider the same way (:func:`ask`), wait for
the answer at most :data:`REACTION_WAIT_S`, take the answer through
:func:`answer` and book it on the relationship with :func:`book`. Which words
the reaction prompt uses for the action comes from :func:`pending`, so the
package answering it never needs to know either engine.
"""
from app.core.log import get_logger
from app.core.timeutils import parse_iso, utc_now

logger = get_logger("pair_reaction")

#: The two kinds of pair action a reaction can belong to.
KINDS = ("prop_action", "interaction")

#: A react pair waits this long (SYSTEM seconds: it waits for a model, not for
#: the world) for the partner's reaction; without one it goes on as accepted.
REACTION_WAIT_S = 60.0
#: Relationship change per ``feeling`` step (-2..2) of a reaction: the
#: partner's sentiment toward the actor, romantic tension for a romantic
#: action; a resisted actor's own sentiment drops by the fixed amount.
SENTIMENT_STEP = 0.05
ROMANTIC_STEP = 0.02
RESISTED_ACTOR_SENTIMENT = -0.03


def request_state(partner: str) -> dict:
    """The reaction a react pair starts with: ``player`` — a player-controlled
    partner reacts in the HUD (it can stop the pair), nothing waits;
    ``none`` — no package supplies ``pair_reaction``, nothing waits;
    ``pending`` — the model is asked, the pair waits for it."""
    from app.core.hooks import get_provider
    from app.models.account import is_player_controlled
    if is_player_controlled(partner):
        state = "player"
    elif get_provider("pair_reaction") is None:
        state = "none"
    else:
        state = "pending"
    return dict(state=state, asked_at=utc_now().isoformat())


def waited_s(asked_at: str) -> float:
    """System seconds since the reaction was asked; a missing or broken
    stamp counts as the whole wait (the pair goes on)."""
    try:
        return (utc_now() - parse_iso(asked_at)).total_seconds()
    except (AttributeError, TypeError, ValueError):
        return REACTION_WAIT_S


def clamp_feeling(feeling) -> int:
    try:
        return max(-2, min(2, int(feeling)))
    except (TypeError, ValueError):
        return 0


def ask(kind: str, reference: str, actor: str, partner: str) -> None:
    """Hand the reaction to the ``pair_reaction`` provider after every lock;
    the provider returns at once and answers through :func:`answer`."""
    from app.core.hooks import get_provider
    from app.core.keyed_lock import _after_locks
    provider = get_provider("pair_reaction")
    if provider is None:
        return

    def call():
        try:
            provider(kind=kind, reference=reference, actor=actor, partner=partner)
        except Exception as e:
            logger.warning("pair_reaction provider failed for %s %s: %s", kind, reference, e)

    _after_locks(call)


def pending(kind: str, reference: str, actor: str, partner: str, lang: str = "en") -> dict | None:
    """What still waits for ``partner``'s reaction, in words: ``{"action":
    <label>, "piece": <furniture name or "">}`` — or None when that pair
    action no longer waits (answered, timed out, ended, someone else's)."""
    if kind == "prop_action":
        from app.core import prop_action_store as runs
        from app.core.i18n import localized
        from app.core.prop_actions import piece_label
        run = runs.get(reference)
        if (not run or run["members"] != [partner] or run["actor"] != actor
                or (run["data"].get("reaction") or {}).get("state") != "pending"):
            return None
        action = localized(run["definition"], "name", lang) or run["definition"].get("name") or ""
        return {"action": action, "piece": piece_label(run["target"], lang)}
    if kind == "interaction":
        from app.core.interaction_engine import get_invite
        from app.core.pose_catalog import pose_label
        inv = get_invite(reference)
        if (not inv or inv["status"] != "reacting" or inv["inviter"] != actor
                or inv["invitee"] != partner):
            return None
        return {"action": pose_label(inv["pose_key"], lang), "piece": ""}
    return None


def answer(kind: str, reference: str, partner: str, accept: bool, *, line: str = "",
           feeling: int = 0, romantic: bool = False) -> dict:
    """The partner's reaction, routed to the engine the pair action belongs
    to (``prop_action_engine.react`` / ``interaction_engine.react``). An
    unknown ``kind`` is refused (``{"status": "refused", "reason":
    "invalid_kind"}``)."""
    if kind == "prop_action":
        from app.core.prop_action_engine import react
    elif kind == "interaction":
        from app.core.interaction_engine import react
    else:
        return {"status": "refused", "reason": "invalid_kind"}
    return react(partner, reference, accept, line=line, feeling=feeling, romantic=romantic)


def book(actor: str, partner: str, action: str, accepted: bool, feeling: int,
         romantic: bool) -> None:
    """The reaction's mark on the pair, after every lock: the partner's
    sentiment toward the actor by ``feeling``, romantic tension for a romantic
    action, and a resisted actor's own sentiment (``record_interaction`` type
    ``pair_reaction``)."""
    from app.core.keyed_lock import _after_locks

    def write():
        try:
            from app.models.relationship import record_interaction
            record_interaction(
                partner, actor, "pair_reaction",
                summary=f"{partner} {'accepted' if accepted else 'resisted'} {actor}'s {action}",
                sentiment_delta_a=SENTIMENT_STEP * feeling,
                sentiment_delta_b=0.0 if accepted else RESISTED_ACTOR_SENTIMENT,
                strength_delta=1.0,
                romantic_delta=ROMANTIC_STEP * feeling if romantic else 0.0)
        except Exception as e:
            logger.warning("booking the reaction of %s failed: %s", partner, e)

    _after_locks(write)
