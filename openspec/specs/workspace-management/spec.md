## ADDED Requirements

### Requirement: Operator can create a workspace
The system SHALL allow an operator to create a new workspace by providing a name. The system SHALL derive a URL-safe slug from the name and store it alongside an autoincrementing integer id and a creation timestamp in SQLite. Workspace slugs SHALL be globally unique; the system SHALL reject duplicates.

#### Scenario: Successful workspace creation
- **WHEN** operator runs `dejaq-admin workspace create --name "Acme Corp"`
- **THEN** a new row is inserted into the `workspaces` table with a generated integer id, name `"Acme Corp"`, slug `"acme-corp"`, and `created_at` timestamp
- **THEN** the CLI prints the new workspace's id, name, and slug

#### Scenario: Duplicate slug rejected
- **WHEN** operator runs `dejaq-admin workspace create --name "Acme Corp"` and a workspace with slug `"acme-corp"` already exists
- **THEN** the system raises a unique-constraint violation
- **THEN** the CLI prints an error message and exits with a non-zero status code

### Requirement: Operator can list workspaces
The system SHALL allow an operator to retrieve all workspaces stored in SQLite, ordered by creation time (newest first).

#### Scenario: List with existing workspaces
- **WHEN** operator runs `dejaq-admin workspace list`
- **THEN** the CLI prints a table with id, name, slug, and created_at for each workspace

#### Scenario: List with no workspaces
- **WHEN** operator runs `dejaq-admin workspace list` and no workspaces exist
- **THEN** the CLI prints a message indicating no workspaces found

### Requirement: Operator can delete a workspace
The system SHALL allow an operator to delete a workspace by its slug or id. Deletion SHALL cascade to all departments belonging to that workspace.

#### Scenario: Successful workspace deletion
- **WHEN** operator runs `dejaq-admin workspace delete --slug "acme-corp"`
- **THEN** the workspace row and all its department rows are deleted from SQLite
- **THEN** the CLI prints a confirmation message including how many departments were removed

#### Scenario: Delete non-existent workspace
- **WHEN** operator runs `dejaq-admin workspace delete --slug "does-not-exist"`
- **THEN** the CLI prints an error indicating the workspace was not found and exits with a non-zero status code

#### Scenario: Cascade warning displayed
- **WHEN** operator deletes a workspace that has one or more departments
- **THEN** the CLI prints a warning listing the department slugs that will be deleted before proceeding
