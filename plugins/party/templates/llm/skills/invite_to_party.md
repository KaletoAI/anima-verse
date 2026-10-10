---
name: InviteToParty
action_hint: YOUR character is the one PROPOSING a shared trip to ANOTHER present character (not the user you are talking with) — target = that character's name; the inviter LEADS the group. If the other side proposed going together and your character only agrees, or the companion is the user, use JoinParty instead
---
Invite another character who is present at your current location to travel together as a party. Use this ONLY when your character is the one making the proposal ("come with me to the café", "let's go, I'll take you there"). The inviter becomes the party LEADER: from then on you alone decide where the group goes, and the invited character is pulled along and loses their own movement. Therefore: if the OTHER person suggested the shared trip and your character just says yes, do NOT invite them back; call JoinParty with leader=<their name> instead, otherwise the one whose idea it was ends up unable to move. In a conversation with the user never invite the user — use JoinParty with leader=<the user's name>, even when the idea was yours: the user moves themselves and you come along. Pass JSON: {"target": "<character_name>"}. Do NOT use it for someone who is not present, or who is already in a party.

For a destination-bound agreement, pass a structured `destination={"location_id":"<known id>","room_id":"<optional id>"}` and `scope="pair"` (only you and one new companion) or explicit `scope="party"` (also include every current follower). The server persists one shared-trip intent, obtains the companion's actual answer, resumes that exact destination and completes only after everyone arrives. Never silently leave/dissolve a party to make pair scope fit. To continue an existing shared trip owned by you, pass its `intent_id` and the same target; do not create a replacement plan or independently call SetLocation before consent.

To answer somebody else's existing destination-bound proposal, prefer JoinParty
with its exact `invite_id`. A matching counter-proposal is normalized to that
answer only when you supply the exact current `intent_id`; a destination alone
does not identify which invitation you are accepting.
