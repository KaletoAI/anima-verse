---
task: random_event
purpose: Escalate an unanswered disruption/danger event (random_events._escalate_event)
placeholders:
  old_text: Previous event text
  new_category: New category (e.g. "danger")
  language_name: Target language name
---
## system
You escalate roleplay events. Make them more urgent.

LANGUAGE: Write the escalated event in {{ language_name }}. Use no other language.

## user
An event happened but nobody reacted:
"{{ old_text }}"

The situation has escalated. Write the NEXT event — more urgent, more serious, demanding immediate action.
Category: {{ new_category }}
Write the event in {{ language_name }} — no other language.
Write ONE short sentence (max 120 characters).
Reply with ONLY the escalated event text.
