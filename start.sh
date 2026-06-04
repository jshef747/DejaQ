#!/usr/bin/env bash
# DejaQ — start local services from the repository root.
# Cross-platform: macOS/Linux (native redis-server) and Windows git-bash
# (venv .exe shims + Redis inside WSL; override the distro with DEJAQ_WSL_DISTRO).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_DIR="$ROOT_DIR/server"
FRONTEND_DIR="$ROOT_DIR/frontend"
CHAT_DIR="$ROOT_DIR/chat"
RUN_DATE="${DEJAQ_RUN_DATE:-$(date +%Y-%m-%d_%H-%M-%S)}"
LOG_DIR="$ROOT_DIR/logs/$RUN_DATE"
VENV="$SERVER_DIR/.venv"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
LOG_SEPARATOR="────────────────────────────────────────────────────────────────────────"

format_terminal_logs() {
  while IFS= read -r line; do
    printf '%s\n%s\n' "$LOG_SEPARATOR" "$line"
  done
}

if [[ "${1:-}" == "--format-log-lines" ]]; then
  format_terminal_logs
  exit 0
fi

mkdir -p "$LOG_DIR"
touch "$LOG_DIR/redis.log"

STACK_ARG=""
MODE_ARG=""
LOG_MODE_ARG=""
VALIDATOR_ARG=""
OLLAMA_URL_ARG=""
OLLAMA_URL_FLAG_SET=false
DRY_RUN=false
FRESH=false
YES=false
ENV_STACK="${DEJAQ_STACK:-}"
ENV_MODE="${DEJAQ_MODE:-}"
ENV_OLLAMA_URL="${DEJAQ_OLLAMA_URL:-}"
ENV_START_LOGS="${DEJAQ_START_LOGS:-}"
ENV_VALIDATOR="${DEJAQ_VALIDATOR_ENABLED:-}"

usage() {
  echo "Usage: $0 [--stack=server|all] [--mode=local|remote] [--logs=requests|all] [--validator=off] [--ollama-url URL] [--fresh] [--yes] [--dry-run]"
  echo ""
  echo "Stacks:"
  echo "  server   Start backend services only: ChromaDB, Redis, Celery, FastAPI"
  echo "  all      Start server plus dashboard frontend and chat app"
  echo ""
  echo "Modes (generation runs through Ollama):"
  echo "  local    Ollama at http://127.0.0.1:11434 (default)"
  echo "  remote   Ollama at --ollama-url=<url> (or DEJAQ_OLLAMA_URL)"
  echo ""
  echo "Logs:"
  echo "  requests Tail compact request/response logs only"
  echo "  all      Tail all service logs"
  echo ""
  echo "Cache-answer validator is ON by default; disable with --validator=off."
  echo ""
  echo "  --fresh  Delete dejaq.db, chroma_data/, and dejaq_stats.db before starting."
  echo "           Prompts for confirmation unless --yes is also passed."
  echo ""
  echo "Environment:"
  echo "  DEJAQ_STACK             Non-interactive stack selection: server or all"
  echo "  DEJAQ_MODE              Non-interactive mode selection: local or remote"
  echo "  DEJAQ_START_LOGS        Non-interactive log mode selection: requests or all"
  echo "  DEJAQ_VALIDATOR_ENABLED Validator toggle: true (default) or false"
  echo "  DEJAQ_OLLAMA_URL        Ollama endpoint (required for remote mode)"
}

