# AGENTS.md

## Global Rules

- Only the user may speak Hebrew. Agents must always respond in English unless the user explicitly asks for something else.

## Project Guidance

Use `CLAUDE.md` as the canonical project guide for architecture, commands, environment variables, endpoints, coding conventions, and current status. Keep this file intentionally small so agent-specific rules do not drift from the main project documentation.

## Running the test suite

From `server/`, `uv run --group test pytest`. Three things bite on a fresh worktree and are not visible from the test files:

- Run `uv run alembic upgrade head` first. Without it ~39 tests fail with `no such table: workspaces`.
- The suite reads the repo's real `server/dejaq.db`, so leftover local workspaces change results - a workspace with id 1 (`demo`) makes routing tests take the configured-LLM path instead of the defaults branch they assert. Start from a freshly migrated DB when tests fail in ways the diff cannot explain.
- `uv run` without `--group test` re-syncs the venv to the *default* dependency groups and silently uninstalls pytest (and anything else test-only) - if a bare `uv run python ...` command run in between test runs leaves `pytest: command not found`, re-run `uv sync --group test` rather than debugging the venv.
- `pyproject.toml`'s `addopts` always renders a self-contained `pytest-html` report; over the full ~920-test suite this environment's `pytest-html` install crashes at `pytest_sessionfinish` with `jinja2.exceptions.TemplateNotFound: 'app.js'` - the tests themselves already ran and the pass/fail counts are real, only the HTML report generation fails. Run with `-o addopts=""` (dropping `-v` too, so add it back if wanted) to skip the report and get a clean exit code; smaller/filtered runs do not hit this.

The repo-root `.no-mistakes.yaml` pins the no-mistakes pipeline's Test step to `-m no_model` (378 of 755 tests - the rest need an Ollama model or in-process torch model not available in the pipeline sandbox) plus `chat/`'s vitest suite; see that file's comments for the full reasoning, including that `commands:` there only takes effect once it reaches `master` (no-mistakes reads `commands` from the default-branch copy of the file, not the pushed branch).

## Product stance: desktop-only

Neither the dashboard nor the chat app supports narrow viewports, by design (captain decision, 2026-08-10). The dashboard still stands exactly as decided then: its sidebar has no responsive breakpoint, and adding one needs a new product decision.

The chat app was scoped out of that stance by the stage-3 redesign (captain decision, 2026-08-19). Its sidebar now collapses to a ~56px icon rail below 1100px (`SIDEBAR_COLLAPSE_WIDTH` in `chat/app/components/ConversationSidebar.tsx`) and the response detail panel becomes an overlay drawer below 1024px. The rule that survives is the reason behind both: a tight window gives up sidebar width, never the reading column's 704px measure. Do not remove the chat's collapse behaviour, and do not add a layout that shrinks or clips the reading column instead.

## Chat styling

The chat owns its own token layer (`chat/app/tokens.css`, light + dark) and must not import the dashboard's `design-system.css` again. Every component reads those tokens by name from inline styles, so change a token's value, never its name. Read that file's header, and the one on `chat/app/globals.css`, before changing anything about how the chat looks.

`--accent` has exactly two sanctioned uses: the cache route (stage 2 of the chat redesign) and the pinned-attachment state in `chat/app/components/MessageInput.tsx`. Nothing else - not a button, not a link, not an active row, not any other surface. Use a neutral (`--fg`/`--border-2`/`--bg-3`) or the appropriate route colour instead (`--local` for local, `--blue` for cloud - see `chat/app/components/provenance.ts`). The same two-use wording sits on the token itself in `chat/app/tokens.css`; change both together or they drift. `chat/app/components/RouteMarker.tsx`, `ResponseDetail.tsx`, and `TypingIndicator.tsx` are the provenance rail, the response detail panel, and the wait strip; read those before touching per-message routing UI.

## Promotion conflicts (staging -> master)

