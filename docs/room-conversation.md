# Room conversation

A character's chat context is the **room perception stream** — everything it heard in
the room, as a multi-party transcript — not a 1:1 history. This page describes who
answers a line.

The decision itself is one module, `app/core/chime_select.py`; the dispatcher that
collects the candidates and hands out the turns is
`AgentLoop.dispatch_room_reactions` (`app/core/agent_loop.py`). Check:
`scripts/smoke_chime_select.py`.

## Who is even asked

The roster is everyone in the room **plus** everyone within hearing distance out in
the open (`perception.nearby_in_the_open`). Two filters run before any weighing:

- **A whisper distributes nothing.** It reaches no open-air listener and triggers no
  bystander at all.
- **Whoever is leaving does not react.** A character whose `movement_target` points
  away from this location gets no room reaction — otherwise it walks out and keeps
  talking.

There is deliberately **no sleep gate and no `thoughts_enabled` gate**: reacting is not
autonomous thinking, so an addressed sleeper answers. The one character never drawn as
a bystander is the **player-controlled avatar**.

## Conversation selection

- **Addressed characters answer.** Everybody a line names as an addressee and who is
  present in the room gets a mandatory turn. The transcript shows them who a line went
  to (`Mira Sol (to Pip): …`, and `(to you)` for the answering character itself).
- **At most ONE bystander per line** may chime in, and the server picks it **before**
  any LLM is called — the model is never asked to decide whether to stay silent.
- **Weight of a bystander.** A character mentioned by its **full name** (whole word, no
  first-name resolution) wins outright, even if it was busy — being named pulls it out
  of whatever it was doing. Several mentions: the one named first in the text.
  Otherwise the weight is `chattiness × relationship × aim`, where `relationship` is
  `0.5 + strength/100` for the relationship to the speaker (no relationship yet counts
  as strength 10, i.e. 0.6) and `aim` is `0.3` when the line had addressees at all (a
  targeted line invites third parties far less) and `1.0` for a line spoken to the room.
  The largest weight is the probability that anybody chimes in at all; who it is, is
  drawn among the candidates by weight.
- **Pairs are derived, never stored.** Two characters who addressed each other within
  `chat.pair_window_game_minutes` **game** minutes count as talking to each other; a
  character that is in such a pair with a third person does not interrupt somebody
  else's line (weight 0). Newest wins — whoever has since been addressed by someone
  else has moved on. A frozen world freezes the pairs with it.
- **An avatar line addressed to nobody gets exactly one answer** — the draw is forced,
  so the player never talks into the void. It cannot conjure a speaker out of nothing,
  though: the room stays silent when every weight is 0, which happens when every
  bystander is bound in a pair with a third person, when `chattiness` is set to 0, or
  when there is nobody left after the avatar and the addressees are removed. Then the
  world itself answers through the storyteller fallback instead.

## The round budget on top

The per-line selection is not the only limiter. The room has an energy budget per
round; an avatar line resets it. While an avatar is in the room and is not the
speaker, the budget drops to a single backstop reaction for
`chat.avatar_floor_timeout_minutes` REAL minutes. When the budget is spent the room
either falls silent or gets one visible wind-down beat from a single character. A chime
the rules above would allow can therefore still be suppressed here.

## The same path serves the NPC features

`dispatch_room_reactions` has four callers, so everything above also governs them:

| Caller | Line |
|---|---|
| `POST /play/say` | the avatar's own line (this is the `is_avatar` case) |
| `npc_actions` | a temporary NPC's `npc_talk` line, addressed at one partner |
| `npc_scenes` | after a director scene, the cascade from its last line, with every scene participant excluded |
| `perception.announce_action` | announcements and storyteller lines, addressed to nobody |

## Settings

| Key | Where | Meaning |
|---|---|---|
| `chat.chattiness` | `/admin/settings → Chat / Anti-Repetition` | World value, 0..1 (default 0.5). 0 means no bystander ever chimes in on its own. |
| `chattiness` | location (Game Admin → location editor) | Optional override for that place; empty clears it and the world value applies again. |
| `chat.pair_window_game_minutes` | `/admin/settings → Chat / Anti-Repetition` | Length of the pair window in game minutes (default 5). |
| `chat.avatar_floor_timeout_minutes` | `/admin/settings → Chat / Anti-Repetition` | How long (REAL minutes) a present avatar holds the room down to one backstop reaction (default 8). |