for arg in "$@"; do
  case "$arg" in
    --stack=*)
      STACK_ARG="${arg#*=}"
      ;;
    --stack)
      echo -e "${RED}Use --stack=<server|all>${NC}"; exit 1
      ;;
    --server-only|--only-server)
      STACK_ARG="server"
      ;;
    --all)
      STACK_ARG="all"
      ;;
    --mode=*)
      MODE_ARG="${arg#*=}"
      ;;
    --mode)
      echo -e "${RED}Use --mode=<mode>${NC}"; exit 1
      ;;
    --logs=*)
      LOG_MODE_ARG="${arg#*=}"
      ;;
    --logs)
      echo -e "${RED}Use --logs=<requests|all>${NC}"; exit 1
      ;;
    --validator=*)
      VALIDATOR_ARG="${arg#*=}"
      ;;
    --validator)
      echo -e "${RED}Use --validator=<on|off>${NC}"; exit 1
      ;;
    --no-validator)
      VALIDATOR_ARG="off"
      ;;
    --ollama-url=*)
      OLLAMA_URL_ARG="${arg#*=}"
      OLLAMA_URL_FLAG_SET=true
      ;;
    --ollama-url)
      echo -e "${RED}Use --ollama-url=<url>${NC}"; exit 1
      ;;
    --dry-run)
      DRY_RUN=true
      ;;
    --fresh)
      FRESH=true
      ;;
    --yes|-y)
      YES=true
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo -e "${RED}Unknown argument: $arg${NC}"
      usage
      exit 1
      ;;
  esac
done

if [[ ! -d "$SERVER_DIR" ]]; then
  echo -e "${RED}Expected server directory at $SERVER_DIR${NC}"; exit 1
fi

# ── Platform detection ──────────────────────────────────────────────────────
# Windows (git-bash) uses .venv/Scripts/*.exe and runs Redis inside WSL; Unix
# uses .venv/bin/* with a native redis-server. Detected by venv layout.
WSL_DISTRO="${DEJAQ_WSL_DISTRO:-Ubuntu}"
if [[ -f "$VENV/Scripts/python.exe" ]]; then
  IS_WINDOWS=true
  BINDIR="$VENV/Scripts"
  EXT=".exe"
elif [[ -f "$VENV/bin/python" ]]; then
  IS_WINDOWS=false
  BINDIR="$VENV/bin"
  EXT=""
else
  echo -e "${RED}No .venv found at $VENV. Run: cd server && uv sync${NC}"; exit 1
fi

# Use project venv executables directly — avoids any venv activated in the parent shell
PYTHON="$BINDIR/python$EXT"
UVICORN="$BINDIR/uvicorn$EXT"
CELERY="$BINDIR/celery$EXT"
CHROMA="$BINDIR/chroma$EXT"
ALEMBIC="$BINDIR/alembic$EXT"

REDIS_PID=""; CELERY_PID=""; CELERY_BEAT_PID=""; UVICORN_PID=""; CHROMA_PID=""
DASHBOARD_PID=""; CHAT_PID=""; TAIL_PID=""; REDIS_STARTED_HERE=false

cleanup() {
  trap - EXIT INT TERM
  if [[ "$DRY_RUN" == "true" ]]; then
    return
  fi
  echo -e "\n${YELLOW}Shutting down services...${NC}"
  stop_service() {
    local pid=$1 name=$2
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      if [[ "$IS_WINDOWS" == "true" ]]; then
        # node/python spawn child trees — kill the whole tree
        taskkill //PID "$pid" //T //F &>/dev/null || true
      else
        pkill -TERM -P "$pid" 2>/dev/null || true
      fi
      kill -TERM "$pid" 2>/dev/null || true
      echo "  $name stopped"
    fi
  }
  [[ -n "$TAIL_PID" ]] && kill "$TAIL_PID" 2>/dev/null || true
  stop_service "$CHAT_PID"        "Chat app"
  stop_service "$DASHBOARD_PID"   "Dashboard"
  stop_service "$UVICORN_PID"     "FastAPI"
  stop_service "$CELERY_BEAT_PID" "Celery beat"
  stop_service "$CELERY_PID"      "Celery worker"
  stop_service "$CHROMA_PID"      "ChromaDB"
  if [[ "$IS_WINDOWS" == "true" ]]; then
    # Drop the VM keepalive session; the WSL2 VM (and its systemd-managed Redis) idle-stops
    # on its own once no sessions remain. We don't force `redis-cli shutdown` — Redis is a
    # system service we didn't necessarily start.
    stop_service "$REDIS_PID"       "Redis keepalive"
  else
    stop_service "$REDIS_PID"       "Redis"
  fi
  echo -e "${GREEN}All services stopped.${NC}"
}
trap cleanup EXIT INT TERM

