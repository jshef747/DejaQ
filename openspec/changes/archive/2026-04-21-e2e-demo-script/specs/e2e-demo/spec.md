## ADDED Requirements

### Requirement: Single-command execution
The script SHALL be executable as a single command (`./scripts/demo.sh`) from the repo root without requiring any arguments.

#### Scenario: Run with no arguments
- **WHEN** the user runs `./scripts/demo.sh` from the repo root
- **THEN** the demo executes all steps in sequence and exits with code 0 on success

#### Scenario: Server not reachable
- **WHEN** the FastAPI server is not running on `http://127.0.0.1:8000`
- **THEN** the script prints a clear error message and exits with code 1 before making any changes

### Requirement: Narrated step output
Each step SHALL print a header line announcing what it is about to do before executing, so an observer can follow along without prior knowledge of DejaQ.

#### Scenario: Step announcement visible before action
- **WHEN** the script is about to create an org
- **THEN** it prints a labeled step header (e.g., `[Step 1/6] Creating demo organization`) before invoking `dejaq-admin org create`

### Requirement: Org and department setup
The script SHALL create one demo organization and two departments under it using the `dejaq-admin` CLI.

#### Scenario: Org created successfully
- **WHEN** the script runs step 1
- **THEN** `dejaq-admin org create` is called and a demo org slug is captured from the output

#### Scenario: Two departments created
- **WHEN** the script runs step 2
- **THEN** `dejaq-admin dept create` is called twice, creating departments `engineering` and `product` under the demo org

### Requirement: API key generation and capture
The script SHALL generate an API key for the demo org and capture the token value for use in subsequent HTTP requests.

#### Scenario: Key generated and token extracted
- **WHEN** `dejaq-admin key generate --org <slug>` succeeds
- **THEN** the script extracts the token string from the CLI output and stores it in a variable

### Requirement: Cache miss demonstration
The script SHALL fire a chat completion request to `/v1/chat/completions` and confirm it is a cache miss (no `X-DejaQ-Response-Id` header, or a fresh store).

#### Scenario: First request is a cache miss
- **WHEN** the script sends a request with a query not previously in the cache
- **THEN** the server returns a 200 response and the script reports "Cache MISS" to the terminal

### Requirement: Cache hit demonstration
The script SHALL fire the identical request a second time (after a short wait for background generalization) and confirm it is a cache hit via the `X-DejaQ-Response-Id` response header.

#### Scenario: Second request is a cache hit
- **WHEN** the script sends the same request a second time after waiting at least 2 seconds
- **THEN** the response includes the `X-DejaQ-Response-Id` header and the script reports "Cache HIT" to the terminal

#### Scenario: Second request misses unexpectedly
- **WHEN** the `X-DejaQ-Response-Id` header is absent on the second request
- **THEN** the script prints a warning ("Cache miss on second request — system may still be loading models") but does not exit with an error

### Requirement: Stats TUI display
The script SHALL launch `dejaq-admin stats` as the final step so the user can see hit rate, latency, and model breakdown.

#### Scenario: Stats TUI launched
- **WHEN** all prior steps complete
- **THEN** the script prints instructions ("Press q to exit stats") and launches `dejaq-admin stats`

### Requirement: Idempotent cleanup
By default, the script SHALL delete the demo org (and all its departments) on exit, so it can be run repeatedly without leaving stale data.

#### Scenario: Cleanup on normal exit
- **WHEN** the script exits normally after the stats TUI is closed
- **THEN** `dejaq-admin org delete --slug <demo-slug>` is called automatically

#### Scenario: Cleanup on interrupt
- **WHEN** the user presses Ctrl+C during the demo
- **THEN** the EXIT trap fires and the demo org is deleted

#### Scenario: Keep flag skips cleanup
- **WHEN** the script is run with `--keep`
- **THEN** the demo org and departments are left in place after the script exits
