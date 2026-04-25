# CLI / API Parity Matrix

This matrix defines business-behavior parity between `dejaq-admin`, shared services, and `/admin/v1/*`. CLI-only presentation such as prompts, spinners, Rich panels, and table colors remains owned by the CLI.

| CLI leaf command | Shared service | HTTP route | Options / inputs | Special behavior |
| --- | --- | --- | --- | --- |
| `org list` | `admin_service.list_orgs()` | `GET /admin/v1/orgs` | none | Returns `{id, name, slug, created_at}` for each org. |
| `org create <name>` | `admin_service.create_org(name)` | `POST /admin/v1/orgs` | body `{name}` | Duplicate derived slug raises `DuplicateSlug`; API maps to `409`. |
| `org delete <slug>` | `admin_service.delete_org(slug)` | `DELETE /admin/v1/orgs/{slug}` | path `slug` | CLI owns confirmation prompt. Service returns `OrgDeleteResult(deleted, departments_removed)` and deletes departments, API keys, and LLM config. |
| `dept list [--org <slug>]` | `admin_service.list_departments(org_slug=None)` | `GET /admin/v1/departments?org=...` | optional `org` filter | Unscoped list returns departments across all orgs with `org_slug`. |
| `dept create <org> <name>` | `admin_service.create_department(org_slug, name)` | `POST /admin/v1/orgs/{org_slug}/departments` | path `org_slug`, body `{name}` | Unknown org raises `OrgNotFound`; duplicate dept slug raises `DuplicateSlug`. |
| `dept delete <org> <dept>` | `admin_service.delete_department(org_slug, dept_slug)` | `DELETE /admin/v1/orgs/{org_slug}/departments/{dept_slug}` | path `org_slug`, `dept_slug` | CLI owns confirmation prompt. Service returns freed `cache_namespace`. |
| `key list <org>` | `admin_service.list_keys(org_slug)` | `GET /admin/v1/orgs/{org_slug}/keys` | path `org_slug` | Service/API list items expose `token_prefix` only; full token is never returned on list. |
| `key generate <org> [--force]` | `admin_service.generate_key(org_slug, force)` | `POST /admin/v1/orgs/{org_slug}/keys?force=...` | query `force` default false | Without force, active key raises `ActiveKeyExists`; with force, existing active key is revoked first. Create result returns full token exactly once. |
| `key revoke <key_id>` | `admin_service.revoke_key(key_id)` | `DELETE /admin/v1/keys/{key_id}` | path `key_id` | Unknown key raises `KeyNotFound`; already-revoked key returns `already_revoked=true`. |
| `stats` | `stats_service.org_stats()`, `stats_service.department_stats()` | `GET /admin/v1/stats/orgs`, `GET /admin/v1/stats/orgs/{org_slug}/departments` | optional `from`, `to` dates on API | Request-log aggregate numbers match for the same window. CLI Cache Health panel remains CLI-only. |
| none | `llm_config_service.read_for_org()`, `llm_config_service.update_for_org()` | `GET/PUT /admin/v1/orgs/{org_slug}/llm-config` | path `org_slug`, body subset of config fields | API-only management surface. Omitted fields preserve, explicit `null` clears override, empty update returns `422`. |
| none | feedback service | `GET/POST /admin/v1/feedback` | list filters; submit body `{org, department?, response_id, rating, comment?}` | Admin submit uses explicit attribution; public `/v1/feedback` continues to use org-key-derived context. |
