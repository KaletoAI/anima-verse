#!/usr/bin/env bash
#
# Start/stop script for Agent System services
#
# Usage:
#   ./start.sh                       Start the main app (default storage: ./storage)
#   ./start.sh --world demo          Start with storage: ./worlds/demo
#   ./start.sh --storage /path/to/x  Start with custom storage directory
#   ./start.sh --stop                Stop the main app
#   ./start.sh --restart             Restart the main app
#   ./start.sh --with-3d             ... and also the 3D client (own process)
#   ./start.sh --status              Show running services
#
# The 3D client is a SEPARATE process on its own port and can just as well run
# on another machine — then don't use --with-3d, but start it over there with
# ANIMA_API pointing at this host:
#   ANIMA_API=http://<this-host>:8000 npm run dev -w client3d

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_DIR="$SCRIPT_DIR/.pids"
LOG_DIR="$SCRIPT_DIR/logs"
ARCHIVE_DIR="$SCRIPT_DIR/logs/archive"
LOCK_DIR="$PID_DIR/start.lock"  # Atomares Lock via mkdir

MAIN_PID="$PID_DIR/main.pid"

MAIN_LOG="$LOG_DIR/main.log"

MAIN_PORT=8000

# pgrep -f pattern — unique enough to identify the main server, stable across
# restarts. Used to recover orphan PIDs when the PID file is missing and to
# kill stragglers when starting fresh.
MAIN_PATTERN="uvicorn app.server:app"

# ── 3D-Client (client3d) ──────────────────────────────────────────────────────
# Eigener Prozess, eigener Port, Opt-in per --with-3d. Er spricht das Backend
# ausschliesslich ueber HTTP an (ANIMA_API), laeuft also genauso gut auf einem
# anderen Rechner. Port und Backend-Ziel sind per Umgebung ueberschreibbar.
CLIENT3D_PORT="${CLIENT3D_PORT:-5183}"
CLIENT3D_PID="$PID_DIR/client3d.pid"
CLIENT3D_LOG="$LOG_DIR/client3d.log"
# Eindeutig, weil wir den Port explizit mitgeben — der nackte Vite-Aufruf
# stuende sonst als "node .../vite" ohne Bezug zu diesem Workspace da.
CLIENT3D_PATTERN="vite --port $CLIENT3D_PORT"
WITH_CLIENT3D=0

mkdir -p "$PID_DIR" "$LOG_DIR" "$ARCHIVE_DIR"

