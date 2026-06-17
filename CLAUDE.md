# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Anima Verse — an LLM-driven character simulator / "living world". A Python/FastAPI backend
drives AI characters that chat, move on a world map, change outfit/activity, and render every
scene through image-generation backends. Both **LLM chat** and **LLM-driven image generation**
are first-class mechanics. NSFW-capable by user configuration; the repo itself ships SFW demo content.

The README is unusually complete — read it for the feature catalog, the world/storage layout,
and the full "getting started with a new world" walkthrough. This file covers what the README does not:
build/run commands and the cross-file architecture.

## Commands

```bash
# Backend (port 8000) — uvicorn app.server:app under the hood
./start.sh                 # bundled demo world (worlds/demo)
./start.sh --world NAME     # open/create worlds/NAME
./start.sh --storage /path  # arbitrary storage dir
./start.sh --stop | --restart | --status
# Logs: logs/main.log  (server), logs/llm_calls.jsonl, logs/image_prompts.jsonl

# Python deps (no .venv activation needed if you call the interpreter directly)
pip install -e .            # inside an activated .venv

# Task queue inspection — works WITHOUT the server, reads the SQLite DB directly
python queue_cli.py list|info|cancel|retry|move|priority|pause|resume|clear|stats
# (docstring in queue_cli.py has full usage; DB path via TASK_QUEUE_DB in legacy .env)

# Tests — plain pytest, no config; tests also run standalone as scripts
./.venv/bin/python -m pytest tests/
./.venv/bin/python tests/test_perception_earshot.py   # single test, direct

# Frontend (React/Vite, lives in frontend/)
cd frontend
npm run dev                 # Vite dev server on :5173, proxies API to :8000
npm run build               # tsc -b && vite build -> static/game_admin/
npm run lint
```

**The user handles restart/reload/testing themselves** — do not list "restart the server" as an open
task. Building + committing is the deliverable. Note that admin pages rendered server-side in Python
(e.g. `admin_settings.py`, `logs.py`) need a **server restart** to reflect JS changes, not just a browser reload.

## Configuration model — no `.env`

The app does **not** read config from a `.env` file or environment variables — do not introduce
either. (Two legacy exceptions still read a root `.env`: `queue_cli.py` for `TASK_QUEUE_DB`, and the
`docker/` setup.) Each world is self-contained under `worlds/<world>/`:

- `config.json` — LLM providers, image backends, TTS, routing. Edited through the Admin UI at `/admin/settings`, not by hand.
- `secrets.json` — API keys / JWT secret / passwords (gitignored, overlaid onto `config.json` at load).
- `world.db` — the single source of truth for nearly all structured data (characters, state, locations/rooms/activities, items, inventory, outfits, memories, knowledge, relationships, mood/history, summaries, notifications, events, scheduler jobs, group chats, story arcs, model capabilities, chat messages, ...).
- `task_queue.db` — persistent task queue (image gen, LLM jobs, animations).

Selection happens at startup via `app/core/paths.py` (`init()` reads `--world`/`--storage`). World data
is **DB-only** — `save_*` functions must not write JSON mirrors/backups. `worlds/demo/` **is** tracked in
git; other runtime/test data (e.g. `model_capabilities.json`, `suitability_cases.json`) must not be.

## Backend architecture (`app/`)

`app/server.py` is the FastAPI entrypoint. Boot order matters: `paths.init()` → `config.load()` →
`db.init_schema()` → one-time migrations → routers + lifespan services (scheduler, provider manager,
TTS, channels, agent loop). Routers under `app/routes/` are thin HTTP adapters; logic lives in `app/core/`.

**LLM access is always queued, never direct-to-provider.** The chain:
- `llm_router.py` maps logical **tasks** (`chat`, `tools`, `summarize`, `vision`, ...) → provider + model (configured in `/admin/settings → LLM Routing`).
- `provider_manager.py` owns one `provider_queue.py` (`ProviderQueue`) **per provider**, with per-provider concurrency limits and priority ordering.
- Chat/story **streaming bypasses the queue** for latency but registers for tracking; while a provider is streaming, its background tasks pause.
- **Never run two image generations in parallel on the same backend** — serialize on the GPU/backend channel. Each GPU is its own queue channel.
- `model_capabilities.py` / `model_suitability.py` track per-model tool-calling and vision support (per-world, in `world.db`, editable in `/admin/models`).

**Prompt construction is Jinja2 templates, not Python string-building.** All LLM prompts live under
`shared/templates/llm/` and are loaded by `prompt_templates.py` (`StrictUndefined` — missing vars raise loudly):
- `tasks/<task>.md` — one per `llm_call()` task, split into `## system` / `## user`.
- `sections/<name>.md` — reusable system-prompt blocks.
- `chat/<scenario>.md` — chat/thought composites.
- `skills/<skill>.md` — name + description metadata per skill.
Templates are live-editable at `/admin/templates`. **Claude improves these prompt templates directly** —
there is no self-service prompt-tuning tool for the user. `system_prompt_builder.py` only loads
per-character data (`load_prompt_data`); the actual composition is in the templates.

