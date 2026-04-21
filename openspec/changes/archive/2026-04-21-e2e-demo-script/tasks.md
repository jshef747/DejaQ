## 1. Scaffold

- [x] 1.1 Create `scripts/` directory in repo root
- [x] 1.2 Create `scripts/demo.sh` with shebang, `set -euo pipefail`, and color variable definitions
- [x] 1.3 Add `--keep` flag parsing (using `getopts` or argument scan loop)
- [x] 1.4 Add server health check (`curl -sf http://127.0.0.1:8000/health`) with fail-fast error message if not reachable
- [x] 1.5 Add EXIT trap that calls a `cleanup` function (deletes demo org unless `--keep`)

## 2. Step Narration Helper

- [x] 2.1 Write a `step` shell function that prints a formatted step header (`[Step N/6] <description>`) with color

## 3. Org and Department Setup (Steps 1–2)

- [x] 3.1 Step 1: call `dejaq-admin org create --name "DejaQ Demo"` and capture the org slug from output
- [x] 3.2 Use a timestamped or fixed slug (`dejaq-demo`) — detect existing org and reuse if present (handles repeated `--keep` runs)
- [x] 3.3 Step 2: call `dejaq-admin dept create --org <slug> --name "Engineering"` and `--name "Product"`

## 4. API Key Generation (Step 3)

- [x] 4.1 Step 3: call `dejaq-admin key generate --org <slug>` and extract the token from CLI output using `grep`/`awk`
- [x] 4.2 Print the captured token (masked to first 12 chars) to confirm capture succeeded

## 5. Cache Miss Request (Step 4)

- [x] 5.1 Step 4: fire `curl` POST to `/v1/chat/completions` with `Authorization: Bearer <token>`, `X-DejaQ-Department: engineering`, and a simple query ("What is the boiling point of water?")
- [x] 5.2 Capture response headers and body; check for absence of `X-DejaQ-Response-Id` (or presence with a note) to report MISS
- [x] 5.3 Print "Cache MISS — request forwarded to LLM" with the first 80 chars of the response content

## 6. Wait and Cache Hit Request (Step 5)

- [x] 6.1 Print "Waiting 3 seconds for background generalization..." and `sleep 3`
- [x] 6.2 Step 5: fire the identical request again with the same query and token
- [x] 6.3 Check for `X-DejaQ-Response-Id` header in the response; print "Cache HIT" if present, print warning (non-fatal) if still a miss

## 7. Stats TUI (Step 6)

- [x] 7.1 Step 6: print "Launching stats dashboard — press q to exit" then exec `dejaq-admin stats`
- [x] 7.2 After stats exits, print demo completion message

## 8. Cleanup and Polish

- [x] 8.1 Implement `cleanup` function: if `--keep` is not set, run `dejaq-admin org delete --slug <slug>` (non-interactive, skip confirm prompt or pipe `y`)
- [x] 8.2 Make script executable: `chmod +x scripts/demo.sh`
- [x] 8.3 Add a usage/help block printed when `--help` is passed
- [x] 8.4 Add a brief "What just happened" summary printed before the stats TUI that recaps each step result
- [ ] 8.5 Test full run on a clean database: confirm org/dept/key created, MISS on first, HIT on second, stats show ≥1 hit
