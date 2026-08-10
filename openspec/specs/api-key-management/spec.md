## ADDED Requirements

### Requirement: Operator can generate an API key for an org
The system SHALL allow an operator to generate a new API key for an existing org by providing the org slug. The key SHALL be a cryptographically random URL-safe token (32 bytes, `secrets.token_urlsafe(32)`). It SHALL be stored in the `api_keys` table with the org's `id`, a UUID primary key, `created_at`, and `revoked_at = NULL`. An org MAY have at most one active (non-revoked) key at a time; generating a new key when one exists SHALL be rejected unless `--force` is passed (which auto-revokes the existing key first).

#### Scenario: Successful key generation
- **WHEN** operator runs `dejaq-admin key generate --org "acme-corp"`
- **THEN** a new row is inserted into `api_keys` with a UUID id, the acme-corp org_id, a random token, and `revoked_at = NULL`
- **THEN** the CLI prints the key id, org slug, token value, and created_at

#### Scenario: Org not found
- **WHEN** operator runs `dejaq-admin key generate --org "nonexistent"`
- **THEN** the CLI prints an error indicating the org was not found and exits with a non-zero status code

#### Scenario: Org already has an active key (no --force)
- **WHEN** operator runs `dejaq-admin key generate --org "acme-corp"` and acme-corp already has an active key
- **THEN** the CLI prints an error stating an active key exists and suggests `--force` to replace it
- **THEN** no new key is inserted

#### Scenario: Force-replace existing key
- **WHEN** operator runs `dejaq-admin key generate --org "acme-corp" --force` and acme-corp has an active key
- **THEN** the existing key's `revoked_at` is set to the current timestamp
- **THEN** a new key row is inserted
- **THEN** the CLI prints the new token value and a note that the old key was revoked

### Requirement: Operator can list API keys for an org
The system SHALL allow an operator to list all API keys (active and revoked) for a given org slug.

#### Scenario: List active and revoked keys
- **WHEN** operator runs `dejaq-admin key list --org "acme-corp"`
- **THEN** the CLI prints a table with id, token (first 12 chars + `...`), created_at, and revoked_at (or `—` if active) for each key belonging to acme-corp

#### Scenario: No keys found
- **WHEN** the org exists but has no keys
- **THEN** the CLI prints a message indicating no keys found for that org

#### Scenario: Org not found
- **WHEN** operator runs `dejaq-admin key list --org "nonexistent"`
- **THEN** the CLI prints an error and exits with a non-zero status code

### Requirement: Operator can revoke an API key
The system SHALL allow an operator to revoke a specific key by its id, setting `revoked_at` to the current timestamp. Revoked keys SHALL NOT be deleted — they remain in the table for audit purposes.

#### Scenario: Successful revocation
- **WHEN** operator runs `dejaq-admin key revoke --id "<uuid>"`
- **THEN** the row's `revoked_at` is set to the current UTC timestamp
- **THEN** the CLI prints a confirmation with the key id and revocation time

#### Scenario: Key not found
- **WHEN** operator runs `dejaq-admin key revoke --id "<nonexistent-uuid>"`
- **THEN** the CLI prints an error and exits with a non-zero status code

#### Scenario: Key already revoked
- **WHEN** operator runs `dejaq-admin key revoke --id "<uuid>"` for a key with a non-NULL `revoked_at`
- **THEN** the CLI prints a warning that the key was already revoked and exits cleanly (no change to DB)

### Requirement: API key table persists across server restarts
The `api_keys` table SHALL be managed by Alembic so it is created via migration, not ad-hoc DDL.

#### Scenario: Migration creates table
- **WHEN** `alembic upgrade head` is run on a database without the `api_keys` table
- **THEN** the table is created with columns: id (TEXT PK), org_id (TEXT FK → orgs.id), token (TEXT UNIQUE NOT NULL), created_at (DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP), revoked_at (DATETIME NULL)
