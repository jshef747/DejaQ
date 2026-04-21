#!/usr/bin/env bash
# DejaQ — end-to-end demo script
# Usage: ./scripts/demo.sh [--keep] [--help]
#   --keep   leave the demo org/departments in place after exit (for dev seeding)
#   --help   show this message
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_DIR="$(dirname "$SCRIPT_DIR")/server"
PYTHON="$SERVER_DIR/.venv/bin/python"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'
BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'

KEEP=false
DEMO_ORG_SLUG="dejaq-demo"
STEP_NUM=0
TOTAL_STEPS=6

usage() {
  echo ""
  echo -e "${BOLD}DejaQ End-to-End Demo${NC}"
  echo ""
  echo "  Walks through the complete DejaQ platform in ~60 seconds:"
  echo "  org → departments → API key → cache miss → cache hit → stats"
  echo ""
  echo -e "${BOLD}Usage:${NC}  ./scripts/demo.sh [--keep] [--help]"
  echo ""
  echo "  --keep    Retain demo org/departments after exit (dev seeding)"
  echo "  --help    Show this message"
  echo ""
  echo -e "${BOLD}Prerequisites:${NC}  cd server && ./start.sh"
  echo ""
}

for arg in "$@"; do
  case "$arg" in
    --keep) KEEP=true ;;
    --help|-h) usage; exit 0 ;;
    *) echo -e "${RED}Unknown argument: $arg${NC}"; usage; exit 1 ;;
  esac
done

step() {
  STEP_NUM=$((STEP_NUM + 1))
  echo ""
  echo -e "${CYAN}${BOLD}┌─ Step ${STEP_NUM}/${TOTAL_STEPS}: $1${NC}"
}
ok()   { echo -e "${GREEN}${BOLD}✓${NC} $1"; }
info() { echo -e "${DIM}  $1${NC}"; }
warn() { echo -e "${YELLOW}⚠  $1${NC}"; }
die()  { echo -e "${RED}${BOLD}✗ $1${NC}" >&2; exit 1; }

# Run a Python snippet in the server directory with access to app modules.
# Always runs directly (not in a pipe capture) so stdin/stdout/stderr are inherited.
py() { (cd "$SERVER_DIR" && "$PYTHON" -c "$@"); }

# Run a Python snippet and capture its stdout as a variable.
pyget() { (cd "$SERVER_DIR" && "$PYTHON" -c "$@"); }

cleanup() {
  if [[ -n "$DEMO_ORG_SLUG" ]] && [[ "$KEEP" == "false" ]]; then
    echo ""
    echo -e "${DIM}Cleaning up demo org '${DEMO_ORG_SLUG}'...${NC}"
    pyget "
from app.db import org_repo
from app.db.session import get_session
with get_session() as s:
    try:
        org_repo.delete_org(s, '${DEMO_ORG_SLUG}')
        print('removed')
    except Exception:
        pass
" > /dev/null 2>&1 || true
    echo -e "${DIM}Demo org removed.${NC}"
  elif [[ -n "$DEMO_ORG_SLUG" ]] && [[ "$KEEP" == "true" ]]; then
    echo ""
    echo -e "${YELLOW}--keep set: demo org '${DEMO_ORG_SLUG}' left in place.${NC}"
    info "Remove manually: cd server && python -m cli.admin org delete --slug ${DEMO_ORG_SLUG}"
  fi
}
trap cleanup EXIT INT TERM

# ── Banner ───────────────────────────────────────────────────────────────────
clear 2>/dev/null || true
echo ""
echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${CYAN}║        DejaQ  End-to-End Demo            ║${NC}"
echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════╝${NC}"
echo ""
echo -e "  Walks through the complete platform in ~60 seconds:"
echo -e "  ${DIM}org → departments → API key → cache miss → cache hit → stats${NC}"
if [[ "$KEEP" == "true" ]]; then
  echo -e "  ${YELLOW}Mode: --keep (demo data retained after exit)${NC}"
else
  echo -e "  ${DIM}Demo data cleaned up on exit. Use --keep to retain it.${NC}"
fi
echo ""

# ── Preflight ────────────────────────────────────────────────────────────────
echo -e "${DIM}Checking server...${NC}"
if ! curl -sf http://127.0.0.1:8000/health > /dev/null 2>&1; then
  die "Server not reachable at http://127.0.0.1:8000 — start it first:\n  cd server && ./start.sh"
