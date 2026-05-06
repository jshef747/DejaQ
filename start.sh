#!/usr/bin/env bash
# DejaQ — start local services from the repository root
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
OLLAMA_URL_ARG=""
OLLAMA_URL_FLAG_SET=false
DRY_RUN=false
ENV_STACK="${DEJAQ_STACK:-}"
ENV_MODE="${DEJAQ_MODE:-}"
ENV_OLLAMA_URL="${DEJAQ_OLLAMA_URL:-}"
ENV_START_LOGS="${DEJAQ_START_LOGS:-}"

usage() {
  echo "Usage: $0 [--stack=server|all] [--mode=in-process|self-hosted|cloud] [--logs=requests|all] [--ollama-url URL] [--dry-run]"
  echo ""
  echo "Stacks:"
  echo "  server   Start backend services only: ChromaDB, Redis, Celery, FastAPI"
  echo "  all      Start server plus dashboard frontend and chat app"
  echo ""
  echo "Logs:"
  echo "  requests Tail compact request/response logs only"
  echo "  all      Tail all service logs"
  echo ""
  echo "Environment:"
  echo "  DEJAQ_STACK        Non-interactive stack selection: server or all"
  echo "  DEJAQ_MODE         Non-interactive deployment mode selection"
  echo "  DEJAQ_START_LOGS   Non-interactive log mode selection: requests or all"
  echo "  DEJAQ_OLLAMA_URL   Required for self-hosted and cloud modes"
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

# Verify the project venv exists
if [[ ! -f "$VENV/bin/python" ]]; then
  echo -e "${RED}No .venv found at $VENV. Run: cd server && uv sync${NC}"; exit 1
fi

# Use project venv executables directly — avoids any venv activated in the parent shell
PYTHON="$VENV/bin/python"
UVICORN="$VENV/bin/uvicorn"
CELERY="$VENV/bin/celery"
CHROMA="$VENV/bin/chroma"
ALEMBIC="$VENV/bin/alembic"

REDIS_PID=""; CELERY_PID=""; CELERY_BEAT_PID=""; UVICORN_PID=""; CHROMA_PID=""
DASHBOARD_PID=""; CHAT_PID=""; TAIL_PID=""

cleanup() {
  trap - EXIT INT TERM
  if [[ "$DRY_RUN" == "true" ]]; then
    return
  fi
  echo -e "\n${YELLOW}Shutting down services...${NC}"
  stop_service() {
    local pid=$1 name=$2
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      pkill -TERM -P "$pid" 2>/dev/null || true
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
  stop_service "$REDIS_PID"       "Redis"
  echo -e "${GREEN}All services stopped.${NC}"
}
trap cleanup EXIT INT TERM

free_port() {
  local port=$1
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
    in-process|in_process|inprocess|dev|development)
      echo "in-process"
      ;;
    self-hosted|self_hosted|selfhosted|on-prem|onprem|prod|production)
      echo "self-hosted"
      ;;
    cloud)
      echo "cloud"
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

select_mode() {
  local selected="${MODE_ARG:-${DEJAQ_MODE:-}}"
  if [[ -n "$selected" ]]; then
    selected="$(normalize_mode "$selected")"
    if [[ -z "$selected" ]]; then
      echo -e "${RED}Invalid DEJAQ mode. Choose in-process, self-hosted, or cloud.${NC}" >&2
      exit 1
    fi
    echo "$selected"
    return
  fi

  echo -e "${CYAN}Select deployment mode:${NC}" >&2
  echo "  1) in-process  (development)" >&2
  echo "  2) self-hosted (on-prem production via Ollama)" >&2
  echo "  3) cloud       (remote Ollama endpoint)" >&2
  read -r -p "Mode [1-3]: " selected
  case "$selected" in
    1|in-process|in_process) echo "in-process" ;;
    2|self-hosted|self_hosted) echo "self-hosted" ;;
    3|cloud) echo "cloud" ;;
    *) echo -e "${RED}Invalid mode selection.${NC}" >&2; exit 1 ;;
  esac
}