free_port() {
  local port=$1
  # lsof is Unix-only; on Windows just let the service fail loudly if the port is taken
  [[ "$IS_WINDOWS" == "true" ]] && return 0
  local pids
  pids=$(lsof -ti :"$port" 2>/dev/null) || true
  if [[ -n "$pids" ]]; then
    echo -e "  ${YELLOW}Port $port already in use — clearing...${NC}"
    echo "$pids" | xargs kill -9 2>/dev/null || true
    sleep 1
  fi
}

load_env_file() {
  local env_file=$1
  if [[ -f "$env_file" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$env_file"
    set +a
  fi
}

normalize_stack() {
  case "$1" in
    server|backend|api|server-only|only-server)
      echo "server"
      ;;
    all|full|everything)
      echo "all"
      ;;
    *)
      echo ""
      ;;
  esac
}

select_stack() {
  local selected="${STACK_ARG:-${DEJAQ_STACK:-}}"
  if [[ -n "$selected" ]]; then
    selected="$(normalize_stack "$selected")"
    if [[ -z "$selected" ]]; then
      echo -e "${RED}Invalid stack. Choose server or all.${NC}" >&2
      exit 1
    fi
    echo "$selected"
    return
  fi

  echo -e "${CYAN}Select startup stack:${NC}" >&2
  echo "  1) server  (backend services only)" >&2
  echo "  2) all     (server + dashboard + chat)" >&2
  read -r -p "Stack [1-2]: " selected
  case "$selected" in
    1|server|backend) echo "server" ;;
    2|all|full) echo "all" ;;
    *) echo -e "${RED}Invalid stack selection.${NC}" >&2; exit 1 ;;
  esac
}

normalize_mode() {
  case "$1" in
    local|localhost|dev|development|in-process|in_process)
      echo "local"
      ;;
    remote|self-hosted|self_hosted|selfhosted|cloud|on-prem|onprem|prod|production)
      echo "remote"
      ;;
    *)
      echo ""
      ;;
  esac
}

normalize_log_mode() {
  case "$1" in
    requests|request|req|clean|compact)
      echo "requests"
      ;;
    all|full|verbose|services)
      echo "all"
      ;;
    *)
      echo ""
      ;;
  esac
}

select_log_mode() {
  local selected="${LOG_MODE_ARG:-${DEJAQ_START_LOGS:-}}"
  if [[ -n "$selected" ]]; then
    selected="$(normalize_log_mode "$selected")"
    if [[ -z "$selected" ]]; then
      echo -e "${RED}Invalid log mode. Choose requests or all.${NC}" >&2
      exit 1
    fi
    echo "$selected"
    return
  fi

  echo -e "${CYAN}Select terminal log output:${NC}" >&2
  echo "  1) requests  (request/response logs only)" >&2
  echo "  2) all       (all service logs)" >&2
  read -r -p "Logs [1-2]: " selected
  case "$selected" in
    1|requests|request|clean) echo "requests" ;;
    2|all|full|verbose) echo "all" ;;
    *) echo -e "${RED}Invalid log mode selection.${NC}" >&2; exit 1 ;;
  esac
}

# Validator is ON by default; only an explicit off flag/env disables it. No prompt.
resolve_validator() {
  local raw="${VALIDATOR_ARG:-${ENV_VALIDATOR:-}}"
  case "$raw" in
    ""|on|true|1|yes|enabled)  echo "on"  ;;
    off|false|0|no|disabled)   echo "off" ;;
    *) echo -e "${RED}Invalid validator value %r. Use on or off.${NC}" >&2; exit 1 ;;
  esac
}

