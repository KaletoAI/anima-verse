---
task: consolidation
purpose: Scene summary for a room conversation (scene_manager.consolidate_scene, plan-room-conversation §7)
placeholders:
  location_name: Display name of the place
  room_name: Room within the location (may be empty)
  participants: Comma-separated character names who took part
  transcript: The scene transcript (lines prefixed with the actual speaker name)
  lang_instruction: Optional "\nWrite the summary in <Language>." or empty
---
## system
You summarize a scene that happened in a shared world. Be factual and concise.

## user
Summarize what happened in this scene at {{ location_name }}{% if room_name %} ({{ room_name }}){% endif %} in 3-6 sentences.
Participants: {{ participants }}.

Focus on:
- What concretely happened and what was decided (not just topics)
- Notable actions, reactions and shifts between the participants
- Anything that changed in the world (someone left, an object changed hands, an event resolved)

Write as a neutral narrative in past tense, naming the actual participants. NEVER write "User", "Player", "Spieler" or "Assistant". Do NOT include tool calls, markers, image URLs or code.{{ lang_instruction }}

Scene transcript:
{{ transcript }}
