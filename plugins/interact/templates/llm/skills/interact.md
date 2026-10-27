---
name: InteractWith
action_hint: Character proposes or answers a specific shared PHYSICAL action with a present partner (holding hands, embracing, dancing together); accept only an actual invitation addressed to this character
---
Propose a shared physical action to ONE other character who is right here with you: a handshake, holding hands, an embrace, a dance together, and similar two-person actions. Pass JSON: {"partner": "<exact complete character name>", "action": "<what you do together>"}. Copy the partner's complete name exactly from the present-character list or the invitation; never use only a first name, a nickname, a pronoun or a guessed character. The action is matched against the known two-person poses; use the offered actions and tool results, do not invent an unavailable pair pose. Only for someone present in your room and close by — use TalkTo for talking, SetActivity for something you do alone.

It takes two. The other one is ASKED, and nothing happens until they agree — you cannot put someone into a shared action. The same tool has three uses:

* **You propose it** — call it with your idea. The other one now has your question. Someone requesting a shared action is a reason to propose it, not proof that the other participant has consented.
* **You accept** — an actual pending invitation names YOU as the invitee and identifies this partner and this specific action (you will be told so). If you want that action, call it back with the exact same partner and action, and the action starts for both of you. A third person's request, a general wish, affectionate dialogue, agreement to another action or narrative describing a pair is not acceptance of this invitation.
* **You refuse** — call it back with the same partner and action plus `"answer": "no"`, and say in character why. Do not just stay silent: the other one is waiting for an answer.

Furniture-bound actions use a separate exact question, not a general pose invitation. When offered an `execution_id`, answer this question with `{"execution_id": "<offered id>", "answer": "yes"}` or `"answer": "no"`. This binds only that action, revision, partner, object and role allocation. A different object or a same-named pose is a new proposal, never consent to the old question. Without an explicit answer the question stays open.

Do not claim the pair has started unless the tool result says it has; an unanswered proposal is still waiting. For the same shared action, do not also call SetActivity before or after InteractWith: it is not a second step and a solo pose change can stop a pair that just started.
