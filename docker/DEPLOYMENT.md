# Anima Verse — Docker Deployment & Reproducible Test

This guide deploys Anima Verse **straight from GitHub** as a Docker container and
points it at an external **LocalAI** server for all LLM work. It is written so
anyone can reproduce the minimal end-to-end test.

The worked example uses the lab hosts below — replace the IPs with your own:

| Role | Host | Address |
|---|---|---|
| Docker host (runs the app container) | `ct112` | `192.168.8.109` |
| LocalAI server (LLM backend, OpenAI-compatible) | `ct405` | `http://192.168.8.197:8080` |

## Architecture in one paragraph

The container runs **only the FastAPI app** (chat orchestration, world simulation,
admin UI, the built React SPA). It does **not** run an LLM — every chat/tool/vision
call is routed over HTTP to the external LocalAI server. Text **embeddings** for
pose matching run **inside** the container on CPU (`fastembed`/ONNX), so no
embedding endpoint is required. Image generation, TTS, ComfyUI etc. are optional
external services configured later through the admin UI. There is **no `.env`
file**: all configuration lives per-world in `config.json` / `world.db` and is
edited at `/admin/settings`.

The image ships the curated **demo world** (`worlds/demo`, including its
`world.db` with characters, locations and rooms) so the deployment has content
immediately.

---

## Prerequisites

- A Linux host you can reach over SSH (the example: `root@192.168.8.109`).
- A running LocalAI instance reachable from that host, with **at least one chat
  model loaded** (verify: `curl http://<localai>:8080/v1/models` must list a
  model — an empty `"data": []` means no model is loaded yet).
- Outbound internet on the Docker host for the first image build (pulls the
  Python base image + dependencies; also fetches the `u2net` and `bge-small`
  models unless the build runs offline, in which case they lazy-download later).

---

## Step 1 — Install Docker (Ubuntu 24.04)

The example host is an Ubuntu 24.04 LXC container. Install Docker Engine from the
official repository:

```bash
apt-get update
apt-get install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
docker --version && docker compose version
```

> **Docker inside a Proxmox LXC:** the Docker daemon needs `nesting=1` (and
> usually `keyctl=1`) enabled on the container. If `docker info` / `docker ps`
> fails with a daemon/cgroup error, run this **on the Proxmox host** (not inside
> the container) and restart the container:
>
> ```bash
> pct set 112 --features nesting=1,keyctl=1
> pct reboot 112
> ```

---

## Step 2 — Clone the repository

The repository is public, so an anonymous HTTPS clone is enough:

```bash
cd /opt
git clone https://github.com/KaletoAI/anima-verse.git
cd anima-verse
```

---

## Step 3 — Build and start

```bash
cd docker
docker compose up -d --build
```

First build takes a few minutes (Python deps + model download). The app is then
served on **port 8100** of the host: `http://192.168.8.109:8100`.

Check it came up healthy:

```bash
docker compose ps        # STATUS should become "healthy"
docker compose logs -f   # follow startup; Ctrl-C to stop following
```

---

## Step 4 — First-run configuration (point it at LocalAI)

1. Open `http://192.168.8.109:8100/` in a browser.
2. Log in with the demo world's bootstrap admin account:

   ```
   username: admin
   password: admin1234
   ```

   (Change it under `/admin/users` for anything beyond a throwaway test.)

3. Go to **`http://192.168.8.109:8100/admin/settings`**.

4. **LLM Providers** — edit the provider named **`LocalAI`** and set its
   **API Base** to your LocalAI URL:

   ```
   http://192.168.8.197:8080
   ```

   Leave the API key empty (LocalAI accepts unauthenticated requests by default).
   Save.

5. **LLM Routing** — the demo ships routing for several task groups
   (`chat_stream`, `extraction`, `image_analysis`, `intent`, …) pre-pointed at the
   `LocalAI` provider but with placeholder model names. Set the **model** field of
   each routing row to a model your LocalAI actually serves (see
   `GET /v1/models`).

   **Minimal setup:** point **every** routing row at one general instruct model
   that supports tool/function calling. That single model then drives chat,
   thoughts, intent, summaries and image-prompt generation. Refine later if you
   want a dedicated vision model for the `image_analysis` / `image_recognition`
   tasks.

6. Save. No restart needed for config changes — they take effect on the next LLM
   call.

> **Embeddings need no configuration.** Pose matching uses the built-in CPU
> embedding model (`bge-small`, downloaded into the `anima_models` volume). It
> works out of the box; LocalAI does not need an embeddings model.

---

## Step 5 — What to test (feature coverage with LocalAI)

With one chat-capable model routed, the following work against LocalAI:

- **Chat** with a demo character (`/play`) — streamed responses.
- **Autonomous "thoughts"** — idle characters take turns via the AgentLoop.
- **Movement & activity** — ask a character to move; watch `current_location`
  change on the map.
- **Skills / tool calls** — outfit change, notifications, retrospection, etc.
  (needs a tool-calling-capable model; otherwise set the character to `rp_first`
  chat mode under its settings).
- **Memory / summaries** — daily summaries and consolidation run on the routed
  utility model.
- **Pose matching** — handled locally via the embedding model.

Optional, **not** covered by LocalAI text models and configured separately under
`/admin/settings` if you want them: image generation (image backends / ComfyUI),
TTS, web search (SearX), n8n.

---

## Operations

```bash
cd /opt/anima-verse/docker

docker compose logs -f          # follow logs
docker compose ps               # status / health
docker compose restart          # restart the app
docker compose down             # stop (keeps data volumes)
docker compose exec app bash    # shell inside the container

# Update to the latest code:
cd /opt/anima-verse && git pull && cd docker && docker compose up -d --build

# Full reset to a fresh demo world (DELETES all world data + downloaded models):
docker compose down -v && docker compose up -d --build
```

### Data persistence

State lives in named Docker volumes, not in the image:

| Volume | Mount | Contents |
|---|---|---|
| `anima_worlds` | `/app/worlds` | World data: characters, state, `config.json`, images. Seeded from the baked demo on first start. |
| `anima_models` | `/app/models` | `u2net` (background removal) + `bge-small` (pose embeddings). |
| `anima_logs` | `/app/logs` | `main.log`, `llm_calls.jsonl`, `image_prompts.jsonl`. |

Because `anima_worlds` is seeded only when **empty**, a later `git pull` that
updates `worlds/demo` will **not** change an already-running deployment. Use
`docker compose down -v` to reset to the fresh demo.

### Choosing a different world

The container opens the world named by the `WORLD` env var (default `demo`). To
run a different world, set it in `docker-compose.yml`:

```yaml
    environment:
      WORLD: myworld     # opens /app/worlds/myworld
```

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `docker` daemon won't start in an LXC | Enable `nesting=1,keyctl=1` on the Proxmox host (see Step 1). |
| Chat hangs / "no model" errors | LocalAI has no model loaded, or the routed model name doesn't match `GET /v1/models`. |
| Container `unhealthy` | `docker compose logs app` — usually a Python import or config error during boot. |
| LocalAI unreachable from the container | Confirm `curl http://<localai>:8080/readyz` works **from the Docker host**; the container shares the host's LAN route. |
| Character "promises" to move but never does | Wrong chat mode for the model — switch the character to `rp_first` and route a tool-capable model to the Tools tasks. |