select_mode() {
  local selected="${MODE_ARG:-${DEJAQ_MODE:-}}"
  if [[ -z "$selected" && "$OLLAMA_URL_FLAG_SET" == "true" ]]; then
    selected="remote"
  fi
  if [[ -n "$selected" ]]; then
    selected="$(normalize_mode "$selected")"
    if [[ -z "$selected" ]]; then
      echo -e "${RED}Invalid mode. Choose local or remote.${NC}" >&2
      exit 1
    fi
    echo "$selected"
    return
  fi

  echo -e "${CYAN}Select Ollama mode:${NC}" >&2
  echo "  1) local   (Ollama at http://127.0.0.1:11434)" >&2
  echo "  2) remote  (Ollama at a given URL)" >&2
  read -r -p "Mode [1-2, default 1]: " selected
  case "${selected:-1}" in
    1|local) echo "local" ;;
    2|remote) echo "remote" ;;
    *) echo -e "${RED}Invalid mode selection.${NC}" >&2; exit 1 ;;
  esac
}

apply_mode() {
  local mode="$1" validator="$2"
  export DEJAQ_MODE="$mode"
  export DEJAQ_VALIDATOR_ENABLED="$([[ "$validator" == "on" ]] && echo true || echo false)"

  if [[ "$OLLAMA_URL_FLAG_SET" == "true" ]]; then
    export DEJAQ_OLLAMA_URL="$OLLAMA_URL_ARG"
  fi

  if [[ "$mode" == "local" ]]; then
    export DEJAQ_OLLAMA_URL="${DEJAQ_OLLAMA_URL:-http://127.0.0.1:11434}"
    return
  fi

  # remote
  if [[ -z "${DEJAQ_OLLAMA_URL:-}" ]]; then
    read -r -p "DEJAQ_OLLAMA_URL: " DEJAQ_OLLAMA_URL
    export DEJAQ_OLLAMA_URL
  fi
  if [[ -z "${DEJAQ_OLLAMA_URL:-}" ]]; then
    echo -e "${RED}DEJAQ_OLLAMA_URL is required for remote mode.${NC}" >&2
    exit 1
  fi
}

# Warn (don't fail) if the Ollama endpoint is unreachable.
check_ollama() {
  local url="$1"
  if command -v curl &>/dev/null; then
    if ! curl -sf --max-time 3 "$url/api/tags" &>/dev/null; then
      echo -e "  ${YELLOW}Warning: Ollama not reachable at $url — start it (ollama serve) and pull models.${NC}"
    else
      echo -e "  ${GREEN}Ollama reachable at $url${NC}"
    fi
  fi
}

ensure_node_app_ready() {
  local dir=$1 name=$2
  if [[ ! -f "$dir/package.json" ]]; then
    echo -e "${RED}$name package.json not found at $dir${NC}"; exit 1
  fi
  if [[ ! -d "$dir/node_modules" ]]; then
    echo -e "${RED}$name dependencies missing. Run: cd $dir && npm install${NC}"; exit 1
  fi
}

start_dashboard() {
  echo -e "${CYAN}[6/7] Starting dashboard frontend...${NC}"
  ensure_node_app_ready "$FRONTEND_DIR" "Dashboard"
  free_port 3000
  # Bind to 127.0.0.1 only — the admin dashboard is control-plane; not LAN-exposed.
  (cd "$FRONTEND_DIR" && npm run dev -- --hostname 127.0.0.1 --port 3000) &>"$LOG_DIR/dashboard.log" &
  DASHBOARD_PID=$!
  sleep 2
  if ! kill -0 "$DASHBOARD_PID" 2>/dev/null; then
    echo -e "${RED}Dashboard failed to start. Check $LOG_DIR/dashboard.log${NC}"; exit 1
  fi
  echo -e "  ${GREEN}Dashboard running (PID $DASHBOARD_PID)${NC}"
}

start_chat() {
  echo -e "${CYAN}[7/7] Starting chat app...${NC}"
  ensure_node_app_ready "$CHAT_DIR" "Chat app"
  free_port 4000
  (cd "$CHAT_DIR" && npm run dev) &>"$LOG_DIR/chat.log" &
  CHAT_PID=$!
  sleep 2
  if ! kill -0 "$CHAT_PID" 2>/dev/null; then
    echo -e "${RED}Chat app failed to start. Check $LOG_DIR/chat.log${NC}"; exit 1
  fi
  echo -e "  ${GREEN}Chat app running (PID $CHAT_PID)${NC}"
}

