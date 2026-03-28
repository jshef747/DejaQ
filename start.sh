#!/usr/bin/env bash
# DejaQ — start all services (Mac)
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$PROJECT_DIR/.logs"
mkdir -p "$LOG_DIR"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

REDIS_PID=""; CELERY_PID=""; UVICORN_PID=""; CHROMA_PID=""

cleanup() {
  echo -e "\n${YELLOW}Shutting down services...${NC}"
  [[ -n "$UVICORN_PID" ]] && kill "$UVICORN_PID" 2>/dev/null && echo "  FastAPI stopped"
  [[ -n "$CELERY_PID"  ]] && kill "$CELERY_PID"  2>/dev/null && echo "  Celery stopped"
  [[ -n "$CHROMA_PID"  ]] && kill "$CHROMA_PID"  2>/dev/null && echo "  ChromaDB stopped"
  [[ -n "$REDIS_PID"   ]] && kill "$REDIS_PID"   2>/dev/null && echo "  Redis stopped"
  echo -e "${GREEN}All services stopped.${NC}"
}
trap cleanup EXIT INT TERM

cd "$PROJECT_DIR"

# ── 1. ChromaDB ─────────────────────────────────────────────────────────────
echo -e "${CYAN}[1/4] Starting ChromaDB server...${NC}"
uv run chroma run --path "$PROJECT_DIR/chroma_data" --host 127.0.0.1 --port 8001 \
  &>"$LOG_DIR/chroma.log" &
CHROMA_PID=$!
sleep 2
if ! kill -0 "$CHROMA_PID" 2>/dev/null; then
  echo -e "${RED}ChromaDB failed to start. Check $LOG_DIR/chroma.log${NC}"; exit 1
fi
echo -e "  ${GREEN}ChromaDB running (PID $CHROMA_PID)${NC}"

# ── 2. Redis ────────────────────────────────────────────────────────────────
echo -e "${CYAN}[1/3] Starting Redis...${NC}"
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

# ── 3. Celery ───────────────────────────────────────────────────────────────
echo -e "${CYAN}[3/4] Starting Celery worker...${NC}"
uv run celery -A app.celery_app:celery_app worker \
  --queues=background --pool=solo --loglevel=info \
  &>"$LOG_DIR/celery.log" &
CELERY_PID=$!
sleep 2
if ! kill -0 "$CELERY_PID" 2>/dev/null; then
  echo -e "${RED}Celery failed to start. Check $LOG_DIR/celery.log${NC}"; exit 1
fi
echo -e "  ${GREEN}Celery running (PID $CELERY_PID)${NC}"

# ── 4. FastAPI ──────────────────────────────────────────────────────────────
echo -e "${CYAN}[4/4] Starting FastAPI...${NC}"
uv run uvicorn app.main:app --reload &>"$LOG_DIR/uvicorn.log" &
UVICORN_PID=$!
sleep 2
if ! kill -0 "$UVICORN_PID" 2>/dev/null; then
  echo -e "${RED}FastAPI failed to start. Check $LOG_DIR/uvicorn.log${NC}"; exit 1
fi
echo -e "  ${GREEN}FastAPI running (PID $UVICORN_PID)${NC}"

# ── Ready ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}✓ All services running${NC}"
echo -e "  API:       http://127.0.0.1:8000"
echo -e "  ChromaDB:  http://127.0.0.1:8001"
echo -e "  Chat UI:   open index.html in browser"
echo -e "  Logs:      $LOG_DIR/"
echo -e "\n${YELLOW}Press Ctrl+C to stop all services.${NC}\n"

# Tail all logs to stdout so you can see live output
tail -f "$LOG_DIR/redis.log" "$LOG_DIR/celery.log" "$LOG_DIR/uvicorn.log"