apply_mode() {
  local mode="$1"
  export DEJAQ_MODE="$mode"

  if [[ "$mode" == "in-process" ]]; then
    export DEJAQ_ENRICHER_BACKEND=in_process
    export DEJAQ_NORMALIZER_BACKEND=in_process
    export DEJAQ_LOCAL_LLM_BACKEND=in_process
    export DEJAQ_GENERALIZER_BACKEND=in_process
    export DEJAQ_CONTEXT_ADJUSTER_BACKEND=in_process
    return
  fi

  export DEJAQ_ENRICHER_BACKEND=ollama
  export DEJAQ_NORMALIZER_BACKEND=ollama
  export DEJAQ_LOCAL_LLM_BACKEND=ollama
  export DEJAQ_GENERALIZER_BACKEND=ollama
  export DEJAQ_CONTEXT_ADJUSTER_BACKEND=ollama

  if [[ "$OLLAMA_URL_FLAG_SET" == "true" ]]; then
    export DEJAQ_OLLAMA_URL="$OLLAMA_URL_ARG"
  fi

  if [[ -z "${DEJAQ_OLLAMA_URL:-}" ]]; then
    read -r -p "DEJAQ_OLLAMA_URL: " DEJAQ_OLLAMA_URL
    export DEJAQ_OLLAMA_URL
  fi

  if [[ -z "${DEJAQ_OLLAMA_URL:-}" ]]; then
    echo -e "${RED}DEJAQ_OLLAMA_URL is required for $mode mode.${NC}" >&2
    exit 1
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
  (cd "$FRONTEND_DIR" && npm run dev) &>"$LOG_DIR/dashboard.log" &
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
LOG_MODE="$(select_log_mode)"
apply_mode "$MODE"

echo -e "${CYAN}Startup stack: ${STACK}${NC}"
echo -e "${CYAN}Deployment mode: ${MODE}${NC}"
echo -e "${CYAN}Log mode: ${LOG_MODE}${NC}"
echo -e "${CYAN}Logs: ${LOG_DIR}/${NC}"
echo -e "  DEJAQ_ENRICHER_BACKEND=${DEJAQ_ENRICHER_BACKEND}"
echo -e "  DEJAQ_NORMALIZER_BACKEND=${DEJAQ_NORMALIZER_BACKEND}"
echo -e "  DEJAQ_LOCAL_LLM_BACKEND=${DEJAQ_LOCAL_LLM_BACKEND}"
echo -e "  DEJAQ_GENERALIZER_BACKEND=${DEJAQ_GENERALIZER_BACKEND}"
echo -e "  DEJAQ_CONTEXT_ADJUSTER_BACKEND=${DEJAQ_CONTEXT_ADJUSTER_BACKEND}"
if [[ "$MODE" != "in-process" ]]; then
  echo -e "  DEJAQ_OLLAMA_URL=${DEJAQ_OLLAMA_URL}"
fi

if [[ "$DRY_RUN" == "true" ]]; then
  echo -e "${GREEN}Dry run complete. Services not started.${NC}"
  exit 0
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
echo -e "${CYAN}[2/5] Starting Redis...${NC}"
if ! command -v redis-server &>/dev/null; then
  echo -e "${RED}redis-server not found. Install with: brew install redis${NC}"; exit 1
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
echo -e "${CYAN}[5/5] Starting FastAPI...${NC}"
free_port 8000
"$UVICORN" app.main:app --reload &>"$LOG_DIR/uvicorn.log" &
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
  echo -e "  API:         http://127.0.0.1:8000"
  echo -e "  ChromaDB:    http://127.0.0.1:8001"
  echo -e "  Dashboard:   http://localhost:3000/dashboard"
  echo -e "  Chat:        http://localhost:4000"
  echo -e "  Mode:        $MODE"
  echo -e "  Logs:        $LOG_DIR/"
  TAIL_LOGS+=("$LOG_DIR/dashboard.log" "$LOG_DIR/chat.log")
else
  echo -e "${GREEN}✓ Server services running${NC}"
  echo -e "  API:         http://127.0.0.1:8000"
  echo -e "  ChromaDB:    http://127.0.0.1:8001"
  echo -e "  Mode:        $MODE"
  echo -e "  Stats TUI:   cd server && uv run python -m cli.stats"
  echo -e "  Logs:        $LOG_DIR/"
fi
echo -e "\n${YELLOW}Press Ctrl+C to stop all services.${NC}\n"

if [[ "$LOG_MODE" == "requests" ]]; then
  (
    tail -n 0 -f "$LOG_DIR/uvicorn.log" \
      | grep --line-buffered -E "router\.openai_compat.*(start org=|done cache=)" \
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
