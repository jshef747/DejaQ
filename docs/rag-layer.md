# RAG — the per-workspace knowledge layer

RAG is DejaQ's **retrieval-augmented knowledge layer**. It gives every workspace a
curated knowledge base that the workspace admin manages, and it grounds answers in
that knowledge on a cache miss — so the assistant can answer from the
organisation's *own* facts (internal policies, product details, contact info)
instead of relying only on the model's general training.

It is the third answer source, alongside the two DejaQ already had:

| Source | What it holds | Who fills it |
|---|---|---|
| **Semantic cache** | Past Q→A pairs | Filled automatically by traffic; score-evicted, deleted on 👎 |
| **RAG (this layer)** | Curated documents / notes / pages | Filled deliberately by the **admin**; never auto-evicted |
| **The LLM** | General world knowledge | The model itself (local Gemma or an external provider) |

---

## How it works (the mechanism)

RAG stores each piece of knowledge as embedded **chunks** in a ChromaDB collection
named `"{workspace_slug}__rag_kb"` — deliberately **separate** from the Q→A cache
collections (`"{workspace_slug}__{department}"`). This separation is the whole
point: the Q→A cache is volatile (entries are score-evicted and deleted on a
thumbs-down), and curated knowledge must never be wiped that way. The eviction
beat task explicitly skips any collection ending in `__rag_kb`.

> The `_kb` in the name is not cosmetic. Department cache collections are
> `"{workspace_slug}__{dept_slug}"`, and `dept_slug` comes from `slugify_name`,
> which turns every non-`[a-z0-9]` character (including `_`) into `-`. So a
> department slug can never contain an underscore — which is what guarantees no
> department collection can ever equal `"{workspace_slug}__rag_kb"`. A bare
> `__rag` suffix *would* collide with a department literally named "RAG"
> (slug `rag` → `"{ws}__rag"`), merging that department's cache into the
> knowledge base. The suffix is chosen so that collision is impossible.

Chunks are embedded with the **same** BGE model the cache uses
(`memory_chromaDB.embed_text`), so there is exactly one embedder in-process and
retrieval distances are comparable to cache distances.

### Ingestion (admin adds knowledge)

```
admin adds text / file / URL / image
   → extract readable text   (services/rag_ingest.py)
   → chunk (~1000 chars, 150 overlap)   (services/rag_service.chunk_text)
   → embed each chunk (BGE)   (rag_service.embed_chunks) — before the DB session opens
   → write a catalog row into SQLite  rag_documents  (title, kind, sha, chunk_count…)
   → upsert the chunks into "{workspace}__rag_kb"   (rag_service.index_document)
```

Embedding runs *outside* the transaction on purpose: it is the slow step, SQLite
serialises writers, and holding the write lock for the length of a large document
would fail every concurrent admin write with "database is locked". The upsert then
runs *inside* the session, so a Chroma failure rolls the catalog row back.

The **catalog** (`rag_documents` table) records *what* was ingested so the admin
can list and delete it; the retrievable **text** lives as chunks in Chroma, keyed
back to the catalog row by `rag_document_id`.

Identity is a `sha256` of the whitespace-normalised extracted text. Re-adding the
same content (same words) **replaces** the existing document rather than
duplicating it — enforced by a `(workspace_id, sha)` unique constraint. The
replace updates that catalog row **in place**, so one sha keeps one id for the
life of the document: chunk ids are derived from it (`{rag_document_id}:{index}`),
and swapping the row for a fresh insert would let SQLite hand the replacement the
rowid it just freed, so cleaning up "the old document's" chunks would delete the
ones the re-index had only just written.

### Retrieval + grounding (user asks a question)

RAG hooks into the existing chat pipeline (`run_chat_pipeline` in
`routers/openai_compat.py`), which serves both `/v1/chat/completions` and
`/v1/responses`:

