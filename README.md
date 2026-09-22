# Anima Verse

**An LLM-driven character simulator — a "living world" of AI characters that chat, travel across a
world map painted in metres, change their outfit and activity, and have every scene rendered through
image-generation backends.** A Python/FastAPI backend drives the simulation; the UI is a React
single-page app, a Three.js 3D client and a set of server-rendered admin pages.

**What sets it apart.** Unlike chat-centric frontends (e.g. SillyTavern) where image generation is
an optional add-on, Anima Verse treats **both LLM chat and LLM-driven image generation as
first-class, deeply integrated mechanics** — characters update their location, activity and outfit
through tool calls, every scene can be rendered, mood drives expression, and the same world is
walkable in 3D. The experiment is to see what kind of "living world" emerges when both modalities
are pushed that hard at the same time.

> ℹ Early-stage, single-developer experiment with adult-content capability — please read
> [Status & disclaimers](#status--disclaimers) before relying on it.

---

## Table of contents

- [How it works (architecture)](#how-it-works-architecture)
- [Features](#features)
- [Installation](#installation)
- [Running the server](#running-the-server)
- [Worlds & storage](#worlds--storage)
- [Getting started](#getting-started)
- [Admin & monitoring surfaces](#admin--monitoring-surfaces)
- [Checks](#checks)
- [Documentation](#documentation)
- [Status & disclaimers](#status--disclaimers)
- [License](#license)

---

## How it works (architecture)

**Backend — Python / FastAPI.** `app/server.py` is the entrypoint. Thin HTTP routers live under
`app/routes/`; the actual logic lives in `app/core/`. Nearly all structured data for a world lives
in a single SQLite database (`world.db`); a second database (`task_queue.db`) holds the persistent
task queue.

**LLM access is always queued.** Logical *tasks* (`chat_stream`, `intent`, `consolidation`,
`image_recognition`, …) are mapped to a concrete *LLM entry* — provider + model + sampling — via
**LLM Routing**. Each provider owns a worker channel with priority ordering and a GPU-slot limit for
image/video/mesh jobs; **how many LLM calls run at once is decided per model** by that entry's
*lanes*, each of which remembers the prompt prefix it last served. Chat and story streaming bypass
the queue for latency but still take a lane. Two image generations never run in parallel on the same
backend.

**Prompts are Jinja2 templates, not Python string-building.** Every LLM prompt lives under
`shared/templates/llm/` and is live-editable at `/admin/templates`.

**Default-deny authentication.** Without a session every route answers `401` (a browser navigation
gets redirected to a login form instead), and non-admins get `403` on the admin surfaces. Only the
two React shells, `/static`, `/i18n`, the login round trip and `/health` are reachable anonymously.
**World-level data is admin-only:** every `POST`/`PUT`/`PATCH`/`DELETE` under `/world`, `/rules`,
`/intents`, `/events`, `/templates`, `/inventory/items` and `/inventory/rooms` needs the admin role,
as do the global queue controls. A player still reads all of it, and keeps every write that belongs
to playing — chat, movement, own inventory and outfit, gifts, scene photos, cancelling own tasks.

**Three frontends, one project:**

- **React / Vite SPA** (`frontend/`, built to `static/game_admin/`, two pages from one project):
  - **Player UI** at **`/play`** — the actual game: chat, a schematic metre map with travel,
    self/others, inventory, mind, gallery, phone, news, quests, tasks. `/` redirects here.
  - **Game-Admin** at **`/game-admin`** — world building in 20 tabs (characters, locations/rooms,
    map, terrain, props, items, rules, states, events, scheduler, improvements, marketplace,
    poses, world-dev, observer, mind …).
- **Server-rendered admin pages** (Python) — `/admin/settings`, `/admin/users`, `/admin/models`,
  `/admin/agent-loop`, `/admin/templates`, `/admin/llm-stats`, `/logs/llm`,
  `/logs/image-prompts`, `/dashboard`. These are the configuration surface; there is no React
  replacement for them. A large settings section can split itself into navigation sub-pages
  (schema key `pages`) — **LLM Routing (Advanced)** does (*Tasks · LLMs · Overview*) and so does
  **Media Generation** (*General & defaults · Backends · Use-cases (styles) · LoRA library · Scene
  rendering · Reference renders & sizes · Blender refinement (3D) · Analysis & rebuild prompts*).
  Saving stays section-wide, the URL hash (`#image_generation/blender`) survives a reload.
- **3D client** (`client3d/`, Three.js + a small React HUD) — a zoomable Age-of-Empires-style view
  of the world that resolves buildings into walkable floor plans as you zoom in, with the same
  player panels docked beside it. It runs as its own process (`./start.sh --with-3d`, port 5183)
  and talks to the backend over the HTTP API only, so it can just as well run on a different
  machine. Everything geometric that both renderers need lives in `packages/scene-render`; the
  player panels both surfaces show live in `packages/player-ui`.

**Three nouns, kept distinct:** a **Character** is any entity; an **Agent** is an LLM-driven chat
partner / NPC; an **Avatar** is a character the user has taken over and now controls directly (it
stops acting autonomously).

---

## Features

### LLM & routing
- Multiple providers per world (types: **OpenAI-compatible**, **Ollama**, **Anthropic**) configured
  through the admin UI — API keys land in a gitignored `secrets.json`.
- **Task-centric routing** (`/admin/settings → LLM Routing`): the **Tasks** page gives every one of
  the 28 tasks an ordered chain of LLM entries, the **LLMs** page holds the entries themselves
  (provider, model, lanes, temperature, max tokens), the **Overview** page shows what the server
  would resolve right now. A task nobody routed borrows its parent's LLM (`intent_*` / `thought_*` /
  `extraction_*` → the parent, `furnish` / `prop_mount_classify` / `room_description_sync` →
  `intent`, `npc_*` → `chat_stream`), so the list never has to be filled completely.
- **Simple model picker** (`LLM Models (Simple)`): one provider + model per job category
  (chat / tools / helper / vision / embedding) that fills the advanced routing for you.
- **Cache lanes**: parallelism is a property of the model entry, not the provider. A lane remembers
  the prompt class + character it last served and prefers to get it back, so a backend's prompt
  cache is not thrashed. Live state at `/admin/agent-loop`.
- Per-provider worker channels with priority ordering, `serialize_group` for backends that share one
  physical GPU, busy-retry on `503`, upstream-failure cooldown and fallback down the chain.
- **Model capabilities** (`/admin/models`): tool-calling, vision, JSON strictness, model class and
  more per model — stored once for all worlds in `shared/config/model_capabilities.json`.
- **Built-in text embeddings** (`fastembed` / ONNX, CPU — no external endpoint needed) used for pose
  matching; `auto` / `internal` / `external`, configurable in the admin UI. The default built-in model
  is English-only — a world played in another language should pick the multilingual
  `paraphrase-multilingual-mpnet-base` model, and the Validate button on `/admin/settings` warns about
  the mismatch whenever the situational memory block is switched on.

### Chat & memory
- Real-time streaming chat over Server-Sent Events.
- **Room-perception model:** a character's context is the multi-party transcript of what it heard in
  its room, not a 1:1 pairwise history. At most one bystander chimes in on a line that was not
  addressed to them; the likelihood is a world setting (`chat.chattiness`) a location can override.
- Two chat modes per character: **`single`** (tool-capable model emits tool calls inline) and
  **`rp_first`** (RP model writes prose, a separate Tool LLM translates it into skill calls —
  recommended for RP fine-tunes).
- Tiered memory consolidation (scene → day → week → month), commitments, semantic facts, per-partner
  day summaries, relationship summaries and anti-repetition control (a repetition penalty that rises
  while a character loops).
- Chat retention: raw chat lines older than `memory.chat_retention_days` (90 by default, `0` = keep
  forever) are deleted once their game day has been summarized — a day that was never rolled up keeps
  its lines regardless of age.
- **Agent Loop:** idle characters take autonomous "thought" turns between user messages
  (importance-weighted round-robin; excludes sleeping characters and the user's avatar).
- **Intent engine** decides which skills to surface for a given turn.
- **Plans & tasks (intents):** one store for everything a character shall or wants to do. A task the
  player gives in chat becomes the character's intent — the reply carries an
  `[INTENT: <title> | <description> | when=… | prio=… | by=player]` marker, the intent is stored with
  `source: human`, and the scene shows a narrator line (`📝 <name> takes on: <title>`). A plan the
  character makes for itself is `source: character` and gets no line. The trigger says when it becomes
  due: `standing` (shown in the prompt until done), `now`, at a game time (`in:2h`) or on arriving at a
  place. Managed in the Game-Admin **Intents** tab; the marker grammar lives in one template fragment
  (`shared/templates/llm/chat/intent_markers.md`) that both prompts that teach it share.

### Characters, avatars & world
- Template-driven character editor (no hardcoded field lists) — appearance, the markdown "soul",
  outfits, mood, height, language, memory budgets, per-character LLM overrides. The repo ships
  `human-roleplay`, `human-default`, `animal-default` and `npc-temporary` under
  `shared/templates/character/`.
- **One name rule for every creator:** the create form, the character ZIP import, World Dev and the
  temporary-NPC spawn all validate a NEW name the same way — letters of any script, digits, single
  spaces, `-`, `'`, `.` and `_` (not leading), up to 60 characters. Existing characters are never re-checked or renamed.
- **Avatar takeover:** step into any character whose template is `playable_avatar` — their location,
  mood and outfit follow your decisions and they stop acting on their own.
- **Structured movement only:** a character changes location through the movement skills
  (`setlocation`, `go_to_character`, `cancel_travel`) or a teleport spell — never by RP text claiming
  a cross-location jump. **Activity is free text**, driven by the room's activity hint plus the
  model's own output; there is no activity library.
- **Map layout backup:** the Map tab's **Download layout** saves where every location stands
  (position and rotation in metres) as a ZIP, **Restore layout** puts them back — matched by id,
  characters travelling along, terrain untouched (`/world/map/export`, `/world/map/import`).
- **A cross-location move is a journey, not a jump:** the path is walked in metres over the painted
  terrain and the position is a pure function of the game clock, so a frozen world freezes every
  journey and all clients derive the same position.
- **Parties:** one leader plus followers travel as one — only the leader moves, followers are pulled
  along, and joining is an LLM tool call, never a keyword match.
- Locations → rooms, with an `entry_room`, per-room floor plans, indoor/outdoor, decency, swim rules,
  `known_locations` discovery and rule-based access control (**Block / Force / Discover** rules with
  free-text conditions such as `has_item:item_a1b2c3d4 OR courage>50`).
- **Automatic NPCs:** slots on locations and painted areas, home areas, time windows and a pool of
  reusable profiles spawn short-lived NPCs that talk to each other and disappear again.
- **Events:** disruption / danger events swap the room background, feed the player's news channel and
  can spawn temporary access rules ("you can't leave during the fire"); announcements bump nearby
  characters.
- **Game calendar:** the world runs on its own calendar of seasons and days with no real dates or
  timezones — a settable clock with a tick factor that drives day/night, schedules, cron jobs, flag
  lifetimes, journeys and every timestamp the game world sees.
- **World freeze** pauses the autonomous simulation (agent loop, ticks, scheduler) while keeping the
  task queue and on-demand LLM tools live; **sleep mode** puts every NPC to bed without stopping the
  clock.

### Image, video and 3D generation
- One pool, three media types. Image backends: **Stable Diffusion WebUI (A1111/Forge)**, **CivitAI**,
  **Together.ai**, **LocalAI**, plus two generic OpenAI-compatible types:
  - **`openai_chat`** — image-returning *chat-completions* endpoints (the model replies with an
    image). Text-only; no reference images.
  - **`openai_diffusion`** — `/v1/images/generations` (DALL·E-style) endpoints. Sends reference
    images as base64 and supports inline `<lora:name:weight>` LoRAs; API key optional.

  **Video** is a backend type in the same list (`openai_video`, `localai_video`, `together_video`) and
  returns one MP4; **3D meshes** are another (`openai_mesh`). Backends are matched per use case with
  cost-based selection and failover — except mesh backends, which never fall back onto each other
  because a wrong-rig mesh binds unusably.
- **One master switch:** *Admin → Settings → Media Generation → „Media generation enabled"* turns
  every image, video and 3D-mesh generation of the world off — requests are refused with a clear
  message and nothing is queued, while existing media stay served.
- **Use-case-driven styling:** every render occasion is a *use case* and the style belongs to the
  use case; `image_family` (`natural` prose for Flux/Qwen vs. `keywords` tags for Z-Image/SD) selects
  both the prompt adapter and the style family.
- Context-aware prompts (appearance, outfit, mood, activity, location, pose), reference-image slots
  in the order Agent > Room > others > Items for face consistency, pose/expression variants, the
  outfit decency/compliance system.
- **Consolidated LoRA library:** one entry per LoRA with its backends, synced hourly from each
  backend's LoRA URL; every dropdown is scoped to the selected backend and the server rejects a pick
  the library does not associate with it.
- Automatic background removal (rembg/u2net), image downscaling and cached thumbnails under
  `/thumbs/…`.
- Optional external **post-processing hand-off** — a separate service is notified, pulls the finished
  image itself and writes the result back through the API. This project does no pixel editing and
  sends no image bytes.

### 3D world
- **The server computes, clients render.** `GET /play/locations/{id}/scene` delivers a whole location
  as finished primitives and placement specs in world metres, so neither the 3D client nor the
  admin's floor-plan preview decides geometry. The payload contract is `docs/schnittstellen-3d.md`.
- **Character models:** one mesh per outfit combination, generated from a dedicated T-pose reference
  render; humanoids come back as one rigged GLB, non-humanoids as FBX plus texture.
- **Location and prop models** are generated from gallery images, with front/back/left/right views
  feeding multi-view mesh aliases.
- **Animations:** shared clip library under `shared/models/clips/` organised into sets, retargeted
  onto one reference rig, with pose presets, pair animations for two characters at one anchor and
  transition clips between them.
- **Room furnishing** (needs → match → place) fills a room with props through a three-pass solver;
  scatter strokes line a street with them.
- Optional **Blender refinement** of generated meshes (headless, no manual modelling).

### Text-to-speech
- Backends: **XTTS v2** (voice cloning), **F5-TTS** (high-quality cloning) and **Magpie** (NVIDIA
  Riva, multilingual), with an optional fallback backend.
- Auto-TTS for every reply or on-demand per message; per-character voice config; speaker-reference
  WAVs are read from the repo-root `voices/` directory; text cleaning strips markdown, emojis and
  mood markers before synthesis.

### Social & narrative
- **Skill packages** ship the social verbs: `talk_to` (face-to-face within earshot), `send_message`
  (remote message, optional image attachment), `instagram` (a virtual per-character feed: image →
  vision-LLM caption → post, plus comment/reply verbs), `act` (an in-scene action narrated by the
  storyteller engine), `interact` (two present characters play a synchronised pair animation),
  `party`, `retrospect`, `take_photo`, `notify_user`, `set_pose`, `sleep`, `consume_item`.
- **Story arcs** progress in the background with beats and per-beat scene images; the player reads
  them spoiler-free in the quest book. The Game-Admin's **Storyteller** tab lists them (title,
  status, participants, beats) and can **Generate arc** by hand or delete one.
- **Relationships** with automatic decay over GAME time (a "week" is seven game days;
  a frozen or slow world clock slows the decay with it) and periodic summaries.
  Each pair also carries a **form of address per direction** — free text saying how A
  addresses B and how B addresses A ("formal, calls her Harbour Mistress" / "informal,
  nickname Pip"). The speaking character gets its own direction in the chat prompt, which
  is what keeps a German world from drifting between a formal and an informal address
  mid-conversation. Edited in Game-Admin → Characters → **Relationships**.
- **Phone panel:** a phone-style chat layout in `/play` for remote conversations, with a
  world-configurable frame.

### Knowledge, search & automation
- **Knowledge extraction** (`knowledge` package): pull facts from local files (Markdown/JSON/…) via
  LLM, mtime-cached, with a search verb the character can use during chat.
- **Web search** via a self-hosted SearX/SearXNG package; **n8n** webhook calls; a **markdown
  writer** so characters keep their own diary and notes.
- **Scheduler:** per-character jobs (`interval` / `cron` / `date`) on the game calendar, with actions
  like send-message, execute-tool or set-status. Each job row carries **Run now** — one run out of
  band that leaves the schedule where it is — and an expandable **Log** of its last runs in world
  time (time, outcome, message).
- **Improvements queue:** the Game-Admin collects "this world could use X" findings as typed,
  gated work items and runs them through the task queue.
- **Content marketplace:** install content and skill packages from one or more configured catalogs
  (each cached per world, optional auth token). **Installed skill packages** are listed in the same
  tab and can be removed again — installing runs code, so it asks for an explicit confirmation;
  removing deletes the folder under `plugins/installed/` and reloads the skills.

### Platform
- **Plugin system:** every skill is a self-contained package under the top-level `plugins/`
  directory (a folder with `plugin.yaml` plus code, LLM templates, config schema, character-template
  fragments, body slots). The core never names a skill — capabilities are wired through hooks,
  intents, tool flags and `requires`/`conflicts`. Deleting a package's folder removes exactly that
  feature, down to its buttons in both clients. Marketplace installs land in `plugins/installed/`.
  **NSFW packages ship separately** and are never part of this repository.
- **Auth & multi-user:** session cookies, bcrypt hashes, admin/user roles, per-user access lists for
  characters, capped uploads and a per-user limit on concurrent GPU jobs. Everyone can change their
  own password (`POST /auth/password`) — players in `/play` under **Avatar settings → Preferences →
  Password**, admins under `/admin/users` → **Change my password**. A change ends every OTHER
  session of that account and keeps the one doing it; an admin password reset under `/admin/users`
  signs the target out everywhere.
- **Logging & monitoring:** LLM call log (`/logs/llm`), image-prompt log (`/logs/image-prompts`),
  LLM stats, dashboard, `GET /health`, and a task queue inspectable from the CLI.
- **i18n:** all UI strings are English at the source and translated through `t()`; translation maps
  live in `shared/languages/<lang>.json` (currently German).

---

## Installation

Tested on **Ubuntu 24.04** (e.g. a Proxmox LXC container). Python **3.11+** required; the Docker
image is built on Python 3.13.

### 1. Prerequisites

At minimum you need **one LLM provider**. Everything else is optional and only needed for the
corresponding feature.

| Purpose            | Options                                                                       |
|--------------------|------------------------------------------------------------------------------|
| **LLM (required)** | Ollama · any OpenAI-compatible API (LocalAI, vLLM, llama-swap, …) · Anthropic |
| Image generation   | Stable Diffusion WebUI (A1111/Forge, run with `--listen --api`) · CivitAI · Together.ai · LocalAI · `openai_chat` · `openai_diffusion` |
| Video generation   | `openai_video` · `localai_video` · `together_video`                           |
| 3D meshes          | `openai_mesh` (an image-to-3D gateway)                                        |
| Text-to-speech     | XTTS v2 · F5-TTS · Magpie (Riva)                                              |
| Web search         | SearX / SearXNG                                                               |

System packages:
```bash
apt update
apt install -y git python3-venv build-essential python3-dev ffmpeg
```

### 2. Clone
```bash
git clone https://github.com/KaletoAI/anima-verse.git
cd anima-verse
```

### 3. Virtual environment
```bash
python3 -m venv .venv

# Linux/Mac (bash/zsh):
source .venv/bin/activate

# fish shell:
source .venv/bin/activate.fish

# Windows:
.venv\Scripts\activate
```
> You do not have to activate the venv to run things — you can always call the interpreter
> directly (`./.venv/bin/python …`, `./.venv/bin/pip …`).

### 4. Install dependencies
```bash
pip install -e .
```

### 5. Download models
The large model binaries are not committed to the repo. Fetch them **after** installing
dependencies:
```bash
./fetch_models.sh
```
This downloads `u2net.onnx` (background removal for outfit previews and world/map images) and the
built-in embedding model `BAAI/bge-small-en-v1.5` (pose matching, via `fastembed`). The script is
idempotent and verifies checksums. The embedding model otherwise auto-downloads on first use, so
this step is optional — but it makes the first run offline-capable and predictable.

### Docker
See [`docker/README.md`](docker/README.md) for container deployment.

### Updating
```bash
git pull origin main
source .venv/bin/activate          # bash/zsh
# source .venv/bin/activate.fish   # fish shell
pip install -e .
```

---

## Running the server

```bash
chmod 755 start.sh        # first time only

./start.sh                  # storage: ./storage
./start.sh --world NAME     # open or create worlds/NAME — e.g. --world demo
./start.sh --storage /path  # use an arbitrary storage directory
./start.sh --with-3d        # also start the 3D client as a second process

./start.sh --stop | --restart | --status
./start.sh --help
```

`--with-3d` combines with the others; `--stop` always stops both processes. The 3D client's port and
backend target come from the environment (`CLIENT3D_PORT`, default `5183`; `ANIMA_API`, default
`http://localhost:8000`).

| Port  | What                                             |
|-------|--------------------------------------------------|
| 8000  | the backend: `/play`, `/game-admin`, `/admin/*`   |
| 5183  | the 3D client (`--with-3d` or `npm run dev -w client3d`) |
| 5173  | the Vite dev server for the React SPA            |

Logs live in `logs/`: `logs/main.log` (server, rotated into `logs/archive/` on restart),
`logs/llm_calls.jsonl`, `logs/image_prompts.jsonl`, and `logs/client3d.log` when the 3D client runs.

Once running, open `http://<host>:8000/` — it redirects to the Player UI at `/play`.

### First login

Every route needs a session. A world that has no users yet gets a bootstrap admin on first start:
the server creates the user `admin` with a **random** password and logs it **once** at WARNING
level.

```bash
grep "BOOTSTRAP ADMIN" logs/main.log
# === BOOTSTRAP ADMIN CREATED === username='admin' password='…' — shown ONCE, log in and change it. ===
```

The password is stored only as a bcrypt hash and is never printed again, so pick it up before you do
anything else. Log in on the form that `/play` shows, then open `/admin/users` and change it in the
**Change my password** block (current + new + repeat) — the same page adds further users. Changing a
password signs out every other session of that account; the one you are using stays. Players without
admin rights find the same form in `/play` under **Avatar settings → Preferences → Password**.
No line at all means the world already has users.

### Frontend development

The repository is an npm workspace root (`frontend`, `client3d`, `packages/*`) — one `npm install`
at the top covers all of them. The React app is committed pre-built under `static/game_admin/`, so a
source checkout runs without Node at all.

```bash
npm install                  # once, from the repository root

npm run dev:admin            # Vite dev server on :5173 (= npm run dev -w frontend)
npm run build:admin          # tsc -b && vite build → static/game_admin/
npm run dev:client3d         # 3D client on :5183
npm run build:client3d       # tsc --noEmit && vite build → client3d/dist/
npm run build                # both apps

npm run lint -w frontend     # the only lint script; covers frontend/ and packages/*/src
ANIMA_API=http://<host>:8000 npm run dev -w client3d   # against a backend elsewhere
```

See [`frontend/README.md`](frontend/README.md) and [`packages/README.md`](packages/README.md) for
the details of each workspace.

---

## Worlds & storage

Each **world** is a self-contained directory under `worlds/`. Multiple worlds can co-exist and are
selected at startup with `--world NAME`. All structured data lives in **two SQLite databases per
world**:

- `world.db` — users, characters and their runtime state, locations/rooms, items, inventory,
  outfits, memories, knowledge, relationships, mood/state history, summaries, notifications, events,
  scheduler jobs/logs, story arcs, parties, perceptions and chat messages, …
- `task_queue.db` — the persistent task queue (image/video/mesh generation, LLM jobs, animations).

World data is **DB-only** — there are no JSON mirrors or backups on disk. Everything else under a
world directory is configuration or binary content, created on demand:

```
worlds/{world}/
  world.db                  # primary data store (see above)
  task_queue.db             # persistent task queue
  config.json               # per-world config: LLM providers, media backends, TTS, routing, …
  secrets.json              # API keys / passwords (gitignored, overlaid at load)
  world_setup.json          # optional per-world briefing injected into prompts
  knowledge/                # source files for the knowledge-extraction skill
  characters/{Name}/        # per-character galleries, generated images, outfits, soul/, 3D models
  items/{item_id}/          # item images
  props/                    # prop source images and variants
  locations/{id}/model3d/   # per-location building meshes
  world_gallery/            # generated location / room backgrounds
  events/                   # event images
  scene_render/             # rendered scene shots
  instagram/                # per-character Instagram posts
  stories/                  # rendered story scene stills
  chat_uploads/             # user-uploaded chat images
  ui/                       # per-world UI assets (e.g. the messaging frame)
  tmp/                      # temporary files (TTS audio, story stills, …)
  .cache/                   # thumbnails and marketplace catalog caches (disposable)
```

Cross-world, read-only resources shared by every world live under `shared/`: character / expression /
pose / soul templates, the LLM prompt templates, the item catalog, surface textures, the animation
clip library and reference rig, language files, and the world-dev prompt specifications
(`character`, `location`, `map`). **Model capabilities are deliberately outside the worlds** —
`shared/config/model_capabilities.json` describes a model plus its hardware, not a world, and is
tracked in git. Model binaries fetched by `fetch_models.sh` live under `models/` (gitignored), as do
`voices/`, `exports/` and `storage/`.

The repository ships a pre-populated `demo/` world as a starter; `worlds/demo/` **is** tracked in
git. Pass `--world <new-name>` to begin from a clean slate — the directory is created on first
start.

### The bundled world: Tidehaven

A small terraced town on a west-facing shore, a few decades from now, after people stopped throwing
things away. Four places — **Salt Quay** at the water, **Market Terrace** above it, **The Terrace
House** on the second terrace and **Wend Light** out on the headland, a 637 m walk along the coast
path. Seven characters live there: five people, a harbour dog and one visitor off the noon ferry.

It is built to exercise the system rather than to look pretty in a screenshot. Between them the
seven cover both chat modes (`single` and `rp_first`), all three importance levels, an
avatar-playable character, a non-humanoid on the second mesh contract, and the temporary-NPC
template. The town carries a story arc, a danger event with its own temporary access rule, two
different kinds of locked room (one by rule, one by item), a travelling party, daily schedules,
scheduler jobs and a knowledge source of local files. The map is painted in metres with two terraces
and a raised headland; every room has a floor plan, so the 3D client and the floor-plan preview have
real geometry to render.

**No images or 3D models ship with it** — those need your own backends. Every prompt field is
filled in, so generating them is a matter of pressing the buttons in the admin UI. The visual style
is set per use case in `config.json`: a painterly gouache look for everything on screen, while the
mesh-source renders keep their neutral, shadowless framing, because image-to-3D needs that more than
it needs the style.

---

## Getting started

The quickest start is the **bundled `demo` world** — `./start.sh --world demo` boots it as-is; you
only need to point it at an LLM backend in the admin UI. To build your own world from zero instead,
the full step-by-step walk-through (create a world, configure providers, build characters, the map,
rules, chat mode, …) lives in
**[docs/getting-started-new-world.md](docs/getting-started-new-world.md)**.

Either way, the part most people get stuck on first is a **working LLM (and image) backend**. Two
setups that work out of the box:

### Option A — LocalAI (self-hosted, OpenAI-compatible)

[LocalAI](https://localai.io) serves chat, vision and image models behind one OpenAI-compatible
endpoint, so it slots straight into Anima Verse as a normal `openai` provider. What the demo world
is configured for:

- **One LLM provider** `LocalAI`, type `openai`, `api_base = http://<host>:8080/v1`, no API key.
  Then split the routing across two LLM entries:
  - a **chat / RP** model (e.g. `rocinante-12b-v1.1`) for `chat_stream`, `story_stream`,
    `storyteller` and `thought` — the `npc_*` tasks follow it automatically;
  - a small **vision-capable** model (e.g. `qwen3-vl-4b`) for everything else — `intent`,
    `extraction`, `extraction_chat_state`, `spell_detect`, `image_prompt`, `image_recognition`,
    `consolidation`, `relationship_summary`, `translation`, `instagram_caption`, the random-event
    and generation helpers. One model that can both reason over tools *and* see images keeps the
    utility and vision tasks on a single endpoint.
- **Embeddings: built-in.** Set the embedding backend to *Internal* — Anima Verse runs a small ONNX
  model on CPU, so LocalAI needs no embeddings model.
- **Image generation:** add backends of type **`openai_diffusion`** (LocalAI's
  `/v1/images/generations`). `API URL = http://<host>:8080` (no `/v1`), API key empty, `Model` e.g.
  `Z-Image-Turbo` or `flux.2-klein-4b`; set `image_family` to `natural` (Flux) or `keywords`
  (Z-Image/SD). LoRAs go into the prompt as `<lora:name:weight>` and are managed in the **LoRA
  library** (enter them by hand, or set a LoRA query URL on the backend to fetch the list).
- **Mind the model's resolution ceiling.** Small distilled diffusion models are picky —
  `flux.2-klein-4b` only rendered small square sizes here (512² / 768²; 1024² and portrait sizes
  returned HTTP 500). Set the use-case / backend dimensions to a size the model actually serves.
- **Single GPU?** Chat and image share the card. Enable LocalAI's **watchdog** (Idle 2m, Busy Check
  2m, Memory Reclaimer) so it reclaims VRAM between requests instead of OOM-ing. To also stop Anima
  Verse from dispatching a chat and an image gen at the same time, give the LLM provider and the
  image backend the **same `serialize_group`** — same group = one call at a time on that GPU.

See **[docker/DEPLOYMENT.md](docker/DEPLOYMENT.md)** for a full reproducible LocalAI-backed
deployment (incl. the watchdog and a Proxmox-LXC note).

### Option B — a hosted OpenAI-compatible cloud

Any OpenAI-compatible endpoint works the same way; a flat-rate cloud such as
[Infermatic](https://infermatic.ai) (`api_base = https://api.totalgpt.ai`, API key from the account)
runs this comfortably on its cheapest plan. The split that works there is three LLM entries:

| Tasks | Kind of model | temp |
|---|---|---|
| `chat_stream`, `story_stream`, `storyteller`, `thought` | a 70B-class **RP fine-tune** | 0.7 |
| `intent`, `spell_detect`, `extraction`, `extraction_chat_state`, `consolidation`, `relationship_summary`, `random_event`, `secret_generation`, `outfit_generation`, `image_prompt`, `translation`, `intro_memory` | a **tool / reasoning** model | 0.1 |
| `image_recognition`, `instagram_caption` | a **vision** model | 0.3 |

Drive the RP model in **`rp_first`** chat mode, with the tool model behind the Tool LLM. Embeddings
(`pose_embedding`) run best built-in (*Internal*), so the cloud needs no embeddings model.

**Image generation is separate** — a text cloud covers only the LLM side. Without a local GPU, two
cheap hosted options are **[Together.ai](https://www.together.ai)** (backend type `together`,
Flux/SD models) and **[Civitai](https://civitai.com)** (backend type `civitai`, a large model + LoRA
catalogue, pay-per-image).

---

## Admin & monitoring surfaces

Everything is managed from two surfaces — no config-file editing needed:

| Surface          | URL               | What lives there                                                              |
|------------------|-------------------|------------------------------------------------------------------------------|
| **Game Admin**   | `/game-admin`     | Characters, locations/rooms, map, terrain, props, items, rules, states, events, scheduler, poses, improvements, marketplace, world-dev — the React management UI. |
| **Server Admin** | `/admin/settings` | Providers & LLM routing, media backends, TTS, users & roles, model capabilities, prompt templates, agent loop, plus LLM stats and the call/image logs — the cross-linked server-side config & monitoring pages. |

The task queue can also be inspected **without the server** — `queue_cli.py` reads the SQLite DB
directly:

```bash
python queue_cli.py list       # pending tasks (-q QUEUE, -s STATUS)
python queue_cli.py info   <task_id>
python queue_cli.py cancel <task_id>
python queue_cli.py retry  <task_id>
python queue_cli.py move   <task_id> <queue>
python queue_cli.py priority <task_id> <int>
python queue_cli.py pause  <queue>
python queue_cli.py resume <queue>
python queue_cli.py clear      # old completed/failed (--hours, --status)
python queue_cli.py stats
```

It is the one place that still reads a root `.env` (the key `TASK_QUEUE_DB`, default
`./storage/task_queue.db`); point it at `worlds/<world>/task_queue.db` for a world. Do not query a
world's databases while the server is running — SQLite locks; the `logs/*.jsonl` files are always
free to read.

---

## Checks

There is no pytest suite. Checks are standalone scripts under `scripts/`, each with a `Usage:`
docstring, each running without the server and mostly without a world DB:

```bash
./.venv/bin/python scripts/test_llm_tools.py       # LLM tool-calling
./.venv/bin/python scripts/smoke_journey_v2.py     # journey math on the metre map
./.venv/bin/python scripts/smoke_scene_recipe.py   # scene geometry against the payload spec
ls scripts/smoke_*.py                              # the rest (200+)
```

A check derives its expected numbers **by hand from the specification, in its docstring** — a script
that only records the current output proves nothing.

---

## Documentation

- **[`docs/getting-started-new-world.md`](docs/getting-started-new-world.md)** — full step-by-step
  walk-through for setting up a fresh world from zero.
- **[`docs/config-defaults.md`](docs/config-defaults.md)** — every configuration key with its
  default.
- **[`docs/llm-task-mapping.md`](docs/llm-task-mapping.md)** / **[`docs/llm-templates.md`](docs/llm-templates.md)**
  — what each LLM task is for and which template it renders.
- **[`docs/movement-model-and-skills.md`](docs/movement-model-and-skills.md)** — journeys, places and
  the movement skills.
- **[`docs/npc-slots.md`](docs/npc-slots.md)** — authoring automatic NPCs: slots on locations and
  painted areas, home areas, time windows, and the `npc.*` settings that bound them.
- **[`docs/room-conversation.md`](docs/room-conversation.md)** — who answers a line in a room:
  addressees, the single bystander the server picks, derived conversation pairs and the
  `chat.chattiness` / per-location chattiness settings.
- **[`docs/plugins.md`](docs/plugins.md)** / **[`docs/skill-core-api.md`](docs/skill-core-api.md)** —
  the plugin manifest reference and the callable core API a package may use.
- **[`docs/schnittstellen-3d.md`](docs/schnittstellen-3d.md)** — the 3D payload contract that the
  server and both renderers agree on.
- **[`docker/DEPLOYMENT.md`](docker/DEPLOYMENT.md)** — reproducible Docker deployment against a
  self-hosted LocalAI backend (single-GPU watchdog, `serialize_group`, Proxmox-LXC note).
- **[`CONTRIBUTING.md`](CONTRIBUTING.md)** — how to work in this repository.

---

## Status & disclaimers

**Alpha — vibe-coded experiment.** This project is an experiment in how far one can push a small
LLM-driven game / character simulator built with massive AI assistance ("vibe coding") rather than
a traditional engineering process. Most of the code was written interactively with an LLM in the
loop. **It has so far only been tested by a single person on a single setup.** Expect rough edges,
inconsistent error handling, undocumented assumptions about your hardware/providers, and breaking
changes between commits. Bug reports and patches are welcome — production use is not.

**Adult / NSFW content.** Anima Verse is a generic creative-writing and character-simulation
framework. The bundled demo world, character templates and image-analysis prompt are SFW. However,
the system was designed flexibly: a user can author their own NSFW character templates, prompt the
LLM into adult content, point the image-generation backends at adult-tuned models, etc. Whether the
framework is used for entirely innocuous storytelling or for explicit content is a choice made by
each user when configuring their own setup. The author does not provide adult content with this
project, and is not responsible for content users produce while running it. Users are responsible
for complying with local laws and with the acceptable-use policies of any third-party services
(LLM providers, image-generation APIs) they configure.

---

## License

Source-available, non-commercial, no public derivatives. See [`LICENSE`](LICENSE) for the binding
text — this section is a non-binding summary.

**Allowed:**
- Personal, educational and research use
- Local modifications for your own use
- Pull requests back to the upstream repository (your contribution becomes part of the project under
  the same license)

**Not allowed (without written permission):**
- Any commercial use (business, SaaS, paid service, revenue-generating product, or for-profit
  internal use)
- Publishing or distributing modified versions (no public forks / repackaged copies / hosted
  derivatives)
- Selling the Software or any derivative work

**Not Open Source.** This is *source available*, not OSI-approved Open Source. If the terms above
don't fit your use case, [contact me](#commercial-use--separate-licensing) for a separate license.

**No Warranty.** The Software is provided "as is" without any warranty. The author is not liable for
any damages or for content users generate while running the Software.

---

### Commercial use / separate licensing

For commercial deployment, hosted derivatives or open-source redistribution, contact:
github.com.discern001@passfwd.com