cd "$SERVER_DIR"

# Load backend env file so uvicorn, celery worker, and beat share the same config
load_env_file "$SERVER_DIR/.env"

if [[ -n "$ENV_STACK" ]]; then
  DEJAQ_STACK="$ENV_STACK"
fi
if [[ -n "$ENV_MODE" ]]; then
  DEJAQ_MODE="$ENV_MODE"
fi
if [[ -n "$ENV_OLLAMA_URL" ]]; then
  DEJAQ_OLLAMA_URL="$ENV_OLLAMA_URL"
fi
if [[ -n "$ENV_START_LOGS" ]]; then
  DEJAQ_START_LOGS="$ENV_START_LOGS"
fi

STACK="$(select_stack)"
MODE="$(select_mode)"
VALIDATOR="$(resolve_validator)"
LOG_MODE="$(select_log_mode)"
apply_mode "$MODE" "$VALIDATOR"

echo -e "${CYAN}Startup stack: ${STACK}${NC}"
echo -e "${CYAN}Ollama mode: ${MODE}${NC}"
echo -e "${CYAN}Validator: ${VALIDATOR}${NC}"
echo -e "${CYAN}Log mode: ${LOG_MODE}${NC}"
echo -e "${CYAN}Logs: ${LOG_DIR}/${NC}"
echo -e "  DEJAQ_OLLAMA_URL=${DEJAQ_OLLAMA_URL}"
echo -e "  DEJAQ_VALIDATOR_ENABLED=${DEJAQ_VALIDATOR_ENABLED}"
check_ollama "${DEJAQ_OLLAMA_URL}"

if [[ "$DRY_RUN" == "true" ]]; then
  echo -e "${GREEN}Dry run complete. Services not started.${NC}"
  exit 0
fi

