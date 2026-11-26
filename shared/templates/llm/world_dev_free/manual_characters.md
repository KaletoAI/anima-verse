# Manual: characters

`create_character{data, home?, home_room?, schedule?}` creates a NEW character;
`update_character{name, patch}` changes an existing one. `get_character{name, fields?}` lists
the field names a character has; `find_characters{query?, location?}` finds them.

## create_character

`data` holds the fields of the character template:

- `name` (or `character_name`) — required. Letters of any script, digits, single spaces, `-`,
  `'`, `.` and `_` (not first); no leading/trailing space or period; at most 60 characters.
  A name that exists already is refused — use `update_character`.
- `template` — one of the offered character templates; default `human-roleplay`.
  For a real NPC — one that remembers, has relationships, thoughts, a soul and clothing — use
  `human-roleplay`. `human-default` is a MINIMAL template: no memory, no relationships, no
  clothing (no outfit system, no outfit field). Only a template WITH outfits takes `outfits` —
  on one without, `outfits` are refused:
{%- for t in character_templates %}
  - `{{ t.name }}` ({{ t.label }}) — {{ "outfits" if t.outfits else "no outfits" }}
{%- endfor %}
- every other key is a field of that template: `describe_template{"template": …, "gender": …}`
  lists them with where they are stored, the values they take and their defaults, plus the body
  slots for that gender. Read it once before creating. Every field it lists is accepted at
  creation, except those marked `editor only`; unknown keys are refused.
- `outfits` — list of outfits, `wear` — the one it starts in (both below); `body_slots` — see
  "Body slots" below.
- home and schedule — see `read_manual homes`.

A crowd of anonymous people (staff, guards, market visitors) is not made of characters: give the
place or painted area `npc_slots` instead (`read_manual locations`, "NPC slots").

## What is still missing

Every `create_character` / `update_character` result ends with `; complete` or
`; missing: …` — what the character still lacks: `no home — not in the world`,
`home <id> is unplaced (no x/z)` (place it with `place_location`), `not placed`,
`no outfits`, `wears nothing`, `no daily schedule`, `soul sections without content: <keys>`,
`body slots unset: <slot.attribute, …>`, `knows only its home` (add `known_places` or
schedule places). For a character you created, all of these are listed — fix them with
`update_character`, except two that only `create_character` can settle: `wears nothing`
(give `outfits` there — it wears the first one) and `not placed` (give `home` there — it
starts at its home; a home added later by `update_character` does not place the character —
`place_character` puts it somewhere, `read_manual homes`). On a character that already exists,
name `wears nothing` in the summary and do not retry — no tool changes what it wears. For a character you only changed, only the parts
your calls touched (home and schedule, known places, outfits, soul, body slots) are checked.
`check_run{}` lists the gaps of everything the run created or changed.

## Field values

- text fields take a string; number fields a number.
- A select with FIXED options takes one of the option VALUES literally, in the option's own type
  (the number 2, not the string "2"). The refusal lists the allowed values.
  - `chat_mode`: `""` = single (the chat model calls the tools itself), `"rp_first"` = role-play
    model plus a separate tool model (for RP fine-tunes).
  - on/off fields of this kind are the STRINGS `"true"` / `"false"`, never true/false.
- A new character defaults to `chat_mode` `"rp_first"`; send `chat_mode: ""` for a
  tool-capable chat model.
