## ADDED Requirements

### Requirement: Operator can create a department under an org
The system SHALL allow an operator to create a department by providing a name and a parent org (by slug or id). The system SHALL derive a slug from the department name, construct a `cache_namespace` as `"{org_slug}__{dept_slug}"`, and store all fields in Supabase. Department slugs SHALL be unique within their parent org.

#### Scenario: Successful department creation
- **WHEN** operator runs `dejaq-admin dept create --org "acme-corp" --name "Customer Support Bot"`
- **THEN** a new row is inserted into the `departments` table with a generated UUID, org_id referencing acme-corp, name `"Customer Support Bot"`, slug `"customer-support-bot"`, and `cache_namespace` `"acme-corp__customer-support-bot"`
- **THEN** the CLI prints the new department's id, name, slug, and cache_namespace

#### Scenario: Duplicate dept slug within org rejected
- **WHEN** operator creates a department whose slug already exists under the same org
- **THEN** the system raises a unique-constraint violation
- **THEN** the CLI prints an error and exits with a non-zero status code

#### Scenario: Same dept slug allowed in different orgs
- **WHEN** two orgs each have a department with the same slug
- **THEN** both rows are stored successfully because uniqueness is scoped to (org_id, slug)

#### Scenario: Parent org not found
- **WHEN** operator runs `dejaq-admin dept create --org "nonexistent-org" --name "Foo"`
- **THEN** the CLI prints an error indicating the org was not found and exits with a non-zero status code

### Requirement: Operator can list departments
The system SHALL allow an operator to list all departments, optionally filtered by org slug.

#### Scenario: List departments for a specific org
- **WHEN** operator runs `dejaq-admin dept list --org "acme-corp"`
- **THEN** the CLI prints a table with id, name, slug, cache_namespace, and created_at for each department belonging to acme-corp

#### Scenario: List all departments across all orgs
- **WHEN** operator runs `dejaq-admin dept list` with no org filter
- **THEN** the CLI prints all departments with an additional org_slug column

#### Scenario: No departments found
- **WHEN** the filtered (or global) query returns no rows
- **THEN** the CLI prints a message indicating no departments found

### Requirement: Operator can delete a department
The system SHALL allow an operator to delete a department by its slug within a given org.

#### Scenario: Successful department deletion
- **WHEN** operator runs `dejaq-admin dept delete --org "acme-corp" --slug "customer-support-bot"`
- **THEN** the department row is deleted from Supabase
- **THEN** the CLI prints a confirmation message with the department's cache_namespace

#### Scenario: Delete non-existent department
- **WHEN** operator runs `dejaq-admin dept delete` for a slug that does not exist under the given org
- **THEN** the CLI prints an error indicating the department was not found and exits with a non-zero status code

### Requirement: cache_namespace is stable and unique across all orgs
The system SHALL guarantee that every department's `cache_namespace` is globally unique. Because org slugs are globally unique and dept slugs are unique per org, the composite `"{org_slug}__{dept_slug}"` SHALL be globally unique without an additional DB constraint.

#### Scenario: Namespace isolation
- **WHEN** two departments exist with cache_namespaces `"acme-corp__support"` and `"beta-inc__support"`
- **THEN** ChromaDB queries scoped to `"acme-corp__support"` SHALL NOT return entries stored under `"beta-inc__support"`
