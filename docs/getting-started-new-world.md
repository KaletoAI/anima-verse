# Getting started with a new world

Walk-through for setting up a fresh world from zero. For a quick, working **LLM +
image backend** to plug in at step 3, see the two ready-made setups (LocalAI /
a hosted OpenAI-compatible cloud) in the [README](../README.md#getting-started).

> If a step is unclear, see [`images/getting-started/`](images/getting-started/) for a
> few annotated screenshots. They are not linked inline, since UIs evolve faster than screenshots.
> The two `llm-routing-*.png` show the OLDER single-page "LLM Routing" mask (one `+ Add LLM`
> list, task rows with a free order number); routing is three pages today — see step 3.

1. **Start the server with a brand-new world name.** Pick any name that does not yet exist under
   `worlds/`:

   ```bash
   ./start.sh --world myworld
   ```

   On first start you'll see a warning that no `config.json` was found — the server boots anyway;
   everything is configured through the admin UI.

2. **Log in as the bootstrap admin.** On the first start of a world that has no users yet, the
   server creates the user `admin` with a **random** password and prints it **once**, at WARNING
   level, to stderr and `logs/main.log`:

   ```bash
   grep "BOOTSTRAP ADMIN" logs/main.log
   # === BOOTSTRAP ADMIN CREATED === username='admin' password='…' — shown ONCE, log in and change it. ===
   ```

   The password is nowhere else — it is stored only as a bcrypt hash — so pick it up now. Open
   `http://<host>:8000/` and log in with it, then set your own password under `/admin/users`.
   (No line at all means the world already has users; log in with those.)

   Authentication is default-deny: without a session every endpoint answers `401`, a browser
   navigation is redirected to the login form, and a non-admin gets `403` on the admin surfaces.

3. **Configure server-side settings** at `http://<host>:8000/admin/settings`, top to bottom. The
   minimum before anything works:

   - **Server** — set `Allowed CORS origins` (`server.cors_origins`) as
     soon as something calls this API from **another** origin: one origin per line (scheme + host
     + port, no trailing slash), e.g. the Vite dev servers (`:5173`, `:5183`) or a 3D client on a
     different machine. `/play` and `/game-admin` are delivered by this server itself and need no
     entry; empty means no cross-origin access at all, a wildcard is not supported, and a change
     **takes effect only after a restart**. `Max upload size (MB)` and `Max jobs in flight per
     user` live here too.
   - **LLM Providers** — at least one provider (`openai`, `ollama` or `anthropic`) with `Name`,
     `Type` and `API Base URL`. `Max Concurrent` sizes this channel's worker pool and is the hard
     limit for its GPU jobs — it is **not** the LLM parallelism any more (that is `Lanes`, per
     model). Optional `Serialize Group`: give the provider and any image backend sharing the same
     physical GPU the same group name so their calls run one at a time.
   - **LLM Models (Simple)** — pick a provider + model per job category (chat / tools / helper /
     vision / embedding). This fills the advanced routing automatically. Embedding can run built-in
     (`Embedding → Backend: internal`) with no external endpoint.
   - **LLM Routing (Advanced)** (only if you want to route a single job differently) has **three**
     pages: **Tasks** — one row per task with its ordered chain of LLM entries (the order IS the
     position, you do not type a number); **LLMs** — the entries themselves (`Provider`, `Model`,
     `Lanes (max concurrent)`, `Temperature`, `Max Tokens`, `Tasks`); **Overview** — what the
     server resolves right now. A task nobody routed falls back to its parent (`intent_*` /
     `thought_*` / `extraction_*` → the parent, `furnish` / `prop_mount_classify` /
     `room_description_sync` → `intent`, `npc_*` → `chat_stream`), so you never have to fill all
     of them.
   - *(optional)* **Media Generation → Backends** for image / video / mesh backends,
     **Text-to-Speech**, **Game calendar** — only for the corresponding features.

   API keys and passwords are written to a separate **`secrets.json`** next to
   `config.json` (gitignored), so the demo world can ship with an empty `config.json` and each user
   fills in their own keys.

4. **Create your first character.** Character creation lives in the game UI, not in
   `/admin/settings`. Open the **Game-Admin** at `/game-admin` → **Characters**, then the
   **New character** button above the list:

   1. Enter a **Name** (e.g. `Rowan Kell`) — the name is also the directory under
      `worlds/<world>/characters/`, so it has to be unique.
   2. Pick a **Template** — e.g. **Human (Roleplay)** for a typical chat partner. This repo ships
      three more: **Human Standard** (pure NPC), **Animal**, and **Temporary NPC** (for the
      short-lived NPCs the world spawns by itself). `Character Base` is the shared base every one
      of them inherits from and is not offered. Further templates — including the NSFW ones — come
      with a content/skill package from the marketplace, or you add your own under
      `shared/templates/character/`.
   3. **Create**. The template-driven editor opens on the new character, and the character is
      auto-added to your access list.

   The **Temporary NPCs** list below the character list, and the **NPC pool** next to it, are for
   the automatic short-lived NPCs — you do not need either to get started.

5. **Fill in the character profile.** Work through the editor's sub-tabs left to right. The field
   tabs (*General*, *Appearance*, *Properties*, …) come generically from the template; the ones
   with their own UI are **Soul**, **Gallery**, **Expressions**, **Activity & Home**, **Locations**,
   **Skills**, **Wardrobe** and **Secrets**. A few notes:

   - The **Soul** holds the character's inner life (personality, beliefs, goals, roleplay rules) as
     markdown under `worlds/<world>/characters/<Name>/soul/`.
   - **Appearance** has two prompts: a full-body `character_appearance` (gallery / outfits) and a
     head-only **Face Prompt (Profile Image)**. The token preview shows the resolved string.
   - **Language** is per-character — it controls what language the model responds in.
   - **Skills** is where the character's verbs are switched on; a verb only appears if its package
     is installed under `plugins/`.
   - Saving is explicit: the toolbar's **Save (n)** button counts the changed fields.

6. **Set a profile image.** Either **generate** one (with an image backend configured and the Face
   Prompt filled — the portrait renders from the Face Prompt through the `profile` use case) or
   **upload** one in the character's **Gallery** and mark it as the **Profile image**. The profile
   image becomes the reference for later generations so the face stays consistent.

7. **Take over the character as your avatar.** Open `/play`. With no avatar set and more than one
   playable character, the **Choose your avatar** screen appears; with exactly one it is picked
   automatically, and the toolbar lets you switch later. From then on that character is *you*:
   their location, mood and outfit follow your decisions and they no longer act autonomously. Only
   templates with the `playable_avatar` feature (`human-roleplay`, `animal-default`) can be
   controlled; `human-default` and `npc-temporary` are NPC-only.

8. **Create at least one more character to talk to.** A world with a single character means
   chatting with yourself. Add a second roleplay character (also playable) or a **Human Standard**
   NPC.

9. **Build the world** in the Game-Admin's **Locations** tab:

   1. **New place** — enter a name in the dialog and press **Create**.
   2. Select it and add one or more **rooms** (a location without rooms exists on the map but
      nobody can enter it). One room is the **Entry room** — the only way in and out; the first
      room becomes it by default.
   3. Per room, fill the **Activity hint** — a free-text nudge about what one does in this room.
      There is no activity library: the hint plus the model's own output is the activity, and it
      resets when the character changes location.
   4. Optionally fill the image prompts (**Day prompt** / **Night prompt**, and a **3D model
      prompt** for the mesh) — backgrounds render asynchronously in the background, so you can
      keep editing.
   5. Optional per room: **Decency**, **Indoor/Outdoor**, **Swim allowed**, **Style hint**, and a
      floor plan drawn in the plan editor. The location itself carries the **Chattiness** override
      that decides how readily bystanders chime in there.

10. **Paint the terrain and position the places.** In the **Terrain** tab paint the ground the
    world is made of; in the **Map** tab drag the location outlines into position — the world is a
    continuous plane in metres (`pos_x` / `pos_z` plus `yaw_deg`), saved on drop. Characters travel
    along that plane as timed journeys, not in jumps.

11. **(Optional) Gate a room behind an item.** In the Game-Admin:

    1. **Items → New item** — create the gating item (e.g. a key) and give it to the character(s)
       who may enter. Note the item's id (it looks like `item_a1b2c3d4`).
    2. **Rules → New rule** — `Type: Block`, `Character: all characters`, `Target: Place / Room`,
       pick the **Place** and the **Rooms**, `Action: Enter`, `Condition: Inventory` with the
       expression `NOT has_item:item_a1b2c3d4`.
    3. Save. The movement skills and any LLM-driven location change both consult these rules, and
       so does the avatar.

    The same editor also writes **Force** rules (the character is made to do something, e.g. go
    home above a danger level) and **Discover** rules (a place becomes known with some probability
    per tick).

12. **Pick the right chat mode.** The character's `chat_mode` controls how skills are invoked and
    **must match your chat model's tool-calling ability**:

    - **`single`** — the chat LLM emits tool calls inline. Needs a model with reliable structured
      tool output (Qwen/Llama-3.x-Instruct, GPT-4-class, Claude, …). One call, fast.
    - **`rp_first`** *(recommended for RP fine-tunes)* — the chat LLM answers in prose, then a
      separate Tool LLM translates it into skill calls. Pairs an RP fine-tune with a tool-capable
      helper behind it.

    **Symptom of the wrong mode:** the character agrees ("I'll come over") but `current_location`
    never changes. Switch to `rp_first` and route a tool-capable model to the `intent` task.

From here you have a working setup: chat in `/play`, watch characters travel across the map, take
over an avatar, and — with `./start.sh --with-3d` — walk the same world in 3D. The remaining
features (Instagram feed, story arcs, scheduler, knowledge extraction, automatic NPCs, room
furnishing, …) are configured in their respective admin sections and skill packages — see the
[Features](../README.md#features) list.