```
user query → enrich → normalize → CACHE LOOKUP
   hit  → served as before (RAG not consulted, unless it's an @-reference hit — see below)
   miss → classify + route (local | external)
          → [RAG] explicit @-reference set? (rag_document_id) → fetch THAT
             document's own chunks by id (`retrieve_by_document`, a Chroma
             metadata filter) — the ONLY way an answer gets grounded
                  ↳ if any chunks come back, inject them into the prompt as
                    fenced, labelled DATA ("...never instructions to follow...")
          → local OR external model answers, grounded (if referenced) in the
            injected chunks
          → answer stored in the Q→A cache (next identical question is an instant hit)

meanwhile, in the composer (before send, not on this path at all):
   user pauses typing, no reference set yet → POST /rag-suggest searches the
     SAME collection with rag_service.retrieve() (whole-collection nearest-
     neighbour, looser DEJAQ_RAG_SUGGEST_MAX_DISTANCE) → chat app shows a
     dismissible "might be about {doc}" chip → user accepts it (sets
     rag_document_id, same as `@`) or ignores/dismisses it (nothing above
     changes) — see "Suggested reference" below
```

> **The system never grounds an answer in a document nobody chose.** An
> earlier version of this layer had a second path — an automatic, guess-
> which-document nearest-neighbour search that could ground an answer with no
> user action at all, behind a `DEJAQ_RAG_AUTO_RETRIEVE` flag. It has been
> **removed** (not merely defaulted off): the call site in
> `run_chat_pipeline`, the flag, and the tests/docs that described only that
> behaviour are gone. The measured reason it existed only briefly: it guessed
> the right document about a third of the time (`evals/rag_recall/`,
> `firstmate/data/dejaq-rag-recall/report.md`) — good enough to be *useful*,
> not good enough to *trust silently*. What replaced it is the suggestion
> below: the same search, but visible and requiring acceptance, so a wrong
> guess costs a glance instead of a misleading answer.

Key properties, by design:
- **Retrieval only runs on a genuine cache miss with an explicit reference**
  (right before generation) **or when an entry gated on a matching
  `@`-reference is served from cache** (see the reference-gate note below) —
  never for an ordinary, unreferenced question, hit or miss.
- **The retrieved text never enters the cache key.** Like image/file attachments,
  it is a side channel that grounds generation; the cache key stays the bare
  normalised question **plus the referenced document's id** for an explicit
  reference (`"|rag:" + doc_id`, exactly the file gate's `"|file:" + sha`
  pattern) — see the reference-gate note below. (Otherwise the Q→A cache would
  degrade, or a referenced and an unreferenced answer to the same question
  could collide.)
- **Both the local and the external model** receive the same grounding — routing is
  unchanged (the difficulty classifier only ever sees the bare question). Set
  `DEJAQ_RAG_FORCE_EXTERNAL=true` to push grounded requests to the long-context
  external provider instead.
