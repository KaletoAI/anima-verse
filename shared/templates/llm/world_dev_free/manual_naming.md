# Manual: naming

- Place names are short, like a signpost: "The Old Mill", "North Gate", "Willow Pond". At most
  120 characters; usually 1–4 words.
- Names and descriptions become world content: write them in the content language — the
  language of the admin's task text unless the task names another (system prompt, "Content
  language"); `world_overview` shows the languages existing characters speak.
- An empty world (`world_overview` counts 0 locations and 0 characters) has nothing to copy:
  the task's language decides — and it has no extent yet: call `set_build_bounds` first
  (`read_manual map`, "Composition").
- A name is not a key. `create_location` with an existing name makes a SECOND place — look first
  (`find_locations{"query": …}`) and use `update_location` for the existing one. A character
  name must be unique; an existing one is refused.
- Room names describe the room's function ("Taproom", "Bedroom", "Cellar"), not the place again.
- Labels of terrain and height areas are short map captions ("Eastern woods", "The river").
- Image prompts, appearance fields and outfit piece names/prompt fragments are ENGLISH; proper
  names inside them stay as they are.
- No real people's names, no real brands.
