"""on_load entry: the party package's decision point.

``party_join``: with a decision model configured, an ordinary NPC invited
to come along may join or decline at once instead of being woken
(docs/decision-models.md). Off by default — then nothing changes. The
decision itself runs in ``PartySkill._decide_join`` (skill.py), where the
invitation is created.
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