**Two chat modes** (`chat_mode` per character, must match the model's tool-calling ability):
- `single` — the chat LLM emits tool calls inline (needs a tool-capable model).
- `rp_first` — chat LLM answers in-character prose first, then a separate **Tool LLM** (`thoughts.py` context) translates that prose into skill calls. Use this for RP fine-tunes. Symptom of the wrong mode: character "promises" to move but `current_location` never changes.

**Skills** (`app/skills/`) are tool calls characters invoke. `BaseSkill` (`skills/base.py`) defines the
contract; `skill_manager.py` registers built-ins by explicit import and auto-loads the **top-level
`plugins/`** directory (`searx/`, `n8n/`, `knowledge/` — each a folder with `plugin.yaml` + `skill.py`)
via `app/plugins/loader.py`; see `docs/plugins.md`. Flags on a skill class: `ALWAYS_LOAD` (loaded always, enabled per-character),
`DEFERRED` (intent detected during chat, executed after the response), `CONTENT_TOOL` (result must flow
back into the RP, triggers a retry in `rp_first`). `intent_engine.py` picks which skills to surface.

**Movement is structured, never narrative.** A character changes location only via `set_location_skill`
(named places, pathfinder), `move_skill` (one grid step), or a teleport spell — never by RP text claiming a
cross-location jump. `move_skill` is `ALWAYS_LOAD` but default-off; passable terrain tiles are reachable only via Move.
**Activity is free text, not a library** — `activity_hint` + free LLM output, no activity-library lookup.
Activity resets are coupled to location changes (account for teleports).

**Image generation is use-case-driven.** Every render occasion is a `use_case` (`config.json → image.use_cases`);
the **style belongs to the use-case** (`use_cases.<uc>.styles.<family>`), not to the model or workflow.
`image_family` (`natural` = flowing prose for Flux/Qwen, `keywords` = comma tags for Z-Image/SD) selects both the
prompt adapter **and** which style family applies. Reference-slot priority is Agent > Room > others > Items; a
reference image supplies **appearance only** — outfit/activity stay in the text, location is stripped only when the
room itself is slotted.

**The AgentLoop** (`agent_loop.py`) is a continuous weighted-round-robin loop (importance 1/2/3 → ticket
count) that gives idle characters autonomous "thought" turns between user messages. It excludes sleeping
characters and the user's avatar, and shares its pause switch with the TaskQueue admin pause (persisted in DB).

**Room/perception model:** chat context for a character is the **room perception stream** (what it heard
in the room, multi-party transcript), not a 1:1 pairwise history — see `perception.py`, `chat_engine.py`.
Chat messages persist in the `chat_messages` table in `world.db`, not in JSON files.

**Three distinct nouns, keep them separate:** **Character** (generic entity) · **Agent** (an
LLM-driven chat partner / NPC) · **Avatar** (a character the user has taken over and now controls;
it stops acting autonomously).

## Frontend

Two coexisting UIs:
- **Legacy vanilla JS** — `templates/index.html` (Jinja) + `static/script.js` + `static/themes/`. The classic chat/admin surface.
- **React/Vite SPA** in `frontend/` — builds to `static/game_admin/` and is served by FastAPI at two routes from one project: `index.html` → **Game-Admin** (`/game-admin`), `play.html` → **Player UI** (`/play`). Tabs are registered in `frontend/src/tabs/registry.ts`; player panels in `frontend/src/player/`; API client in `frontend/src/lib/api.ts`.

New work is React. Modals inside the `/play` react-grid-layout must be rendered via `createPortal` to
`document.body`, or they render as an empty floating window. No `window.prompt/alert/confirm` — build real
in-app UI for inputs and confirmations.

## Conventions

- **A feature is backend + UI.** Never ship a backend capability and tell the user to edit the DB; it needs a UI surface.
- **Character settings render generically from templates** (`shared/templates/character/*.json` via `TemplateTab`/`TemplateField`) — never hardcode field lists or per-feature forms.
- **New/changed Admin-UI strings: English only** (existing German strings stay; no sweep). **Communicate with the user in German.** Code comments are a German/English mix — match the surrounding file.
- **No backward-compat shims on renames/refactors** without asking — no fallback readers, no alias fields.
- **No hardcoded character stats** (stamina/stress/lust/...) — keep stat handling generic (regex/dict-driven).
- **No real usernames in code** (docstrings/CLI help/examples) — `demo` is the only OK sample name.
- **UTC everywhere** — timestamps via `app/core/timeutils` (`utc_now`, `parse_iso`); never naive `datetime.now()`/`fromisoformat`.
- **ComfyUI workflows:** only overwrite nodes titled `input_*`; everything else is the user's workflow design. For `Switch any [Crystools]` nodes set only `boolean`. Reference-image slots use deterministic names (`<workflow>_slot_ref_N.png`), never timestamps. `backend.generate` returns the literal string `"NO_NEW_IMAGE"` on a cache hit — catch it explicitly before indexing `images[0]`.
- **Propose before implementing** — agree on *what* is next and the approach before doing it; one topic at a time; ask before structural/setup changes (repo location, `git init`, remotes). Commits are fine when asked.

## Git

End commit messages with:

```
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
```

## Design docs

`development_instructions/` holds the living plan/design docs — read the relevant one before changing a
subsystem (e.g. `image-creation.md`, `plan-room-conversation*`, `plan-temporary-npcs.md`, `plan-missing-ui-features.md`).
`shared/world_dev_schemas/` holds the JSON Schemas the world-dev UI validates against.

`docs/` is the technical reference (config defaults, LLM task mapping/templates, movement model, plugins).
`CHAT_PROMPTS.md` documents the chat system/user prompt layout and caching behavior. `documentation/` is
an older Telegram/channel-era doc set — prefer `docs/` and `development_instructions/` when they conflict.
