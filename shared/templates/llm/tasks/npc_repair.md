---
purpose: |
  Stage 3 of the temporary-NPC pipeline. The draft from stage 1 plus the gap
  list from stage 2 go back to the same model, which re-emits the COMPLETE NPC.

  Emitting only the changed keys was tried and is a trap: the apply step takes
  one flat object, so a partial answer silently drops every field it omits.
  Hence the "complete object, every field" instruction.
placeholders:
  schema_text: the npc_character.md schema with every placeholder resolved
  draft_json: the stage-1 draft, pretty-printed JSON
  gaps: the validator's findings, one `- ...` line each
---
## system
{{ schema_text }}

## user
This is the draft you produced:

```json
{{ draft_json }}
```

These points are wrong or missing:

{{ gaps }}

Fix exactly those points. Leave everything else as it is — do not rewrite fields
that were not criticised, and do not invent new ones.

Answer with the COMPLETE NPC again, every field included, as exactly one
```json:npc block and nothing else. A partial object loses every field it omits.
