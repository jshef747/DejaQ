## ADDED Requirements

### Requirement: Operator can create an organization
The system SHALL allow an operator to create a new organization by providing a name. The system SHALL derive a URL-safe slug from the name and store it alongside a UUID and creation timestamp in Supabase. Org slugs SHALL be globally unique; the system SHALL reject duplicates.

#### Scenario: Successful org creation
- **WHEN** operator runs `dejaq-admin org create --name "Acme Corp"`
- **THEN** a new row is inserted into the `organizations` table with a generated UUID, name `"Acme Corp"`, slug `"acme-corp"`, and `created_at` timestamp
- **THEN** the CLI prints the new org's id, name, and slug

#### Scenario: Duplicate slug rejected
- **WHEN** operator runs `dejaq-admin org create --name "Acme Corp"` and an org with slug `"acme-corp"` already exists
- **THEN** the system raises a unique-constraint violation
- **THEN** the CLI prints an error message and exits with a non-zero status code

### Requirement: Operator can list organizations
The system SHALL allow an operator to retrieve all organizations stored in Supabase, ordered by creation time (newest first).

#### Scenario: List with existing orgs
- **WHEN** operator runs `dejaq-admin org list`
- **THEN** the CLI prints a table with id, name, slug, and created_at for each org

#### Scenario: List with no orgs
- **WHEN** operator runs `dejaq-admin org list` and no orgs exist
- **THEN** the CLI prints a message indicating no organizations found

### Requirement: Operator can delete an organization
The system SHALL allow an operator to delete an organization by its slug or id. Deletion SHALL cascade to all departments belonging to that org.

#### Scenario: Successful org deletion
- **WHEN** operator runs `dejaq-admin org delete --slug "acme-corp"`
- **THEN** the org row and all its department rows are deleted from Supabase
- **THEN** the CLI prints a confirmation message including how many departments were removed

#### Scenario: Delete non-existent org
- **WHEN** operator runs `dejaq-admin org delete --slug "does-not-exist"`
- **THEN** the CLI prints an error indicating the org was not found and exits with a non-zero status code

#### Scenario: Cascade warning displayed
- **WHEN** operator deletes an org that has one or more departments
- **THEN** the CLI prints a warning listing the department slugs that will be deleted before proceeding
