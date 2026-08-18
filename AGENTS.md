# AGENTS.md

## Global Rules

- Only the user may speak Hebrew. Agents must always respond in English unless the user explicitly asks for something else.

## Project Guidance

Use `CLAUDE.md` as the canonical project guide for architecture, commands, environment variables, endpoints, coding conventions, and current status. Keep this file intentionally small so agent-specific rules do not drift from the main project documentation.

## Running the test suite

From `server/`, `uv run --group test pytest`. Two things bite on a fresh worktree and are not visible from the test files:

- Run `uv run alembic upgrade head` first. Without it ~39 tests fail with `no such table: workspaces`.
- The suite reads the repo's real `server/dejaq.db`, so leftover local workspaces change results - a workspace with id 1 (`demo`) makes routing tests take the configured-LLM path instead of the defaults branch they assert. Start from a freshly migrated DB when tests fail in ways the diff cannot explain.

## Product stance: desktop-only

Neither the dashboard nor the chat app supports narrow viewports, by design (captain decision, 2026-08-10). Neither sidebar has a responsive breakpoint. Do not file this as a defect or add responsive/collapsible-sidebar behavior without a new product decision.

## Chat styling

The chat owns its own token layer (`chat/app/tokens.css`, light + dark) and must not import the dashboard's `design-system.css` again. Every component reads those tokens by name from inline styles, so change a token's value, never its name. Read that file's header, and the one on `chat/app/globals.css`, before changing anything about how the chat looks.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