fi
ok "Server is up at http://127.0.0.1:8000"

# ── Step 1: Create org ───────────────────────────────────────────────────────
step "Create Demo Organization"
info "Creating org 'DejaQ Demo' (slug: ${DEMO_ORG_SLUG})..."

ORG_STATUS=$(pyget "
from app.db import org_repo
from app.db.session import get_session
with get_session() as s:
    o = org_repo.get_org_by_slug(s, '${DEMO_ORG_SLUG}')
    if o:
        print('exists:' + str(o.id))
    else:
        result = org_repo.create_org(s, 'DejaQ Demo')
        print('created:' + str(result.id))
")

case "$ORG_STATUS" in
  exists:*)  warn "Org '${DEMO_ORG_SLUG}' already exists — reusing it." ;;
  created:*) ok  "Organization created: name='DejaQ Demo'  slug='${DEMO_ORG_SLUG}'" ;;
  *)         die "Failed to create org: $ORG_STATUS" ;;
esac

# ── Step 2: Create departments ───────────────────────────────────────────────
step "Create Departments"
info "Creating 'Engineering' and 'Product' under the demo org."
info "Each department gets its own isolated cache namespace."
echo ""

DEPT_RESULT=$(pyget "
from app.db import dept_repo
from app.db.session import get_session
results = []
with get_session() as s:
    for name in ['Engineering', 'Product']:
        try:
            d = dept_repo.create_dept(s, '${DEMO_ORG_SLUG}', name)
            results.append('created:' + d.slug + ':' + d.cache_namespace)
        except ValueError as e:
            results.append('exists:' + name.lower())
print('\n'.join(results))
")

while IFS= read -r line; do
  case "$line" in
    created:*)
      slug=$(echo "$line" | cut -d: -f2)
      ns=$(echo "$line" | cut -d: -f3)
      ok "Department created: slug='${slug}'  cache_namespace='${ns}'"
      ;;
    exists:*)
      name=$(echo "$line" | cut -d: -f2)
      warn "Department '${name}' already exists — skipping."
      ;;
  esac
done <<< "$DEPT_RESULT"

# ── Step 3: Generate API key ─────────────────────────────────────────────────
step "Generate API Key"
info "Generating a new API key for '${DEMO_ORG_SLUG}' (revokes any existing key)."
echo ""