# ── Fresh start (optional) ──────────────────────────────────────────────────
if [[ "$FRESH" == "true" ]]; then
  FRESH_TARGETS=()
  [[ -f "$SERVER_DIR/dejaq.db" ]]     && FRESH_TARGETS+=("dejaq.db")
  [[ -f "$SERVER_DIR/dejaq_stats.db" ]] && FRESH_TARGETS+=("dejaq_stats.db")
  [[ -d "$SERVER_DIR/chroma_data" ]]  && FRESH_TARGETS+=("chroma_data/")

  if [[ ${#FRESH_TARGETS[@]} -eq 0 ]]; then
    echo -e "  ${YELLOW}--fresh: nothing to delete (databases not found)${NC}"
  else
    echo -e "${YELLOW}--fresh: will permanently delete:${NC}"
    for t in "${FRESH_TARGETS[@]}"; do
      echo -e "  ${RED}  server/$t${NC}"
    done

    if [[ "$YES" != "true" ]]; then
      read -r -p "$(echo -e "${YELLOW}This cannot be undone. Continue? [y/N]: ${NC}")" CONFIRM
      if [[ "${CONFIRM,,}" != "y" && "${CONFIRM,,}" != "yes" ]]; then
        echo -e "${RED}Aborted.${NC}"; exit 1
      fi
    fi

    [[ -f "$SERVER_DIR/dejaq.db" ]]     && rm -f "$SERVER_DIR/dejaq.db"     && echo -e "  Deleted dejaq.db"
    [[ -f "$SERVER_DIR/dejaq_stats.db" ]] && rm -f "$SERVER_DIR/dejaq_stats.db" && echo -e "  Deleted dejaq_stats.db"
    [[ -d "$SERVER_DIR/chroma_data" ]]  && rm -rf "$SERVER_DIR/chroma_data" && echo -e "  Deleted chroma_data/"
    echo -e "  ${GREEN}Fresh start: data cleared${NC}"
  fi
fi

# ── 0. Database migrations ──────────────────────────────────────────────────
echo -e "${CYAN}[0/5] Applying database migrations...${NC}"
"$ALEMBIC" upgrade head &>"$LOG_DIR/alembic.log"
echo -e "  ${GREEN}Database schema is up to date${NC}"

# ── 1. ChromaDB ─────────────────────────────────────────────────────────────
echo -e "${CYAN}[1/5] Starting ChromaDB server...${NC}"
free_port 8001
"$CHROMA" run --path "$SERVER_DIR/chroma_data" --host 127.0.0.1 --port 8001 \
  &>"$LOG_DIR/chroma.log" &
CHROMA_PID=$!
sleep 2
if ! kill -0 "$CHROMA_PID" 2>/dev/null; then
  echo -e "${RED}ChromaDB failed to start. Check $LOG_DIR/chroma.log${NC}"; exit 1
fi
echo -e "  ${GREEN}ChromaDB running (PID $CHROMA_PID)${NC}"

# ── 2. Redis ────────────────────────────────────────────────────────────────
if [[ "$IS_WINDOWS" == "true" ]]; then
  echo -e "${CYAN}[2/5] Starting Redis (WSL: $WSL_DISTRO)...${NC}"
  # Ensure Redis is up. It is usually a systemd service inside WSL; fall back to a manual
  # daemon if systemd isn't managing it.
  if ! wsl -d "$WSL_DISTRO" -u root -- redis-cli ping 2>/dev/null | grep -q PONG; then
    wsl -d "$WSL_DISTRO" -u root -- systemctl start redis-server 2>/dev/null \
      || wsl -d "$WSL_DISTRO" -u root -- redis-server --daemonize yes --bind 127.0.0.1 &>/dev/null
    sleep 2
    if ! wsl -d "$WSL_DISTRO" -u root -- redis-cli ping 2>/dev/null | grep -q PONG; then
      echo -e "${RED}Redis failed to start in WSL ($WSL_DISTRO). Install redis in that distro.${NC}"; exit 1
    fi
  fi
  # CRITICAL: hold the WSL2 VM open for the script's lifetime. Without an active session the
  # VM idle-shuts-down ~8s after the last `wsl` command returns, taking Redis with it and
  # breaking the long-lived Celery/uvicorn connections. This keepalive session prevents that;
  # cleanup kills REDIS_PID on exit, after which the VM is free to idle-stop normally.
  wsl -d "$WSL_DISTRO" -u root -- sleep infinity &
  REDIS_PID=$!
  REDIS_STARTED_HERE=true
  echo -e "  ${GREEN}Redis running (WSL); VM keepalive PID $REDIS_PID${NC}"
else
  echo -e "${CYAN}[2/5] Starting Redis...${NC}"
  if ! command -v redis-server &>/dev/null; then
    echo -e "${RED}redis-server not found. Install it (macOS: brew install redis, Linux: apt install redis-server).${NC}"; exit 1
  fi
  if redis-cli ping &>/dev/null; then
    echo -e "  ${GREEN}Redis already running — skipping${NC}"
  else
    redis-server --daemonize no &>"$LOG_DIR/redis.log" &
    REDIS_PID=$!
    sleep 1
    if ! kill -0 "$REDIS_PID" 2>/dev/null; then
      echo -e "${RED}Redis failed to start. Check $LOG_DIR/redis.log${NC}"; exit 1
    fi
    echo -e "  ${GREEN}Redis running (PID $REDIS_PID)${NC}"
  fi
fi

# ── 3. Celery worker ────────────────────────────────────────────────────────
echo -e "${CYAN}[3/5] Starting Celery worker...${NC}"
"$CELERY" -A app.celery_app:celery_app worker \
  --queues=background --pool=solo --loglevel=info \
  &>"$LOG_DIR/celery.log" &
CELERY_PID=$!
sleep 2
if ! kill -0 "$CELERY_PID" 2>/dev/null; then
  echo -e "${RED}Celery worker failed to start. Check $LOG_DIR/celery.log${NC}"; exit 1
fi
echo -e "  ${GREEN}Celery worker running (PID $CELERY_PID)${NC}"

# ── 4. Celery beat ──────────────────────────────────────────────────────────
echo -e "${CYAN}[4/5] Starting Celery beat (periodic tasks)...${NC}"
"$CELERY" -A app.celery_app:celery_app beat \
  --loglevel=info \
  &>"$LOG_DIR/celery_beat.log" &
CELERY_BEAT_PID=$!
sleep 2
if ! kill -0 "$CELERY_BEAT_PID" 2>/dev/null; then
  echo -e "${RED}Celery beat failed to start. Check $LOG_DIR/celery_beat.log${NC}"; exit 1
fi
echo -e "  ${GREEN}Celery beat running (PID $CELERY_BEAT_PID) — eviction runs every 30 min${NC}"

# ── 5. FastAPI ──────────────────────────────────────────────────────────────
# Bind to 0.0.0.0 so the data plane (/v1/*) is reachable over the LAN.
# The AdminLoopbackMiddleware blocks non-loopback peers on /admin/v1/* in-app.
echo -e "${CYAN}[5/5] Starting FastAPI...${NC}"
free_port 8000
"$UVICORN" app.main:app --host "${DEJAQ_BIND_HOST:-0.0.0.0}" --reload &>"$LOG_DIR/uvicorn.log" &
UVICORN_PID=$!
sleep 2
if ! kill -0 "$UVICORN_PID" 2>/dev/null; then
  echo -e "${RED}FastAPI failed to start. Check $LOG_DIR/uvicorn.log${NC}"; exit 1
fi
echo -e "  ${GREEN}FastAPI running (PID $UVICORN_PID)${NC}"

if [[ "$STACK" == "all" ]]; then
  start_dashboard
  start_chat
fi

TAIL_LOGS=("$LOG_DIR/redis.log" "$LOG_DIR/celery.log" "$LOG_DIR/celery_beat.log" "$LOG_DIR/uvicorn.log")

echo ""
if [[ "$STACK" == "all" ]]; then
  echo -e "${GREEN}✓ Full local stack running${NC}"
  echo -e "  Data plane (/v1):       http://0.0.0.0:8000   — LAN-accessible, key-protected"
  echo -e "  Admin API (/admin/v1):  127.0.0.1 only        — loopback-restricted"
  echo -e "  Dashboard:              http://127.0.0.1:3000/dashboard  — loopback-only"
  echo -e "  ChromaDB:               http://127.0.0.1:8001"
  echo -e "  Chat:                   http://localhost:4000"
  echo -e "  Mode:                   $MODE"
  echo -e "  Logs:                   $LOG_DIR/"
  echo -e ""
  echo -e "  Remote admin? Run on your machine: ssh -L 3000:localhost:3000 -L 8000:localhost:8000 user@server"
  TAIL_LOGS+=("$LOG_DIR/dashboard.log" "$LOG_DIR/chat.log")
else
  echo -e "${GREEN}✓ Server services running${NC}"
  echo -e "  Data plane (/v1):       http://0.0.0.0:8000   — LAN-accessible, key-protected"
  echo -e "  Admin API (/admin/v1):  127.0.0.1 only        — loopback-restricted"
  echo -e "  ChromaDB:               http://127.0.0.1:8001"
  echo -e "  Mode:                   $MODE"
  echo -e "  Stats:                  cd server && uv run dejaq-admin stats"
  echo -e "  Logs:                   $LOG_DIR/"
fi
echo -e "\n${YELLOW}Press Ctrl+C to stop all services.${NC}\n"

if [[ "$LOG_MODE" == "requests" ]]; then
  (
    tail -n 0 -f "$LOG_DIR/uvicorn.log" \
      | grep --line-buffered -E "router\.openai_compat.*(start org=|done cache=|validator rejected)" \
      | format_terminal_logs
  ) &
else
  (
    tail -f "${TAIL_LOGS[@]}" \
      | format_terminal_logs
  ) &
fi
TAIL_PID=$!
wait $TAIL_PID
