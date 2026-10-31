---
name: PropAction
action_hint: Walk to and use a furniture action offered here, or stop the character's own one
---
Use a furniture action offered in this room: {"furniture": "<furniture name>", "action": "<action name>", "partner": "<name, only for an action with partners>"} — names exactly as listed. The server picks the nearest free piece of that name. To stop your own action or withdraw your question: {"stop": true}.

A request starts walking there; it is not instant success. A pair starts only when the partner agrees. A free body pose without furniture is SetActivity.
