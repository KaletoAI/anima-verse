# Docker

Run Anima Verse as a single container. The container runs only the FastAPI app
(chat orchestration, world simulation, admin UI, the built React SPA) — the LLM
runs on a **separate, external** OpenAI-compatible server (e.g. LocalAI / Ollama /
vLLM) that you point the app at after the first start.

There is **no `.env` file**: configuration is per-world (`config.json` / `world.db`)
and edited at `/admin/settings`. The image ships the demo world with content.

## Quick start

```bash
git clone https://github.com/KaletoAI/anima-verse.git
cd anima-verse/docker
docker compose up -d --build
# → http://<host>:8100
docker compose logs | grep "BOOTSTRAP ADMIN"   # the one-time admin password
```

The seeded demo world has no users, so the first start creates the user `admin` with a **random**
password and logs it **once** (WARNING level). Pick it up from `docker compose logs` and change it
under `/admin/users` — it is stored only as a hash and is never printed again. Authentication is
default-deny: nothing but the login form is reachable without a session.

Then open `/admin/settings`, set the **LocalAI** provider's **API Base URL** to your LLM
server, and assign models under **LLM Routing**.

## Full guide

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for the complete, reproducible
walkthrough: installing Docker (incl. the Proxmox-LXC `nesting` note), pointing
the app at a LocalAI backend, the feature-coverage test, data volumes, updating
and resetting.

## What is in the image

Built from `Dockerfile` (two stages, `python:3.13-slim`): the Python dependencies come from
`pyproject.toml`, and the runtime image carries

- `app/` — the backend,
- `static/` — the **pre-built** React bundle (the `frontend/` sources are excluded by
  `.dockerignore`; the built assets are committed to the repository),
- `shared/` — LLM prompt templates, character templates, languages, schemas,
- `plugins/` — the skill packages. Without them the server boots but no character has any skill:
  no movement, no sleep, no party. The private NSFW pack symlinks and `plugins/installed/` are
  excluded,
- `worlds/` — including the baked demo world (`worlds/demo/world.db`; the queue DB, WAL sidecars
  and `secrets.json` are excluded).

`fetch_models.sh` runs during the build (non-fatal — without build-time internet the models
lazy-download on first use). The container listens on **8000**, published on **8100** by
`docker-compose.yml`, and has a `HEALTHCHECK` against `GET /health`.

`docker-entrypoint.sh` maps the `WORLD` environment variable (default `demo`) onto `STORAGE_DIR`
and starts uvicorn in the foreground.

## Volumes

| Volume | Mount | Contents |
|---|---|---|
| `anima_worlds` | `/app/worlds` | World data (characters, state, `config.json`, images). Seeded from the baked demo on first start. |
| `anima_models` | `/app/models` | `u2net` (background removal) + `bge-small` (pose embeddings). |
| `anima_logs` | `/app/logs` | Application logs (`main.log`, `llm_calls.jsonl`, `image_prompts.jsonl`). |

## External services (optional, configured in the admin UI)

LLM (LocalAI/Ollama/vLLM), image / video / mesh generation (LocalAI, A1111/Forge, CivitAI,
Together.ai), TTS (XTTS/F5/Magpie), SearX, n8n. None of these run inside the container — point the
app at them under `/admin/settings`. Embeddings for pose matching run **inside** the container on
CPU and need no external endpoint.

The 3D client is **not** part of this image. It is a separate Vite process that only needs the HTTP
API, so run it wherever you like with `ANIMA_API=http://<docker-host>:8100 npm run dev -w client3d`
(and add that origin to `server.cors_origins`).
