<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

## Model catalog (Settings page)

`app/dashboard/settings` reads the LiteLLM-backed model catalog via
`app/actions/model-catalog.ts` (`GET /admin/v1/model-catalog/providers`
and `.../providers/{key}/models`). The old `GET /admin/v1/providers`
endpoint and `server/app/services/provider_registry.py` it served from
are both deleted (migration stage A1c) - don't add a new caller of that
path back, it's gone server-side.

## Dev-tools indicator vs. sidebar user block

Next's on-screen dev indicator defaults to `bottom-left` (`devIndicators.position`
in `next.config.mjs`), the same corner the sidebar (`components/Sidebar.tsx`)
uses for the signed-in user block (avatar + email + role). Left at the
default, the indicator's fixed button paints on top of that block. Pinned to
`bottom-right` in `next.config.mjs`. If a future page anchors something else
to bottom-right, move the indicator or the conflicting element instead of
reverting this.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
