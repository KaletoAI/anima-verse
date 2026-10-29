"""Lying down on a bed — the ENTRY bridge of every `lie` place (rule
walking -> @lie in clip_transitions.json): the library's get-up-bed played
backwards, so it ends exactly in the lying start the bed clips share and
starts standing where getting up ends."""
from animstudio.dsl import Reversed

ANIM = Reversed(kind="lie-down", source="get-up-bed")
