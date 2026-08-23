{# The situational memory block. Rendered by
   ``app/core/memory_situational.py:render_block`` and appended to the CURRENT
   USER TURN of a chat reply (app/routes/chat.py) — never to the system
   prompt, whose cached prefix has to stay byte-identical.

   These are the character's own facts and open promises that came out closest
   to the incoming message by embedding similarity. They are already in the
   system prompt's memory section by importance and age; this block says
   "these ones are about what was just said".

   Rendered only when at least one memory cleared the threshold — an empty
   selection means no block at all, so this file never has to handle the
   empty case.

   Required:
     memories — list of {content, due, is_commitment}
                due: "in 20 min" / "in 3 h" / "overdue" / "" (commitments only)
#}
[You remember, and it bears on what was just said — use only what fits, never invent details:]
{# The entry line deliberately ends in an expression, not in a block tag: the
   loader runs Jinja with trim_blocks, which eats the newline after a closing
   {% ... %} and would glue every entry onto the previous one. #}
{% for m in memories %}
- {{ "You promised: " if m.is_commitment else "" }}{{ m.content }}{{ " (due: " ~ m.due ~ ")" if m.due else "" }}
{% endfor %}
