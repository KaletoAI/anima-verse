"""Register the party decision point and consent-bound intent runtime.

The party package owns the targeted NPC continuation; the core only emits
generic intent/world events and consumes optional capability providers.
"""
from app.core import decision
from plugins.party.skill import PARTY_JOIN

decision.register_point(
    PARTY_JOIN,
    label="Party invitation: join?",
    description=("An NPC invited to come along with a group decides whether it joins; "
                 "in mode 'on' a confident answer settles the invitation at once, "
                 "otherwise the NPC is woken as before."),
    default_min_confidence=0.75,
    default_timeout_s=3.0,
    origin="party",
)

from plugins.party.trip_intents import register

register()
