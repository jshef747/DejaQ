## MODIFIED Requirements

### Requirement: Every chat request is logged after response is sent

The system SHALL continue logging completed chat requests. In addition, request logging SHALL support escalation-generated answers by recording:

- `source`: `chat` or `feedback_escalation`
- `interaction_id`
- optional `parent_interaction_id`
- `served_tier`
- `model_used`
- org and department
- latency
- whether an external provider was used

If the current request log schema cannot store these fields, the system SHALL add compatible nullable columns or an equivalent escalation log table during startup.

#### Scenario: Normal chat request is logged with source

- **WHEN** a normal chat request completes
- **THEN** the request log stores `source="chat"` and the response `interaction_id`

#### Scenario: Escalation request is logged with parent interaction

- **WHEN** feedback escalation generates a new answer
- **THEN** the request log stores `source="feedback_escalation"`, the new answer's `interaction_id`, and the rejected answer's `parent_interaction_id`

#### Scenario: External escalation is visible in usage analytics

- **WHEN** a local-tier answer is escalated to an external provider
- **THEN** the request log records the external model/provider usage so cost and usage reports can include it
