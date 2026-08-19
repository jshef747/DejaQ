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

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
