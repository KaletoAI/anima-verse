---
name: TalkTo
action_hint: Character speaks to someone present in the room
---
Speak face-to-face to a character who IS at your current location. Input: JSON {"name": "CharacterName", "message": "the spoken words"} — optionally add "volume": "whisper" (only the addressee hears the words) or "volume": "shout" (carries location-wide). Plain 'CharacterName, message' also works (normal volume). In an ACTIVE CHAT, never use this for the person you are already talking to — they receive your words through the RP itself; TalkTo is only for THIRD characters present. In an AUTONOMOUS turn (no active conversation) the opposite holds: your narrative prose is NOT delivered to anyone — TalkTo is the ONLY way your spoken words reach a present person, so route every spoken line through it. Do NOT use for remote contact (different location) — use SendMessage instead.
