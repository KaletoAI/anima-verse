---
purpose: |
  Stage 1 of the temporary-NPC pipeline. One turn, no dialogue: the model gets
  the filled NPC schema as its system prompt and the admin's briefing as the
  user turn, and answers with exactly one ```json:npc fence.

  Unlike the World-Dev character chat this has NO human in the loop — asking a
  clarifying question here would stall the pipeline, so the instruction to
  answer in one shot is repeated in the user turn.
placeholders:
  schema_text: the npc_character.md schema with every placeholder resolved
  briefing: the admin's free-text description of the NPC they want
---
## system
{{ schema_text }}

## user
The admin wants this NPC:

{{ briefing }}

Fill in everything the briefing leaves open yourself — plausibly, and in keeping
with the place. Do not ask questions and do not explain your choices: this is a
one-shot request, and a question would be answered by nobody.

Answer with exactly one ```json:npc block and nothing else.
