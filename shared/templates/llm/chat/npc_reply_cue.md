[SCENE STATE — reply requirement, nobody said this.]
Your next reply is only the actual spoken answer of this NPC, normally one or two short sentences. No narration, actions, thoughts, gestures, delivery descriptions or quotation marks, even when earlier assistant replies contain them. Keep actual tool calls and required intent/state markers separate from the spoken line.
{% if skip_allowed | default(false) %}
If you have nothing natural to add in this optional or closing turn, reply with exactly SKIP.
{% endif %}
[END OF SCENE STATE]
