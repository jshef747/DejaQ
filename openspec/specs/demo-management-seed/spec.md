# demo-management-seed Specification

## Purpose
Define the idempotent demo setup path that creates a ready-to-use management workspace, sample dashboard data, and optional encrypted provider credentials for local demonstrations.

## Requirements

### Requirement: Setup seeds a demo workspace
The system SHALL provide an idempotent setup path that creates a default demo organization, one or two departments, and sample stats data so a new install has a populated management dashboard immediately (the dashboard requires no sign-in).

The demo organization SHALL use a stable slug. Demo departments SHALL use stable slugs. Running the seed more than once SHALL NOT duplicate organizations, departments, or sample stat batches.

The `seed demo` command SHALL accept the demo provider credential via either:

1. An optional `--provider-key-stdin <provider>` flag that reads the raw key from stdin (e.g., `echo $GEMINI_API_KEY | dejaq-admin seed demo --provider-key-stdin google`), OR
2. The `DEJAQ_SEED_PROVIDER_KEY` environment variable in `<provider>:<key>` format.

The system SHALL NOT accept the raw key as a literal argv value, because argv values are captured by shell history, `ps auxe`, container inspect output, and CI logs - exposing the key. After all other seed steps complete, the command SHALL upsert the provided key as an encrypted provider credential for the demo org. If `DEJAQ_CREDENTIAL_ENCRYPTION_KEY` is not set when a provider key is supplied, the command SHALL print a warning and skip the credential upsert rather than exiting with an error.

#### Scenario: Demo seed creates the demo org
- **WHEN** setup runs
- **THEN** SQLite contains the default demo organization

#### Scenario: Demo seed creates departments
- **WHEN** the demo seed completes
- **THEN** the default demo organization contains one or two departments with stable names, slugs, and cache namespaces

#### Scenario: Demo seed is idempotent
- **WHEN** the demo seed is run twice
- **THEN** there is still exactly one demo user, one default demo organization, one membership between them, and one row per seeded department

#### Scenario: Demo seed with provider key via stdin upserts credential
- **WHEN** `echo AIzaXXXXXXXXX | dejaq-admin seed demo --provider-key-stdin google` is run and `DEJAQ_CREDENTIAL_ENCRYPTION_KEY` is set
- **THEN** the demo org has an encrypted `google` credential in `org_provider_credentials`
- **THEN** rerunning the command replaces the credential rather than creating a duplicate

#### Scenario: Demo seed with provider key via env var upserts credential
- **WHEN** `dejaq-admin seed demo` is run with `DEJAQ_SEED_PROVIDER_KEY=google:AIzaXXXXXXXXX` and `DEJAQ_CREDENTIAL_ENCRYPTION_KEY` set
- **THEN** the demo org has an encrypted `google` credential in `org_provider_credentials`

#### Scenario: Demo seed never accepts the raw key on argv
- **WHEN** an operator attempts to pass the key as a literal argv value (any flag form that places the key in argv)
- **THEN** the command rejects the input with a clear error pointing to `--provider-key-stdin` or `DEJAQ_SEED_PROVIDER_KEY`

#### Scenario: Demo seed with provider key skips on missing encryption key
- **WHEN** a provider key is supplied via stdin or env var and `DEJAQ_CREDENTIAL_ENCRYPTION_KEY` is NOT set
- **THEN** the command prints a warning and completes the rest of the seed without error
- **THEN** no credential row is inserted

### Requirement: Demo seed populates sample dashboard stats
The system SHALL populate enough sample request-log rows for the default demo organization and departments to make management stats views non-empty immediately after setup. The sample rows SHALL include both cache hits and misses and at least one easy and one hard miss.

Sample stats SHALL be written to `DEJAQ_STATS_DB` using the same `requests` schema used by `RequestLogger`. The seed path SHALL initialize or create that stats schema before inserting sample rows. Seeded rows SHALL have deterministic seed identifiers, for example `response_id` values prefixed with `demo-seed:`, and reruns SHALL replace or skip existing seeded rows so the sample batch count remains stable.

#### Scenario: Demo dashboard has org stats
- **WHEN** the demo user signs in and calls `GET /admin/v1/stats/orgs`
- **THEN** the response includes the default demo organization with non-zero request totals

#### Scenario: Demo dashboard has department stats
- **WHEN** the demo user signs in and calls `GET /admin/v1/stats/orgs/{demo_slug}/departments`
- **THEN** the response includes the seeded departments with non-zero request totals

#### Scenario: Demo stats seed initializes stats schema
- **WHEN** the demo seed runs before FastAPI has created the request-log table
- **THEN** the seed initializes the `DEJAQ_STATS_DB` request-log schema before inserting sample rows

#### Scenario: Demo stats seed is idempotent
- **WHEN** the demo seed is run twice
- **THEN** seeded stats rows are not duplicated
- **THEN** the sample stats batch count remains stable

### Requirement: Demo seed setup is documented
`CLAUDE.md` SHALL document that the management API needs no sign-in or credential setup (loopback-bound, unauthenticated dev-admin context), the environment variables or credentials needed for demo seeding, and `DEJAQ_CREDENTIAL_ENCRYPTION_KEY` in the environment variable table (with a backup-or-lose-everything warning), and SHALL include both the `--provider-key-stdin` flag and the `DEJAQ_SEED_PROVIDER_KEY` env var usage for `dejaq-admin seed demo`.

#### Scenario: Developer can find setup steps
- **WHEN** a developer reads `CLAUDE.md`
- **THEN** they can identify that the management API requires no login and how to seed demo data

#### Scenario: Documentation states gateway is unaffected
- **WHEN** a developer reads the management auth documentation in `CLAUDE.md`
- **THEN** it states that `/v1/chat/completions` continues to use DejaQ org API keys

#### Scenario: Documentation covers credential encryption key
- **WHEN** a developer reads `CLAUDE.md`
- **THEN** they can find `DEJAQ_CREDENTIAL_ENCRYPTION_KEY` in the environment variable table with a description of how to generate it
- **THEN** they can find the `--provider-key-stdin` and `DEJAQ_SEED_PROVIDER_KEY` usage for seeding the demo org's external LLM credential without exposing the key on argv
