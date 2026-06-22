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
# → http://<host>:8100   (login: admin / admin1234)
```

Then open `/admin/settings`, set the **LocalAI** provider's API base to your LLM
server, and assign models under **LLM Routing**.

## Full guide

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for the complete, reproducible
walkthrough: installing Docker (incl. the Proxmox-LXC `nesting` note), pointing
the app at a LocalAI backend, the feature-coverage test, data volumes, updating
and resetting.

## Volumes

| Volume | Mount | Contents |
|---|---|---|
| `anima_worlds` | `/app/worlds` | World data (characters, state, `config.json`, images). Seeded from the baked demo on first start. |
| `anima_models` | `/app/models` | `u2net` (background removal) + `bge-small` (pose embeddings). |
| `anima_logs` | `/app/logs` | Application logs. |

## External services (optional, configured in the admin UI)

LLM (LocalAI/Ollama/vLLM), image generation (ComfyUI / SD / Together), TTS
(F5/XTTS), SearX, n8n. None of these run inside the container — point the app at
them under `/admin/settings`. Embeddings for pose matching run **inside** the
container on CPU and need no external endpoint.