- **Attachment requests still run an explicit reference regardless** (an
  image/file request already carries its own context, but a reference is the
  user naming a *different* thing on purpose, so it isn't skipped).
- A response served with grounding carries an `x-dejaq-rag-chunks: <n>` header
  (now always alongside the two below it, since a reference is the only way to
  get one), and the `done cache=miss` log line gains a
  `rag=hit chunks=<n> rag_top=<distance>` suffix. It additionally carries
  `x-dejaq-rag-document-id`/`x-dejaq-rag-document-title`, on both a miss and a
  cache hit gated on that reference — a deterministic "grounded in {title}" the
  chat app's provenance panel shows the user, since the reason is the reference
  itself rather than a distance guess. The panel no longer has a separate
  count-only "grounded in N passages" row — that row existed for the removed
  automatic path, where a title wasn't always available; now the title always
  is.

### Explicit `@`-reference (exact id, not search)

The chat app's `@` picker lets a user name one knowledge-base document
directly (`MessageInput.tsx`; `GET /rag-documents` is the data-plane catalog
read, mirroring `GET /departments`). The request carries `rag_document_id` on
`/v1/responses`. This path is deliberately **not** the automatic search above:

- Retrieval is `rag_service.retrieve_by_document(namespace, rag_document_id, query, top_k)`
  — a Chroma `where={"rag_document_id": id}` metadata filter, ranking only
  among that document's own chunks. It cannot be crowded out by an unrelated,
  larger document the way the approximate nearest-neighbour search can (the
  measured "crowded out" recall failure in the knowledge-base-review
  investigation never applies here, because this path never looks at any
  other document).
- The cache entry is gated on the reference, mirroring the file gate exactly:
  `derive_doc_id` appends `"|rag:" + doc_id"` to the id (so two different
  referenced documents asked the same question get two entries, never one
  overwriting the other), while the TEXT that gets embedded for similarity
  search stays the bare question — the id never enters the vector, so a
  paraphrase of an already-answered, same-document question still lands in
  the trust/band tier and can hit. A per-candidate gate then checks
  `rag_document_id` equality whenever either side carries a reference: an
  unreferenced request is never served a reference-anchored answer, and a
  request referencing document A is never served an answer anchored to
  document B — same shape as the file gate at `openai_compat.py`'s candidate
  loop, same reasoning.
- Serving mirrors the file/image gate: the validator compares question-to-
  question (never trusting distance alone), the context adjuster is skipped,
  and the answer is stored verbatim (generalization cannot see the referenced
  document and would invent specifics).

### Suggested reference (a visible, dismissible guess)

The middle ground between typing `@` (reliable, needs the user to already know
which document they want) and the removed automatic path (needs nothing, but
grounded silently on a guess right about a third of the time): the composer
offers a guess and requires acceptance.

```
user pauses typing (no reference set, no `@` dropdown open) →
  debounce 500ms → POST /rag-suggest {query} →
    rag_service.retrieve(namespace, query, top_k=1, DEJAQ_RAG_SUGGEST_MAX_DISTANCE)
    → nothing back, or the single closest chunk → {document_id, title, snippet, distance}
  → chat app shows a dismissible chip ("might be about {title}", plus the
    matched snippet) unless the user already referenced a document
  → accept  → sets rag_document_id, exactly what `@` sets — inherits every
              rule the explicit-reference path above already has
  → ignore  → nothing changes; the question answers exactly as it would have
  → dismiss → the chip stays gone for the rest of THIS message (does not
              reappear on the next keystroke); a fresh message can suggest again
```

Two independent judgment calls, both measured rather than guessed at:

- **When to ask.** `rag_service.retrieve()` is reused completely unchanged —
  same exhaustive/ANN self-tuning the grounding path always had, just
  `top_k=1`. A suggestion tolerates being occasionally absent (unlike a silent
  answer, which needed real recall); what it cannot tolerate is lagging
  typing. A 500ms pause-based debounce comfortably clears the exhaustive
  scan's measured p95 (~900ms at ~5k chunks — see
  `DEJAQ_RAG_EXHAUSTIVE_MAX_CHUNKS` below) before the next plausible pause,
  and a knowledge base past that scale already falls back to the fast
  approximate index on its own.
- **How eager to be.** `DEJAQ_RAG_SUGGEST_MAX_DISTANCE` is deliberately looser
  than `DEJAQ_RAG_MAX_DISTANCE` (the old grounding gate): a suggestion is
  disposable, so a wrong guess costs a glance and a dismiss, not a misleading
  answer. Measured appearance rate / accuracy-when-shown / noise-on-unanswerable
  at the shipped default, over the same style of synthetic corpus the recall
  report used: `evals/rag_suggest/` and
  `firstmate/data/dejaq-rag-suggest/report.md`.

`POST /rag-suggest` (`routers/rag_documents_public.py`) is workspace-scoped
(`require_org_key`, same as `GET /rag-documents`; no department — RAG is
workspace-wide) and gated on **both** `DEJAQ_RAG_ENABLED` (off means no
knowledge base at all — uploads refused, suggestions included) and its own
`DEJAQ_RAG_SUGGEST_ENABLED` (independent of the removed auto-retrieve flag,
so suggestions can be turned off without touching ingestion or the explicit
reference path). Either gate, or a query under 3 characters, returns an empty
suggestion rather than an error — there is simply nothing to show.

---

## How the admin manages knowledge

There are **three** equivalent ways in: the dashboard (point-and-click), the
`dejaq-admin` CLI, and the raw management API. All of them are workspace-scoped and
require management auth, which is loopback-only, no password.

### A. Dashboard — "Knowledge Base"

