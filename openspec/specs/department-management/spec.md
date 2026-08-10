## ADDED Requirements

### Requirement: cache_namespace is used as the ChromaDB collection name
The system SHALL use a department's `cache_namespace` (e.g. `"acme-corp__customer-support"`) as the ChromaDB collection name when reading or writing cache entries for requests scoped to that department. The `"anonymous/__default__"` namespace SHALL also resolve to a ChromaDB collection of the same name. Collections are created on first use via `get_or_create_collection`.

#### Scenario: Namespace-scoped cache write
- **WHEN** a cache miss occurs for a request with `cache_namespace = "acme-corp__customer-support"`
- **THEN** the generalized response is stored in the ChromaDB collection named `"acme-corp__customer-support"`, not `"dejaq_default"`

#### Scenario: Namespace-scoped cache read
- **WHEN** a cache check occurs for a request with `cache_namespace = "acme-corp__customer-support"`
- **THEN** only entries in the `"acme-corp__customer-support"` collection are queried; entries from other namespaces are never returned

#### Scenario: Default namespace does not bleed into department namespace
- **WHEN** a cached entry exists in `"acme-corp/__default__"` for query Q
- **THEN** a cache check for the same query Q scoped to `"acme-corp__customer-support"` returns a miss
