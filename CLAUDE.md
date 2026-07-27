# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DejaQ is an LLM cost-optimization platform that reduces API costs through semantic caching, query classification, and hybrid model routing.

**Cache miss pipeline:** User Query → Context Enricher (Qwen 1.5B + regex gate, makes query standalone) → Normalizer (Qwen 2.5, produces cache key) → Cache Filter (heuristics) → LLM gets **original query + history** (preserves tone) → Response to user → Background: Generalize response (Phi-3.5 Mini) → Store in ChromaDB (if filter passes)

**Cache hit pipeline:** User Query → Context Enricher → Normalizer → ChromaDB lookup → **trusted hit** (cosine ≤ `DEJAQ_CACHE_TRUST_DISTANCE`, 0.15) served directly, or **band hit** (0.15–`DEJAQ_CACHE_BAND_MAX_DISTANCE`, 0.20), or **lexical rescue** (≤ `DEJAQ_CACHE_RESCUE_MAX_DISTANCE`, 0.60, when word-level alignment confirms a typo'd variant) — band/rescue hits served only if the **Cache Validator** (Gemma E2B checks cached answer covers the new query, aided by a word-mismatch hint) accepts → INVALID → treat as miss → Context Adjuster adds tone → Response to user. Validated band/rescue hits store the typo'd phrasing as an **alias** entry (`alias_of` metadata) so the same typo becomes an instant trusted hit next time; deleting an entry cascades to its aliases.

> **Image gate (`/v1/responses` only):** when a request carries an image, the text pipeline runs as usual, but a cache hit is served only if the **image gate** also passes. The gate has two paths, chosen by what the image actually contains:
>
> - **Document** (OCR returns confident text — `mean confidence ≥ 80` AND `≥ 6 words at conf ≥ 60`): compared **by its words**. The word floor is low on purpose: confidence is what separates a document from a photo, and a short crop read well (measured: 9 words at 86.8) is a small document, not something to refuse. Served only when `token overlap ≥ DEJAQ_CACHE_IMAGE_TEXT_MIN_JACCARD (0.80)` against the entry's stored `image_text` — one threshold, no identifier rule. 0.80 is the measured zero-false-merge point: over 69,411 different-document pairs the highest overlap reached was 0.798 (two exams for one course differing by a date, a time and one letter). Recall is ~45–54% and that is the accepted trade. `services/image_text.py`, engine = the `tesseract` binary.
> - **Ambiguous** (≥ `DEJAQ_CACHE_IMAGE_AMBIGUOUS_MIN_WORDS` (4) tokens found but read *below* the confidence floor): **never served and never stored.** These used to fall through to the pixel path, which was the largest single source of wrong answers (1,712 + 204 false merges measured) because two different pages of text look near-identical to CLIP. It matters because only ~11% of real scanned business forms clear the confidence floor. The test is OCR quality, not amount of text — an unreliable read of a lot of text is garbage, a confident read of a little text is a document.
> - **Photo** (little or no readable text): compared **by its pixels** — `CLIP distance ≤ DEJAQ_CACHE_IMAGE_MAX_DISTANCE (0.10)` **AND** `dHash hamming ≤ DEJAQ_CACHE_IMAGE_MAX_HAMMING (15)` against `image_dhash`/`image_clip`. No unguarded trusted tier; both thresholds load-bearing. A near-uniform image (under `DEJAQ_CACHE_IMAGE_MIN_TILE_VARIETY` (10) distinct dHashes over a 4×4 grid) is refused outright — every blank page is the same white rectangle to CLIP. `services/image_fingerprint.py`.
>
> Once the gate passes, the hit is served differently from a text hit, because every downstream model is blind to the image: the **validator compares question-to-question** (the cached answer is never sent — it is asked only whether both questions ask for the same thing about the verified-identical image) and the **context adjuster is skipped** (image answers are stored verbatim, so no tone was stripped to restore). This is not the same as trusting the distance: numbered-item siblings (`solve part a`/`part b`, 0.0898) sit *closer* than legitimate paraphrases (0.1094), so the embedding cannot separate them and the validator stays load-bearing. Measured 9/9 paraphrases served, 0 reachable false serves, validator 6,468 ms → 577 ms.
>
> Kinds never mix: a photo cannot match a document entry, and a text request matches neither. Raw image bytes are never stored — only fingerprints. On a miss, image requests bypass the difficulty classifier and route straight to the workspace's external (vision-capable) provider. Without `tesseract` installed, documents degrade to the photo path (a warning is logged; `start.sh` warns at boot). Separate paths exist because pixel similarity is *inverted* for documents: two different courses on one template measured CLIP 0.027 / hamming 0 (would have been served as the same image) while two screenshots of the same syllabus measured hamming 10–19 (would have missed). Border trimming and a digit-token identifier rule were both implemented and **removed** — each helped only the small sample it was derived from. Every threshold here is swept over 286,000 labelled pairs; do not hand-tune them. Measurements: [docs/image-gate.md](docs/image-gate.md); harness: [evals/image_similarity/](evals/image_similarity/). After changing any of them, run `dejaq-admin cache purge-images --workspace <slug>` — entries stored under the old rules may carry fingerprints the new ones would never accept.

> **Typo handling:** there is deliberately **no spell correction** anywhere in the pipeline — a dictionary checker mangles jargon and proper nouns ("frnce"→"fence", "itly"→"idly") and poisons cache keys. Instead: *typos change letters, different questions change words*. `services/lexical_match.py::align()` does word-level fuzzy alignment (exact words cancel, leftovers must fuzzy-match, question words never satisfy each other) — 99.1% typo recall / 99.9% sibling rejection ([docs/lexical-match-report.md](docs/lexical-match-report.md)). BGE embeddings absorb single typos in the trusted zone; heavier typos land in the band or the align-gated rescue tier, always behind the validator. The validator prompt carries word-swap few-shots plus the gate's mismatch hint ("'list' vs 'string'"). Phonetic spellings ("duz"→"does") intentionally miss — LLM answers.

## Branching

`staging` is the integration branch: feature branches merge into `staging` first for review and end-to-end testing, and only `staging` merges into `master`. Do not merge feature branches directly into `master`.

**Feature branch workflow:**
1. Create feature branch from `staging` (e.g., `git checkout -b feat/my-feature staging`)
2. Work on the feature and push to the feature branch
3. When ready, request approval (code review, testing, etc.)
4. After approval, merge the feature branch into `staging` and delete the branch
5. Later, `staging` merges into `master` when ready for release

## Commands

### Setup
Run from `server/` — the Python project (pyproject.toml + uv.lock) lives there; there is no root project.
```bash
cd server

# Mac (Apple Silicon) - enables Metal GPU acceleration
CMAKE_ARGS="-DLLAMA_METAL=on" uv sync

# Windows (NVIDIA) - enables CUDA acceleration
$env:CMAKE_ARGS = "-DLLAMA_CUBLAS=on"; uv sync

# CPU only
uv sync
```

### Run
Generation runs through **Ollama** (local or remote). Start Ollama and pull the model tags first:
```bash
ollama serve
ollama pull qwen2.5:0.5b qwen2.5:1.5b gemma4:e2b gemma4:e4b phi3.5:latest
```

```bash
# Preferred: start from the repo root with stack + Ollama-mode selection
./start.sh

# Stacks: all = backend + dashboard + chat; server = backend + dashboard (no chat);
# client = chat app only (connects to a DejaQ server elsewhere on the network).

# Non-interactive examples:
./start.sh --stack=all --mode=local
./start.sh --stack=server --mode=local
./start.sh --stack=client                    # chat only; set the server in chat Settings
./start.sh --stack=all --mode=remote --ollama-url=http://<host>:11434
./start.sh --stack=all --mode=local --lan   # expose chat (4000) + API (8000) on the LAN
# --lan binds chat + API to 0.0.0.0 so other devices on the same network can reach them;
# dashboard (3000), ChromaDB (8001), and Redis stay localhost-only. In AUTH_MODE=local
# the admin API is unauthenticated — only use --lan on trusted networks.

# Manual (Terminal 1) Redis
redis-server

# Terminal 2: FastAPI
uv run uvicorn app.main:app --reload
# Server at http://127.0.0.1:8000
# UI: the chat/ Next.js app (http://localhost:4000)

# Terminal 3: Celery background worker (--pool=solo for single-worker safety)
uv run celery -A app.celery_app:celery_app worker --queues=background --pool=solo --loglevel=info

# Without Redis (fallback mode — generalize+store runs in-process):
DEJAQ_USE_CELERY=false uv run uvicorn app.main:app --reload
```

### Workspace model

DejaQ is multi-**workspace**: you (the operator) are above all workspaces and can create as many as needed. Each workspace owns API keys + provider credentials + LLM routing config; departments are cache partitions within a workspace. The workspace slug is the billing/isolation boundary — departments only segment the cache.

On first launch with an empty DB the dashboard routes to an **onboarding wizard**: create a workspace → department → reveal the one-time API key. The CLI `dejaq-admin workspace create --name <name>` is the headless alternative.

### Control-plane vs data-plane split

| Surface | Bound to | Protected by |
|---|---|---|
| Dashboard (`:3000`) | 127.0.0.1 | Localhost (+ optional Supabase JWT) |
| Admin API (`/admin/v1/*`) | 127.0.0.1 | `AdminLoopbackMiddleware` (403 from LAN) |
| Data plane (`/v1/*`) | 0.0.0.0 (LAN) | Workspace API key |

Remote admin access: `ssh -L 3000:localhost:3000 -L 8000:localhost:8000 user@server-ip` — see [docs/admin-access.md](docs/admin-access.md).

### Management auth modes (`/admin/v1/*`)

`config.AUTH_MODE` controls how the management API authenticates. It auto-selects
`local` when `SUPABASE_URL` is blank, `supabase` otherwise (override with `DEJAQ_AUTH_MODE`).

- **`local` (default — recommended for on-prem):** `require_management_auth` returns an unauthenticated dev-admin context (`ManagementAuthContext.local_dev()`); the dashboard opens with no login. Protected by localhost binding, not a password.
- **`supabase` (optional — for hosted/multi-user deployments):** validates a Supabase JWT per request. Set up a free project at [supabase.com](https://supabase.com), copy the Project URL + anon key into `server/.env` (`SUPABASE_URL`, `SUPABASE_ANON_KEY`) and the dashboard env. The `users` + `user_workspace_memberships` tables back this mode (dormant under `local`).

Bootstrap a workspace + API key with the dashboard onboarding wizard or with:
`dejaq-admin workspace create --name "Acme"` then `dejaq-admin key generate --workspace acme`.

> **Note:** `/v1/chat/completions` and `/v1/feedback` always use DejaQ workspace API keys, never Supabase JWTs. Only `/admin/v1/*` is affected by `AUTH_MODE`.

### Environment Variables
Generation always runs through Ollama (`DEJAQ_OLLAMA_URL`); there is no per-role backend switch.

| Variable | Default | Description |
|----------|---------|-------------|
| `DEJAQ_AUTH_MODE` | auto | `local` (dev-admin bypass) or `supabase` (JWT). Auto: `local` when `SUPABASE_URL` blank, else `supabase` |
| `SUPABASE_URL` | `` | Supabase project URL — set to enable `supabase` auth mode for `/admin/v1/*` |
| `SUPABASE_ANON_KEY` | `` | Supabase anon/public key — used by management auth dependency in `supabase` mode |
| `SUPABASE_SERVICE_ROLE_KEY` | `` | Supabase service-role key — reserved for admin Supabase operations (not used at runtime auth) |
| `DEJAQ_REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL (broker + result backend) |
| `DEJAQ_USE_CELERY` | `true` | Set to `false` to disable Celery and run tasks in-process |
| `DEJAQ_ADMIN_LOOPBACK_ONLY` | `true` | Restrict `/admin/v1/*` to loopback peers (127.0.0.1/::1); set `false` behind a trusted reverse proxy |
| `DEJAQ_BIND_HOST` | `0.0.0.0` (start.sh) | Uvicorn listen host; defaults `127.0.0.1` for bare `uv run uvicorn` |
| `DEJAQ_KEY_CACHE_TTL` | `60` | Workspace API-key lookup cache TTL in seconds |
| `DEJAQ_STATS_DB` | `dejaq_stats.db` | Path to SQLite request log (used by `dejaq-admin stats`) |
| `DEJAQ_LOG_LEVEL` | `INFO` | App logging level |
| `DEJAQ_LOG_SHOW_CONTENT` | `false` | Include prompt/response content in request logs when explicitly enabled |
| `DEJAQ_EVICTION_FLOOR` | `-5.0` | Score floor for cache eviction; entries below this are deleted by the beat task |
| `DEJAQ_CREDENTIAL_ENCRYPTION_KEY` | `` | Fernet key used to encrypt workspace provider credentials. Generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`; back it up because losing it makes stored credentials unrecoverable |
| `DEJAQ_EXTERNAL_MODEL` | `gemini-2.5-flash` | Default hard-query model when workspace config has no override; provider is inferred from model name |
| `DEJAQ_ROUTING_THRESHOLD` | `0.3` | Default per-workspace LLM routing threshold used when no workspace override exists |
| `DEJAQ_CHROMA_HOST` | `127.0.0.1` | ChromaDB HTTP server host |
| `DEJAQ_CHROMA_PORT` | `8001` | ChromaDB HTTP server port |
| `DEJAQ_OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama HTTP endpoint for all generation roles (local or remote) |
| `DEJAQ_OLLAMA_TIMEOUT_SECONDS` | `60.0` | Timeout for Ollama backend requests |
| `DEJAQ_ENRICHER_MODEL_NAME` | `qwen_1_5b` | Logical model label for context enricher (→ Ollama tag) |
| `DEJAQ_NORMALIZER_MODEL_NAME` | `gemma_e2b` | Logical model label for normalizer (→ Ollama tag) |
| `DEJAQ_LOCAL_LLM_MODEL_NAME` | `gemma_local` | Logical model label for local generation (→ Ollama tag) |
| `DEJAQ_GENERALIZER_MODEL_NAME` | `phi_generalizer` | Logical model label for background generalizer (→ Ollama tag) |
| `DEJAQ_CONTEXT_ADJUSTER_MODEL_NAME` | `qwen_1_5b` | Logical model label for context adjuster (→ Ollama tag) |
| `DEJAQ_VALIDATOR_MODEL_NAME` | `gemma_e2b` | Logical model label for cache-answer validator (→ Ollama tag) |
| `DEJAQ_VALIDATOR_SKIP_DISTANCE` | `0.05` | Cache hits at or below this cosine distance skip the validator |
| `DEJAQ_CACHE_TRUST_DISTANCE` | `0.15` | Trusted-zone cosine ceiling; hits at or below are served directly |
| `DEJAQ_CACHE_BAND_MAX_DISTANCE` | `0.20` | Upper bound of the validator-guarded band; hits in `(trust, band_max]` need validator approval. Set at or below trust distance to disable |
| `DEJAQ_CACHE_RESCUE_ENABLED` | `true` | Lexical-rescue tier: candidates past the band are eligible when `lexical_match.align` confirms a typo'd variant; always validator-gated |
| `DEJAQ_CACHE_RESCUE_MAX_DISTANCE` | `0.60` | Distance ceiling for the rescue tier |
| `DEJAQ_CACHE_ALIAS_ENABLED` | `true` | Alias learning: validated band/rescue hits store the typo'd phrasing as an alias pointing at the same answer |
| `DEJAQ_CACHE_IMAGE_MAX_DISTANCE` | `0.10` | Photo-path CLIP cosine ceiling |
| `DEJAQ_CACHE_IMAGE_MAX_HAMMING` | `15` | Photo-path dHash hamming ceiling; both this AND the CLIP distance must pass |
| `DEJAQ_CACHE_IMAGE_OCR_ENABLED` | `true` | Route text-bearing images to the OCR document path; `false` sends every image to the photo path |
| `DEJAQ_CACHE_IMAGE_OCR_MIN_CONFIDENCE` | `80.0` | Mean OCR word confidence required to treat an image as a document |
| `DEJAQ_CACHE_IMAGE_OCR_MIN_WORDS` | `6` | Words at confidence ≥ 60 required to treat an image as a document; the confidence floor does the real separating, so this stays low — a short crop read well is still a document |
| `DEJAQ_CACHE_IMAGE_TEXT_MIN_JACCARD` | `0.80` | Document path: the only matching threshold. Measured zero-false-merge point; lower it for recall (0.70 buys ~78% at 114 measured merges) |
| `DEJAQ_CACHE_IMAGE_AMBIGUOUS_MIN_WORDS` | `4` | Tokens at which a text-bearing image read BELOW the confidence floor becomes un-cacheable instead of falling to the photo path |
| `DEJAQ_CACHE_IMAGE_TEXT_MIN_SHARED_TOKENS` | `4` | Shared tokens required before an overlap ratio counts as evidence at all |
| `DEJAQ_CACHE_IMAGE_MIN_TILE_VARIETY` | `10` | Distinct dHashes over a 4×4 grid required to fingerprint by pixels; below it the image is too uniform to identify |
| `DEJAQ_TESSERACT_BIN` | `tesseract` | OCR binary path (`brew install tesseract` / `apt install tesseract-ocr tesseract-ocr-heb`) |
| `DEJAQ_TESSERACT_LANGS` | `heb+eng` | OCR languages; needs the matching `traineddata` installed |
| `DEJAQ_OCR_TIMEOUT_SECONDS` | `20.0` | Per-image OCR timeout; on timeout the image is treated as un-cacheable |

Threshold rationale (why 0.20, 0.60, 0.05, and why images get no trusted tier): [docs/image-gate.md](docs/image-gate.md).

### Endpoints
- `GET /health` — health check; also reports Celery worker status
- `POST /v1/chat/completions` — OpenAI Chat Completions-compatible chat (streaming + non-streaming); **requires** `Authorization: Bearer <workspace-api-key>` (401 when missing/invalid — no anonymous fallback) and optional `X-DejaQ-Department` header; response includes `X-DejaQ-Response-Id` header when cached or stored. Hard queries return HTTP 402 when the workspace has no credential for the configured external provider.
- `POST /v1/responses` — OpenAI Responses API endpoint (newer recommended format). Same auth (401 without a valid workspace API key) and `X-DejaQ-*` headers. Body: `{model, input: string | [{role, content}...], instructions?, stream?, temperature?, max_output_tokens?}`. Non-streaming: `{id, object:"response", output:[...], output_text, usage:{input_tokens, output_tokens, total_tokens}}`. Streaming: typed SSE events (`response.created`, `response.output_text.delta`, `response.completed`, etc.). `previous_response_id` / `conversation` rejected with HTTP 400 — DejaQ is stateless; clients send full history in `input`. The `chat/` Next.js app is the reference client. **Images:** an `input_image` content part (data URL only; remote URLs rejected 400) attaches one image (>1 image → 400). Image requests bypass the difficulty classifier and always route to the workspace's external (vision-capable) provider on a miss; the cache serves an image hit only when the text pipeline hits AND the image fingerprint gate passes (see below). Only `/v1/responses` accepts images — `/v1/chat/completions` stays text-only.
- `POST /v1/feedback` — thumbs-up/down feedback on a cached response; requires `Authorization: Bearer <workspace-api-key>`; body: `{"response_id": "<X-DejaQ-Response-Id value>", "rating": "positive"|"negative", "comment": "<optional>"}`; first negative deletes entry, subsequent negatives decrement score by 2.0; positive increments score by 1.0
- `/admin/v1/*` management endpoints — **loopback-only** (127.0.0.1); auth via `local` dev-admin (default) or Supabase JWT when `SUPABASE_URL` is set. In local mode no token is required:
  - `GET /admin/v1/whoami`
  - `GET|POST|DELETE /admin/v1/workspaces[/{slug}]`
  - `GET /admin/v1/departments`, `POST|DELETE /admin/v1/workspaces/{workspace_slug}/departments[/{dept_slug}]`
  - `GET|POST /admin/v1/workspaces/{workspace_slug}/keys`, `DELETE /admin/v1/keys/{key_id}`
  - `GET /admin/v1/stats/workspaces`, `GET /admin/v1/stats/workspaces/{workspace_slug}/departments`
  - `GET|PUT /admin/v1/workspaces/{workspace_slug}/llm-config`
  - `GET /admin/v1/workspaces/{workspace_slug}/credentials`
  - `PUT /admin/v1/workspaces/{workspace_slug}/credentials/{provider}`
  - `DELETE /admin/v1/workspaces/{workspace_slug}/credentials/{provider}`
  - `POST /admin/v1/workspaces/{workspace_slug}/test-provider`
  - `GET|POST /admin/v1/feedback`
- `dejaq-admin cache purge-images --workspace <slug> [--department <slug>] [--no-dry-run]` — delete image-anchored cache entries after a gate rule change; text entries untouched, defaults to a dry run

## Architecture

Layering: `routers/` (endpoints) → `services/` (business logic) → `schemas/` (Pydantic models) → `db/models/` (ORM) → `db/*_repo.py` (DB access). Grep for a filename rather than expecting a per-file index here.

| Directory | Holds |
|---|---|
| `app/main.py`, `config.py`, `celery_app.py` | FastAPI init + CORS + health, centralized settings, Celery broker/queue config |
| `app/routers/` | `openai_compat.py` (`/v1/chat/completions`, `/v1/responses`), `feedback.py`, `departments.py`, `admin/` (`/admin/v1/*`) |
| `app/services/` | The pipeline: `normalizer`, `context_enricher`, `context_adjuster`, `validator`, `cache_filter`, `classifier`, `lexical_match`, `memory_chromaDB` (semantic cache), `image_fingerprint` (image gate). Plus infra: `model_backends` (OllamaBackend + `MODEL_RUNTIME_SPECS`), `service_factory`, `llm_router`, `external_llm` + `llm_providers/` (Google/OpenAI/Anthropic), `credential_service`, `provider_inference`, `admin_service`, `stats_service`, `llm_config_service`, `feedback_service`, `request_logger` |
| `app/tasks/cache_tasks.py` | Celery `generalize_and_store_task` (Phi-3.5 + ChromaDB) |
| `app/db/` | SQLAlchemy base/session, repos, and `models/` (org, department, api_key, org_llm_config, org_provider_credentials) |
| `app/middleware/`, `app/dependencies/` | Bearer token → org/department resolution onto `request.state` |
| `app/utils/` | `logger.py`, `exceptions.py` (`ExternalLLMError` / `…AuthError` / `…TimeoutError`) |
| `cli/` | `dejaq-admin` (org, dept, key, stats) + Rich rendering helpers |

**Key patterns:**
- All generation runs through Ollama (`OllamaBackend`); `service_factory` builds one shared backend from `DEJAQ_OLLAMA_URL` (local or remote)
- `MODEL_RUNTIME_SPECS` maps logical role names (e.g. `gemma_e2b`) to Ollama tags (e.g. `gemma4:e2b`)
- The DeBERTa difficulty classifier and BGE cache embeddings are the only in-process ML (torch); generation is not in-process
- All schemas use Pydantic BaseModel
- Client sends full message history in the `messages` array (stateless; no server-side conversation store)
- Cache miss triggers background generalization + storage via Celery task queue (falls back to in-process if Celery disabled) — only if cache filter passes
- Celery workers reach the same shared Ollama endpoint for generation (no per-worker model loading)
- Context enricher rewrites follow-up queries ("tell me more") into standalone questions before normalization
- Cache filter skips storing trivial messages (filler words, too short, too vague)
- Per-request stats logged to SQLite (fire-and-forget via asyncio.create_task)
- Feedback adjusts ChromaDB entry scores (+1.0 positive, −2.0 negative); first negative deletes immediately
- External LLM routing supports Google, OpenAI, and Anthropic provider clients through encrypted org credentials; `ExternalLLMService` is a singleton
- Org/dept/API-key data lives in SQLite (SQLAlchemy + Alembic); `dejaq.db` by default

### Management API

`/admin/v1/*` is a separate operator surface from the OpenAI-compatible `/v1/*` gateway. It requires Supabase JWT authentication; system access is reserved for configured service paths such as demo seeding.

The org API-key middleware skips `/admin/v1/*` before parsing or logging `Authorization`, so admin tokens are never treated as customer API keys.

## Coding Conventions

- **Never use `print()`** — use `logging.getLogger("dejaq.<module>")` via `app.utils.logger`
- **Package manager**: `uv` only (no pip)
- **Async/await** for all I/O operations
- **Strong typing** with Pydantic for all request/response models
- **Directory structure**: routers (endpoints) → services (business logic) → schemas (data models) → models (DB) → repositories (DB access)

## Models (actual)

| Role | Model | Ollama tag |
|------|-------|-----------|
| Context Enricher (v5) | Qwen 2.5-1.5B-Instruct | `qwen2.5:1.5b` |
| Normalizer (cleaning) | Qwen 2.5-0.5B-Instruct | `qwen2.5:0.5b` |
| Normalizer (opinion rewrite, v22) | Gemma 4 E2B-Instruct | `gemma4:e2b` |
| Cache Validator | Gemma 4 E2B-Instruct | `gemma4:e2b` |
| Context Adjuster (adjust) | Qwen 2.5-1.5B-Instruct | `qwen2.5:1.5b` |
| Generalizer (strip tone) | Phi-3.5-Mini-Instruct | `phi3.5:latest` |
| Local LLM (generation) | Gemma 4 E4B-Instruct | `gemma4:e4b` |
| Difficulty Classifier | NVIDIA DeBERTa-v3-base | in-process torch (not Ollama) |
| Cache embeddings | BAAI/bge-small-en-v1.5 | in-process torch (not Ollama) |
| Image fingerprint (CLIP) | clip-ViT-B-32 | in-process torch (not Ollama) |
| Image OCR (documents) | Tesseract `heb+eng` | external `tesseract` binary (not Ollama) |

## Deployment Modes (Ollama local / remote)

All generation runs through Ollama — `--mode=local` uses `http://127.0.0.1:11434`, `--mode=remote` takes `--ollama-url` (see the Run section for both invocations). The DeBERTa classifier and BGE cache embeddings still load in-process (torch) on first request. ChromaDB starts with the app stack; Redis backs Celery (or set `DEJAQ_USE_CELERY=false` to run background storage in-process).

FastAPI stays lightweight and sends independent async HTTP requests to Ollama; total throughput is bounded by the Ollama host. For external (hard-query) provider credentials set `DEJAQ_CREDENTIAL_ENCRYPTION_KEY` (back it up; losing it is unrecoverable).

## Test Harnesses

Offline eval harnesses live under `evals/` (`enricher`, `normalizer`, `adjuster`, `validator`, `image_similarity`). Image-gate thresholds are derived by `evals/image_similarity/protocol.py` over a labelled corpus — never by hand. Invocations, metrics, datasets, and per-config results: [evals/README.md](evals/README.md). Generated `reports/` are gitignored.

## Current Status

**Working:** FastAPI HTTP, Normalizer (Qwen 0.5B, v22), LLM Router (Gemma 4 E4B local → provider-backed external LLMs), Context Adjuster (generalize via Phi-3.5 + adjust via Qwen 1.5B), Semantic cache (ChromaDB, cosine ≤ 0.15), Background generalize+store on cache miss, Context Enricher v5 (Qwen 1.5B + regex gate, 88.7% @0.15 across 5 datasets), Smart Cache Filter (skip non-cacheable prompts), Difficulty Classifier (NVIDIA DeBERTa — routes easy→local, hard→org credential backed provider), Celery + Redis task queue (non-blocking generalize+store), OpenAI-compatible endpoint with API-key auth + per-department cache namespacing, Org/department/API-key/credential management (SQLAlchemy + Alembic SQLite + `dejaq-admin` CLI), Stats tracking (SQLite + Rich CLI — `dejaq-admin stats`), Score-based cache eviction (Celery beat), Feedback API (score adjustments + delete on first negative), Web dashboard (Next.js) with local dev-bypass auth (Supabase JWT in deployment), Ollama-only generation (local or remote via `OllamaBackend`/service_factory — decouples inference from FastAPI for multi-user parallelism). DeBERTa classifier + BGE cache embeddings run in-process (torch). Hard-query runtime credentials come from encrypted `org_provider_credentials`. Image caching on `/v1/responses` (one image per request, external vision provider on miss): documents matched by OCR text (Tesseract) at a single swept threshold, photos by CLIP+dHash, and text-bearing images that miss the document bar refused outright — CLIP embedder runs in-process (torch), OCR shells out to `tesseract`. Thresholds derived over 286,000 labelled pairs; expect ~45–54% recall on documents, which is the measured ceiling for this approach.
**Planned:** Local vision-model generation + per-workspace image routing config (customizable local-vs-external for images — needs a local VLM answer-quality eval first), multi-image / PDF / file support, image alias learning, RAG within organizations (per-org document retrieval), PostgreSQL migration, Subject-extraction preprocessing for bare comparative failures ("Which is cheaper?" — 1.5B model not sufficient)

## Active Technologies

- Python 3.13+ + FastAPI + Uvicorn, ChromaDB (HttpClient), redis-py (Celery dependency), Pydantic v2, Celery, aiosqlite (request log), Rich (stats CLI), SQLAlchemy + Alembic (org/dept/key/credential DB, SQLite), cryptography/Fernet, google-genai, openai, anthropic

## Dashboard

The web dashboard lives in `dashboard/` (Next.js 16, TypeScript, Tailwind v4, App Router). It talks to the management API at `/admin/v1/*`. Setup and env vars: see [dashboard/README.md](dashboard/README.md).

> ⚠️ Next.js 16 differs from older versions — see [dashboard/AGENTS.md](dashboard/AGENTS.md). Notably the middleware file convention was renamed `middleware.ts` → `proxy.ts`; the project root `proxy.ts` is the active middleware.

**Auth modes** (mirrors backend `AUTH_MODE`, gated by `lib/authMode.ts` = `!NEXT_PUBLIC_SUPABASE_URL`):
- **Local dev (no `NEXT_PUBLIC_SUPABASE_URL`):** dashboard skips login; `lib/api.ts` sends `Authorization: Bearer dev-local` (backend ignores it in local mode). Dev only.
- **Supabase (deployment):** user signs in via `@supabase/ssr`; `lib/api.ts` attaches the session JWT to every `/admin/v1/*` call; FastAPI validates it. `/v1/chat/completions` and `/v1/feedback` always use DejaQ org API keys, never Supabase JWTs.

**CORS:** FastAPI must allow `http://localhost:3000` (`allow_origins` in `server/app/main.py`) for local development.