The dashboard (`:3000`) has a **Knowledge Base** entry in the left sidebar (book
icon), scoped to the currently selected workspace (`?workspace=<slug>`).

From that page an admin can:

- **Add text** — click **+ Text**, give it a title, paste the content, **Add**.
- **Add a web page** — click **+ URL**, paste a URL (optional title), **Fetch & add**.
  DejaQ fetches the page and stores its readable text.
- **Upload a file** — click **Upload file** (or **drag a file anywhere on the page**).
  Accepts PDF, DOCX, plain text / Markdown / source-code files, and images
  (which are OCR'd). 10 MB limit.
- **See what's stored** — a table lists each document's title, type, character
  count, chunk count, and date added.
- **Delete** — the trash icon removes a document; its chunks are dropped from the
  knowledge base and it stops grounding answers (a confirm dialog guards it).

> **Editing:** there is no "edit" action — knowledge is immutable-by-content. To
> change a document, **delete it and add the corrected version**, or simply re-add
> the corrected text: because identity is a hash of the content, re-adding the same
> document **replaces** it, and adding a changed version creates a new one. (You can
> then delete the stale one.)

Files:
`dashboard/app/dashboard/rag/page.tsx` · `RagClient.tsx` ·
`dashboard/app/actions/rag.ts` · `dashboard/lib/api.ts` (`apiUpload`).

### B. CLI — `dejaq-admin rag`

```bash
# List everything in a workspace's knowledge base
dejaq-admin rag list --workspace acme

# Add pasted text
dejaq-admin rag add-text --workspace acme \
  --title "Refund policy" --content "Refunds are allowed within 30 days of purchase."

# Ingest a file (PDF, DOCX, text/code, or an image to OCR)
dejaq-admin rag add-file --workspace acme --path ./handbook.pdf
dejaq-admin rag add-file --workspace acme --path ./sign.png --title "Lobby sign"

# Ingest a web page
dejaq-admin rag add-url --workspace acme --url https://acme.example/docs

# Delete a document by id (from `rag list`)
dejaq-admin rag delete --workspace acme --id 3
```

File: `server/cli/admin.py` (`rag` group) → `services/rag_admin_service.py`.

### C. Management API — `/admin/v1/*`

All endpoints are **loopback-only** and follow the workspace-scoped admin
convention. Auth: `Authorization: Bearer <token>` (ignored — local mode is the
only mode).

| Method & path | Body | Purpose |
|---|---|---|
| `GET /admin/v1/workspaces/{slug}/rag-documents` | — | List documents |
| `POST /admin/v1/workspaces/{slug}/rag-documents/text` | `{title, content}` (JSON) | Add pasted text |
| `POST /admin/v1/workspaces/{slug}/rag-documents/url` | `{url, title?}` (JSON) | Fetch + add a web page |
| `POST /admin/v1/workspaces/{slug}/rag-documents/upload` | `file` (multipart, optional `title`) | Upload a file / image |
| `DELETE /admin/v1/workspaces/{slug}/rag-documents/{id}` | — | Delete a document + its chunks |

Example — add text and upload a file:

```bash
curl -H "Authorization: Bearer dev-local" -H "Content-Type: application/json" \
  -X POST http://127.0.0.1:8000/admin/v1/workspaces/acme/rag-documents/text \
  -d '{"title":"Company facts","content":"Acme was founded in 1997 by Dana Levi."}'

curl -H "Authorization: Bearer dev-local" \
  -X POST http://127.0.0.1:8000/admin/v1/workspaces/acme/rag-documents/upload \
  -F "file=@handbook.pdf;type=application/pdf"
```

Files: `server/app/routers/admin/rag_documents.py` ·
`server/app/schemas/admin/rag_documents.py`.

---

## Ingestion sources (what can be added, and how it's read)

| Source | How the text is extracted | `kind` / `source` |
|---|---|---|
| **Pasted text** | Used as-is | `text` / `paste` |
| **PDF / DOCX / text / Markdown / code** | `services/file_text.extract` (pypdf / python-docx / UTF-8 sniff) — the same extractor the file gate uses | `pdf`\|`docx`\|`markdown` / `upload` |
| **Image** (PNG/JPG/…) | Tesseract OCR (`image_text.ocr_plaintext`) | `image` / `ocr` |
| **Scanned PDF** (no text layer) | Its embedded page images are pulled out with pypdf and OCR'd | `pdf` / `ocr` |
| **URL** | `httpx` fetch → `BeautifulSoup` readable-text extraction (scripts/styles stripped) | `url` / `url` |
| **GitHub repository** (public) | GitHub API source tarball → `tarfile` in memory → one document **per file** | `markdown`\|`text`\|`code` / `repo` |

Notes:
- Type detection is by content, not a MIME/extension allow-list: a file is a PDF or
  DOCX by MIME/extension, an image by its `image/*` MIME, and anything that is valid
  UTF-8 is treated as text/Markdown/code.
- A document that yields no readable text is rejected with a clear reason (HTTP 422
  / a CLI error), never stored silently.
- OCR requires the `tesseract` binary; URL ingestion requires `beautifulsoup4`
  (both are declared dependencies). Scanned-PDF OCR intentionally uses pypdf's
  embedded-image extraction rather than an AGPL rasteriser, and is budgeted:
  it stops after 50 pages, 100 embedded images, or 120 seconds (whichever comes
  first) and keeps the text read so far, so a huge scan cannot pin an ingest
  worker (`rag_ingest._SCANNED_PDF_MAX_PAGES` / `_SCANNED_PDF_MAX_IMAGES` /
  `_SCANNED_PDF_MAX_SECONDS`). The image and time budgets are checked per
  embedded image, not only per page — a single page can carry hundreds of
  rasters, and a per-page check would let that one page run unbounded.

### GitHub repository import

`POST /admin/v1/workspaces/{slug}/rag-documents/repo` (body `{url, ref?}`, 202 like
its three siblings) imports **one public GitHub repository as one catalog row per
file**. `url` accepts `owner/repo`, `github.com/owner/repo`, the full https URL, or
a `/tree/<branch>` deep link; `ref` (branch, tag, or sha) overrides it.

One row per file, rather than one per repository, is the load-bearing decision:

- **Provenance.** An answer grounded in the repo names the *file* it came from, and
  an explicit `@`-reference can pin one file (`retrieve_by_document`), which a
  single whole-repo document could not express.
- **Re-import is an update, for free.** The existing `(workspace_id, sha)` identity
  already makes re-adding identical content a replace, so an unchanged file keeps
  its row, its id, and its chunks. A changed file hashes differently and becomes a
  new row; `rag_admin_service.begin_repo` then prunes any row in the group whose sha
  is no longer in the repo, through the ordinary `delete_document` (Chroma chunks and
  grounded cache entries included). Pruning runs *after* the new rows exist, so a
  failed fetch leaves the previous import intact.

Rows imported together share a nullable **`group_key`** (`github:{owner}/{repo}`,
migration `a7b8c9d0e1f2`), which is what the dashboard collapses into one expandable
entry and what the prune above queries by. Every other source leaves it null.

**File selection** lives entirely in `rag_ingest._repo_skip_reason` and the constants
above it — do not scatter new rules into the read loop. Defaults:

| Rule | Value |
|---|---|
| Tarball ceiling | 50 MB compressed (`_REPO_TARBALL_MAX_BYTES`) — a backstop, not the real limit |
| Per-file ceiling | 256 KB (`_REPO_MAX_FILE_BYTES`) |
| Files per import | 400 (`_REPO_MAX_FILES`) |
| Minimum file size | 50 normalised characters (`_REPO_MIN_FILE_CHARS`) |
| Excluded directories | `.git`, `.github`, `node_modules`, `vendor`, `third_party`, `dist`, `build`, `out`, `target`, `.next`, `__pycache__`, `.venv`, `.tox`, caches, IDE/VCS metadata |
| Excluded files | lockfiles (`package-lock.json`, `uv.lock`, `Cargo.lock`, `go.sum`, …), binaries/media/archives/fonts/model weights, `.ipynb`, `.map`, minified bundles |
| Also dropped | anything that is not a strict UTF-8 decode, and the second of two byte-identical files (they share one sha, so the second would silently replace the first's row) |

Everything else — source, Markdown, plain text — is indexed, labelled `markdown`,
`text`, or `code`, titled by its repo-relative path, with `source_ref` set to the
file's GitHub blob URL at the resolved ref.

**Public repositories only.** An unauthenticated fetch of a private repo gets a
GitHub 404 (GitHub will not confirm it exists), so the one message names both
possibilities and says plainly that private repositories need a stored token that
DejaQ does not have. Redirect hops are re-checked against the same private-address
rules `from_url` uses.

**Not built, deliberately:** private repositories, and any mechanism that keeps an
import in sync with the repo (webhook, poll, scheduled re-import). Re-importing is a
manual operator action.

#### Measured retrieval quality (what this is good and bad at)

Measured end to end against two real repositories
(`RichardLitt/standard-readme`, 13 files/45 chunks; `psf/requests`, 94 files/840
chunks), asking through `/rag-suggest` + `/v1/responses`:

- **Markdown answers well.** "What sections are required in a standard readme, and
  in what order?" retrieved `spec.md` chunks 0/1/2 and answered correctly.
- **Code sometimes works and sometimes does not, and the failure mode is chunking.**
  `chunk_text` splits on sentence/paragraph boundaries — prose logic — so it cuts
  through the middle of a function. In `src/requests/utils.py`, `super_len` is split
  across chunks 5–8; chunk 5 also carries the tail of `proxy_bypass` and all of
  `dict_to_sequence`. Asked what `super_len` returns for a partially-read file, top-4
  retrieval returned chunks 5, 6, 44 and 7 — the `return max(0, total_length -
  current_position)` line is in chunk **8**, and the answer was wrong. The same repo
  answered a `rebuild_auth` question correctly, because that function happened to fit
  inside one chunk.
- **It does not invent answers.** "How much does the requests library's commercial
  enterprise support plan cost?" was answered "the provided workspace knowledge does
  not contain information about…".
- **The suggestion picks the wrong file for code questions.** `/rag-suggest` chose
  `tests/test_requests.py` and `tests/test_utils.py` over the source modules for both
  code questions — test files restate the API in prose-like assertions and embed
  closer to a natural-language question than an implementation does.

A code-aware chunker (split on top-level `def`/`class`, keep a function whole) is the
obvious next step and is deliberately **not** built here: measure it against this
same battery before adding it.

---

## Configuration

All settings live in `server/app/config.py` (env-overridable):

| Variable | Default | Meaning |
|---|---|---|
| `DEJAQ_RAG_ENABLED` | `true` | Master switch for the whole layer. Off means no retrieval of ANY kind (explicit `@`-reference or a suggestion) **and** no ingestion: every add path (dashboard, API, CLI) is refused at `rag_admin_service`, so knowledge cannot accumulate that nothing will ever read. Listing and deleting stay available so existing documents can be cleaned up |
| `DEJAQ_RAG_SUGGEST_ENABLED` | `true` | Whether the composer may offer a visible, dismissible document suggestion (`POST /rag-suggest`). Independent of `DEJAQ_RAG_ENABLED` above (both gate suggestions; either off is enough) and unrelated to the removed `DEJAQ_RAG_AUTO_RETRIEVE` flag — a suggestion never grounds anything by itself, so defaulting it on carries none of that flag's risk. See "Suggested reference" above |
| `DEJAQ_RAG_SUGGEST_MAX_DISTANCE` | `0.45` | Cosine-distance ceiling to OFFER a suggestion — looser than `DEJAQ_RAG_MAX_DISTANCE` on purpose, since a wrong suggestion costs a dismiss, not a misleading answer. Measured tradeoff at this value: `evals/rag_suggest/`, `firstmate/data/dejaq-rag-suggest/report.md` |
| `DEJAQ_RAG_TOP_K` | `4` | How many chunks to retrieve per query for an explicit `@`-reference (a suggestion always asks for 1 — it only needs to name the single best guess) |
| `DEJAQ_RAG_MAX_DISTANCE` | `0.35` | Cosine-distance ceiling for a `retrieve()`-based grounding call. Not wired to any current call site — the explicit `@`-reference path (`retrieve_by_document`) has no distance gate at all (the document is already pinned by id) and the suggestion path uses its own, looser `DEJAQ_RAG_SUGGEST_MAX_DISTANCE`. Kept, per the retrieval machinery it belongs to, as the constant a future re-introduction of distance-gated grounding would use |
| `DEJAQ_RAG_EXHAUSTIVE_MAX_CHUNKS` | `20,000` | Below this many total chunks in a workspace's collection, `retrieve()` scans exhaustively (exact cosine, via a NumPy matmul) instead of Chroma's approximate HNSW index — see below |
| `DEJAQ_RAG_CHUNK_CHARS` | `1000` | Chunk window size when splitting a document |
| `DEJAQ_RAG_CHUNK_OVERLAP` | `150` | Overlap between adjacent chunks |
| `DEJAQ_RAG_MAX_CONTEXT_CHARS` | `6000` | Cap on total injected context per prompt (protects the local model's context budget) |
| `DEJAQ_RAG_FORCE_EXTERNAL` | `false` | When set, grounded requests route to the external provider regardless of the difficulty classifier |
| `DEJAQ_MAX_ATTACHMENT_BYTES` | `10 MB` | Upload size cap (shared with image/file attachments) |

### Tuning `DEJAQ_RAG_MAX_DISTANCE`

The default `0.35` is deliberately **conservative**, because the failure modes are
asymmetric: if nothing is retrieved the model simply answers from its own
knowledge (graceful), but if the *wrong* chunk is injected the model can be
confidently misled — so a miss is cheaper than a bad grounding.

Measured BGE cosine distances (short one-sentence facts) give a feel for where to
set it:

| Query vs. stored fact | Distance |
|---|---|
| "what's the internet password" vs. "the office WiFi password is …" | ~0.23 |
| "can I get my money back after 3 weeks" vs. "refunds are allowed within 30 days …" | ~0.31 |
| "where do I leave my car" vs. "employee parking is in the underground lot …" | ~0.45 |
| unrelated topic (e.g. baking bread) vs. any office fact | ≥ ~0.55 |

So `0.35` catches direct paraphrases but **misses looser ones** (the parking
example above). Raise it toward `0.45–0.50` for higher recall on paraphrased
questions, accepting more risk of injecting a loosely-related chunk; keep it low
if wrong groundings are unacceptable. There is no swept, corpus-derived value here
(unlike the image gate) — it is a per-deployment recall/precision dial.

This table is exactly why `DEJAQ_RAG_SUGGEST_MAX_DISTANCE` (a visible, dismissible
*suggestion*, not a silent grounding) can sit at the looser end of this same dial —
see `evals/rag_suggest/` for the corpus-measured appearance/accuracy/noise numbers
at the shipped default, rather than the illustrative examples above.

### `DEJAQ_RAG_EXHAUSTIVE_MAX_CHUNKS` and why retrieval isn't purely approximate

Chroma's HNSW index can fail to return a chunk that is *objectively* the best
match — not a threshold problem, a search-recall problem. Measured on a
5-document, ~4,943-chunk synthetic knowledge base (one document ~80% of all
chunks, matching how a curated KB accumulates over time): the approximate
search found the correct document for only 2/15 realistic questions, even
though an exhaustive query proved 5 of those misses had a true match well
inside the distance gate (crowded out by the large document's chunks
dominating the graph — even `n_results=2000` of 5,136 chunks in a very similar
case did not recover it). Switching to an exact scan below
`RAG_EXHAUSTIVE_MAX_CHUNKS` chunks fixed every crowd-out miss (recall@1 2/15 →
5/15, all remaining misses genuinely outside the distance gate) with 0/5 false
positives before and after, at 635ms p50 / 908ms p95 — well under a second at
this scale. The `20,000` default is a conservative, deliberately *untuned*
ceiling — real latency scaling past ~5k chunks hasn't been measured; re-measure
(`evals/rag_recall/measure_latency.py` has a starting point) before trusting it
at real production scale, the same way `DEJAQ_RAG_MAX_DISTANCE` needs tuning
against real data.

A single-document, `where`-filtered query (what explicit document reference
uses) does **not** have this problem — measured 14/14 (100%) recall finding
the true best chunk within a 4,030-chunk document embedded in the same
collection, at ~11ms. Crowd-out is a whole-collection phenomenon; do not add
exhaustive-scan machinery to the filtered path, it isn't needed there.

---

## Isolation & safety

- **Separate collection per workspace** (`{slug}__rag_kb`) — one workspace's knowledge
  is never visible to another, and it is never mixed into the Q→A cache.
- **Never auto-evicted** — the score-floor eviction beat task skips `__rag_kb`
  collections, so curated knowledge is not removed by inactivity or 👎 feedback.
- **Injected as untrusted DATA** — retrieved text is fenced and explicitly labelled
  as data to answer *from*, never instructions to follow (a document containing
  "ignore your instructions…" is treated as content). Mirrors the attachment
  inlining rule.
- **Deleting a workspace** drops its `rag_documents` rows (FK cascade) *and* its
  `{slug}__rag_kb` Chroma collection (`admin_service.delete_workspace`).
- **Access is checked before any ingest work runs.** All ingest endpoints are on the
  loopback-only management API; on top of that, `rag_admin_service` verifies the
  caller has access to the workspace *before* it fetches a URL or extracts a file,
  so an authenticated admin without access to a given workspace cannot make the
  server fetch a URL on their behalf.
- **URL ingestion cannot reach the server's own network.** `rag_ingest.from_url`
  resolves the host and refuses anything that is not a globally routable address —
  loopback, RFC1918 private ranges, link-local (including the `169.254.169.254`
  cloud-metadata endpoint), CGNAT and the unspecified address. A hostname is
  refused if *any* address it resolves to is non-public. Redirects are followed by
  hand (max 5 hops) so every hop is re-checked, because a public URL can 302 into
  an internal one. Not covered: DNS rebinding, where the name resolves to a public
  address for the check and an internal one for the connect — closing that needs a
  pinned-IP transport rather than a stricter rule.

---

## Known limitation (accepted for v1)

An answer produced with RAG grounding is stored in the **Q→A cache**. If an admin
later edits or deletes the underlying knowledge, previously cached answers can go
stale until normal feedback/eviction ages them out. A follow-up could purge Q→A
entries derived from a changed knowledge document; that is out of scope for the
initial layer.

---

## Where the code lives

| Concern | File |
|---|---|
| Catalog model / migration / repo | `server/app/db/models/rag_document.py`, `server/alembic/versions/e2f3a4b5c6d7_add_rag_documents.py`, `server/app/db/rag_document_repo.py` |
| Vector logic (chunk / index / retrieve / delete) | `server/app/services/rag_service.py` |
| Text extraction (all four sources) | `server/app/services/rag_ingest.py` (+ `file_text.py`, `image_text.ocr_plaintext`) |
| Admin orchestration (auth + catalog + vectors) | `server/app/services/rag_admin_service.py` |
| Management API | `server/app/routers/admin/rag_documents.py`, `server/app/schemas/admin/rag_documents.py` |
| Pipeline retrieval + injection (explicit reference only) | `server/app/routers/openai_compat.py` (`_query_with_rag_context`, retrieval step in `run_chat_pipeline`) |
| `GET /rag-documents`, `POST /rag-suggest` (chat-app data plane) | `server/app/routers/rag_documents_public.py` |
| Chat-app `@` picker + suggestion chip | `chat/app/components/MessageInput.tsx`, `chat/app/components/chat-api.ts` (`fetchRagDocuments`, `fetchRagSuggestion`), `chat/app/api/rag-documents/route.ts`, `chat/app/api/rag-suggest/route.ts` |
| Eviction guard | `server/app/tasks/cache_tasks.py` |
| CLI | `server/cli/admin.py` (`rag` group) |
| Dashboard UI | `dashboard/app/dashboard/rag/`, `dashboard/app/actions/rag.ts`, `dashboard/lib/api.ts` (`apiUpload`) |
| Config | `server/app/config.py` (`DEJAQ_RAG_*`) |
| Tests | `server/tests/test_rag_*.py` |
| Suggestion measurement (appearance / accuracy / noise) | `evals/rag_suggest/` (reuses the corpus in `evals/rag_recall/corpus.py`) |
