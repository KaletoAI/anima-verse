# Manual: characters

`create_character{data, home?, home_room?, schedule?}` creates a NEW character;
`update_character{name, patch}` changes an existing one. `get_character{name, fields?}` lists
the field names a character has; `find_characters{query?, location?}` finds them.

## create_character

`data` holds the fields of the character template:

- `name` (or `character_name`) — required. Letters of any script, digits, single spaces, `-`,
  `'`, `.` and `_` (not first); no leading/trailing space or period; at most 60 characters.
  A name that exists already is refused — use `update_character`.
- `template` — one of the offered character templates (the refusal lists them); default
  `human-default`.
- every other key is a field of that template (`get_character` on a similar character shows
  them). Unknown keys are refused.
- `outfits` — list of outfits (below); `body_slots` — `{"<slot>": {"<attribute>": "<value>"}}`.
- home and schedule — see `read_manual homes`.

## Field values

- text fields take a string; number fields a number.
- A select with FIXED options takes one of the option VALUES literally, in the option's own type
  (the number 2, not the string "2"). The refusal lists the allowed values.
  - `chat_mode`: `""` = single (the chat model calls the tools itself), `"rp_first"` = role-play
    model plus a separate tool model (for RP fine-tunes).
  - on/off fields of this kind are the STRINGS `"true"` / `"false"`, never true/false.
- A season-day field takes `"<season>:<day>"` of this world's calendar (e.g. `"spring:14"`).
- `character_appearance`, `face_appearance`, `body_appearance` are ENGLISH comma-separated
  attribute lists for image generation, never a sentence with the name ("young woman, slim, long
  blonde hair"). With body slots, hair/eyes/skin/build go into `body_slots`.
- Personality and other prose are written in the character's language, without the name as the
  sentence opener.

## Soul sections

Soul fields (personality, presence, tasks, roleplay rules, soul, beliefs, lessons, goals) are
Markdown files. In `create_character` you send them under their field key; in
`update_character` as `"soul:<field_key>"` (e.g. `"soul:character_personality"`) with the
WHOLE new text of that section — it replaces the file. Keep the headings, fill content under them:

- `character_personality`: `# Personality` / `## Core nature` / `## How I present myself`
- `character_presence`: `# Presence` / `## First impression` / `## Underlying vibe`
- `character_task`: `# Tasks` / `## Main task` / `## Concrete activities`
- `roleplay_instructions`: `# Roleplay rules` / `## Identity` (keep its default text exactly) /
  `## Language & style` (the speaking manner belongs ONLY in `dialogue_style`)
- `character_soul`, `character_beliefs`, `character_lessons`, `character_goals`: keep the
  headings the field's default text has.

A section shared with a linked character is changed on its owner.

## Outfits

`{"name": "Daily", "pieces": [...], "locations": [], "activities": [], "excluded_locations": []}`

A piece is EITHER an existing catalog piece `{"item_id": "<id>"}` (the id alone) OR a new piece:

- `slots` (required) — every slot it occupies, from `head, neck, underwear_top,
  underwear_bottom, legs, feet, top, bottom, outer` (a dress is `["top", "bottom"]`; do not add
  a second piece for the extra slot).
- `name` (required) — short ENGLISH item name, 2–4 words.
- `prompt_fragment` — concrete ENGLISH description for the image, no name, no pose.
- `description`, `covers`, `partially_covers` — optional.

A complete everyday outfit has at least underwear top and bottom, top, bottom and feet. Give a
new character 2–3 outfits. `locations` / `activities` (empty = everywhere / always) and
`excluded_locations` name places by name.

## update_character

`patch` keys: template fields (not `character_name` or `template`), `"soul:<field_key>"`,
and `home` / `home_room` / `schedule` (only these spellings in a patch). Fields of a linked
character that belong to its leader are changed on the leader.