# ── Virtualenv aktivieren (falls vorhanden) ───────────────────────────────────
# POSIX-Layout:   .venv/bin/activate          (Linux, macOS, Git-Bash on Windows)
# Windows-Layout: .venv/Scripts/activate      (native Python unter Windows)
if [[ -f "$SCRIPT_DIR/.venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/.venv/bin/activate"
elif [[ -f "$SCRIPT_DIR/.venv/Scripts/activate" ]]; then
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/.venv/Scripts/activate"
fi

# ── Lock ──────────────────────────────────────────────────────────────────────
# Verhindert parallele start.sh Aufrufe (mkdir ist atomar)

acquire_lock() {
    if ! mkdir "$LOCK_DIR" 2>/dev/null; then
        echo "[start] Bereits aktiv – anderer start.sh Prozess laeuft noch."
        echo "[start] Falls nicht: rm -rf $LOCK_DIR"
        exit 1
    fi
    trap 'rm -rf "$LOCK_DIR"' EXIT
}

# ── Helpers ───────────────────────────────────────────────────────────────────

rotate_log() {
    local log_file="$1"
    if [[ -f "$log_file" && -s "$log_file" ]]; then
        local timestamp
        timestamp=$(date +%Y%m%d_%H%M%S)
        cp "$log_file" "$ARCHIVE_DIR/$(basename "${log_file%.log}_${timestamp}.log")"
        : > "$log_file"
        echo "[logs] Rotated $(basename "$log_file") -> archive/"
    fi
}

is_running() {
    local pid_file="$1"
    if [[ -f "$pid_file" ]]; then
        local pid
        pid=$(cat "$pid_file")
        if kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
        # Stale PID file
        rm -f "$pid_file"
    fi
    return 1
}

# Finds the PID of a running service by its uvicorn command-line pattern.
# Echoes a single PID or nothing. Tries lsof first (more precise — port
# binding), then falls back to pgrep -f (works without lsof installed).
discover_pid() {
    local port="$1"
    local pattern="$2"
    local pid=""
    if command -v lsof >/dev/null 2>&1; then
        pid=$(lsof -ti :"$port" 2>/dev/null | head -1 || true)
    fi
    if [[ -z "$pid" ]] && command -v pgrep >/dev/null 2>&1; then
        pid=$(pgrep -f "$pattern" 2>/dev/null | head -1 || true)
    fi
    echo "$pid"
}

# Like is_running, but also recovers from a missing PID file by locating
# the orphan process. When found, the PID file is restored so subsequent
# calls behave normally. Returns 0 if alive, 1 otherwise.
is_running_or_orphan() {
    local pid_file="$1"
    local port="$2"
    local pattern="$3"
    if is_running "$pid_file"; then
        return 0
    fi
    local pid
    pid=$(discover_pid "$port" "$pattern")
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
        echo "$pid" > "$pid_file"
        return 0
    fi
    return 1
}

# Wartet bis ein Prozess wirklich beendet ist (nicht nur Port freigegeben hat).
# Gibt 0 zurueck wenn tot, 1 wenn Timeout.
wait_for_death() {
    local pid="$1"
    local max_secs="${2:-8}"
    local i=0
    while kill -0 "$pid" 2>/dev/null; do
        ((i++)) || true
        if (( i > max_secs * 2 )); then
            return 1
        fi
        sleep 0.5
    done
    return 0
}

# Beendet alle Prozesse, die das Pattern matchen ODER auf dem Port lauschen,
# und wartet bis sie WIRKLICH tot sind. Erst danach ist es sicher,
# rotate_log aufzurufen.
kill_port() {
    local port="$1"
    local name="$2"
    local pattern="${3:-}"
    local pids=""
    if command -v lsof >/dev/null 2>&1; then
        pids=$(lsof -ti :"$port" 2>/dev/null || true)
    fi
    if [[ -z "$pids" && -n "$pattern" ]] && command -v pgrep >/dev/null 2>&1; then
        pids=$(pgrep -f "$pattern" 2>/dev/null || true)
    fi
    [[ -z "$pids" ]] && return

    for pid in $pids; do
        [[ "$pid" == "$$" ]] && continue
        echo "[$name] Stopping process on port $port (PID $pid)..."
        kill "$pid" 2>/dev/null || true
    done

    # Auf vollstaendigen Tod warten – verhindert, dass Shutdown-Logs
    # in die soeben geleerte neue Log-Datei geschrieben werden
    for pid in $pids; do
        [[ "$pid" == "$$" ]] && continue
        if ! wait_for_death "$pid" 8; then
            echo "[$name] Force killing PID $pid..."
            kill -9 "$pid" 2>/dev/null || true
            sleep 0.3
        fi
    done
}

start_main() {
    if is_running "$MAIN_PID"; then
        echo "[main] Already running (PID $(cat "$MAIN_PID"))"
        return
    fi
    # Erst alten Prozess vollstaendig beenden, DANN Log rotieren
    kill_port "$MAIN_PORT" "main" "$MAIN_PATTERN"
    rotate_log "$MAIN_LOG"
    echo "[main] Starting main app on port $MAIN_PORT..."
    cd "$SCRIPT_DIR"
    nohup "$SCRIPT_DIR/.venv/bin/python" -m uvicorn app.server:app --host 0.0.0.0 --port 8000 \
        >> "$MAIN_LOG" 2>&1 &
    local pid=$!
    echo "$pid" > "$MAIN_PID"
    echo "[main] Started (PID $pid, log: $MAIN_LOG)"
}

start_client3d() {
    if is_running "$CLIENT3D_PID"; then
        echo "[client3d] Already running (PID $(cat "$CLIENT3D_PID"))"
        return
    fi
    # Vite liegt im WORKSPACE, wenn npm es nicht an die Wurzel heben kann —
    # das haengt an den uebrigen Abhaengigkeiten und aendert sich beim
    # Aktualisieren, ohne dass jemand etwas falsch gemacht haette. Beide
    # Stellen pruefen, statt den Benutzer zu einem 'npm install' zu schicken,
    # das nichts aendert (Befund 2026-07-29: @vitejs/plugin-react 6 brachte
    # kein vite 5 mehr mit, die gehobene Kopie verschwand, der Client startete
    # nicht mehr).
    local vite=""
    for cand in "$SCRIPT_DIR/client3d/node_modules/.bin/vite" \
                "$SCRIPT_DIR/node_modules/.bin/vite"; do
        [[ -x "$cand" ]] && { vite="$cand"; break; }
    done
    if [[ -z "$vite" ]]; then
        echo "[client3d] Vite not found — looked in client3d/node_modules/.bin"
        echo "[client3d] and node_modules/.bin."
        echo "[client3d] Run 'npm install' in $SCRIPT_DIR once, then try again."
        return 1
    fi
    kill_port "$CLIENT3D_PORT" "client3d" "$CLIENT3D_PATTERN"
    rotate_log "$CLIENT3D_LOG"
    # Kein Backend-Ziel gesetzt? Dann das lokale. Ein bereits gesetztes
    # ANIMA_API bleibt stehen — so zeigt der Client auf einen anderen Rechner.
    export ANIMA_API="${ANIMA_API:-http://localhost:$MAIN_PORT}"
    echo "[client3d] Starting 3D client on port $CLIENT3D_PORT (backend: $ANIMA_API)..."
    # Vite DIREKT statt ueber 'npm run dev': npm wuerde als Elternprozess
    # dazwischenhaengen, und beim Stoppen bliebe der echte Server als Waise.
    cd "$SCRIPT_DIR/client3d"
    nohup "$vite" --port "$CLIENT3D_PORT" --host 0.0.0.0 \
        >> "$CLIENT3D_LOG" 2>&1 &
    local pid=$!
    echo "$pid" > "$CLIENT3D_PID"
    cd "$SCRIPT_DIR"
    echo "[client3d] Started (PID $pid, log: $CLIENT3D_LOG)"
}

stop_service() {
    local name="$1"
    local pid_file="$2"
    local port="$3"
    local pattern="$4"
    if is_running_or_orphan "$pid_file" "$port" "$pattern"; then
        local pid
        pid=$(cat "$pid_file")
        local note=""
        # Detect orphan (pid file freshly recovered from port lookup).
        if [[ "$(stat -c %Y "$pid_file" 2>/dev/null || stat -f %m "$pid_file" 2>/dev/null)" -ge "$(($(date +%s) - 2))" ]]; then
            note=" (orphan, recovered via port $port)"
        fi
        echo "[$name] Stopping (PID $pid)$note..."
        kill "$pid" 2>/dev/null || true
        if ! wait_for_death "$pid" 8; then
            echo "[$name] Force killing..."
            kill -9 "$pid" 2>/dev/null || true
        fi
        rm -f "$pid_file"
        echo "[$name] Stopped"
    else
        echo "[$name] Not running"
    fi
}

show_status() {
    echo "=== Service Status ==="
    if is_running_or_orphan "$MAIN_PID" "$MAIN_PORT" "$MAIN_PATTERN"; then
        echo "[main]         Running (PID $(cat "$MAIN_PID"))"
    else
        echo "[main]         Stopped"
    fi
    if is_running_or_orphan "$CLIENT3D_PID" "$CLIENT3D_PORT" "$CLIENT3D_PATTERN"; then
        echo "[client3d]     Running (PID $(cat "$CLIENT3D_PID"), port $CLIENT3D_PORT)"
    else
        echo "[client3d]     Stopped"
    fi
}

# ── Parse arguments ───────────────────────────────────────────────────────────

ACTION="start"
STORAGE_ARG=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --with-3d|--with-client3d)
                         WITH_CLIENT3D=1; shift ;;
        --stop)          ACTION="stop"; shift ;;
        --restart)       ACTION="restart"; shift ;;
        --status)        ACTION="status"; shift ;;
        --world)
            STORAGE_ARG="$SCRIPT_DIR/worlds/$2"
            shift 2 ;;
        --storage)
            STORAGE_ARG="$2"
            shift 2 ;;
        --help|-h)
            echo "Usage: $0 [--stop|--restart|--status] [--with-3d] [--world NAME|--storage PATH]"
            echo ""
            echo "  (no flags)       Start the main app (storage: ./storage)"
            echo "  --world NAME     Use ./worlds/NAME as storage directory"
            echo "  --storage PATH   Use custom storage directory"
            echo "  --with-3d        Also start the 3D client (separate process,"
            echo "                   port \$CLIENT3D_PORT, default $CLIENT3D_PORT)"
            echo "  --stop           Stop the main app AND the 3D client"
            echo "  --restart        Restart whatever the flags name"
            echo "  --status         Show service status"
            echo ""
            echo "  The 3D client only needs the HTTP API, so it can run on another"
            echo "  machine instead. Over there:"
            echo "    ANIMA_API=http://<this-host>:$MAIN_PORT npm run dev -w client3d"
            echo "  Environment: CLIENT3D_PORT (default 5183), ANIMA_API (default"
            echo "  http://localhost:$MAIN_PORT)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Export storage directory for Python app
