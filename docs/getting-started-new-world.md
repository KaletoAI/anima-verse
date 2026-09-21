# Getting started with a new world

Walk-through for setting up a fresh world from zero. For a quick, working **LLM +
image backend** to plug in at step 3, see the two ready-made setups (LocalAI /
Infermatic) in the [README](../README.md#getting-started).

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

3. **Configure server-side settings** at `http://<host>:8000/admin/settings`, top to bottom. The
   minimum before anything works:

   - **Server** — set a real `JWT Secret`. Also `Allowed CORS origins` (`server.cors_origins`) as
     soon as something calls this API from **another** origin: one origin per line (scheme + host
     + port, no trailing slash), e.g. the Vite dev servers (`:5173`, `:5183`) or a 3D client on a
     different machine. `/play` and `/game-admin` are delivered by this server itself and need no
     entry; empty means no cross-origin access at all, a wildcard is not supported, and a change
     **takes effect only after a restart**.
   - **LLM Providers** — at least one provider (Ollama, OpenAI-compatible, Anthropic) with `name`,
     `type` and `api_base`. Optional `serialize_group`: give the provider and any image backend
     sharing the same physical GPU the same group name so their calls run one at a time.
   - **LLM Models (Simple)** — pick a provider + model per job category (chat / tools / helper /
     vision / embedding). This fills the advanced routing automatically. Embedding can run built-in
     ("Internal") with no external endpoint.
   - **LLM Routing** (the advanced view, only if you want to route a single job differently) has
     **three** pages: **Tasks** — one row per task with its ordered chain of LLM entries (the
     order IS the position, you do not type a number); **LLMs** — the entries themselves
     (provider, model, sampling, `Lanes`); **Overview** — what the server resolves right now.
     A task nobody routed falls back to its parent, so you never have to fill all of them.
   - *(optional)* **Image Backends**, **TTS** — only for the corresponding features.
   - *(optional)* **Telegram** — `Webhook secret token` (`telegram.webhook_secret`). Until it is
     set, `POST /telegram/webhook` is **refused** for every caller. Pass the same value as
     `secret_token` when you register the webhook with Telegram's `setWebhook`; Telegram returns
     it in the `X-Telegram-Bot-Api-Secret-Token` header and the server compares the two. Stored in
     `secrets.json`.

   API keys, the JWT secret and passwords are written to a separate **`secrets.json`** next to
   `config.json` (gitignored), so the demo world can ship with an empty `config.json` and each user
   fills in their own keys.

4. **Create your first character.** Character creation lives in the game UI, not in
   `/admin/settings`. Open the **Game-Admin** at `/game-admin` → **Characters → `+ New`**:

   1. Pick a template — e.g. **Human (Roleplay)** for a typical chat partner. This repo ships
      three more: **Human Standard** (pure NPC), **Animal**, and **Temporary NPC** (for the
      short-lived NPCs the world spawns by itself). `Character Base` is the shared base every one
      of them inherits from and is not offered. Further templates — including the NSFW ones — come
      with a content/skill package from the marketplace, or you add your own under
      `shared/templates/character/`.
   2. Enter a name (e.g. `Rowan Kell`).
   3. The template-driven editor opens on the new character — fill in appearance, personality
      (soul), outfits, etc. The character is auto-added to your access list.

5. **Fill in the character profile.** Work through the editor tabs top to bottom; a few notes:

   - The **Soul** holds the character's inner life (personality, beliefs, goals, roleplay rules) as
     markdown under `worlds/<world>/characters/<Name>/soul/`.
   - **Appearance** has two prompts: a full-body `character_appearance` (gallery / outfits) and a
     head-only **Face Prompt** (profile image). The token preview shows the resolved string.
   - **Language** is per-character — it controls what language the model responds in.

6. **Set a profile image.** Either **generate** one (with an image backend configured and the Face
   Prompt filled, use the camera action — it renders a portrait from the Face Prompt) or **upload**
   one in the character's gallery and mark it as the profile image. The profile image becomes the
   reference for later generations so the face stays consistent.

7. **Take over the character as your avatar.** Once it has a profile image and a filled profile,
   pick it in the active-character selector. From then on that character is *you*: their location,
   mood and outfit follow your decisions and they no longer act autonomously. Only templates with
   the `playable_avatar` flag (`human-roleplay`, `animal-default`) can be
   controlled; `human-default` is NPC-only.

8. **Create at least one more character to talk to.** A world with a single character means
   chatting with yourself. Add a second roleplay character (also playable) or a Human (Default) NPC.

9. **Build the world map** in the Game-Admin:

   1. **`+ New Location`** — name + short description, save.
   2. Select it and add one or more **rooms** (a location without rooms exists on the map but can't
      host activities).
   3. Add **activities** per room (free text, e.g. "drinking coffee", "people-watching") — picked
      by the LLM via the `set_activity` skill.
   4. Optionally fill day / night **image prompts** — backgrounds render asynchronously in
      the background; you can keep editing.

10. **Position locations on the world map.** Drag the location outlines in the Map tab — positions
    are metres (`pos_x`/`pos_z`), saved on drop. Characters travel along routes over the painted
    terrain.

11. **(Optional) Gate a room behind an item.** In the Game-Admin:

    1. **Items → `+ New`** — create the gating item (e.g. a key with id `key_room_506`) and assign
       it to the character(s) who may enter.
    2. **Rules → `+ New`** — Scope `All characters`, Subject `Location / Room`, Action `Enter`,
       pick the gated room, Condition `NOT has_item:key_room_506`.
    3. Save. The set-location skill and any LLM-driven location change both consult
       these rules.

12. **Pick the right chat mode.** The character's `chat_mode` controls how skills are invoked and
    **must match your chat model's tool-calling ability**:

    - **`single`** — the chat LLM emits tool calls inline. Needs a model with reliable structured
      tool output (Qwen/Llama-3.x-Instruct, GPT-4-class, Claude, …). One call, fast.
    - **`rp_first`** *(recommended for RP fine-tunes)* — the chat LLM answers in prose, then a
      separate Tool LLM translates it into skill calls. Pairs an RP fine-tune with a tool-capable
      helper behind it.

    **Symptom of the wrong mode:** the character agrees ("I'll come over") but `current_location`
    never changes. Switch to `rp_first` and route a tool-capable model to the Tools tasks.

From here you have a working setup: chat, watch characters move on the map, take over an avatar, run
a group chat. The remaining features (Instagram feed, story arcs, scheduler, knowledge extraction, …)
are configured in their respective admin sections — see the [Features](../README.md#features) list.
