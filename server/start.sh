#!/usr/bin/env bash
# DejaQ — start all services (Mac)
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$PROJECT_DIR/.logs"
VENV="$PROJECT_DIR/.venv"
mkdir -p "$LOG_DIR"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

# Verify the project venv exists
if [[ ! -f "$VENV/bin/python" ]]; then
  echo -e "${RED}No .venv found at $VENV. Run: uv sync${NC}"; exit 1
fi

# Use project venv executables directly — avoids any venv activated in the parent shell
PYTHON="$VENV/bin/python"
UVICORN="$VENV/bin/uvicorn"
CELERY="$VENV/bin/celery"
CHROMA="$VENV/bin/chroma"

REDIS_PID=""; CELERY_PID=""; CELERY_BEAT_PID=""; UVICORN_PID=""; CHROMA_PID=""; TAIL_PID=""

cleanup() {
  trap - EXIT INT TERM
  echo -e "\n${YELLOW}Shutting down services...${NC}"
  stop_service() {
    local pid=$1 name=$2
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      pkill -TERM -P "$pid" 2>/dev/null || true  # kill children first
      kill -TERM "$pid" 2>/dev/null || true
      echo "  $name stopped"
    fi
  }
  [[ -n "$TAIL_PID" ]] && kill "$TAIL_PID" 2>/dev/null || true
  stop_service "$UVICORN_PID"     "FastAPI"
  stop_service "$CELERY_BEAT_PID" "Celery beat"
  stop_service "$CELERY_PID"      "Celery worker"
  stop_service "$CHROMA_PID"      "ChromaDB"
  stop_service "$REDIS_PID"       "Redis"
  echo -e "${GREEN}All services stopped.${NC}"
}
trap cleanup EXIT INT TERM

# Kill any process holding a port before we try to bind it
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

cd "$PROJECT_DIR"

# ── 1. ChromaDB ─────────────────────────────────────────────────────────────
echo -e "${CYAN}[1/4] Starting ChromaDB server...${NC}"
free_port 8001
"$CHROMA" run --path "$PROJECT_DIR/chroma_data" --host 127.0.0.1 --port 8001 \
  &>"$LOG_DIR/chroma.log" &
CHROMA_PID=$!
sleep 2
if ! kill -0 "$CHROMA_PID" 2>/dev/null; then
  echo -e "${RED}ChromaDB failed to start. Check $LOG_DIR/chroma.log${NC}"; exit 1
fi
echo -e "  ${GREEN}ChromaDB running (PID $CHROMA_PID)${NC}"

# ── 2. Redis ────────────────────────────────────────────────────────────────
echo -e "${CYAN}[2/4] Starting Redis...${NC}"
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

# ── Ready ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}✓ All services running${NC}"
echo -e "  API:         http://127.0.0.1:8000"
echo -e "  ChromaDB:    http://127.0.0.1:8001"
echo -e "  Demo UI:     open openai-compat-demo.html in browser"
echo -e "  Stats TUI:   uv run python -m cli.stats"
echo -e "  Logs:        $LOG_DIR/"
echo -e "\n${YELLOW}Press Ctrl+C to stop all services.${NC}\n"

# Tail all logs — kill tail pid in cleanup so it doesn't linger
tail -f "$LOG_DIR/redis.log" "$LOG_DIR/celery.log" "$LOG_DIR/celery_beat.log" "$LOG_DIR/uvicorn.log" &
TAIL_PID=$!
wait $TAIL_PID
