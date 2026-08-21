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

## The HARD/EASY judge mechanism is non-deterministic

`_judge_hard_content` (`openai_compat.py`, shared by the attachment hard-content judge and the Hebrew routing judge) calls `LLMRouterService.generate_local_response`, which hardcodes `temperature=0.7` with no override. Measured: the same question through the same judge/prompt can flip HARD/EASY across identical repeated calls (5 draws on one question: `['EASY','HARD','HARD','EASY','HARD']`). Any future caller of this mechanism for a routing decision (not just a quality check) should know the verdict is a coin flip near the model's decision boundary, not a stable property of the input - see `dejaq-model-refresh-implement/report.md`'s Hebrew-hybrid findings for a worked example.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
