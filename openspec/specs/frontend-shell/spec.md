## ADDED Requirements

### Requirement: Next.js app scaffold
The system SHALL contain a `dashboard/` directory at the repo root with a Next.js 16 application using TypeScript, Tailwind CSS, and the App Router. The package manager SHALL be npm.

#### Scenario: App starts locally
- **WHEN** a developer runs `npm run dev` inside `dashboard/`
- **THEN** Next.js starts on `http://localhost:3000` without errors

#### Scenario: TypeScript compiles cleanly
- **WHEN** `npm run build` is executed
- **THEN** the build completes with no TypeScript errors

### Requirement: Dashboard requires no sign-in
The dashboard SHALL open directly to `/dashboard/*` routes with no login or sign-up flow. There SHALL be no session cookie, no middleware auth gate (no `middleware.ts` and no Next.js 16 `proxy.ts`), and no `/login` or `/signup` route — every dashboard page renders without an authentication check, backed by the loopback-bound, unauthenticated dev-admin management API context. The only redirect out of the dashboard SHALL be the first-run onboarding guard, which sends a user to `/onboarding` when the backend reports zero workspaces; a backend that is unreachable SHALL NOT redirect.

#### Scenario: Dashboard access requires no session
- **WHEN** a user navigates to `/dashboard` and at least one workspace exists
- **THEN** the dashboard layout renders with the sidebar, with no redirect and no session check

#### Scenario: Direct navigation to a dashboard sub-route
- **WHEN** a user navigates to `/dashboard/workspaces` and at least one workspace exists
- **THEN** the page renders directly, with no authentication redirect

#### Scenario: First run with an empty database
- **WHEN** a user navigates to `/dashboard` and the management API reports no workspaces
- **THEN** the user is redirected to `/onboarding`

### Requirement: Sidebar navigation
The dashboard layout SHALL include a persistent sidebar with a "Workspace" section listing, in order: Analytics, Workspaces, Departments, Workspace Tree, API Keys, Knowledge Base, followed by an external "Chat demo" link to `NEXT_PUBLIC_CHAT_URL` (default `http://localhost:4000`); and an "Account" section containing Settings. Workspace-scoped nav links SHALL carry the active `?workspace=<slug>` query param. The sidebar SHALL display the dev-admin context's email and a 22×22px avatar circle with its initials. The sidebar background SHALL be `#181818` (distinct from the page background `#1c1c1c`).

#### Scenario: Active page highlighted
- **WHEN** the user is on `/dashboard/workspaces`
- **THEN** the Workspaces nav item is visually active (icon in `#f97316`, background `var(--bg-3)`)

#### Scenario: Sidebar displays dev-admin email
- **WHEN** a user is on any dashboard page
- **THEN** the dev-admin context's email is visible in the sidebar footer

### Requirement: Sidebar logo and workspace switcher
The sidebar SHALL include a logo mark ("Dq" text, 22×22px square, `var(--accent)` background, bold monospace font, border-radius 4px) and a workspace switcher button (border 1px `var(--border)`, border-radius 5px) below the logo row. Selecting a workspace SHALL update the `?workspace=<slug>` query param on workspace-scoped routes.

#### Scenario: Logo mark renders correctly
- **WHEN** any dashboard page loads
- **THEN** the sidebar shows a 22×22px orange square with "Dq" in bold monospace (not an icon)

#### Scenario: Workspace switcher visible
- **WHEN** any dashboard page loads
- **THEN** a workspace switcher button is visible below the logo, showing the current workspace name

### Requirement: Dashboard home page
The `/dashboard` route SHALL render a real page — not a placeholder. It SHALL display at minimum: the dev-admin context's email, a welcome heading, and a status card that calls `GET /health` with a 5-second timeout. If the backend responds, show "Backend connected". If unreachable or timed out, show "Backend unavailable" — this SHALL NOT block page render.

#### Scenario: Dashboard home renders
- **WHEN** a user visits `/dashboard`
- **THEN** a welcome heading and the dev-admin email are displayed without errors

#### Scenario: Backend unreachable does not break dashboard
- **WHEN** the FastAPI backend is not running and the user visits `/dashboard`
- **THEN** the page renders with a "Backend unavailable" status card, not an error page

### Requirement: Section pages
Routes `/dashboard/analytics`, `/dashboard/workspaces`, `/dashboard/departments`, `/dashboard/tree`, `/dashboard/keys`, `/dashboard/rag`, and `/dashboard/settings` SHALL each render a working page — backed by the management API, not a "Coming soon" placeholder — within the dashboard layout.