Master has received both real merge commits and squash merges from staging (e.g. `ffb690b` is a squash, `7b9274b` a real merge). When a promotion is squashed, the same content ends up on both branches under different commit identities, so the next `staging` -> `master` PR shows false conflicts on any file touched since that squashed promotion. Fix by back-merging master into staging (never the reverse, never squash/rebase staging): for each conflict, diff `origin/master...origin/staging` on that file first to confirm staging already carries everything master has (it should, since the squash commit is just staging's own prior commits) - staging's side wins. Verify with `git diff origin/staging HEAD` on the resulting merge commit: an empty diff confirms nothing was lost. Only stop and escalate if master's side contains content genuinely absent from staging - that means a change landed on master and never made it back.

## SQLite batch migrations can silently drop what they don't explicitly touch

Inside `op.batch_alter_table(..., recreate="always")` SQLite rebuilds the table, and a constraint the batch does not explicitly re-declare can vanish from the rebuilt table rather than carry over; one it never touches can also keep a stale pre-rename name. Neither drift is caught by any test, because `server/tests/conftest.py` builds test databases with `Base.metadata.create_all()` - constraints read from the ORM model, never from replayed migration history. So the model source is not evidence of what is on disk: before writing a migration that touches an already-rebuilt table, run `alembic upgrade head` against a fresh SQLite file and read `sqlite_master.sql`. Worked example (a unique constraint that silently stopped existing and a CHECK constraint still named `ck_org_*` long after the org -> workspace rename), with the recovery path for the duplicate rows the missing constraint let through: `server/alembic/versions/e5f6a7b8c9d0_drop_provider_check_constraint.py`, regression test `server/tests/test_credential_unique_migration.py`.

## Running the full stack for a visual check

`./start.sh --stack=all --mode=local` needs `--logs=requests` (or `DEJAQ_START_LOGS=requests`) when run non-interactively, or it blocks on a TTY prompt and exits. On a fresh worktree it also needs, once: `chat/` and `dashboard/` each have their own `node_modules` (`npm install` in both - `--stack=all` starts both), a `chat/.env.local` with `DEJAQ_API_KEY` (mint one with `dejaq-admin key generate --workspace <slug>`, and the workspace/department first with `dejaq-admin workspace create` / `dejaq-admin dept create` - a fresh `server/dejaq.db` has neither), and a clean `server/dejaq.db` (delete the gitignored file and let migrations recreate it if a half-finished prior run leaves tables without an `alembic_version` row - migration then fails with "table already exists").

`chrome-devtools-axi` runs against a machine-wide shared browser bridge whose own process cwd is unrelated to any worktree. Its `screenshot`/`take_screenshot` silently no-ops outside the bridge's configured MCP "workspace roots" (the CLI still prints a success line and the resolved path you asked for) - `/tmp` is always allowed. Screenshot to `/tmp/<name>.png` and `cp` into the worktree afterward; do not trust a `screenshot` success message alone without checking the file landed.

## Testing the LiteLLM transport against a fake server

`tests/_fake_llm_server.py`'s `FakeLLMServer` records real wire bytes; point LiteLLM at it per provider with an env var, not a client monkeypatch (that seam does not exist under LiteLLM): `OPENAI_API_BASE` (openai/xai/deepseek all resolve through the openai-compatible path), `GROQ_API_BASE`, `ANTHROPIC_API_BASE`, `GEMINI_API_BASE` (not `GOOGLE_API_BASE` - `google` is not a real LiteLLM provider key, see `litellm_transport._LITELLM_PROVIDER_KEYS`). Groq's response transformer reads `service_tier` off the reply unconditionally (`litellm/llms/groq/chat/transformation.py`); a scripted Groq response body without it raises `AttributeError` inside LiteLLM, surfaced as a generic `APIConnectionError` with no hint it's a fixture problem, not a transport bug.

## Provider resolution needs a legacy fallback, not just the stored column

`workspace_llm_configs.external_provider` is null for more than "an old unmigrated row": the server-wide `DEJAQ_EXTERNAL_MODEL` env default has no database row at all, so it can never carry a stored provider. Any call site resolving a provider from `(external_model, external_provider)` (`openai_compat.py`, `escalation.py`, `routers/admin/test_provider.py`) must fall back to `llm_config_service.resolve_provider_for_model` when the stored value is null, not just 422 - that env-default path is live and tested (`tests/test_unconfigured_external_model.py`). That function tries a frozen exact table first (`_LEGACY_BARE_MODEL_PROVIDERS`, all that survives of the deleted `provider_registry.PROVIDERS` after A1c - a bare model name still needs an EXACT lookup, never a guess: LiteLLM's own bare-name resolution is provably wrong for several of DejaQ's defaults, e.g. every `gemini-*` id resolves to `vertex_ai`, not `gemini`) and only then LiteLLM's own qualified-name resolution. Do not confuse this with the deleted `provider_inference.py` name-prefix guess (`gemini-` -> `google`, etc.) - that guess is gone for good (migration `f7a8b9c0d1e2` is now the only place it ever runs, once, at backfill time); a call site should never resurrect it.

## Two provider-key maps exist on purpose, until A1's namespace unification deletes both

`litellm_transport._LITELLM_PROVIDER_KEYS` (DejaQ -> LiteLLM: `google`->`gemini`, `together`->`together_ai`, `fireworks`->`fireworks_ai`) and `llm_config_service._DEJAQ_PROVIDER_KEYS` (its inverse) are two views of the same 3-entry fact, not independent drift. `external_provider` stays in DejaQ's own provider namespace (it is still the credential-lookup key `get_workspace_provider_key` reads directly) until migration stage A1's provider-key-namespace unification (plan `dejaq-litellm-migration-plan-v2/report.md` section 2.11, "M7") moves `workspace_provider_credentials.provider` onto LiteLLM's own names and deletes both maps together. Do not "simplify" one without the other, and do not add a third copy - if a new call site needs this translation, import `_litellm_key`/`_LITELLM_PROVIDER_KEYS` from `litellm_providers.litellm_transport` rather than hand-rolling it again.

## litellm import is confined by a guardrail test

`tests/test_litellm_single_import.py::test_litellm_is_imported_in_exactly_the_allowed_modules` fails the build the moment a new module does `import litellm` - it is not a lint suggestion. Route new litellm-touching code through one of the already-allowed modules (`llm_providers/_litellm_config.py`, `llm_providers/litellm_transport.py`, `services/model_catalog.py`) instead of adding a new importer; if a stage genuinely needs a new one, add it to that test's `_ALLOWED_IMPORTERS` in the same commit; the migration plan's exit-seam argument (§4) is why this exists at all.

## Ollama's /api/tags capabilities are wrong; /api/show is correct

Both endpoints report a per-model `capabilities` array, but they disagree, and `/api/tags` is the one already cached (`ollama_catalog.list_available_models`, backing the Pipeline model pickers). Measured live: `/api/tags` omits `"vision"` for `gemma4:e4b` even though the model demonstrably reads images and `/api/show` reports it correctly. Any future capability check (routing, gating, display) must call `/api/show` per model - see `ollama_catalog.supports_vision` and its call-site comment. Do not "optimise" a capability check back onto the already-cached `/api/tags` data.

## The HARD/EASY judge mechanism is deterministic (fixed on `fm/dejaq-refresh-corrections`)

`_judge_hard_content` (`openai_compat.py`, shared by the attachment hard-content judge and the Hebrew routing judge) used to hardcode `temperature=0.7` on `LLMRouterService.generate_local_response`, and the same question could flip HARD/EASY across identical repeated calls (5 draws: `['EASY','HARD','HARD','EASY','HARD']`) - see `dejaq-model-refresh-implement/report.md`. Fixed by passing `temperature=0.0` explicitly at this call site (both `generate_local_response` and `_completion_request` gained the parameter; ordinary answer generation still defaults to `0.7`). Measured after the fix: 0/80 flips across 5 repeated draws each. Do not reintroduce sampling on a routing-decision judge call.

## Only two Groq gotchas exist so far, both bit on first real use

The first real (non-credential-boundary) exercise of external routing, against `groq/openai/gpt-oss-120b`, surfaced two things no text-only test had caught (`dejaq-preflight-acceptance/report.md`):
- **Provider resolution**: the *unqualified* id `openai/gpt-oss-120b` resolves through `model_catalog.resolve_provider` (LiteLLM) to provider `openai`, not `groq` - this exact trap is already documented in `llm_config_service.py`'s `_LEGACY_BARE_MODEL_PROVIDERS` comment, but the admin `PUT .../llm-config` write path does not consult that table, only LiteLLM's own (wrong, for this id) resolution. Always set `external_model` to the fully-qualified `groq/openai/gpt-oss-120b`, never the bare id.
- **No vision/document capability**: `gpt-oss-120b` is text-only. Fixed on `fm/dejaq-acceptance-fixes` (`dejaq-acceptance-fixes/report.md`, defect #3): `litellm_transport._build_messages` now checks `litellm.get_model_info(model)["supports_vision"/"supports_pdf_input"]` before building an image/file content part and raises `ExternalAttachmentUnsupportedError` (surfaced as a clear 422) instead of letting the provider 400 raw. Only blocks when LiteLLM's catalog *affirmatively* confirms incapability - a model LiteLLM has no entry for at all (several real Anthropic/Gemini ids, verified live) is never blocked, so an uncatalogued text-only model still reaches the provider and 400s raw. A durable fix (a vision-capable external model actually answering attachment traffic) needs a product decision - a second per-workspace `external_model` for attachments, or capability-aware fallback - not made in that task.

## Groq's vision-capable model still can't take a native PDF, and needs `reasoning_format` set explicitly

`groq/qwen/qwen3.6-27b` (the vision-capable replacement for `gpt-oss-120b`, chosen in `dejaq-vision-provider-scout/report.md`) fixes the image gap that section documents but has its own: LiteLLM's catalog reports `supports_pdf_input: None` for it, so a hard/unreadable PDF that must route external hits the same `ExternalAttachmentUnsupportedError` 422 gpt-oss-120b hit for images - confirmed live, `dejaq-400-reality-test`. DOCX/Markdown/text/code attachments are unaffected (inlined as text, never a native file part, per CLAUDE.md's file-gate description) - use those, not PDF, to test the hard-attachment-forces-external path on a model with no PDF support. Separately, this model emits literal `<think>...</think>` unless `reasoning_format="hidden"` is sent - LiteLLM has no first-class param for it (not in `get_supported_openai_params`), so it must go through as `extra_body` (`litellm_transport.py`, both `generate_response` and `stream_response`, gated to `self._provider == "groq"`); confirmed reaching the wire with `tests/test_provider_routing_litellm.py::test_groq_requests_hidden_reasoning_format_so_think_tags_dont_leak`. Hidden reasoning still burns real output-token budget before the visible answer starts - a hard-content call with `max_output_tokens` set too low (300) came back completed-empty, all budget spent on the hidden scratchpad; do not cap external calls tightly on this model.

**Update, `dejaq-200-test-fixes`:** an unreadable-locally PDF forced onto a PDF-incapable external model no longer dead-ends in a bare 422. `file_text.py` now rescues a scanned page's own embedded raster image via pypdf's `page.images` (no rasterization engine needed - re-encoded to PNG through Pillow), and `openai_compat.py` routes it to the LOCAL vision model instead - `_external_pdf_capable` (backed by the new `litellm_transport.external_supports_pdf()`) gates this so a workspace with a genuinely PDF-capable external model keeps its richer native-document-part path unchanged. A PDF pypdf can't even parse (genuinely corrupt) has no pixels to rescue either, so it gets an honest local explanation instead. Both paths verified live against the real `gemma4:e4b` local model, not just mocked. See `tests/test_local_pdf_vision_fallback.py`.

## Deleting/recreating a live ChromaDB collection without restarting its consumers poisons every later store and read

`uvicorn` and the Celery worker each hold their own long-lived `chromadb.HttpClient` collection reference, resolved once and cached by collection *id*, not name. Calling `delete_collection` + `get_or_create_collection` on the same name (e.g. to wipe smoke-test entries mid-task) leaves both processes pointing at a collection id ChromaDB no longer has - every subsequent read and background store then fails with `chromadb.errors.NotFoundError`, silently as far as the client is concerned (the HTTP request to DejaQ still returns 200; only the store/lookup underneath is broken). This is a sharper case of the stale-reference class `dejaq-acceptance-retest-2/report.md` already documents for a full ChromaDB *server* restart - it also happens from a same-process collection delete with no server restart at all. Caught live on `dejaq-400-reality-test`: 173 calls, zero real cache hits, before the mistake was found via the Celery log. Fix: never delete/recreate a collection while `uvicorn`/Celery are running against it - restart both after, and verify with a real store-then-hit round trip before trusting any further result.

## Attachments are classified for difficulty like text, not always routed external

CLAUDE.md's "on a miss, image/file requests bypass the difficulty classifier and route straight to the external provider" is only true for attachments the local pipeline can't extract usable content from (scanned PDFs, unreadable OCR). Ordinary-difficulty attachment content goes through the same `route = "external" if complexity == "hard" else "local"` decision as plain text (`openai_compat.py`) and answers locally. Measured live on `fm/dejaq-acceptance-retest`: four attachment probes built with easy content (a short note image, a simple multi-page PDF) all answered locally and never touched the external model or its capability gate at all. Test attachment-routing/capability-gate behavior with genuinely hard or unreadable content, not just any attachment.

## A large inlined-text attachment can still 400 raw on the external path — FIXED

`DEJAQ_MAX_ATTACHMENT_BYTES` (10MB) only bounds what DejaQ accepts; it says nothing about the *external provider's* context window once a text/Markdown/code attachment (not PDF - those go as a native document part) is inlined into the prompt. A ~10.48MB text file, just under the byte cap, was judged too large for `local_attachment_max_tokens` and routed external, where Groq rejected the resulting oversized prompt with the same opaque `"...may not be supported"` message the attachment-capability gate (see above) was built to replace for the *modality* case - there was no equivalent check for the *token-budget* case. Fixed on `fm/dejaq-acceptance-fixes-2`: `litellm_transport._build_messages()` now checks LiteLLM's own catalog (`get_model_info(model)["max_input_tokens"]`, the same data source the capability gate uses) whenever a request carries no native image/file part, and raises `ExternalAttachmentTooLargeError` (surfaced as a clear 422 naming the estimated vs. budget token counts) before the request reaches the wire. Same conservative bias as the capability gate: a model LiteLLM has no catalog entry for is never blocked. Verified live against the exact 10.48MB repro (real Groq, `groq/openai/gpt-oss-120b`, budget 131072 tokens): raw 400 → clean 422. See `dejaq-acceptance-fixes-2/report.md`.

## Generic pronoun-only follow-ups can cross-collide between unrelated conversations — enricher fix PARTIAL, embedder swap closes the rest (unmerged)

The enricher's standalone-question rewrite sometimes translates a Hebrew follow-up ("how long does this take?") into a *generic English* standalone question, losing the conversation-specific referent (which dish, which topic); `context_enricher.DEFAULT_SYSTEM_PROMPT`'s "never translate" instruction (`fm/dejaq-acceptance-fixes-2`) reduces but does not eliminate this - re-measured on `fm/dejaq-hebrew-model-swap` with a fresh 6-topic real-enricher sample, 2/6 rewrites still lost the dish name or code-switched to English (one flipped topic entirely: a carbonara follow-up enriched into "...bake a pita bread"). The remaining part of this defect - that even a correctly Hebrew, correctly topic-specific rewrite still collided across unrelated conversations (15/15 pairs at/under band-tier distance under `BAAI/bge-small-en-v1.5`, an English-trained embedder that doesn't separate short templated Hebrew questions) - is closed by the `TEXT_EMBEDDING_MODEL` swap to Qwen3-Embedding-0.6B on `fm/dejaq-hebrew-model-swap` (not yet merged): the same real-enricher-output sweep dropped to 0/15 pairs in-band. See `dejaq-hebrew-model-swap/report.md`.

## Cache validator's residual Hebrew false-rejects are not tied to the validator model

Root-caused on `fm/dejaq-acceptance-fixes-2`, direct answer to "why did staging measure fine and this stack didn't": the `mismatch_hint` mechanism itself is old (present at staging `ee032b1`) and not the regression - a controlled 2x2 (old/new `lexical_match.align()` × `gemma4:e2b`/`granite4.1:3b`) on the same 9 EN + 6 HE paraphrase pairs shows the OLD (unfiltered) hint mechanism paired with `granite4.1:3b` breaks EN to 4/9 (staging's own `gemma4:e2b` + old hint scored 9/9), while the NEW narrowed hint ([[fix1]] on `fm/dejaq-acceptance-fixes`) restores EN to 9/9 on *either* model. So the visible regression was the model swap interacting with the pre-existing broad hint, not the model swap alone - and fix #1 (already merged before this task) is what actually closes it, independent of which validator model is configured. Hebrew's own residual (one pair reproduces stably: `כמה כפיות יש בכף אחת?` / `מה יחס ההמרה מכפית לכף?`, `validator-verdict: invalid`) does not track the model swap either - `granite4.1:3b` scored 6/6 and `gemma4:e2b` 5/6 on the same 6-pair set with the current hint mechanism. Direct diagnosis (asking the model to gloss the Hebrew words it read) caught it mistranslating "כף"/"כפית" (tablespoon/teaspoon) as "palm"/"finger" on one specific short answer phrasing ("יש 3 כפיות בכף אחת") - a real small-model Hebrew-vocabulary gap on that phrasing, not reproducible with a slightly more verbose real-generated answer of the same fact. Not further fixable with a prompt/mechanism change measured here; a stronger Hebrew-capable validator model is the only lever that would move it, and that is a product decision, not made here. See `dejaq-acceptance-fixes-2/report.md`.

## The lexical alignment gate's mismatch-hint can silently vanish on a punctuation-driven tokenizer quirk, and that also produces a validator false-ACCEPT (not just the false-rejects above)

Opposite failure direction from the entry above: `lexical_match.py`'s tokenizer (`_NON_ALNUM`) used to strip the Hebrew geresh (`׳`, and ASCII `'`) to a space like any other punctuation, so a word like `ניז'ר` (Niger) tokenized as TWO words. Against `ניגריה` (Nigeria), that turns a genuine single-word swap into a 1-vs-2 leftover mismatch, which trips the "only hint on a clean 1-vs-1 swap" suppression heuristic ([[fix1]] on `fm/dejaq-acceptance-fixes`, built for broadly-reworded paraphrases) - so the validator got NO hint at all on a real different-country pair and said VALID (`dejaq-400-reality-test`, distance 0.1795, band tier, model `granite4.1:3b`, which was `DEJAQ_VALIDATOR_MODEL_NAME`'s default at the time; the default is `gemma_e2b` again as of 2026-08-26, matching CLAUDE.md's model table). Fixed on `dejaq-200-test-fixes`: keep `'`/`׳` as word-internal characters instead of splitters. Confirmed against the real validator model both ways (VALID before the fix, INVALID with a hint after, same exact pair) and on a built 12-pair EN+HE near-identical-proper-noun sweep (Niger/Nigeria, Austria/Australia, Iran/Iraq, Slovakia/Slovenia, Mauritania/Mauritius, Dominica/Dominican Republic): 11/12 siblings correctly rejected post-fix, 8/8 genuine paraphrases still correctly accepted. The one residual miss (Dominica/Dominican Republic) is a genuine multi-word swap, not this tokenizer bug, and is unfixed - see `dejaq-200-test-fixes/report.md`.

## The validator's 300-pair eval set does not predict referential follow-ups; run both corpora

`evals/validator` has two populations and they rank models differently. The original 300 pairs
(`dataset/pairs*.json` minus the follow-up file) are standalone questions; `pairs_follow_up_fragment.json`
(112 pairs) is referential fragments - "what's the difference?", "how so?", "and the other one?" - which
is what the validator actually receives, because `openai_compat.py` passes the raw `user_query`, not the
enriched question. Measured 2026-08-26 through the shipped `ValidatorService`: `gemma4:e4b` scores
300/300 on the old set and 82/112 (73.2%) on the new one; `granite4.1:3b` 266/300 and the same 82/112;
`gemma4:e2b` 281/300 and 96/112 (85.7%). The correlation is inverted, so a validator decision made on the
300-pair set alone will keep picking the wrong model - that is how `granite4.1:3b` shipped as the default
on 2026-08-21 with no config in `evals/validator/configs/` at all. `server/tests/test_validator_eval_coverage.py`
now fails if `VALIDATOR_MODEL_NAME` names a model the harness cannot run.

Two harness facts that are not visible from the files: a config with an `"ollama_model"` key runs the real
`app.services.validator.ValidatorService` against live Ollama (so it inherits production's prompt, few-shots
and 400-word answer cap, and cannot drift), and it must therefore be run from the **server** venv -
`cd evals/validator && ../../server/.venv/bin/python -m harness.runner --all-datasets`. The older GGUF
configs are disabled: each carries its own copy of a system prompt that had drifted from the shipped one.

## Measuring the real cache-hit path needs alias learning off, or the second request is not a hit of the same kind

A validated band hit stores the probe's phrasing as an alias (`DEJAQ_CACHE_ALIAS_ENABLED`), so repeating a
probe to collect samples turns it into a *trusted* hit that skips the validator entirely - measured 40-64 ms
instead of ~1,100 ms, which reads as a spectacular result and is really a different code path. Set
`DEJAQ_CACHE_ALIAS_ENABLED=false` for the run. Two more knobs matter: `DEJAQ_CACHE_TRUST_DISTANCE=0.0` and
`DEJAQ_VALIDATOR_SKIP_DISTANCE=0.0` force every hit through the validator, otherwise close paraphrases skip
it. Read the per-step numbers off the server's own `done cache=hit ... steps=...validate:Xms adjust:Yms` log
line rather than the client's wall clock: `adjust()` dominates the total and is noisy enough (±100 ms
between identical runs) to swamp the step being measured.

## Local dev stack gotchas: ChromaDB under a sandboxed shell, and Qwen3 tags ignoring `think:false`

A `chroma run` process started from a sandboxed shell (Claude Code's default Bash tool) can bind its port and answer reads, but every write fails with `chromadb.errors.InternalError: ... attempt to write a readonly database` (SQLite's WAL/mmap layer is blocked, not the file permissions - `touch`/`ls` on the same directory work fine). Start `chroma run` with the sandbox disabled for that one command. Separately: this machine's pulled `qwen3:*` Ollama tags (unlike `gemma4:*`) do not honor the `"think": false` request field or a `/no_think` prompt suffix - they always emit a long reasoning preamble before the real answer, which breaks any caller expecting a short, strictly-parsed reply within a small `max_tokens` (the cache validator, the attachment hard-content judge). Do not point either role at a `qwen3:*` tag without first confirming `think:false` actually suppresses reasoning on the exact Ollama build in use.

## Routing runs off the LaBSE classifier now; the old NVIDIA one is in the tree but not loaded by default

`dejaq-classifier-cutover` (stacked on `dejaq-classifier-wire-in`) cut the `classify` step over from `ClassifierService` (NVIDIA DeBERTa) to `LabseClassifierService` (LaBSE + `LogisticRegression`, `app/services/labse_classifier.py`) for every language, no per-language branching - see `DEJAQ_LOAD_LABSE_CLASSIFIER`/`DEJAQ_LOAD_LEGACY_CLASSIFIER`/`DEJAQ_LABSE_CLASSIFIER_THRESHOLD` in CLAUDE.md. This is what closes the Hebrew regression `dejaq-classifier-wire-in` opened (Hebrew has no dedicated judge - see below - so it rode the same classify step as every language, and the old classifier measured 0/44 hard-Hebrew caught): live-measured through the real server, `הוכח שיש אינסוף מספרים ראשוניים` (prove there are infinitely many primes) now scores hard at 0.7522 and routes external, where it used to score easy at 0.1293 and get missed. `ClassifierService` and its model stay in the tree unmodified, gated behind `DEJAQ_LOAD_LEGACY_CLASSIFIER` (default `false` on this branch) rather than deleted, so `staging` (which still routes off it) loses nothing when this branch merges. Matched A/B on the same process (`vmmap -summary <pid> | grep "Physical footprint"` - `ps` RSS is unreliable for a torch/MPS process, see below): legacy classifier not loaded measured 2.7GB at startup / 4.0GB warmed; loaded measured 3.2GB / 4.5GB - about +0.5GB for the classifier that no longer has a job, so not loading it is a real, unconditional savings, not just memory-neutral.

The cutover initially left `LabseClassifierService.predict_complexity()` deciding easy/hard itself against the global `DEJAQ_LABSE_CLASSIFIER_THRESHOLD`, so a workspace's own `routing_threshold` (dashboard-writable, loaded into `EffectiveLlmConfig`) was carried around but never consulted - changing it on the site did nothing (`fm/dejaq-threshold-wiring`). Fixed: `openai_compat.py`'s classify step now recomputes `complexity` from the classifier's returned `score` against `llm_config.routing_threshold` (still falling back to `DEJAQ_ROUTING_THRESHOLD` when a workspace has no override, unchanged). `predict_complexity()` itself is untouched and still used directly (with the env threshold) by anything that calls it standalone, e.g. `tests/test_labse_classifier.py`.

## Per-workspace classifier picker: two classifiers, two thresholds, both lazy-loaded

`fm/dejaq-fixtures-and-classifier-picker` adds a per-workspace `classifier_choice` ("legacy"/"labse", default "labse" - unchanged behaviour on upgrade) alongside the existing `*_model` pipeline-config pattern. The two classifiers score on incomparable scales (legacy's own decision boundary is 0.2986, LaBSE's is 0.50 - see `DEJAQ_ROUTING_THRESHOLD`/`DEJAQ_LEGACY_ROUTING_THRESHOLD` in `config.py`), so they were given **separate** threshold columns (`workspace_llm_configs.routing_threshold` for LaBSE, `.legacy_routing_threshold` for legacy) rather than one shared field - `EffectiveLlmConfig.active_routing_threshold` picks the right one by `classifier_choice`. Do not add a third classifier option without giving it its own threshold column the same way; a shared threshold across differently-scaled classifiers is the exact bug this feature exists to prevent (see CLAUDE.md's `LEGACY_ROUTING_THRESHOLD` comment). Neither classifier is loaded eagerly just because the picker exists - `openai_compat._get_legacy_classifier()`/`_get_labse_classifier()` lazy-load on the first request that actually selects that `classifier_choice`, then keep it resident (no unload) - see `LOAD_LEGACY_CLASSIFIER`/`LOAD_LABSE_CLASSIFIER`'s comments for why eager-preload env escape hatches exist separately for staging/dev. **`_get_labse_classifier()` was added in `fm/dejaq-audit-fixes` (2026-08-24) - before that, `_classifier_for_choice("labse")` returned the bare module-level `_labse_classifier`, which stayed `None` under `DEJAQ_LOAD_LABSE_CLASSIFIER=false`, so `None.predict_complexity(...)` raised, was swallowed by the classify step's bare `except Exception`, and every hard query for every workspace on the default `classifier_choice="labse"` silently routed to the weak local model.** If you add a third classifier option, give it a matching `_get_<name>_classifier()` lazy-load getter in the same pass - `test_classifier_picker.py::test_labse_classifier_lazy_loads_when_load_flag_is_false` is the regression test for this exact class of bug; write its sibling for a new classifier rather than skipping it. Also fixed earlier: `app/main.py` used to import `app.routers.openai_compat` (which logs at module-import time - service singletons, model loading) *before* calling `setup_logging()`, so every import-time `logger.info` in the whole app was silently dropped in real server boots (default logging has no handler); `setup_logging()` now runs immediately after `load_dotenv()`, before any router/service import.

## The LaBSE classifier head is rebuildable from the repo - the training corpus is checked in

`server/app/services/model_artifacts/classifier_corpus.jsonl` is the full training corpus for `head_full_labse.joblib` (860 items, 7 languages): 770 base items carried over faithfully from the `dejaq-classifier-probe-multilang` investigation (`ab59099`), plus the 90 `source: "fm/dejaq-classifier-examples"` items (`"provenance": "examples_90"`) that `6500206` added and refit on - conceptual `what is/explain X` -> easy, non-questions -> easy, applied word problems -> hard, 15 each x EN+HE. Rebuild with `cd server && uv run python scripts/rebuild_classifier_head.py` (deterministic - fixed `random_state`, overwrites `head_full_labse.joblib` in place); rebuilding from this exact corpus reproduces the shipped head to within float noise (coefficient max abs diff ~1.4e-6), not byte-identical. `server/tests/test_classifier_eval_set.py` runs a fixed, held-out 38-item set (`server/tests/data/classifier_eval_set.jsonl`, disjoint from the training corpus) against whatever head is on disk, so a bad corpus edit fails CI instead of silently shipping.

## Hebrew's routing judge is gone; no per-language branching remains anywhere in the classify step

`dejaq-classifier-wire-in` removed `HEBREW_ROUTING_ENABLED`/`HEBREW_ROUTING_FRACTION`/`_judge_hebrew_hard` entirely (captain decision - the corpus-scale investigation in `dejaq-classifier-probe-multilang/report.md` showed a trained-on-labelled-Hebrew classifier beats a dedicated judge on every axis). Hebrew falls through the same `classify` step as every other language, with no Hebrew-specific interception, and since `dejaq-classifier-cutover` that step is LaBSE - see above.

## generalize()'s tone-neutralization prompt can destroy fenced code blocks; only that content class was affected

`dejaq-cached-code-loss`: the store-time generalizer (`context_adjuster.generalize()`, Gemma 4 E2B) deterministically (temp=0) rewrote a real multi-block Python answer into pure prose with zero code fences left, passing every existing sanity check (similar length, high content-word overlap from surviving identifier names, same script) - so the corrupted, code-free answer was what every future cache hit served. Not a block-count effect: a single fenced block is destroyed the same way. Measured against 10+ real answers spanning content classes: only fenced code blocks were ever altered in structure by this prompt - inline code, markdown tables, numbered/bulleted lists, and links all survived unchanged. `adjust()` (serve-time, Qwen 1.5B) does not share the defect - its prompt already forbids dropping/merging content, confirmed 8/8 across varied tone queries on code-bearing answers - so the fix (placeholder-swap fenced code blocks out before the generalize() call, splice back byte-for-byte after, fall back to storing the raw answer if a placeholder didn't round-trip) is scoped to `generalize()` only; see `_protect_code_blocks`/`_restore_code_blocks` in `context_adjuster.py` for the mechanism and why. See `dejaq-cached-code-loss/report.md`.

## RAG-grounded cache entries carry provenance and are purged when their document is deleted

A cache entry generated with RAG context stores `rag_document_ids` in its Chroma metadata (comma-joined - one answer can draw on chunks from several documents). `MemoryService.grounded_entry_ids`/`purge_grounded_entries` (mirrors `image_entry_ids`/`purge_image_entries`) find and delete entries grounded in a given document id. This codebase has no in-place document edit - `rag_admin_service._store` only replaces a document when re-added content hashes identical (a true no-op); different content always becomes a new row - so "correcting" a document is delete-then-add, and `rag_admin_service.delete_document` is the one place that hooks the purge (`_purge_grounded_cache_entries`, sweeps every department namespace in the workspace since RAG is workspace-wide but the Q&A cache is per-department). Entries stored before this shipped carry no provenance and cannot be identified this way. Gotcha: SQLite hands a deleted row's rowid to the next insert on a table without `AUTOINCREMENT`, so a corrected document re-added right after deleting the wrong one commonly gets the SAME id back - harmless here since the purge already ran at delete time, but do not assume a RAG document's id is stable proof of "same content." See `dejaq-rag-recall/report.md`.

## Chroma's where-filtered ANN query is reliable within one document; only whole-collection search crowds out small documents

Measured (`evals/rag_recall/`, `dejaq-rag-recall/report.md`): `collection.query()` with an unfiltered embedding search can fail to return an objectively-best chunk (HNSW crowd-out - a large document's chunks starve a smaller, unrelated document's true match even at high `n_results`), but the SAME query with `where={"rag_document_id": id}` reliably found the true best chunk within that one document 14/14 times (100%) even at 4,030 chunks in a ~4,943-chunk collection, at ~11ms p50. Do not build brute-force/exhaustive machinery for a single-document (explicit-reference) retrieval path - it isn't needed. `rag_service.retrieve()` does gate to an exhaustive scan below `RAG_EXHAUSTIVE_MAX_CHUNKS` chunks for the whole-collection (automatic, non-filtered) case, where crowd-out is real - keep the two cases distinct.

## A treehouse worktree pool slot can carry another task's leftover local state

`server/dejaq.db`, `dejaq_stats.db`, `chroma_data/`, `dump.rdb`, and `celerybeat-schedule` are gitignored, so `git status` shows a treehouse worktree as clean even when a previous, unrelated task left real data in them (observed twice: an orphaned `dejaq.db` stamped with an alembic revision absent from this checkout's history, workspaces named for unrelated features). Before trusting local DB/vector state in a treehouse worktree, check for this rather than assuming a fresh checkout - move the stale files aside with a timestamp suffix (never delete) and let migrations/services recreate fresh ones, same as `dejaq-knowledge-base-review/report.md` section 1 already did once.

## Both Next.js dev servers silently fail to hydrate when hit via `127.0.0.1`, not `localhost`

Next 16 blocks `/_next/*` dev-asset requests (HMR, RSC payload chunks, fonts) from an origin outside `allowedDevOrigins`, and its default allowlist does not treat `"127.0.0.1"` as equivalent to `"localhost"`. Hitting either dev server (`chat/` or `dashboard/`) at `http://127.0.0.1:<port>` renders the static shell fine but every client effect silently never runs - no click handler fires, no console error, no React warning - the only clue is a "Blocked cross-origin request to Next.js dev resource" line in the dev server's own terminal log, not the browser. Confirmed reproducible on unmodified code in both apps: the exact same page hydrates fine at `http://localhost:<port>`. Fixed in both `chat/next.config.mjs` and `dashboard/next.config.mjs` - `127.0.0.1` is always in `allowedDevOrigins` now - so this should no longer bite, but if a from-scratch dev server ever looks "connected: false, nothing renders/clicks" again with a clean browser console, check that config and the server's own terminal log before suspecting the app code or the browser-automation tool. Found while browser-testing `fm/dejaq-rag-at-reference` (chat) and `fm/dejaq-fixtures-and-classifier-picker` (dashboard) against a stack addressed by IP.

## RAG document ingestion is now a background job, split fast/slow at `begin_ingest`/`run_ingest`

`rag_admin_service.py` used to run extract→chunk→embed→index synchronously inside the HTTP request (`_store`); a large upload held the request open for minutes with a bare spinner and no way to tell it from a hang (`dejaq-knowledge-base-review/report.md` §2.4, fixed on `fm/dejaq-kb-upload-progress`). Now split into `begin_ingest` (fast: extract, chunk - free, no model call - dedupe by sha, write a `rag_documents` row with `status="processing"` and a real `progress_total`) and `_embed_and_index`/`run_ingest` (slow: embed one chunk at a time via `rag_service.embed_chunks(..., on_progress=...)`, reporting `progress_current` to the row every `total//50`-ish chunks, then index into Chroma and flip to `status="ready"`/`"failed"`). The HTTP router dispatches the slow phase to a new Celery task (`app/tasks/rag_tasks.py::ingest_rag_document_task`, mirroring `tasks/cache_tasks.py`), falling back to FastAPI `BackgroundTasks` calling the exact same `run_ingest` function when Celery is off or its broker is unreachable - same fallback pattern as `openai_compat.py`'s cache-store path. The CLI (`dejaq-admin rag add-*`) and any other synchronous caller use `add_text`/`add_upload`/`add_url`, which just call `begin_ingest` then `_embed_and_index` inline and block - unaffected by any of this.

The Celery task needs its own `soft_time_limit`/`time_limit` override (1800s/1860s) - the app-wide default (`celery_app.py`, 120s/180s) is sized for the cache-store task and is nowhere near enough for embedding thousands of chunks one at a time. The dashboard (`RagClient.tsx`) polls the existing list endpoint every 1.2s while any row is `"processing"` - no new endpoint, no SSE/websocket - and that alone is what makes progress survive a page reload: the row's state lives in `rag_documents`, not in React state.

## Automatic RAG grounding is gone; a visible, dismissible suggestion replaced it

`DEJAQ_RAG_AUTO_RETRIEVE` and its silent guess-which-document call site in `run_chat_pipeline` (`openai_compat.py`) were removed outright, not defaulted off - the system no longer grounds an answer in a document nobody chose. The retrieval machinery underneath it is untouched and still live: `rag_service.retrieve()` (exhaustive/ANN self-tuning), `retrieve_multi`, `RAG_MAX_DISTANCE`/`RAG_TOP_K`/chunking settings, and `evals/rag_recall/` all stay - they're what the new feature searches with. `POST /rag-suggest` (`routers/rag_documents_public.py`, workspace-scoped like `GET /rag-documents`) calls `retrieve(ns, query, top_k=1, RAG_SUGGEST_MAX_DISTANCE)` on a 500ms debounce as the chat composer's `@`-mention text changes, and shows a dismissible "might be about {doc}" chip (`MessageInput.tsx`) when one comes back. Accepting it sets the exact same `ragDocument` state the `@` picker sets - there is no second grounding path, so everything the explicit-reference feature already has (cache gate, provenance row, verbatim serving) applies for free. `RAG_SUGGEST_MAX_DISTANCE` (0.45) is looser than `RAG_MAX_DISTANCE` (0.35) on purpose - a wrong suggestion costs a dismiss, not a misleading answer - and was picked by sweeping 0.35/0.45/0.55/0.65 on the `evals/rag_recall` corpus (reused, not rebuilt) with a new `evals/rag_suggest/measure.py`: 0.45 is the last point before real questions the KB can't answer start getting a suggestion anyway. See `firstmate/data/dejaq-rag-suggest/report.md`.

## `uv run <anything>` without `--group test` silently strips pytest from the shared venv

Any `uv run` invocation - not just a bare `uv run pytest` missing `--group test`, but `uv run python some_script.py` too - re-syncs the environment to the DEFAULT dependency group first. If the venv currently has the `test` group installed (from an earlier `uv sync --group test`, e.g. after following the Setup section), a later `uv run python ...eval_script.py` (no `--group test`) silently uninstalls pytest/pytest-html/etc. mid-session, and the next test run fails with "Failed to spawn: `pytest`" or "No module named pytest" - not an error naming what happened. Also happens indirectly: `tests/test_start_script.py` runs the real `start.sh`, which itself calls a bare `uv sync` (no `--group test`), so running that one test file has the same side effect on the shared venv as running an eval script does. Fix: `uv sync --group test` again before the next `pytest` invocation. When running both eval scripts and the test suite in one session, expect to re-sync between them, or deselect `test_start_script.py` from routine runs and only run it (then immediately re-sync) at the end.

## The dashboard needs its own `NEXT_PUBLIC_API_BASE_URL`, or every server-action page 500s behind a misleading empty state

`dashboard/.env.local` (`NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000`, see `dashboard/.env.local.example`) is required, not optional despite the README's phrasing - without it, Pipeline/Workspaces/every page that calls a server action to hit `/admin/v1/*` renders "No workspaces found. Use the onboarding flow..." with no visible error, even though real workspaces exist. The actual failure (`NEXT_PUBLIC_API_BASE_URL is required`, thrown from `lib/api.ts`'s `apiFetch`) only shows up as a 500 on the page's own server-action POST in the browser console/network tab - the rendered page gives no hint. `chat/.env.local` was already documented as required (see the full-stack section above); the dashboard needs the equivalent and was previously undocumented here. Next.js only reads `NEXT_PUBLIC_*` vars at dev-server start, so the server must be restarted (not just the browser refreshed) after creating or editing this file.

## A locally-started Redis/Celery can silently race a concurrently-running pytest suite

`DEJAQ_USE_CELERY` defaults `true` with no test-suite override, and the store-dispatch path (`openai_compat.py`) falls back to synchronous in-process storage only when the real dispatch throws (Redis unreachable) - see `USE_CELERY`/`apply_async` in `openai_compat.py`. If a pytest run is already in flight (using the default `redis://localhost:6379/0`) when a Redis instance happens to come up for unrelated reasons (e.g. a human/agent starting one for manual E2E testing in the same environment), tests that hit the cache-store path silently switch from the synchronous in-process fallback to real async Celery dispatch mid-run, with no Celery worker yet consuming the queue - tasks queue silently rather than executing, and the switch depends entirely on timing. Observed on `dejaq-model-refresh-e2e`: two smoke-test cache-store calls sat queued in Redis and only ran when a manually-started Celery worker connected minutes later. Not confirmed to cause an actual test failure here (no assertion depended on synchronous completion), but the risk is real. Do not start a shared-port Redis/Celery stack while a pytest run using the same default port is in progress - run the full suite to completion first (or point one of them at a different Redis DB index/port) before bringing up a manual dev stack.

## The "one attachment per request" check counts the whole `input` array, not just the latest turn

`openai_responses._responses_request_to_messages` raises its 400 ("At most one file/image per request is supported") the moment a second `input_image`/`input_file` part appears anywhere in `req.input`, including a past turn's history - not just the current message. The `chat/` reference client never triggers this: `buildResponsesInput` (`chat/app/api/chat/route.ts`) attaches the file/image part only to the *last* user message and sends every earlier turn as `input_text` only, so a resent "sticky" attachment never coexists with its own earlier appearance in the same request. A test harness or any hypothetical client that instead threads full raw history (attachment parts included) back into every subsequent turn will hit this 400 the moment a second turn also carries an attachment - reproduced live on `dejaq-acceptance-retest-2` with a naive test driver, not a real client bug. Follow the `chat/` client's pattern (attachment on the latest turn only) when building conversation history for `/v1/responses`.

## Local generation can fumble a bare pronoun-only follow-up the enricher already resolved correctly

Measured on `dejaq-acceptance-retest-2`: 4/4 ultra-terse pronoun-only follow-ups ("How long does it take?", "How much does that cost?", no other words) got a "please clarify, what does 'it'/'that' refer to?" reply from local generation (`gemma4:e4b`) instead of an answer - even though the context enricher (`qwen2.5:1.5b`), given the *same* history, correctly resolved the reference for the cache key in every one of those four cases (logged `enriched_prompt` values like "How many weeks typically do I need to train for my first marathon?"). The enriched query is used only for cache lookup/keying, not sent to the generator - CLAUDE.md's pipeline sends the *original* query + history to the LLM ("preserves tone"), so the generator must resolve the pronoun itself from raw history, and a smaller purpose-built model sometimes does that better than the larger general-purpose one on very sparse input. A less terse follow-up that keeps any topic word ("Is Lisbon walkable?" style) did not reproduce this in the same round. Not fixed here - a real, reproducible generation-quality gap, not a cache defect. See `dejaq-acceptance-retest-2/report.md`.

## A single-threaded Celery worker can fall meaningfully behind under a fast sequence of store-triggering calls

`--pool=solo` (the documented standard config) processes background stores strictly one at a time, ~1-6s each (embedding + generalize LLM call + Chroma write). A test driver (or any burst of traffic) that fires requests faster than that will build a real backlog - measured on `dejaq-acceptance-retest-2`: ~30 novel questions ahead of a probe was enough for the probe's own store to still be unlanded 12+ seconds later. A "did the collection's document count go up" check is not sufficient proof that *your* document landed - it can be satisfied by an unrelated backlog item completing first. Poll for the specific `doc_id` (from the response's `x-dejaq-response-id` header) instead, and expect wait times to scale with how much store-triggering traffic already ran, not with a single store's own latency. Not a code defect - a real throughput characteristic of the shipped single-worker config, worth knowing before treating a "still shows as a miss" result as a cache-correctness bug.

## Rebasing onto a newer base needs a fresh `alembic upgrade head`, not just once per worktree

A `server/dejaq.db` migrated at the start of a session goes stale the moment the branch is rebased onto a newer point in history that added its own migrations - the newly-rebased code expects columns the DB doesn't have yet (measured: `no such column: workspace_llm_configs.external_provider` after rebasing a task branch onto a `staging` that had since added the `external_provider` column). `alembic upgrade head` is safe to re-run any number of times and does not touch existing workspace/department/key rows - run it again after any rebase/merge that could have added migrations, not just once per fresh worktree.

## `pytest`'s `--self-contained-html` report can crash at session-finish in this venv, after every test already passed

The repo's `pyproject.toml` `addopts` always requests `--html=test_reports/report.html --self-contained-html`. In this environment that can fail at `pytest_sessionfinish` with `jinja2.exceptions.TemplateNotFound: 'app.js' not found in search path: .../pytest_html/resources` - a broken/incomplete `pytest-html` install, not a test failure: every test already ran and passed by the time this fires, and the traceback is easy to mistake for a suite-wide failure since it prints after the dot/verbose output. Also separately: `uv run <anything>` without `--group test` re-syncs the venv to the default dependency group and can silently drop `pytest` itself mid-session (see the entry above on this) - chain `uv sync --group test && uv run pytest ...` in one command rather than assuming a prior sync still holds. Work around the html-report crash with `uv run pytest -q -o addopts=""` (or any override that drops `--self-contained-html`) to get a clean pass/fail summary.

## A GitHub repo import is one RAG document PER FILE, grouped by `group_key`

`POST /admin/v1/workspaces/{slug}/rag-documents/repo` (`rag_ingest.from_repo` +
`rag_admin_service.begin_repo`, branch `fm/dejaq-kb-github-repo`) fetches the GitHub
API source tarball and writes one `rag_documents` row per indexable file, not one per
repository - so an answer names the file it came from, and the existing
`(workspace_id, sha)` identity makes an unchanged file's row/id/chunks survive a
re-import untouched. Rows from one import share the nullable `group_key`
(`github:{owner}/{repo}`, migration `a7b8c9d0e1f2`); every other source leaves it
null. `begin_repo` prunes rows in the group whose sha is no longer in the repo, so a
re-import is an update rather than an append - and it prunes AFTER writing the new
rows, so a failed fetch cannot half-delete the previous import. Every file-selection
rule lives in `rag_ingest._repo_skip_reason` and the constants above it; do not put
new ones in the read loop. Full rationale, defaults, and measured retrieval numbers:
[docs/rag-layer.md](docs/rag-layer.md#github-repository-import).

`group_key` is the ONE grouping concept - do not add a second. Everything that treats
an import as a unit keys off it: the dashboard's collapsed catalog row, the chat `@`
picker's expandable repository entry (`chat/app/components/rag-mention.ts`), the
`rag_group_key` reference on `/v1/responses` (whose member ids
`rag_document_repo.list_for_group` resolves), and `begin_repo`'s prune. Per-document
rows and their status machine stay per-document everywhere below the presentation
layer - the group is derived, never stored as its own row.

`_REPO_MAX_FILES = 400` is a HARD cap applied in tar order (alphabetical) and it
truncates SILENTLY - dropped files land in the response's `skipped_files` count with
no reason attached, indistinguishable from a lockfile. Importing `jshef747/DejaQ`
itself measured 654 candidate files and dropped 244, which is every one of the 241
files under `server/`, because `server/` sorts last. An import of a repository near
or above that many files answers questions about the wrong half of it. Raise the cap,
or report per-reason skip counts, before trusting an import of anything repo-sized.

## The knowledge-base chunker is code-aware for Python only

`rag_service.chunk_document(text, source_ref)` is the single entry point ingestion
uses (`rag_admin_service.begin_ingest`). It picks the strategy from the file
extension in `source_ref`: `.py`/`.pyi` go through `chunk_python` (an `ast` walk that
keeps a function, method or class whole, splits an over-budget one at its own inner
statement boundaries, and heads each later fragment with a `# fragment of:` comment
naming the enclosing declarations); everything else - Markdown, JS, JSON, plain text,
and any Python that will not parse - falls through to the prose `chunk_text`
unchanged. Deliberately no language registry and no tree-sitter dependency: one `if`,
because one language is what the battery measures. Chunking is a pure function of
(text, source_ref), which is what makes a re-import of an unchanged file
byte-identical - verified live, 884 chunks, 0 changed.

Measured on the battery `c45c8f3` established (`RichardLitt/standard-readme` +
`psf/requests`, 28 questions through `/rag-suggest` + `/v1/responses`, 25 of them
with a specific answer line): prose chunking retrieved the answer line for 13,
code-aware for 25, zero regressions. `psf/requests` grew 840 -> 897 chunks (+6.8%);
Markdown documents are byte-identical. Ranking was NOT touched and moved anyway -
`/rag-suggest`'s top pick for the 23 `requests` code questions went from 11 test
files / 4 correct source modules to 2 / 15, because an implementation chunk that
starts at `def` competes with a test file's prose-like assertions and a mid-function
fragment did not. Full numbers, including the DejaQ secondary run:
[docs/rag-layer.md](docs/rag-layer.md#chunking).

## A background cache write that fails is a real failure mode, and it has a counter now

`_bg_generalize_and_store` (`server/app/routers/openai_compat.py`) and
`generalize_and_store_task` (`server/app/tasks/cache_tasks.py`) both run AFTER the
response - `X-DejaQ-Response-Id` header and all - has already gone out, so a failure
there has no request-level status to ride on. It used to be swallowed whole: one
`background_store status=failed` ERROR line, a client holding an id for an entry that
was never written, and a cache that quietly stopped filling. That is how a plain
`TypeError` from a signature mismatch (`48db1e9`) survived - indistinguishable from a
ChromaDB blip. Both paths now write a `cache_store_failures` row to the stats DB
(`request_logger.record_store_failure`, surfaced as `store_failures` on
`/admin/v1/stats/*` and in `dejaq-admin stats`); any non-zero value is a defect or an
outage, never normal traffic. The router's handler also re-raises
`_PROGRAMMING_ERRORS` (TypeError/AttributeError/...) instead of tolerating them - a
defect in our own code is not a runtime condition. Same rule as the classify step's
bare `except Exception` above: an `except Exception` that exists to tolerate a flaky
dependency must let programming errors through, or the next broken call site is
invisible again. Regression test:
`server/tests/test_cache_store_failure_visibility.py`.

The id itself is still emitted optimistically, before the write - see the long comment
at the `_planned_response_id` assignment for why (withholding it means withholding the
streaming response head), and `chat/app/components/chat-api.ts` for the client-side
retry-then-honest-404 that pairs with it. Making the id conditional on a completed
write is a contract change, not a bug fix.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
