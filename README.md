# DejaQ

DejaQ is an LLM gateway that reduces cost and latency with semantic caching, local routing, workspace-scoped provider credentials, and a per-workspace knowledge base that grounds answers in the organisation's own documents. Existing clients can use the OpenAI-compatible API while operators manage workspaces, API keys, credentials, stats, and feedback through the management API, CLI, TUI, or dashboard.

## Project Document

[Project document](https://docs.google.com/document/d/18XAP_r1MI7rwU2BvKt5mA25AI7YqmIRA5KEmLbwauAo/edit?tab=t.0)

## Runtime Flow

```text
OpenAI-compatible request
  -> context enrichment
  -> normalization
  -> ChromaDB semantic cache lookup
     -> hit: cache validator (Gemma E2B) checks coverage
        -> VALID: context adjuster re-tones cached answer
                  (skipped when there is no tone gap to close)
        -> INVALID: treat as miss
     -> miss: difficulty classifier
        -> easy: local model (Gemma 4 E4B)
        -> hard: workspace provider credential (OpenAI / Anthropic / Google)
        -> either way: relevant chunks from the workspace knowledge base (Rug)
           are injected into the prompt as grounding, when any are close enough
  -> response
  -> background generalize + store when cacheable
```

## Repository Structure

```text
server/              FastAPI app, gateway, management API, dejaq-admin CLI, Celery tasks
dashboard/           Next.js dashboard (/admin/v1/*; dev-admin auth, loopback-only)
chat/                Standalone Next.js chat app with server-side workspace API key proxy
evals/               Offline eval harnesses (see evals/README.md for the list)
docs/                Product/API notes + getting-started.md
openspec/            Specs and proposal history
```

## Quick Start

Local development needs **no `.env`** — the dashboard runs
in dev-bypass mode (no login) and the backend grants a dev-admin context.

Generation runs through **Ollama** (local or remote). Start it and pull the model tags first:

```bash
ollama serve
ollama pull qwen2.5:0.5b qwen2.5:1.5b gemma4:e2b gemma4:e4b
```

```bash
cd server
uv sync
uv run alembic upgrade head
cd ..
./start.sh --stack=all --mode=local         # cross-platform (macOS/Linux/Windows git-bash)
# remote Ollama: ./start.sh --stack=all --mode=remote --ollama-url=http://<host>:11434
# LAN access:    ./start.sh --stack=all --mode=local --lan
```

Add `--lan` to expose the chat UI (port 4000) and API (port 8000) on `0.0.0.0` so other
devices on the same network can reach them (the script prints the LAN URLs). The dashboard
(3000), ChromaDB (8001), and Redis stay localhost-only. The admin API is unauthenticated,
so only use `--lan` on trusted networks.

Then open the dashboard at `http://localhost:3000/dashboard`, create a workspace
and generate an API key, and use it as `Authorization: Bearer <key>` against the gateway
(or paste it into the chat app at `http://localhost:4000`).

Stacks: `all` (backend + dashboard + chat), `server` (backend + dashboard, no chat),
`client` (chat app only — connects to a DejaQ server elsewhere on the network; set the
server address and API key in the chat Settings modal, or via `DEJAQ_API_BASE_URL` /
`DEJAQ_API_KEY` in `chat/.env.local` — see [chat/README.md](chat/README.md)).

Backend + dashboard (no chat), or manual launch:

```bash
./start.sh --stack=server --mode=local
# or, by hand:
redis-server
uv run uvicorn app.main:app --reload
uv run celery -A app.celery_app:celery_app worker --queues=background --pool=solo --loglevel=info
# without Redis:
DEJAQ_USE_CELERY=false uv run uvicorn app.main:app --reload
```

> **Dashboard auth:** dev bypass only — no login, no configuration. The management API is
> protected by loopback binding, not a credential.

## Frontend

```bash
cd dashboard
npm install
cp .env.local.example .env.local
npm run dev
```

The dashboard runs at `http://localhost:3000` and talks to the backend through `NEXT_PUBLIC_API_BASE_URL`.

## Chat

```bash
cd chat
npm install
cp .env.local.example .env.local
npm run dev
```

Fill `DEJAQ_API_KEY` in `chat/.env.local`, or leave it blank and paste a key into the chat app's Settings modal instead (a Settings key wins). The chat app runs at `http://localhost:4000`, calls its own `/api/*` routes from the browser, and those server routes forward to the backend through `DEJAQ_API_BASE_URL`. See [chat/README.md](chat/README.md) for details.

## Main Interfaces

- `GET /health`
- `POST /v1/chat/completions` — OpenAI Chat Completions-compatible gateway, authenticated by DejaQ workspace API key
- `POST /v1/responses` — OpenAI Responses API (newer recommended format), same auth, stateless (`previous_response_id` rejected)
- `POST /v1/feedback` — cache feedback with optional thumbs-down escalation to the next serving tier (cache → local → external), authenticated by DejaQ workspace API key
- `/admin/v1/*` — management API; unauthenticated dev-admin context, protected by loopback binding
- `dejaq-admin` — workspace, department, key, stats, and knowledge-base CLI (headless/server-only bootstrap)

Responses include `X-DejaQ-Interaction-Id`, `X-DejaQ-Tier` (`cache`|`local`|`external`), and (when cached) `X-DejaQ-Response-Id` headers. See [docs/getting-started.md](docs/getting-started.md), [docs/openai-compat-api.md](docs/openai-compat-api.md), [docs/cli-instructions.md](docs/cli-instructions.md), [server/README.md](server/README.md), and [dashboard/README.md](dashboard/README.md).

## Attachments (images and files)

`/v1/responses` accepts **one** attachment per request — either an `input_image` or an
`input_file`, never both, and never two of a kind (each violation is a `400`). Both must be
`data:` URLs and are capped at `DEJAQ_MAX_ATTACHMENT_BYTES` (10 MB). `/v1/chat/completions`
does not accept attachments.

The attachment never enters the cache key: the text pipeline runs exactly as it would
without it, and a cache hit is served only if an **attachment gate** also confirms the
stored entry was anchored to the *same* attachment. On a miss, attachment requests skip the
difficulty classifier and route straight to the workspace's external provider.

- **Images** (`input_image`) — an image that OCRs to confident text is treated as a
  *document* and matched by its words; one with little readable text is a *photo* and
  matched by its pixels (CLIP + dHash); one with at least `DEJAQ_CACHE_IMAGE_AMBIGUOUS_MIN_WORDS`
  (4) tokens read *below* the confidence floor is refused outright — never served, never
  stored, while fewer tokens than that leave it a photo. Documents need the `tesseract` binary
  (`start.sh` warns when it is missing; without it, documents fall back to the photo path).
  Raw image bytes are never stored, only fingerprints.
- **Files** (`input_file`) — PDF (via `pypdf`), Word documents (`.docx`, via `python-docx`,
  paragraphs and tables only), and any text or code file (Markdown, `.txt`, source, config,
  or extensionless files like `Dockerfile` — anything that decodes as UTF-8). The gate is an
  exact `sha256` of the whitespace-normalised extracted text, so false merges are impossible
  by construction. `DEJAQ_CACHE_FILE_MIN_CHARS` (200) applies only to PDF and DOCX, where
  extraction can fail silently — a scanned PDF with no text layer, or a corrupt/encrypted
  file, is never served and never stored; the answer still comes back, there is just no
  cache entry. Text/code files have no such floor and are cached down to one character.

Thresholds and their measured derivations: [docs/image-gate.md](docs/image-gate.md) and
[docs/file-gate.md](docs/file-gate.md). Every setting is listed in `.env.example`.

## Knowledge base (Rug)

Each workspace has an admin-curated knowledge base — a third answer source alongside the
semantic cache and the model. Admins add pasted text, uploaded files (PDF / DOCX / text /
code / OCR'd images), or web pages through the dashboard's **Knowledge Base** page,
`dejaq-admin rag`, or `/admin/v1/workspaces/{slug}/rag-documents`. On a cache miss the
closest chunks are injected into the prompt as grounding, so answers come from the
organisation's own facts; the retrieved text never enters the cache key. Setup, tuning, and
safety rules: [docs/rag-layer.md](docs/rag-layer.md).

## Pipeline customization

The dashboard's **Pipeline** page (`/dashboard/pipeline`) renders the cache pipeline as a
flow and lets each workspace override, per stage, both the Ollama model it runs on (any tag
installed on the configured host) and its system prompt - context enricher, normalizer,
cache validator (a text-question prompt and an image & file-attachment prompt), context
adjuster, generalizer, and the local answering model. Every override is optional; resetting
one restores the shipped default. The external answering model stays on **Settings**,
because it is tied to the provider credential. Editing the context adjuster or generalizer
prompt invalidates the calibration of their runaway/looping safety-net thresholds, which
were measured against the shipped prompts - the page warns on those two stages.

The same page also sets the workspace's three token budgets - the answer budget used when a
client sends no limit of its own, the rewrite budget for the generalizer and context
adjuster, and the Ollama context window - each attached to the stages it governs and each
showing the current effective value as its placeholder, so an empty field means "using the
shipped default". They are validated together, not one at a time: a combination that would
leave the rewrite budget or the context window too small to carry the answer being rewritten
is rejected with an explanatory error rather than clamped, because a too-low budget produces
no error anywhere - it just silently stops the cache from filling, since a truncated answer
is never stored. The **Analytics** page shows the resulting truncation rate (over generated
answers; a cache hit is never truncated) next to hit rate, latency, and tokens saved.

## Bootstrap a workspace + key

Either through the dashboard (Workspaces → create, Keys → generate) or headless via the CLI:

```bash
cd server
uv run dejaq-admin workspace create --name Demo
uv run dejaq-admin key generate --workspace demo
```

## Verification

```bash
cd server
uv run pytest --collect-only -q
uv run pytest -q -m no_model

cd ../dashboard
npx tsc --noEmit --pretty false
npm run build

cd ../chat
npx tsc --noEmit --pretty false
npm run build
```
