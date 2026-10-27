---
name: SetActivity
action_hint: Changes only the character's own solo free body pose or room-owned marker; never claims furniture or starts a shared action
---
Sets a free body pose (or an existing room-owned marker), never allocates furniture or bypasses a prop action's rules. For furniture use PropAction with an offered action ID, current revision and exact target instead. An explicit call interrupts the character's own current semantic action.

Pass JSON: {"pose": "<solo pose key>", "detail": "<visible action, 2-6 words, third person>"}. Copy an offered free pose key exactly. Detail is display text, not consent, a prop target, sleep state or a rule override; it may be empty.

Only for something the character does ALONE. A pose marked *(with partner)* is a two-person action — it is started together via InteractWith, never here. A shared action remains a pair action even if its name also sounds like an ordinary solo pose: dancing with someone, holding hands or embracing them is not a solo activity. Do not hide the partner or shared action in "detail".

For one shared action, call InteractWith, not both tools. Do not add SetActivity to illustrate or confirm a pair proposal, acceptance or start: changing your solo pose can end the pair that just started. Use SetActivity only for a separate, genuinely solo activity you intend to switch to.
