# Manual: naming

- Place names are short, like a signpost: "The Old Mill", "North Gate", "Willow Pond". At most
  120 characters; usually 1–4 words.
- Names and descriptions become world content: write them in the same language as the existing
  places and characters (`world_overview` / `find_locations` show them).
- A name is not a key. `create_location` with an existing name makes a SECOND place — look first
  (`find_locations{"query": …}`) and use `update_location` for the existing one. A character
  name must be unique; an existing one is refused.
- Room names describe the room's function ("Taproom", "Bedroom", "Cellar"), not the place again.
- Labels of terrain and height areas are short map captions ("Eastern woods", "The river").
- Image prompts, appearance fields and outfit piece names/prompt fragments are ENGLISH; proper
  names inside them stay as they are.
- No real people's names, no real brands.