API_TOKEN=$(pyget "
import secrets
from datetime import datetime, timezone
from app.db import org_repo, api_key_repo
from app.db.session import get_session
with get_session() as s:
    org = org_repo.get_org_by_slug(s, '${DEMO_ORG_SLUG}')
    if org is None:
        raise SystemExit('Org ${DEMO_ORG_SLUG} not found')
    existing = api_key_repo.get_active_key_for_org(s, org.id)
    if existing:
        api_key_repo.revoke_key(s, existing.id)
    key = api_key_repo.create_key(s, org.id)
    print(key.token)
")

if [[ -z "$API_TOKEN" ]]; then
  die "Failed to generate API key."
fi

ok "API key generated: ${BOLD}${API_TOKEN:0:16}...${NC}${DIM} (truncated)${NC}"
info "Use this as: Authorization: Bearer <token>"

# ── Step 4: Cache miss ───────────────────────────────────────────────────────
step "First Request — Cache MISS"
info "Query: \"What is the boiling point of water?\""
info "Not cached yet — will route to the local LLM."
echo ""

REQUEST_BODY='{"model":"dejaq","messages":[{"role":"user","content":"What is the boiling point of water?"}]}'

MISS_RESPONSE=$(curl -si \
  -H "Authorization: Bearer ${API_TOKEN}" \
  -H "Content-Type: application/json" \
  -H "X-DejaQ-Department: engineering" \
  -d "$REQUEST_BODY" \
  http://127.0.0.1:8000/v1/chat/completions)

RESPONSE_ID_MISS=$(echo "$MISS_RESPONSE" | grep -i "^x-dejaq-response-id:" | awk '{print $2}' | tr -d '\r\n')
MISS_BODY=$(echo "$MISS_RESPONSE" | awk '/^\r$/{found=1; next} found{print}')
MISS_CONTENT=$(echo "$MISS_BODY" | "$PYTHON" -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d['choices'][0]['message']['content'][:120])
except Exception as e:
    print('(parse error: ' + str(e) + ')')
" 2>/dev/null)

echo -e "  ${DIM}Answer:${NC} ${MISS_CONTENT}"
echo ""

if [[ -z "$RESPONSE_ID_MISS" ]]; then
  echo -e "${YELLOW}${BOLD}↓ Cache MISS${NC} — LLM answered; response queued for background storage"
  info "Celery worker will generalize + store this response now..."
else
  warn "Already cached (prior warm run). Response ID: ${RESPONSE_ID_MISS}"
fi

# ── Step 5: Wait + cache hit ─────────────────────────────────────────────────
step "Second Request — Cache HIT"
echo -ne "  ${DIM}Waiting for background generalization"
for _ in 1 2 3 4 5; do sleep 1; echo -ne "."; done
echo -e "${NC}"
info "Sending identical query..."
echo ""

HIT_RESPONSE=$(curl -si \
  -H "Authorization: Bearer ${API_TOKEN}" \
  -H "Content-Type: application/json" \
  -H "X-DejaQ-Department: engineering" \
  -d "$REQUEST_BODY" \
  http://127.0.0.1:8000/v1/chat/completions)

RESPONSE_ID_HIT=$(echo "$HIT_RESPONSE" | grep -i "^x-dejaq-response-id:" | awk '{print $2}' | tr -d '\r\n')
HIT_BODY=$(echo "$HIT_RESPONSE" | awk '/^\r$/{found=1; next} found{print}')
HIT_CONTENT=$(echo "$HIT_BODY" | "$PYTHON" -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d['choices'][0]['message']['content'][:120])
except Exception as e:
    print('(parse error: ' + str(e) + ')')
" 2>/dev/null)

echo -e "  ${DIM}Answer:${NC} ${HIT_CONTENT}"
echo ""

if [[ -n "$RESPONSE_ID_HIT" ]]; then
  echo -e "${GREEN}${BOLD}↑ Cache HIT${NC} — served from semantic cache, zero LLM cost"
  info "Response ID: ${RESPONSE_ID_HIT}"
else
  warn "Still a miss — server may need more warm-up time."
  info "Re-run the demo after the server has been running for ~30 seconds."
fi

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${CYAN}┌──────────────── What Just Happened ─────────────────┐${NC}"
echo -e "${BOLD}${CYAN}│${NC}                                                      ${BOLD}${CYAN}│${NC}"
echo -e "${BOLD}${CYAN}│${NC}  1. Org + 2 departments created (isolated caches)    ${BOLD}${CYAN}│${NC}"
echo -e "${BOLD}${CYAN}│${NC}  2. API key generated (Bearer token auth)            ${BOLD}${CYAN}│${NC}"
echo -e "${BOLD}${CYAN}│${NC}  3. Request #1 → LLM → generalize → stored in cache  ${BOLD}${CYAN}│${NC}"
echo -e "${BOLD}${CYAN}│${NC}  4. Request #2 → cache hit, no LLM call              ${BOLD}${CYAN}│${NC}"
echo -e "${BOLD}${CYAN}│${NC}                                                      ${BOLD}${CYAN}│${NC}"
echo -e "${BOLD}${CYAN}└──────────────────────────────────────────────────────┘${NC}"

# ── Step 6: Stats TUI ────────────────────────────────────────────────────────
step "Stats Dashboard"
info "Hit rate, latency, and model breakdown across all requests."
echo ""
echo -e "${YELLOW}  Press ${BOLD}q${NC}${YELLOW} to exit the stats view and finish the demo.${NC}"
echo ""
read -rp "  Press Enter to open stats... " _
echo ""

(cd "$SERVER_DIR" && "$PYTHON" -m cli.stats) || true

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}╔══════════════════════════════════════╗${NC}"
echo -e "${GREEN}${BOLD}║      DejaQ demo complete!            ║${NC}"
echo -e "${GREEN}${BOLD}╚══════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${GREEN}✓${NC} Org + department management"
echo -e "  ${GREEN}✓${NC} API key auth + department-scoped cache isolation"
echo -e "  ${GREEN}✓${NC} Cache miss → LLM → generalize → store"
echo -e "  ${GREEN}✓${NC} Cache hit on identical query"
echo -e "  ${GREEN}✓${NC} Stats TUI with hit rate + latency breakdown"
echo ""
[[ "$KEEP" == "false" ]] && info "Cleaning up demo data..."
