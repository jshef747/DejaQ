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

## Styleable dropdowns

A native `<select>`/`<optgroup>` and an `<input list>`/`<datalist>` both render
their open popup with OS chrome that no CSS in this app can reach - it will
always look like a different program next to the dark theme. Use
`components/ui/Combobox.tsx` instead: one component covers both a grouped,
non-editable picker (`SettingsClient.tsx`'s provider field) and a filterable,
free-text picker (its model field, `filterable` prop), built from the
dashboard's own `.ds-combo*` styles in `design-system.css`. It implements the
full WAI-ARIA combobox keyboard/focus contract (arrows, Home/End, typeahead,
Escape-reverts, click-outside/scroll/blur close) - reuse it rather than
reaching for a plain `<select>` or a new dependency.

One easy-to-miss pitfall when writing a component like this: keyboard
navigation's `scrollIntoView` can scroll a new option under a stationary
mouse cursor, which fires a real `mouseenter`/`mouseover` on it and hijacks
the keyboard selection. Handle hover with `onMouseMove`, not `onMouseEnter` -
`mousemove` only fires on actual pointer movement, not on content shifting
under a still pointer.

## Verifying with chrome-devtools-axi

`chrome-devtools-axi screenshot <path>` silently fails to write outside a
narrow sandbox root when invoked from an agent shell - it reports success and
even prints the path you asked for, but nothing lands there. Screenshot to a
relative path or somewhere under `/tmp` or the session scratchpad instead,
then `cp` the file out to wherever it actually needs to end up. Confirm with
`ls` after the first shot in a session, since the failure mode gives no error.

Likewise, prefer real keystroke simulation (`chrome-devtools-axi type "..."`,
or one `press <key>` per call with a fresh `snapshot`/`eval` read after each)
over setting an input's `.value` directly or the `fill` command - both bypass
React's controlled-input event chain, so the DOM shows the new text but
component state never updates.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
