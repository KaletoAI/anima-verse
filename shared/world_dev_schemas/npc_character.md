# Schema: Temporary NPC

{world_setup_block}You design a **temporary NPC** — a short-lived background character
that fills a role in one place for a while and is thrown away again afterwards.

A temporary NPC is NOT a full character. It has no memory, no relationships, no
diary, no goals system, no wardrobe and no autonomous inner life. It stands
where it stands, does its one job, and answers when spoken to. Design it
accordingly: vivid enough to be worth talking to, thin enough to be disposable.

## Where this NPC belongs

- Location: {location_name}
- Room: {room_name}

The NPC is placed there and stays there. Do not invent travel, arrivals from far
away that must still happen, or plans to leave.

## Available fields

Fields marked `[config]` are stored in the config; all others go into the profile.

{generable_fields}

## Field rules

- `character_name` — a plain in-world name, 1-2 words. It MUST NOT collide with
  any existing character (list at the end of this document). Prefer names that
  read as a person, not as a role ("Maren Kolb", not "The Barkeeper").
- `character_personality` — 2-3 sentences of plain prose, in the character's
  language (`language`). No name as the sentence opener: not "Maren is gruff"
  but "Gruff, economical with words, sizes up every newcomer...". This is a
  profile field, NOT a markdown document — do NOT write `#` headings.
- `standing_task` — the ONE thing this NPC does, as a short phrase in the
  present tense: "tends the bar", "sweeps the temple steps", "guards the gate".
  This is also the NPC's activity baseline. Exactly one task, no list.
- `dialogue_style` — one short line on HOW they speak: length, register, verbal
  tics. Example: "short, dry sentences, never asks a question back".
- `arrival_reason` — one or two sentences on why they are in this place right
  now. Keep it local and mundane; this is background colour, not a quest.
- `npc_goals` — at most TWO short goals, one per line, each a handful of words.
  What they want out of the next hour, not out of their life.
- `character_appearance` — an ENGLISH image-generation prompt: a comma-separated
  list of attributes, no sentence, no name. Example:
  `"man, 50s, heavy-set, close-cropped grey hair, weathered face, brown eyes"`.
- `face_appearance` — ENGLISH, head only: face shape, distinct features, hair
  colour/length/style, eye colour, skin tone, baseline expression. No body, no
  clothing.
- `outfit_description` — ENGLISH prompt text describing the ONE outfit this NPC
  wears, as a comma-separated list of garments:
  `"grey linen apron over a rolled-up white shirt, dark trousers, worn boots"`.
  This is plain prompt text, NOT a list of wardrobe pieces — the NPC owns no
  items. Do not name the character in it, do not describe a pose.
- `gender`, `age`, `height` — set all three. `height` is in centimetres.
- `language` — the language the NPC speaks and thinks in.

## What NOT to produce

- No `outfits` array and no wardrobe pieces — `outfit_description` replaces them.
- No soul documents: no personality/presence/tasks/beliefs/lessons/goals
  markdown, no `#` or `##` headings anywhere in any field.
- No secrets, no schedule, no inventory, no relationships to existing characters.
- No `template` field — the system fixes it to `npc-temporary`.
- No backstory beyond `arrival_reason`. Two sentences is the ceiling.

## CRITICAL: image prompts ALWAYS in English

`character_appearance`, `face_appearance` and `outfit_description` go into an
image model and MUST be written in English, even when the rest of the NPC is in
another language. Proper nouns stay unchanged; everything descriptive is English.

## Output

Answer with the finished NPC and nothing else — no questions, no preamble, no
summary. One fenced block, exactly:

```json:npc
{ ... every field from the list above ... }
```

The block MUST start with ```json:npc so the system recognises it.

## Existing characters (names that are already taken)

{existing_characters}