if [[ -n "$STORAGE_ARG" ]]; then
    export STORAGE_DIR="$STORAGE_ARG"
    echo "[config] Storage directory: $STORAGE_DIR"
fi

# ── Load specific config from .env ────────────────────────────────────────────
# Only extract specific keys we need (source would fail on unquoted values with spaces)

# ── Execute ───────────────────────────────────────────────────────────────────

case "$ACTION" in
    start)
        acquire_lock
        start_main
        [[ "$WITH_CLIENT3D" == "1" ]] && start_client3d
        echo ""
        echo "==> Browser: http://localhost:8000"
        echo "==> Admin:   http://localhost:8000/admin"
        [[ "$WITH_CLIENT3D" == "1" ]] && echo "==> 3D:      http://localhost:$CLIENT3D_PORT"
        ;;
    stop)
        # Immer beide — wer mit --with-3d gestartet hat, erwartet bei --stop
        # nicht, dass der Client weiterlaeuft. Nicht laufend = "Not running".
        stop_service "main" "$MAIN_PID" "$MAIN_PORT" "$MAIN_PATTERN"
        stop_service "client3d" "$CLIENT3D_PID" "$CLIENT3D_PORT" "$CLIENT3D_PATTERN"
        ;;
    restart)
        acquire_lock
        echo "[restart] Restarting main app..."
        stop_service "main" "$MAIN_PID" "$MAIN_PORT" "$MAIN_PATTERN"
        stop_service "client3d" "$CLIENT3D_PID" "$CLIENT3D_PORT" "$CLIENT3D_PATTERN"
        sleep 1
        start_main
        [[ "$WITH_CLIENT3D" == "1" ]] && start_client3d
        echo ""
        echo "==> Browser: http://localhost:8000"
        echo "==> Admin:   http://localhost:8000/admin"
        [[ "$WITH_CLIENT3D" == "1" ]] && echo "==> 3D:      http://localhost:$CLIENT3D_PORT"
        ;;
    status)
        show_status
        ;;
esac
