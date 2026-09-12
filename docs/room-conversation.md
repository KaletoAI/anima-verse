# Room conversation

A character's chat context is the **room perception stream** — everything it heard in the room,
as a multi-party transcript — not a 1:1 history. This page describes who answers a line.

## Conversation selection

- **Addressed characters answer.** Everybody a line names as an addressee and who is present in
  the room gets a mandatory turn. The transcript shows them who a line went to
  (`Kai (to Liesa): …`, `(to you)` for the answering character itself).
- **At most ONE bystander per line** may chime in, and the server picks it **before** any LLM is
  called — the model is never asked to decide whether to stay silent.
- **Weight of a bystander.** A character mentioned by its **full name** (whole word, no first-name
  resolution) wins outright. Otherwise the weight is `chattiness × relationship × aim`, where
  `relationship` is `0.5 + strength/100` for the relationship to the speaker and `aim` is `0.3`
  when the line was addressed to someone else (a targeted line invites third parties far less)
  and `1.0` for a line spoken to the room. The largest weight is the probability that anybody
  chimes in at all; who it is, is drawn among the candidates by weight.
- **Pairs are derived, never stored.** Two characters who addressed each other within
  `chat.pair_window_game_minutes` **game** minutes count as talking to each other; a character
  that is in such a pair with a third person does not interrupt somebody else's line.
- **An avatar line addressed to nobody gets exactly one answer** — the draw is forced, so the
  player never talks into the void. The only exception is a room where every bystander is bound
  in a pair with a third person; then nobody breaks off to answer.

## Settings

| Key | Where | Meaning |
|---|---|---|
| `chat.chattiness` | `/admin/settings → Chat` | World value, 0..1 (default 0.5). |
| `chattiness` | location (Game Admin → location editor) | Optional override for that place; empty = the world value. |
| `chat.pair_window_game_minutes` | `/admin/settings → Chat` | Length of the pair window in game minutes (default 5). |
