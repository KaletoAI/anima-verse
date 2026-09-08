---
name: InteractWith
action_hint: Character does something TOGETHER with a present character (shake hands, dance with them) — a shared, synchronised action
---
Propose a shared physical action to ONE other character who is right here with you: a handshake, a dance together, and similar two-person actions. Pass JSON: {"partner": "<character name>", "action": "<what you do together>"}. The action is matched against the known two-person poses; the tool result tells you which ones exist. Only for someone present in your room and close by — use TalkTo for talking, SetActivity for something you do alone.

It takes two. The other one is ASKED, and nothing happens until they agree — you cannot put someone into a shared action. So the same tool has two uses:

* **You propose it** — call it with your idea. The other one now has your question.
* **You accept** — someone asked YOU (you will be told so). Call it back with the same partner and the same action, and the action starts for both of you.
* **You refuse** — call it back with the same partner and action plus `"answer": "no"`, and say in character why. Do not just stay silent: the other one is waiting for an answer.
