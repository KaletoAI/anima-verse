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
admin UI, the built React SPA, and the skill packages from `plugins/`). It does **not**
run an LLM — every chat/tool/vision call is routed over HTTP to the external LocalAI
server. Text **embeddings** for
pose matching run **inside** the container on CPU (`fastembed`/ONNX), so no
embedding endpoint is required. Image generation, TTS etc. are optional
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

### Important: LocalAI watchdog on a single GPU

If the chat model and the image model share **one GPU**, they cannot both stay
resident at once — loading the second on top of the first exhausts VRAM and the
request fails with `HTTP 500 … cudaMalloc failed: out of memory` (or
`inference failed`). Enable LocalAI's **watchdog** so it unloads the idle model
and reclaims VRAM before serving the next request. In the LocalAI settings
(`/app/studio` → settings, or the server config), the working setup is:

| Setting | Value |
|---|---|
| Idle watchdog (Idle Timeout) | **enabled, 2m** |
| Busy watchdog (Busy Check Enabled, Busy Timeout) | **enabled, 2m** |
| Memory Reclaimer | **enabled** |

With this, concurrent chat + image requests serialize on LocalAI's side (the
second waits while the first model is reclaimed) instead of OOM-ing.

**Optional — serialize on the Anima Verse side too.** `Max Concurrent` only limits
parallelism *within* one channel. To make the chat provider and the image backend
share **one** slot (so Anima Verse never even dispatches a chat and an image gen at
the same time), give them the same **Serialize Group**: in `/admin/settings`, set the
same free-text group name (e.g. `localai-gpu`) on the **LLM Provider** *and* on each
LocalAI entry under **Media Generation → Backends**. Same group = one call at a time
across those channels, the rest queue. Leave it empty to keep the default per-channel
behavior.

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
2. Log in with the bootstrap admin account. The seeded demo world has no users, so the first
   start created the user `admin` with a **random** password and logged it **once** at WARNING
   level:

   ```bash
   docker compose logs | grep "BOOTSTRAP ADMIN"
   # === BOOTSTRAP ADMIN CREATED === username='admin' password='…' — shown ONCE, log in and change it. ===
   ```

   The password is stored only as a bcrypt hash and is never printed again, so copy it out of the
   log now. Change it under `/admin/users` once you are in. (`docker compose down -v` resets the
   volume to the fresh demo world — the next start then logs a NEW bootstrap password.)

3. Go to **`http://192.168.8.109:8100/admin/settings`**.

4. **LLM Providers** — edit the provider named **`LocalAI`** and set its
   **API Base URL** to your LocalAI URL:

   ```
   http://192.168.8.197:8080
   ```

   Leave the API key empty (LocalAI accepts unauthenticated requests by default).
   Save.

5. **LLM Routing** — the demo ships two LLM entries on the `LocalAI` provider: a
   chat/RP model for `chat_stream`, `story_stream`, `storyteller` and `thought`, and a
   small vision-capable model for the utility tasks (`intent`, `extraction`,
   `extraction_chat_state`, `spell_detect`, `consolidation`, `relationship_summary`,
   `image_prompt`, `image_recognition`, `translation`, `instagram_caption`, the
   random-event and generation helpers). Open the **LLMs** page and set each entry's
   **Model** to a model your LocalAI actually serves (see `GET /v1/models`); the
   **Tasks** page shows which task ends up where and the **Overview** page shows what
   the server would resolve right now.

   **Minimal setup:** one entry, one general instruct model with tool/function
   calling, and give it every task. A task nobody routes falls back to its parent
   (`npc_*` → `chat_stream`, `furnish` → `intent`, …), so the Tasks page does not have
   to be filled completely. Refine later with a dedicated vision model for
   `image_recognition`.

6. Save. No restart needed for config changes — they take effect on the next LLM
   call. The one exception is **Server → Allowed CORS origins**, which is read at
   startup: set it (and restart the container) only if something outside this server
   calls the API — for example the 3D client, which is not part of the image and runs
   as its own Vite process (`ANIMA_API=http://192.168.8.109:8100 npm run dev -w client3d`).

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
  chat mode under its settings). The verbs come from the `plugins/` packages baked
  into the image — a character with no skills at all means the directory is missing.
- **Memory / summaries** — daily summaries and consolidation run on the routed
  utility model.
- **Pose matching** — handled locally via the embedding model.

Optional, **not** covered by LocalAI text models and configured separately under
`/admin/settings` if you want them: image generation (image backends),
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
# Use reset --hard, not plain "git pull": the baked demo world.db is modified at
# runtime, so the checkout is dirty and a pull would fail with a merge conflict.
# (World data lives in named volumes and survives the rebuild — see below.)
cd /opt/anima-verse && git fetch origin && git reset --hard origin/main \
  && cd docker && docker compose up -d --build

# Verify it came back healthy:
docker inspect -f '{{.State.Health.Status}}' anima-verse   # -> healthy
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8100/play   # -> 200

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
| `HTTP 500 … cudaMalloc failed: out of memory` / `inference failed` | A single GPU can't hold the chat + image model at once. Enable LocalAI's watchdog (Idle 2m, Busy Check 2m, Memory Reclaimer) so it reclaims VRAM between requests — see "LocalAI watchdog on a single GPU" above. |
| Image render fails with `inference failed` only at larger sizes | The image model has a resolution ceiling on this GPU (e.g. `flux.2-klein-4b` only does small square sizes ≤768²). Lower the use-case / backend dimensions. |
| Container `unhealthy` | `docker compose logs app` — usually a Python import or config error during boot. |
| LocalAI unreachable from the container | Confirm `curl http://<localai>:8080/readyz` works **from the Docker host**; the container shares the host's LAN route. |
| Character "promises" to move but never does | Wrong chat mode for the model — switch the character to `rp_first` and route a tool-capable model to the `intent` task. |
