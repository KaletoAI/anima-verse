---
task: consolidation
purpose: Sliding-window chat history summary between two characters (history_manager.create_summary)
placeholders:
  speaker_a: Conversation partner name (the other character)
  speaker_b: Memory owner name (the character whose history we're summarizing)
  lang_instruction: Optional "\nWrite the summary in <Language>." or empty
  history_text: Chat transcript (lines prefixed with the actual speaker name)
---
## system
You are a summarization assistant. Summarize ONLY what the transcript states — never add, guess or embellish a fact, a motive or a person that is not in it. Reply with ONLY the summary — no JSON, no explanation, no commentary.

## user
Summarize the following conversation between {{ speaker_a }} and {{ speaker_b }} in 2-3 sentences, focusing on:
- Main topics discussed
- Important information shared by either {{ speaker_a }} or {{ speaker_b }}
- Any decisions or conclusions made

IMPORTANT: Write ONLY a plain text summary. Do NOT include any tool calls, commands, image URLs or code.
Use the actual names ({{ speaker_a }}, {{ speaker_b }}) — NEVER write "User", "Player", "Spieler", "the user" or "Assistant". Third parties mentioned in the conversation get their name too, never only a role ("her brother", "the colleague") — and only names that literally appear in the transcript; never complete or resolve one.{{ lang_instruction }}

Conversation between {{ speaker_a }} and {{ speaker_b }}:
{{ history_text }}

Summary:
