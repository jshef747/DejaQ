## ADDED Requirements

### Requirement: Next.js app scaffold
The system SHALL contain a `frontend/` directory at the repo root with a Next.js 15 application using TypeScript, Tailwind CSS, and the App Router. The package manager SHALL be npm.

#### Scenario: App starts locally
- **WHEN** a developer runs `npm run dev` inside `frontend/`
- **THEN** Next.js starts on `http://localhost:3000` without errors

#### Scenario: TypeScript compiles cleanly
- **WHEN** `npm run build` is executed
- **THEN** the build completes with no TypeScript errors

### Requirement: Supabase email/password authentication
The system SHALL implement sign-in and sign-up flows using Supabase Auth with email and password as the only sign-in method. Sessions SHALL be managed via cookies using `@supabase/ssr` — no manual JWT storage in localStorage.

#### Scenario: Sign-in with valid credentials
- **WHEN** a user submits the sign-in form with `demo@dejaq.local` / `demo1234`
- **THEN** the user is redirected to `/dashboard` and a session cookie is set

#### Scenario: Sign-in with invalid credentials
- **WHEN** a user submits the sign-in form with an incorrect password
- **THEN** an error message is displayed and no session cookie is set

#### Scenario: Sign-up creates a new account
- **WHEN** a user submits the sign-up form with a valid new email and password
- **THEN** a Supabase Auth user is created and the user is redirected to `/dashboard`

#### Scenario: Sign-out clears the session
- **WHEN** a user triggers the sign-out action
- **THEN** the session cookie is cleared and the user is redirected to `/login`

#### Scenario: Authenticated user visits login page
- **WHEN** a user with an active session navigates to `/login` or `/signup`
- **THEN** they are redirected to `/dashboard` without seeing the auth form

### Requirement: Protected dashboard layout
All routes under `/dashboard/*` SHALL require an authenticated session. Unauthenticated requests SHALL redirect to `/login`. The protection SHALL be enforced via Next.js middleware — not per-page checks. The middleware SHALL use a `matcher` config to exclude static assets (`/_next/*`, `/favicon.ico`, etc.).

#### Scenario: Unauthenticated access to dashboard
- **WHEN** an unauthenticated user navigates to `/dashboard`
- **THEN** they are redirected to `/login`

#### Scenario: Authenticated access to dashboard
- **WHEN** an authenticated user navigates to `/dashboard`
- **THEN** the dashboard layout renders with the sidebar

#### Scenario: Direct navigation to protected sub-route
- **WHEN** an unauthenticated user navigates to `/dashboard/organizations`
- **THEN** they are redirected to `/login`

#### Scenario: Token refresh fails in middleware
- **WHEN** the middleware calls `supabase.auth.getUser()` and the refresh token is expired or invalid
- **THEN** the session cookie is cleared and the user is redirected to `/login`

### Requirement: Sidebar navigation
The dashboard layout SHALL include a persistent sidebar with the following nav items in order: Organizations, Departments, API Keys, Analytics, Settings. The sidebar SHALL display the signed-in user's email, a 22×22px avatar circle with the user's initials, and a sign-out button. The sidebar background SHALL be `#181818` (distinct from the page background `#1c1c1c`).

#### Scenario: Active page highlighted
- **WHEN** the user is on `/dashboard/organizations`
- **THEN** the Organizations nav item is visually active (icon in `#f97316`, background `var(--bg-3)`)

#### Scenario: Sign-out visible in sidebar
- **WHEN** the user is authenticated and viewing any dashboard page
- **THEN** the sidebar footer shows the user's initials avatar, email, and a sign-out affordance

#### Scenario: Sidebar displays user email
- **WHEN** an authenticated user is on any dashboard page
- **THEN** their email is visible in the sidebar footer

### Requirement: Sidebar logo and org switcher
The sidebar SHALL include a logo mark ("Dq" text, 22×22px square, `var(--accent)` background, bold monospace font, border-radius 4px) and an org switcher button (border 1px `var(--border)`, border-radius 5px) below the logo row.

#### Scenario: Logo mark renders correctly
- **WHEN** any dashboard page loads
- **THEN** the sidebar shows a 22×22px orange square with "Dq" in bold monospace (not an icon)

#### Scenario: Org switcher visible
- **WHEN** any dashboard page loads
- **THEN** an org switcher button is visible below the logo, showing the current org name

### Requirement: Dashboard home page
The `/dashboard` route SHALL render a real page — not a placeholder. It SHALL display at minimum: the signed-in user's email, a welcome heading, and a status card that calls `GET /health` with a 5-second timeout. If the backend responds, show "Backend connected". If unreachable or timed out, show "Backend unavailable" — this SHALL NOT block page render.

#### Scenario: Dashboard home renders
- **WHEN** an authenticated user visits `/dashboard`
- **THEN** a welcome heading and user email are displayed without errors

#### Scenario: Backend unreachable does not break dashboard
- **WHEN** the FastAPI backend is not running and the user visits `/dashboard`
- **THEN** the page renders with a "Backend unavailable" status card, not an error page

### Requirement: Placeholder pages for future sections
Routes `/dashboard/organizations`, `/dashboard/departments`, `/dashboard/keys`, `/dashboard/analytics`, and `/dashboard/settings` SHALL each render a styled placeholder page within the protected layout. Each placeholder SHALL display the section name and a "Coming soon" indicator.

#### Scenario: Placeholder renders in layout
- **WHEN** an authenticated user visits `/dashboard/organizations`
- **THEN** the sidebar is visible, the Organizations placeholder content renders, and no 404 is returned

### Requirement: Management API client module
The system SHALL include `frontend/lib/api.ts` — a server-only fetch wrapper (marked with `'use server'` or placed in a server-only module) that reads the current Supabase session via the server client, extracts the JWT access token, and adds `Authorization: Bearer <token>` to every request sent to the FastAPI management API. The base URL SHALL be read from `NEXT_PUBLIC_API_BASE_URL`. `apiFetch` SHALL throw if no session exists before making the request. `apiFetch` SHALL throw on HTTP 401 or 5xx responses. All other responses are returned to the caller.

#### Scenario: Authenticated API call includes Bearer token
- **WHEN** `apiFetch('/admin/v1/whoami')` is called from a server component while a valid session exists
- **THEN** the request is sent with `Authorization: Bearer <supabase-access-token>` to `${NEXT_PUBLIC_API_BASE_URL}/admin/v1/whoami`

#### Scenario: API call without session throws
- **WHEN** `apiFetch('/admin/v1/whoami')` is called with no active session
- **THEN** an error is thrown before any HTTP request is made

#### Scenario: API call returns 401
- **WHEN** `apiFetch` sends a request and receives a 401 response
- **THEN** an error is thrown with a message indicating authentication failure

### Requirement: Design system — dark theme, orange accent
The frontend SHALL implement the full design token set from the Claude Design file as CSS custom properties in `globals.css`. Required tokens: `--bg` (`#1c1c1c`), `--bg-2` (`#1f1f1f`), `--bg-3` (`#242424`), `--bg-hover` (`#262626`), `--border` (`#2a2a2a`), `--border-2` (`#333`), `--fg` (`#ededed`), `--fg-dim` (`#a1a1a1`), `--fg-dimmer` (`#6e6e6e`), `--accent` (`#f97316`), `--accent-hover` (`#fb8533`), `--accent-bg` (`rgba(249,115,22,0.12)`), `--accent-border` (`rgba(249,115,22,0.3)`), `--amber` (`#f59e0b`), `--amber-bg` (`rgba(245,158,11,0.12)`), `--amber-border` (`rgba(245,158,11,0.3)`), `--red` (`#ef4444`), `--red-bg` (`rgba(239,68,68,0.12)`), `--red-border` (`rgba(239,68,68,0.3)`), `--green` (`#22c55e`), `--green-bg` (`rgba(34,197,94,0.12)`), `--blue` (`#3b82f6`), `--blue-bg` (`rgba(59,130,246,0.12)`), `--purple` (`#a855f7`), `--purple-bg` (`rgba(168,85,247,0.12)`). Body SHALL have `font-size: 13px`, `letter-spacing: -0.005em`, and `-webkit-font-smoothing: antialiased`. Fonts SHALL be Inter (UI) and JetBrains Mono (keys/IDs/code), with weights Inter 400/500/600/700 and JetBrains Mono 400.

#### Scenario: Page background is dark
- **WHEN** any dashboard page renders
- **THEN** the page background is `#1c1c1c` and text is `#ededed`

#### Scenario: Accent color applied to active nav item
- **WHEN** a sidebar nav item is active
- **THEN** its icon is rendered in `#f97316` (orange accent)

### Requirement: Environment configuration
The frontend SHALL read three environment variables: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, and `NEXT_PUBLIC_API_BASE_URL`. A `frontend/.env.local.example` file SHALL document all three with placeholder values. The Supabase client modules SHALL throw a descriptive error at instantiation if either Supabase env var is missing. `lib/api.ts` SHALL throw at module load time if `NEXT_PUBLIC_API_BASE_URL` is falsy.

#### Scenario: Missing env var fails clearly
- **WHEN** `NEXT_PUBLIC_SUPABASE_URL` is not set and the Supabase client is instantiated
- **THEN** an error is thrown with a message identifying the missing variable

#### Scenario: Missing API base URL fails at load time
- **WHEN** `NEXT_PUBLIC_API_BASE_URL` is not set and `lib/api.ts` is imported
- **THEN** an error is thrown with the message `"NEXT_PUBLIC_API_BASE_URL is required"`

### Requirement: CLAUDE.md documents frontend setup
CLAUDE.md at the repo root SHALL include a `### Frontend (dashboard)` section covering: how to install deps (`npm install`), how to copy env file (`cp .env.local.example .env.local`), how to fill in env vars, how to run locally (`npm run dev`, port 3000), required env vars table, demo account credentials (`demo@dejaq.local` / `demo1234`), how the dashboard authenticates with the FastAPI backend (Supabase JWT → Bearer token), and a note that FastAPI CORS must allow `http://localhost:3000`.

#### Scenario: Developer can onboard from CLAUDE.md
- **WHEN** a developer reads the Frontend section of CLAUDE.md and follows the steps
- **THEN** they can run the dashboard locally and sign in with the demo account
