---
name: SetActivity
action_hint: Explicitly changes a free body pose or room-owned marker; never claims furniture
---
Sets a free body pose (or an existing room-owned marker), never allocates furniture or bypasses a prop action's rules. For furniture use PropAction with an offered action ID, current revision and exact target instead. An explicit call interrupts the character's own current semantic action.

Pass JSON: {"pose": "<solo pose key>", "detail": "<visible action, 2-6 words, third person>"}. Copy an offered free pose key exactly. Detail is display text, not consent, a prop target, sleep state or a rule override; it may be empty.

Only for something the character does ALONE. A pose marked *(with partner)* is a two-person action — it is started together via InteractWith, never here.
