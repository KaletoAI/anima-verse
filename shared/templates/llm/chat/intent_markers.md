{# The [INTENT:] marker grammar — ONE source for every prompt that teaches it.

   Included by chat/chat_stream.md and chat/agent_thought.md (the character
   writes its own markers) and rendered by
   app/core/streaming.py::intent_marker_help for both rp_first tool-decision
   prompts (the tool LLM writes the markers the character forgot). Each caller
   supplies its own one-line lead-in in its own voice; the SYNTAX and the
   by=player rule live only here, so the prompts cannot drift apart again.
   "An open plan listed in this prompt": where a caller has the character's
   open plans, it shows them WITH their ids in the same prompt (the
   assignments block, or the compact id | title list of the room tool
   decision) — not necessarily below this fragment, hence "in this prompt".

   Parsed by app/models/intents.py::parse_and_apply_intent_markers.
   No variables — this fragment renders standalone. #}
[INTENT: <title> | <description> | when=<standing|now|in:2h|at_location:Place> | prio=<1-5> | by=<player|self>]
  when: standing=ongoing; now=the character sets off to do it on its own right after this exchange — never for something the reply already does; in:2h=in 2 hours (or in:30m / in:1d); at_location:<Place>=on the next arrival at that place
  prio: 1=critical, 3=normal, 5=background
  by: player=the OTHER person explicitly asked the character to do it — the request stands in THEIR words. self=everything else, even when it concerns the other person. When in doubt: self. Left out it counts as self.
Only for something still to be done AFTER this reply — never for hypothetical or past actions. What the reply itself already does (showing, handing over, answering, a feeling, a wish about how something should go) is never an intent.
If an open plan listed in this prompt already covers it — even in other words — write [INTENT_PROGRESS: <id> | <note>] instead of a new [INTENT:], or [INTENT_DONE: <id>] once it is done.
