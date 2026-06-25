# Anima Verse

**An LLM-driven character simulator — a "living world" of AI characters that chat, move
around a world map, change their outfit and activity, and have every scene rendered through
image-generation backends.** A Python/FastAPI backend drives the simulation; the UI is a
React single-page app plus a set of server-rendered admin pages.

**What sets it apart.** Unlike chat-centric frontends (e.g. SillyTavern) where image generation is
an optional add-on, Anima Verse treats **both LLM chat and LLM-driven image generation as
first-class, deeply integrated mechanics** — characters update their location, activity and outfit
through tool calls, every scene can be rendered, mood drives expression, and the world map shows
what each character is currently doing. The experiment is to see what kind of "living world"
emerges when both modalities are pushed that hard at the same time.

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
- [Documentation](#documentation)
- [Status & disclaimers](#status--disclaimers)
- [License](#license)

---

## How it works (architecture)

**Backend — Python / FastAPI.** `app/server.py` is the entrypoint. Thin HTTP routers live under
`app/routes/`; the actual logic lives in `app/core/`. Nearly all structured data for a world lives
in a single SQLite database (`world.db`); a second database (`task_queue.db`) holds the persistent
task queue.

**LLM access is always queued.** Logical *tasks* (`chat`, `tools`, `summarize`, `vision`,
`embedding`, …) are mapped to a concrete *provider + model* via **LLM Routing**. Each provider has
its own queue with concurrency limits and priority ordering; each GPU is its own channel. Chat /
story streaming bypasses the queue for latency but is still tracked. Two image generations never
run in parallel on the same backend.

**Prompts are Jinja2 templates, not Python string-building.** Every LLM prompt lives under
`shared/templates/llm/` and is live-editable at `/admin/templates`.

**Two frontends, one project:**

- **React / Vite SPA** (`frontend/`, built to `static/game_admin/`):
  - **Player UI** at **`/play`** — the actual game: chat, world map, character panels, gallery,
    phone messaging. `/` redirects here.
  - **Game-Admin** at **`/game-admin`** — world building: characters, locations/rooms/activities,
    items, rules, events, per-character "Mind" debugging.
- **Server-rendered admin pages** (Python) — `/admin/settings`, `/admin/users`, `/admin/models`,
  `/admin/agent-loop`, `/admin/templates`, `/admin/llm-stats`, `/logs/*`, `/dashboard`. These are
  the configuration surface; there is no React replacement for them.

**Three nouns, kept distinct:** a **Character** is any entity; an **Agent** is an LLM-driven chat
partner / NPC; an **Avatar** is a character the user has taken over and now controls directly (it
stops acting autonomously).

---

## Features

### LLM & routing
- Multiple providers per world (types: **OpenAI-compatible**, **Ollama**, **Anthropic**) configured
  through the admin UI — API keys land in a gitignored `secrets.json`.
- **Simple model picker** (`/admin/settings → LLM Models`): one provider + model per job category
  (chat / tools / helper / vision / embedding). It auto-fills the full **LLM Routing (Advanced)**
  page, which supports per-task fallback chains, per-provider concurrency/timeouts and per-character
  overrides.
- Per-provider queues with priority ordering; per-GPU channels; automatic availability checks and
  upstream-failure cooldown + fallback.
- **Model Capabilities** database (per-world): tracks tool-calling and vision support per model,
  editable at `/admin/models`.
- **Built-in text embeddings** (`fastembed` / ONNX, CPU — no external endpoint needed) used for
  pose matching; `auto` / `internal` / `external` backends, configurable in the admin UI.

### Chat & memory
- Real-time streaming chat over Server-Sent Events.
- **Room-perception model:** a character's context is the multi-party transcript of what it heard
  in its room, not a 1:1 pairwise history.
- Two chat modes per character: **`single`** (tool-capable model emits tool calls inline) and
  **`rp_first`** (RP model writes prose, a separate Tool LLM translates it into skill calls —
  recommended for RP fine-tunes).
- Tiered memory consolidation (day → week → month summaries), commitments, cross-character
  knowledge, anti-repetition temperature control.
- **Agent Loop:** idle characters take autonomous "thought" turns between user messages
  (importance-weighted round-robin; excludes sleeping characters and the user's avatar).
- **Intent Engine** decides which skills to surface for a given turn.

### Characters, avatars & world
- Template-driven character editor (no hardcoded field lists) with appearance, personality
  (the markdown "soul"), outfits, mood, location and activity.
- **Avatar takeover:** step into any playable character — their location/mood/outfit follow your
  decisions and they stop acting on their own.
- **Structured movement only:** characters change location via the `set_location` skill
  (pathfinder over named places), a single `move` grid step, or a teleport spell — never by RP text
  claiming a cross-location jump. A 2D **world map** shows where everyone is and what they're doing.
- Locations → rooms → activities (**activity is free text**, not a fixed library). Per-location
  `known_locations`, an `entry_room`, item-gated rooms, and rule-based access control.
- **Events:** disruption / danger events can swap the room background and spawn temporary access
  rules (e.g. "can't leave during the fire"); announcements bump nearby characters.
- **World Freeze:** pause the autonomous simulation (agent loop, ticks, scheduler, Telegram) while
  keeping the task queue and LLM tools live.

### Image generation & animation
- Backends: **ComfyUI**, **Stable Diffusion WebUI (A1111/Forge)**, **CivitAI**, **Together.ai**,
  **Mammouth AI** — cost-based selection with failover.
- **Use-case-driven styling:** every render occasion is a *use case* and the style belongs to the
  use case; `image_family` (`natural` prose for Flux/Qwen vs. `keywords` tags for Z-Image/SD)
  selects the prompt adapter and style family.
- Context-aware prompts (appearance, outfit, mood, activity, location), reference-image slots for
  face consistency, pose/expression variants, outfit decency/compliance system.
- ComfyUI workflow management, automatic background removal (rembg/u2net) and image downscaling.
- Optional external **post-processing hand-off** (a separate service pulls finished images and
  writes results back via the API — this project does no pixel editing itself).
- **Animation:** turn a gallery image into a short video via a ComfyUI img2video workflow,
  asynchronously.

### Text-to-speech
- Backends: **XTTS v2** (voice cloning), **F5-TTS** (high-quality cloning), **Magpie** (NVIDIA
  Riva, multilingual) and **ComfyUI (Qwen3-TTS)**.
- Auto-TTS for every reply or on-demand per message; per-character voice config; text cleaning
  (strips markdown / emojis / mood markers before synthesis).

### Social & narrative
- **Instagram feed** (virtual) per character: image → vision-LLM caption + hashtags → post.
- **Story engine:** background story-arc progression with beats and per-beat scene images.
- **Group chat** with turn-taking; **TalkTo** for face-to-face character-to-character exchange;
  **SendMessage** for remote messages; social reactions between characters.
- **Relationships** with automatic decay over time.
- **Messaging pillar:** phone-style chat layout in `/play`, plus a Telegram integration where the
  user acts as their avatar.

### Knowledge, search & automation
- **Knowledge extraction:** pull facts from local files (Markdown/JSON/…) via LLM, mtime-cached,
  with a `KnowledgeSearch` skill for use during chat.
- **Web search** via a self-hosted SearX/SearXNG plugin.
- **Scheduler:** APScheduler-based per-character jobs (`interval` / `cron` / `date`) with actions
  like send-message, execute-tool, set-status.
- **Content marketplace:** install content packs from configured catalogs.

### Platform
- **Plugin system:** drop-in skills/integrations under the top-level `plugins/` directory
  (each a folder with `plugin.yaml` + `skill.py`).
- **Auth & multi-user:** JWT auth, bcrypt hashes, admin/user roles, per-user isolated access to
  characters.
- **Logging & monitoring:** LLM call log (`/logs/llm`), image-prompt log, LLM stats, dashboard,
  health endpoint (`GET /health`), optional Beszel GPU/VRAM monitoring.

---

## Installation

Tested on **Ubuntu 24.04** (e.g. a Proxmox LXC container). Python **3.11+** required.

### 1. Prerequisites

At minimum you need **one LLM provider**. Everything else is optional and only needed for the
corresponding feature.

| Purpose            | Options                                                                       |
|--------------------|------------------------------------------------------------------------------|
| **LLM (required)** | Ollama · any OpenAI-compatible API (vLLM, llama-swap, …) · Anthropic          |
| Image generation   | ComfyUI · Stable Diffusion WebUI (A1111/Forge, run with `--listen --api`) · CivitAI · Together.ai · Mammouth |
| Text-to-speech     | XTTS v2 · F5-TTS · Magpie (Riva) · ComfyUI (Qwen3-TTS)                        |
| Web search         | SearX / SearXNG                                                               |
| Animation          | ComfyUI (img2video workflow, e.g. Wan2.2)                                     |
| GPU monitoring     | Beszel                                                                        |

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

./start.sh                # bundled demo world (worlds/demo), port 8000
./start.sh --world NAME   # open or create worlds/NAME
./start.sh --storage /path  # use an arbitrary storage directory

./start.sh --stop | --restart | --status
```

Logs: `logs/main.log` (server), `logs/llm_calls.jsonl`, `logs/image_prompts.jsonl`.

Once running, open `http://<host>:8000/` — it redirects to the Player UI at `/play`.

### Frontend development
The React app lives in `frontend/` and is committed pre-built under `static/game_admin/`.
```bash
cd frontend
npm run dev      # Vite dev server on :5173, proxies the API to :8000
npm run build    # tsc -b && vite build → static/game_admin/
npm run lint
```

---

## Worlds & storage

Each **world** is a self-contained directory under `worlds/`. Multiple worlds can co-exist and are
selected at startup with `--world NAME`. All structured data lives in **two SQLite databases per
world**:

- `world.db` — accounts, characters and their runtime state, locations/rooms/activities, items,
  inventory, outfits, memories, knowledge, relationships, mood/state history, summaries,
  notifications, events, scheduler jobs/logs, group chats, story arcs, model capabilities,
  pose variants, chat messages, …
- `task_queue.db` — the persistent task queue (image generation, LLM jobs, animations).

World data is **DB-only** — there are no JSON mirrors/backups on disk. Everything else under a
world directory is configuration or binary content:

```
worlds/{world}/
  world.db                  # primary data store (see above)
  task_queue.db             # persistent task queue
  config.json               # per-world config: LLM providers, image backends, TTS, routing, …
  secrets.json              # API keys / passwords (gitignored, overlaid onto config.json at load)
  world_setup.json          # optional per-world briefing injected into prompts
  characters/{Name}/        # per-character galleries, generated images, outfits, soul/, skills/
  instagram/                # per-character Instagram posts
  stories/                  # rendered story scene stills
  world_gallery/            # generated location / room backgrounds
  chat_uploads/             # user-uploaded chat images
  tmp/                      # temporary files (TTS audio, story stills, …)
```

Cross-world, read-only resources shared by every world live under `shared/` (character/expression/
pose/soul templates, LLM prompt templates, item catalog, activity definitions, world-dev JSON
schemas). Model binaries fetched by `fetch_models.sh` live under `models/` (gitignored).

The repository ships a pre-populated `demo/` world as a starter; `worlds/demo/` **is** tracked in
git. Pass `--world <new-name>` to begin from a clean slate — the directory is created on first
start.

---

## Getting started

The quickest start is the **bundled `demo` world** — `./start.sh` boots it as-is; you only need to
point it at an LLM backend in the admin UI. To build your own world from zero instead, the full
step-by-step walk-through (create a world, configure providers, build characters, the map, rules,
chat mode, …) lives in
**[docs/getting-started-new-world.md](docs/getting-started-new-world.md)**.

Either way, the part most people get stuck on first is a **working LLM (and image) backend**. Two
setups that work out of the box:

### Option A — LocalAI (self-hosted, OpenAI-compatible)

[LocalAI](https://localai.io) serves chat, vision and image models behind one OpenAI-compatible
endpoint, so it slots straight into Anima Verse as a normal `openai` provider. What worked for us:

- **One LLM provider** `LocalAI`, type `openai`, `api_base = http://<host>:8080/v1`, no API key. Then
  split the routing across two models (LLM Routing):
  - a **chat / RP** model (e.g. `rocinante-12b-v1.1`) for `chat_stream`, `story_stream`,
    `group_chat_stream`, `talk_to`, `send_message`, `thought`;
  - a small **vision-capable** model (e.g. `qwen3-vl-4b`) for everything else — `extraction`,
    `intent`, `expression_map`, `image_prompt`, `image_analysis`, `image_recognition`, summaries,
    `translation`. One model that can both reason over tools *and* see images keeps the
    utility + vision tasks on a single endpoint.
- **Embeddings: built-in.** Set the embedding backend to *Internal* — Anima Verse runs a small ONNX
  model on CPU, so LocalAI needs no embeddings model.
- **Image generation:** add Image Backends of type **`openai_diffusion`** (LocalAI's
  `/v1/images/generations`). `API URL = http://<host>:8080` (no `/v1`), API key empty, `Model` e.g.
  `Z-Image-Turbo` or `flux.2-klein-4b`; set `image_family` to `natural` (Flux) or `keywords`
  (Z-Image/SD). LoRAs go into the prompt as `<lora:name:weight>` and are managed per-endpoint in the
  **LoRA Library** ("Load LoRAs" only scans ComfyUI; for LocalAI enter them by hand).
- **Mind the model's resolution ceiling.** Small distilled diffusion models are picky —
  `flux.2-klein-4b` only rendered small square sizes here (512² / 768²; 1024² and portrait sizes
  returned HTTP 500). Set the use-case / backend dimensions to a size the model actually serves.
- **Single GPU?** Chat and image share the card. Enable LocalAI's **watchdog** (Idle 2m, Busy Check
  2m, Memory Reclaimer) so it reclaims VRAM between requests instead of OOM-ing. To also stop Anima
  Verse from dispatching a chat and an image gen at the same time, give the LLM provider's GPU and
  the image backend's GPU the **same Label** — same label = same physical GPU = one call at a time.

See **[docker/DEPLOYMENT.md](docker/DEPLOYMENT.md)** for a full reproducible LocalAI-backed
deployment (incl. the watchdog and a Proxmox-LXC note).

### Option B — Infermatic (cloud, the cheapest plan is enough)

[Infermatic](https://infermatic.ai) is an OpenAI-compatible cloud with a flat subscription — the
**cheapest plan already runs Anima Verse comfortably**. Add one provider and route different jobs to
different fine-tunes:

- **Provider** `Infermatic`, type `openai`, `api_base = https://api.totalgpt.ai`, API key from your
  Infermatic account.
- **LLM Routing** — the three-model split from the *Anima Dome* world (the demo author's working
  Infermatic setup):

  | Tasks | Model | temp |
  |---|---|---|
  | `chat_stream`, `story_stream`, `group_chat_stream`, `storyteller`, `send_message`, `talk_to`, `thought`, `thought_greeting` | `TheDrummer-Anubis-70B-v1.1-FP8-Dynamic` | 0.7 |
  | `social_reaction`, `random_event`, `secret_generation`, `outfit_generation`, `intent`, `spell_detect`, `expression_map`, `extraction`, `pose_normalize`, `memory_consolidation`, `consolidation`, `relationship_summary`, `image_prompt`, `image_comment`, `translation`, `extraction_chat_state` | `Sao10K-72B-Qwen2.5-Kunou-v1-FP8-Dynamic` | 0.1 |
  | `instagram_caption`, `image_recognition`, `image_analysis` *(vision)* | `Llama-3.2-11B-Vision-Instruct` | 0.3 |

  In short: one **RP fine-tune** for the in-character prose (Anubis-70B), one **tool/reasoning**
  model for everything skill- and analysis-related (Sao10K-72B-Kunou), and a **vision** model for
  image captioning/recognition. Embeddings (`pose_embedding`) run best **built-in** (*Internal*), so
  Infermatic needs no embeddings model.
- Drive the RP model in **`rp_first`** chat mode, with the Sao10K tool model behind the Tool LLM.
- **Image generation** is separate — Infermatic only covers the LLM side. Without a local GPU, two
  cheap hosted options are **[Together.ai](https://www.together.ai)** (backend type `together`,
  Flux/SD models) and **[Civitai](https://civitai.com)** (backend type `civitai`, huge model + LoRA
  catalogue, pay-per-image). Add either under **Image Backends** instead of running ComfyUI/LocalAI
  yourself.

---

## Admin & monitoring surfaces

Everything is managed from two surfaces — no config-file editing needed:

| Surface          | URL               | What lives there                                                              |
|------------------|-------------------|------------------------------------------------------------------------------|
| **Game Admin**   | `/game-admin`     | Characters, world map, locations/rooms, items, rules, story arcs, group chats — the React management UI. |
| **Server Admin** | `/admin/settings` | Providers & LLM routing, image/TTS backends, users & roles, model capabilities, prompt templates, agent loop, plus LLM stats and call/image logs — the cross-linked server-side config & monitoring pages. |

The task queue can also be inspected **without the server** via `python queue_cli.py`
(`list` / `info` / `cancel` / `retry` / `stats` / …) — it reads the SQLite DB directly.

---

## Documentation

- **[`docs/getting-started-new-world.md`](docs/getting-started-new-world.md)** — full step-by-step
  walk-through for setting up a fresh world from zero.
- **[`docker/DEPLOYMENT.md`](docker/DEPLOYMENT.md)** — reproducible Docker deployment against a
  self-hosted LocalAI backend (single-GPU watchdog, GPU-label serialization, Proxmox-LXC note).
- **`docs/`** — technical reference (config defaults, LLM task mapping/templates, movement model,
  plugins).

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