- A season-day field takes `"<season>:<day>"` of this world's calendar (e.g. `"spring:14"`).
- `character_appearance`, `face_appearance`, `body_appearance` are ENGLISH comma-separated
  attribute lists for image generation, never a sentence with the name ("young woman, slim, long
  blonde hair"). With body slots, hair/eyes/skin/build go into `body_slots`. The server renders
  the hairstyle, the portrait and the 3D figure from these fields after your turn
  (system prompt, *Images and 3D models*).
- Personality and other prose are written in the character's language, without the name as the
  sentence opener.

## Body slots

Some templates get body slots from installed packages (hair, eyes, skin, build, …). Which slots
and attributes a character has, and the values they take, depend on its template and gender:
`get_character{"name": …, "fields": ["body_slots"]}` lists them as
`slot: attribute=value [allowed values]` (`-` = unset, `|other` = another short English value
is allowed, `[text]` = free short English text). For a new character, send `body_slots` in
`create_character` — `describe_template` with the gender shows them.

- `body_slots` is `{"<slot>": {"<attribute>": "<value>"}}`, values in English.
- Set EVERY slot and attribute that applies to the character. Hair, eyes, skin, build etc. go
  there — `character_appearance` / `face_appearance` keep only what no slot covers
  (distinctive marks, hairstyle details, posture); never repeat a slot value there.
- A slot, attribute or value that does not apply is refused; nothing of the call is written.
- In `update_character` the given attributes are merged into the stored ones; the others stay.
  Values cannot be cleared here.

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

Only for a template with outfits (see `template` above). `create_character` takes them in
`data.outfits`; `update_character` ADDS outfits to an existing character with
`patch.outfits` (same shape). An outfit name the character has already is refused — outfits
are never replaced or removed here; `get_character` lists the outfit names.

`{"name": "Daily", "pieces": [...]}` — only these keys. Outfits are not bound to places or
activities: `locations` / `activities` / `excluded_locations` are refused.

A piece is EITHER an existing catalog piece `{"item_id": "<id>"}` (the id alone — `find_items{slot}`
finds them) OR a new piece:

- `slots` (required) — every slot it occupies; `describe_template` lists the clothing slots
  of the template (line `outfit slots:`), a slot not listed there is refused (a dress is
  `["top", "bottom"]`; do not add a second piece for the extra slot).
- `name` (required) — short ENGLISH item name, 2–4 words.
- `prompt_fragment` — concrete ENGLISH description for the image, no name, no pose.
- `description`, `covers`, `partially_covers` — optional.

A complete everyday outfit has at least underwear top and bottom, top, bottom and feet. Give a
new character 2–3 outfits.

A new character starts DRESSED: `data.wear` names the outfit it wears (one of `data.outfits`,
case-insensitive); without `wear` it wears the first outfit. `wear` exists only in
`create_character` — the worn outfit of an existing character is changed in the wardrobe.

## Items

`find_items{query?, category?, slot?}` before creating: an item that exists is REUSED by its id
(across characters, rooms and outfits), never created twice — a name already in the catalog is
refused. `create_item` makes a non-clothing item (`category` of `list_catalog item_categories`;
clothing comes with outfits). A stackable item needs `max_stack` (2 or more).

`give_items{character, items: [{item_id, quantity?}]}` accepts only a NEW entry (an item the
character does not hold yet; quantity 1 unless the item is stackable, at most `max_stack`) or
MORE of a stackable item it already holds, up to `max_stack` in total. A non-stackable item it
already holds, a sum above `max_stack` and an item that reveals a secret are refused.
`delete_created{kind: "item", id}` removes an item this run created in THIS turn and that
nobody holds; an item of an earlier turn stays until the run is discarded.

## Forms of address

`set_address{speaker, addressee, text}` sets how ONE character addresses another — one
direction per call; the other direction is its own call (the smith calls the apprentice "lad",
the apprentice calls the smith "Master"). `text` is one line of at most 120 characters, no line
breaks, no leading or trailing blanks, in the content language ("calls him Master", "formal,
uses her title"); `""` clears it. Setting the value it already has is refused. A linked body
speaks with its leader's mind: its direction is stored on the leader, and members of one linked
family have no form of address between them. `get_character{"name": …, "fields":
["addresses"]}` lists both directions of every pair.

## Secrets

`add_secret{name, content, category?, severity?, known_by?, related_characters?,
related_location?, consequences?}` gives a character a secret it KEEPS ("He broke the anvil.",
"Owes the miller money."): `name` is the keeper, `content` one to 1000 characters in the
content language, without leading or trailing blanks. `category` (default `personal`) and
`severity` (a whole number, default 2) come from `list_catalog{name: "secret_categories"}`; a
value outside those lists is refused, never rounded. `known_by` lists the characters who ALREADY
know it, `related_characters` those it is about — existing characters, each once, never the
keeper or its linked family; for a linked body name its leader in `known_by` (a body knows what
its leader knows). `related_location` is an existing location id, `consequences` (at most 500
characters) what happens if it comes out. A body's secret is stored on its leader.
`get_character{"name": …, "fields": ["secrets"]}` lists the secrets a character keeps.
`delete_created{kind: "secret", id}` removes a secret this run added in THIS turn; one of an
earlier turn stays until the run is discarded. While a secret names a place or a character, that
place or character cannot be removed with `delete_created` — remove the secret first.

## Skills

`set_skill{name, skill, enabled}` switches ONE skill of a character on (`true`) or off (`false`) —
e.g. a guard who never leaves the gate gets the movement skills (`setlocation`,
`go_to_character`) switched off. `list_catalog{name: "skills"}` lists the skill ids,
`get_character{"name": …, "fields": ["skills"]}` shows each skill as on/off and whether that is
the default or a setting. Switching to the state a skill already has is refused, and so is
switching on a skill whose package needs another one first (the line says which). Only on/off
is set here — the settings of a skill stay in the admin's Skills tab, and a character whose skill
settings cannot be read is refused until it is fixed there.

## delete_created

`delete_created{kind: "character", id: "<name>"}` removes a character THIS run created — in
this turn or an earlier one; a character that existed before the run is never deleted. In an
earlier turn it is refused while the character is in a party, a pair interaction or a furniture
action, is linked to other characters, has chat messages, or other characters' memories name it.

## update_character

`patch` keys: template fields (not `character_name` or `template`), `"soul:<field_key>"`,
`home` / `home_room` / `schedule` (only these spellings in a patch), `body_slots` (merged per
attribute) and `outfits` (NEW outfits, added — see above). A character without clothing or with
unset body slots (`get_character` shows both) is completed this way. Fields of a linked character that belong to its leader are changed on the leader.
