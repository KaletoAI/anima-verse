{# The [INTENT:] marker grammar — ONE source for both prompts that teach it.

   Included by chat/chat_stream.md (the character writes its own markers) and
   rendered by app/core/streaming.py::build_tool_decision_input (the rp_first
   tool LLM writes the markers the character forgot). Each caller supplies its
   own one-line lead-in in its own voice; the SYNTAX lives only here, so the
   two prompts cannot drift apart again.

   Parsed by app/models/intents.py::parse_and_apply_intent_markers.
   No variables — this fragment renders standalone. #}
[INTENT: <title> | <description> | when=<standing|now|in:2h|at_location:Place> | prio=<1-5> | by=<player|self>]
  when: standing=ongoing, now=act on it right away, in:2h=in 2 hours (or in:30m / in:1d), at_location:<Place>=on the next arrival at that place
  prio: 1=critical, 3=normal, 5=background
  by: player=the task was given by the person in the conversation (an errand, a promise, something to do later); self=a plan of one's own. Left out it counts as self.
To advance or finish one that already exists: [INTENT_PROGRESS: <id> | <note>] or [INTENT_DONE: <id>]
Only for genuine plans or tasks — never for hypothetical, past, or one-off roleplay actions.
