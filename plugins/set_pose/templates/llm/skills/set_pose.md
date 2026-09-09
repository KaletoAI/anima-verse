---
name: SetActivity
action_hint: Character changes what they're physically doing right now (pose key + short detail)
---
Sets the character's current pose: a pose key from the catalog plus a short detail of what they do in it.

Pass JSON: {"pose": "<pose key>", "detail": "<what you do, 2-6 words>"}. The pose key MUST be one of the keys the prompt lists under "Places here" / "Anywhere here", copied exactly (e.g. "sitting", "standing", "reading"). "detail" is what a bystander would see — the object handled, the direction faced — in the character's own language; it carries no facial expression, no mood, no clothing. It may be left empty.

Only for something the character does ALONE. A pose marked *(with partner)* is a two-person action — it is started together via InteractWith, never here.
