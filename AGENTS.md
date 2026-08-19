# AGENTS.md

## Global Rules

- Only the user may speak Hebrew. Agents must always respond in English unless the user explicitly asks for something else.

## Project Guidance

Use `CLAUDE.md` as the canonical project guide for architecture, commands, environment variables, endpoints, coding conventions, and current status. Keep this file intentionally small so agent-specific rules do not drift from the main project documentation.

## Running the test suite

From `server/`, `uv run --group test pytest`. Two things bite on a fresh worktree and are not visible from the test files:

- Run `uv run alembic upgrade head` first. Without it ~39 tests fail with `no such table: workspaces`.
- The suite reads the repo's real `server/dejaq.db`, so leftover local workspaces change results - a workspace with id 1 (`demo`) makes routing tests take the configured-LLM path instead of the defaults branch they assert. Start from a freshly migrated DB when tests fail in ways the diff cannot explain.

The repo-root `.no-mistakes.yaml` pins the no-mistakes pipeline's Test step to `-m no_model` (307 of 682 tests - the rest need an Ollama model or in-process torch model not available in the pipeline sandbox) plus `chat/`'s vitest suite; see that file's comments for the full reasoning, including that `commands:` there only takes effect once it reaches `master` (no-mistakes reads `commands` from the default-branch copy of the file, not the pushed branch).

## Product stance: desktop-only

Neither the dashboard nor the chat app supports narrow viewports, by design (captain decision, 2026-08-10). The dashboard still stands exactly as decided then: its sidebar has no responsive breakpoint, and adding one needs a new product decision.

The chat app was scoped out of that stance by the stage-3 redesign (captain decision, 2026-08-19). Its sidebar now collapses to a ~56px icon rail below 1100px (`SIDEBAR_COLLAPSE_WIDTH` in `chat/app/components/ConversationSidebar.tsx`) and the response detail panel becomes an overlay drawer below 1024px. The rule that survives is the reason behind both: a tight window gives up sidebar width, never the reading column's 704px measure. Do not remove the chat's collapse behaviour, and do not add a layout that shrinks or clips the reading column instead.

## Chat styling

The chat owns its own token layer (`chat/app/tokens.css`, light + dark) and must not import the dashboard's `design-system.css` again. Every component reads those tokens by name from inline styles, so change a token's value, never its name. Read that file's header, and the one on `chat/app/globals.css`, before changing anything about how the chat looks.

`--accent` has exactly two sanctioned uses: the cache route (stage 2 of the chat redesign) and the pinned-attachment state in `chat/app/components/MessageInput.tsx`. Nothing else - not a button, not a link, not an active row, not any other surface. Use a neutral (`--fg`/`--border-2`/`--bg-3`) or the appropriate route colour instead (`--local` for local, `--blue` for cloud - see `chat/app/components/provenance.ts`). The same two-use wording sits on the token itself in `chat/app/tokens.css`; change both together or they drift. `chat/app/components/RouteMarker.tsx`, `ResponseDetail.tsx`, and `TypingIndicator.tsx` are the provenance rail, the response detail panel, and the wait strip; read those before touching per-message routing UI.

## Promotion conflicts (staging -> master)

Master has received both real merge commits and squash merges from staging (e.g. `ffb690b` is a squash, `7b9274b` a real merge). When a promotion is squashed, the same content ends up on both branches under different commit identities, so the next `staging` -> `master` PR shows false conflicts on any file touched since that squashed promotion. Fix by back-merging master into staging (never the reverse, never squash/rebase staging): for each conflict, diff `origin/master...origin/staging` on that file first to confirm staging already carries everything master has (it should, since the squash commit is just staging's own prior commits) - staging's side wins. Verify with `git diff origin/staging HEAD` on the resulting merge commit: an empty diff confirms nothing was lost. Only stop and escalate if master's side contains content genuinely absent from staging - that means a change landed on master and never made it back.

## SQLite batch migrations can silently drop what they don't explicitly touch

`d1e2f3a4b5c6` (rename organizations to workspaces) recreated `workspace_provider_credentials` via `batch_alter_table(recreate="always")`. It explicitly dropped/recreated the unique constraint, so that one got renamed correctly - but it never touched the CHECK constraint, and that constraint kept its pre-rename name (`ck_org_provider_credentials_provider`) forever after, never `ck_workspace_provider_credentials_provider` as the model declares. Worse: a constraint *not* re-declared inside a batch op can vanish entirely rather than carry over - the same migration's unique constraint on `(workspace_id, provider)` silently stopped existing on a from-scratch database (confirmed by inserting duplicate rows and finding nothing rejects them; not caught by any test, since `tests/conftest.py` builds test DBs with `Base.metadata.create_all()`, which reads constraints from the model, not from replaying migration history). Before writing a migration that touches an already-renamed table, verify the ORM model's declared constraint names against an actual `alembic upgrade head` on a fresh SQLite file (`sqlite_master.sql`), not against the model source - they can diverge, and only a from-scratch run of the real migration history shows it.

## Running the full stack for a visual check

`./start.sh --stack=all --mode=local` needs `--logs=requests` (or `DEJAQ_START_LOGS=requests`) when run non-interactively, or it blocks on a TTY prompt and exits. On a fresh worktree it also needs, once: `chat/` and `dashboard/` each have their own `node_modules` (`npm install` in both - `--stack=all` starts both), a `chat/.env.local` with `DEJAQ_API_KEY` (mint one with `dejaq-admin key generate --workspace <slug>`, and the workspace/department first with `dejaq-admin workspace create` / `dejaq-admin dept create` - a fresh `server/dejaq.db` has neither), and a clean `server/dejaq.db` (delete the gitignored file and let migrations recreate it if a half-finished prior run leaves tables without an `alembic_version` row - migration then fails with "table already exists").

`chrome-devtools-axi` runs against a machine-wide shared browser bridge whose own process cwd is unrelated to any worktree. Its `screenshot`/`take_screenshot` silently no-ops outside the bridge's configured MCP "workspace roots" (the CLI still prints a success line and the resolved path you asked for) - `/tmp` is always allowed. Screenshot to `/tmp/<name>.png` and `cp` into the worktree afterward; do not trust a `screenshot` success message alone without checking the file landed.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