#### Scenario: Section page renders in layout
- **WHEN** a user visits `/dashboard/workspaces`
- **THEN** the sidebar is visible, the Workspaces page renders live management-API data, and no 404 is returned

### Requirement: Management API client module
The system SHALL include `dashboard/lib/api.ts` — a server-only fetch wrapper (imports `server-only`) that adds `Authorization: Bearer dev-local` to every request sent to the FastAPI management API (the backend ignores the token and grants a dev-admin context). The base URL SHALL be read from `NEXT_PUBLIC_API_BASE_URL`. `apiFetch` SHALL throw on HTTP 401 or 5xx responses. All other responses are returned to the caller. The module SHALL also export `apiUpload` for multipart uploads, which sends the same `Authorization` header but SHALL NOT set `Content-Type` (the runtime must generate the multipart boundary itself).

#### Scenario: API call includes dev-local Bearer token
- **WHEN** `apiFetch('/admin/v1/whoami')` is called from a server component
- **THEN** the request is sent with `Authorization: Bearer dev-local` to `${NEXT_PUBLIC_API_BASE_URL}/admin/v1/whoami`

#### Scenario: API call returns 401
- **WHEN** `apiFetch` sends a request and receives a 401 response
- **THEN** an error is thrown with a message indicating authentication failure

### Requirement: Design system — dark theme, orange accent
The dashboard SHALL implement the full design token set from the Claude Design file as CSS custom properties reachable from `app/globals.css` (which imports `app/design-system.css`). Required tokens: `--bg` (`#1c1c1c`), `--bg-2` (`#1f1f1f`), `--bg-3` (`#242424`), `--bg-hover` (`#262626`), `--border` (`#2a2a2a`), `--border-2` (`#333`), `--fg` (`#ededed`), `--fg-dim` (`#a1a1a1`), `--fg-dimmer` (`#6e6e6e`), `--accent` (`#f97316`), `--accent-hover` (`#fb8533`), `--accent-bg` (`rgba(249,115,22,0.12)`), `--accent-border` (`rgba(249,115,22,0.3)`), `--amber` (`#f59e0b`), `--amber-bg` (`rgba(245,158,11,0.12)`), `--amber-border` (`rgba(245,158,11,0.3)`), `--red` (`#ef4444`), `--red-bg` (`rgba(239,68,68,0.12)`), `--red-border` (`rgba(239,68,68,0.3)`), `--green` (`#22c55e`), `--green-bg` (`rgba(34,197,94,0.12)`), `--blue` (`#3b82f6`), `--blue-bg` (`rgba(59,130,246,0.12)`), `--purple` (`#a855f7`), `--purple-bg` (`rgba(168,85,247,0.12)`). Body SHALL have `font-size: 13px`, `letter-spacing: -0.005em`, and `-webkit-font-smoothing: antialiased`. Fonts SHALL be Inter (UI) and JetBrains Mono (keys/IDs/code), with weights Inter 400/500/600/700 and JetBrains Mono 400.

#### Scenario: Page background is dark
- **WHEN** any dashboard page renders
- **THEN** the page background is `#1c1c1c` and text is `#ededed`

#### Scenario: Accent color applied to active nav item
- **WHEN** a sidebar nav item is active
- **THEN** its icon is rendered in `#f97316` (orange accent)

### Requirement: Environment configuration
The dashboard SHALL read one required environment variable, `NEXT_PUBLIC_API_BASE_URL`, and one optional one, `NEXT_PUBLIC_CHAT_URL` (default `http://localhost:4000`). A `dashboard/.env.local.example` file SHALL document the required variable with a placeholder value. `lib/api.ts` SHALL throw if `NEXT_PUBLIC_API_BASE_URL` is falsy when a request is made.

#### Scenario: Missing API base URL fails the request
- **WHEN** `NEXT_PUBLIC_API_BASE_URL` is not set and `apiFetch` is called
- **THEN** an error is thrown with the message `"NEXT_PUBLIC_API_BASE_URL is required"`

### Requirement: Dashboard onboarding documented in one place
`dashboard/README.md` SHALL own dashboard setup: install (`npm install`), env file (`cp .env.local.example .env.local`), env vars, and how to run locally (`npm run dev`, port 3000). CLAUDE.md at the repo root SHALL carry only a short `## Dashboard` pointer to it, plus the two facts that are not dashboard-local: the dev-bypass auth model and the requirement that FastAPI CORS allow `http://localhost:3000`.

#### Scenario: Developer can onboard from the dashboard README
- **WHEN** a developer follows `dashboard/README.md`
- **THEN** they can run the dashboard locally with no sign-in step
