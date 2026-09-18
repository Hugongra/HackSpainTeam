# HappyRobot Public API v2 — endpoint reference

Generated from the public OpenAPI spec at `https://platform.happyrobot.ai/api/v2/docs/json` (v0.1.1, 179 paths).

- **Base URL:** `https://platform.happyrobot.ai/api/v2` (EU: `https://platform.eu.happyrobot.ai/api/v2`)
- **Auth:** `Authorization: Bearer <API key>` (opaque). All data is scoped to the key's org.
- Full spec: [`happyrobot-api-v2.openapi.json`](happyrobot-api-v2.openapi.json)

## Watcher-relevant endpoints (read side)

| Layer | Endpoint | Notes |
|---|---|---|
| Org | `GET /org/`, `GET /api-key/describe` | self-identify |
| Workflow | `GET /workflows/`, `GET /workflows/{id}`, `GET /workflows/{id}/versions` | latest_version, is_live |
| Graph | `GET /versions/{id}/nodes` | node types: prompt, tool, condition, path, loop, cron… |
| Run | `GET /workflows/{id}/runs?status=&start_date=&sort=desc` | tokens, annotation, env |
| Run detail | `GET /runs/{id}/nodes`, `GET /runs/{id}/outputs/{output_id}` | node exec order + edges; full payloads |
| Session | `GET /runs/{id}/sessions`, `GET /sessions/{id}`, `GET /sessions/?caller_id=` | duration, sip, models, failure_reason |
| Messages | `GET /sessions/{id}/messages` | transcript turns, tool_calls, artifacts |
| Live | `GET /sessions/{id}/stream` (SSE) | `message` events until session ends |
| Live | `POST /realtime/tokens` | channels: runs_firehose, run_detail, conversations_org, conversation_group, adversarial_test — **WS host undocumented** |
| Live audio | `POST /voice/tokens/` with `session_id`, `should_takeover:false` | LiveKit subscribe-only observer |
| Recordings | `GET /runs/{id}/recordings` | signed URLs |
| Quality | `GET /runs/{id}/audits`, `/runs/{id}/flags`, `/workflows/{id}/issues`, `/workflows/{id}/audits/stats`, `/audits/node-errors` | northstar grades, flags |
| Contacts | `GET /contacts/`, `/contacts/{id}/interactions`, `/contacts/{id}/memories` | CRM/memory layer |
| Billing | `GET /billing/usage/totals|details|credits`, `/billing/usage/runs/{id}` | credits per run |
| Twin | `GET /twin/schema`, `POST /twin/sql`, `POST /twin/dump` | raw SQL over org data |

## All endpoints by tag

### API Keys

- `GET /api-key/describe` — Describe the current API key

### Adversarial Suites

- `GET /nodes/{node_id}/adversarial-suites` — List adversarial suites for a node
- `GET /adversarial-suites/{suite_id}` — Get an adversarial suite by ID
- `GET /adversarial-suites/{suite_id}/runs` — List adversarial suite runs
- `GET /adversarial-suites/runs/{suite_run_id}` — Get adversarial suite run by ID
- `GET /adversarial-suites/runs/{suite_run_id}/test-runs` — List test runs in a suite run

### Adversarial Tests

- `GET /nodes/{node_id}/adversarial-tests` — List adversarial tests for a node
- `GET /adversarial-tests/{test_id}` — Get an adversarial test by ID
- `GET /adversarial-tests/{test_id}/runs` — List adversarial test runs
- `GET /adversarial-tests/runs/{run_id}` — Get adversarial test run by ID
- `GET /adversarial-tests/runs/{run_id}/messages` — Get adversarial test run messages
- `GET /adversarial-tests/{test_id}/effective-scope` — Get the resolved audit scope for an adversarial test

### Apps

- `POST /apps/{app_slug}/duplicate` — Duplicate an app

### Artifacts

- `POST /artifacts/download-urls` — Create artifact download URLs
- `POST /artifacts/resolve` — [Deprecated] Resolve artifact download URLs

### Audits

- `GET /workflows/{workflow_id}/audits/northstars` — List northstar audits for a workflow
- `GET /workflows/{workflow_id}/audits/northstars/{northstar_id}/remarks` — List audit remarks for a northstar
- `GET /workflows/{workflow_id}/audits/remarks` — List audit remarks for a workflow
- `GET /workflows/{workflow_id}/audits/node-errors` — List node errors for a workflow
- `GET /workflows/{workflow_id}/audits/stats` — Get audit stats for the live workflow version
- `GET /workflows/{workflow_id}/audits/versions` — List audited versions for a workflow
- `GET /audit-remarks/{audit_remark_id}` — Get an audit remark by ID
- `POST /audit-remarks/{audit_remark_id}/feedback` — Submit feedback for an audit remark
- `GET /audit-remarks/{audit_remark_id}/feedback` — Get feedback for an audit remark
- `DELETE /audit-remarks/{audit_remark_id}/feedback` — Delete feedback for an audit remark

### Billing

- `GET /billing/usage/totals` — Get usage totals
- `GET /billing/usage/details` — Get usage details
- `GET /billing/usage/credits` — Get credits
- `GET /billing/usage/runs/{run_id}` — Get run credits

### Chat

- `POST /chat/tokens/` — Create a chat client token
- `POST /chat/sessions/` — Create a chat session
- `POST /chat/sessions/{id}/messages` — Send a chat message
- `POST /chat/sessions/{id}/close` — Close a chat session
- `GET /chat/sessions/{id}/history` — Get chat session history
- `GET /chat/upload/presigned` — Get presigned upload URL
- `POST /chat/upload/complete` — Complete file upload

### Contacts

- `GET /contacts/resolve` — Lookup contact by identifier
- `GET /contacts/` — List contacts
- `GET /contacts/{contact_id}` — Get contact
- `GET /contacts/{contact_id}/interactions` — List contact interactions
- `GET /contacts/{contact_id}/memories` — List contact memories

### Custom Evals

- `GET /nodes/{node_id}/custom-evals` — List custom evals for a prompt node
- `POST /nodes/{node_id}/custom-evals` — Create a custom eval for a prompt node
- `GET /nodes/{node_id}/custom-evals/tools` — Get available tools for custom evals
- `GET /nodes/{node_id}/custom-evals/default-variables` — Get default variables for custom evals
- `POST /nodes/{node_id}/custom-evals/extract-from-run` — Extract custom eval from a run
- `POST /nodes/{node_id}/custom-evals/folders` — Create a shared Tests folder in a prompt node’s workflow
- `GET /custom-evals/{eval_id}` — Get a custom eval by ID
- `PATCH /custom-evals/{eval_id}` — Update a custom eval
- `DELETE /custom-evals/{eval_id}` — Delete a custom eval
- `POST /custom-evals/{eval_id}/run` — Run a custom eval
- `GET /custom-evals/{eval_id}/runs` — List custom eval runs

### E2E Scenarios

- `GET /e2e-scenarios/`
- `POST /e2e-scenarios/`
- `GET /e2e-scenarios/{scenario_id}`
- `PATCH /e2e-scenarios/{scenario_id}`
- `DELETE /e2e-scenarios/{scenario_id}`
- `POST /e2e-scenarios/{scenario_id}/run`
- `GET /e2e-scenarios/{scenario_id}/runs`

### Events

- `GET /events/{event_id}/config-schema` — Get config schema for an event

### Integration Resources

- `GET /integrations/whatsapp/message-templates` — List WhatsApp message templates
- `GET /integrations/whatsapp/businesses` — List WhatsApp businesses
- `GET /integrations/whatsapp/business-accounts` — List WhatsApp business accounts
- `GET /integrations/whatsapp/phone-numbers` — List WhatsApp phone numbers
- `GET /integrations/slack/channels` — List Slack channels
- `GET /integrations/slack/users` — List Slack users
- `GET /integrations/google-sheets/spreadsheets` — List Google Sheets spreadsheets
- `GET /integrations/google-sheets/worksheets` — List Google Sheets worksheets
- `GET /integrations/google-sheets/columns` — List Google Sheets columns
- `GET /integrations/google-sheets/rows` — List Google Sheets rows
- `GET /integrations/teams/teams` — List Microsoft Teams teams
- `GET /integrations/teams/channels` — List Microsoft Teams channels
- `GET /integrations/teams/users` — List Microsoft Teams users
- `GET /integrations/twilio-sms/phone-numbers` — List Twilio SMS phone numbers
- `GET /integrations/telnyx-sms/phone-numbers` — List Telnyx SMS phone numbers

### Integrations

- `GET /integrations/` — List integrations
- `GET /integrations/categories` — List integration categories with providers
- `GET /integrations/{integrationId}` — Get an integration
- `POST /integrations/{integrationId}/create-credential` — Create a credential for an integration
- `PUT /integrations/{integrationId}/credentials/{credentialId}` — Update a credential for an integration

### Issues

- `GET /workflows/{workflow_id}/issues` — List issues for a workflow
- `PATCH /issues/{issue_id}` — Update issue status

### Knowledge Bases

- `GET /knowledge-bases/`
- `POST /knowledge-bases/`
- `GET /knowledge-bases/{kbId}/files`
- `POST /knowledge-bases/{kbId}/upload-urls`
- `POST /knowledge-bases/{kbId}/trigger-chunking`
- `DELETE /knowledge-bases/{kbId}`
- `DELETE /knowledge-bases/{kbId}/files/{fileId}`

### MCP Servers

- `GET /mcp/` — List MCP servers
- `POST /mcp/` — Create MCP server
- `POST /mcp/{mcpId}/refresh` — Refresh MCP server tools
- `GET /mcp/authorized-orgs` — List authorized organizations

### Messages

- `GET /messages/{message_id}/flags` — List message flags
- `POST /messages/{message_id}/flags` — Create message flag

### Northstars

- `GET /nodes/{node_id}/northstars` — List northstars for a prompt node
- `POST /nodes/{node_id}/northstars` — Create a northstar for a prompt node
- `POST /nodes/{node_id}/northstars/generate` — Generate northstars for a prompt node
- `PATCH /nodes/{node_id}/northstars/batch-toggle` — Batch toggle northstars
- `POST /nodes/{node_id}/northstars/iterate` — Iterate northstars for a prompt node
- `POST /nodes/{node_id}/northstars/assess-coverage` — Assess northstar coverage for a prompt node
- `POST /nodes/{node_id}/northstars/folders` — Create a northstar folder for a prompt node
- `GET /northstars/{northstar_id}` — Get a northstar by ID
- `PATCH /northstars/{northstar_id}` — Update a northstar
- `DELETE /northstars/{northstar_id}` — Delete a northstar
- `GET /northstars/{northstar_id}/history` — Get northstar history
- `POST /northstars/{northstar_id}/feedback` — Submit northstar feedback
- `DELETE /northstars/{northstar_id}/feedback` — Delete northstar feedback

### Organization

- `GET /org/` — Get current organization
- `GET /org/members/` — List members of the current organization
- `POST /org/members/` — Add a member to the current organization
- `DELETE /org/members/` — Remove a member from the current organization

### Phone Numbers

- `GET /phone-numbers/` — List phone numbers
- `POST /phone-numbers/` — Purchase a phone number
- `POST /phone-numbers/validate-toll-free-numbers` — Validate toll-free numbers for TextAgent
- `DELETE /phone-numbers/tollfree-verification/{verification_sid}` — Delete a toll-free verification
- `POST /phone-numbers/free-up-number` — Free up a phone number
- `POST /phone-numbers/delete-number` — Delete a phone number
- `GET /phone-numbers/usage` — Get phone number usage
- `POST /phone-numbers/remove-from-workflow` — Remove phone number from a workflow
- `GET /phone-numbers/tollfree-verification` — Get toll-free verification status
- `POST /phone-numbers/tollfree-verification` — Submit toll-free verification
- `POST /phone-numbers/sip-trunk` — Create and attach SIP trunk
- `PUT /phone-numbers/{id}` — Update a phone number

### Realtime

- `POST /realtime/tokens` — Create a realtime client token

### Runs

- `GET /runs/` — [Legacy] List runs
- `POST /runs/{run_id}/cancel` — Cancel a run
- `GET /runs/{run_id}/recordings` — Get recordings for a run
- `GET /runs/{run_id}/sessions` — List run sessions
- `GET /runs/{run_id}` — Get run
- `GET /runs/{run_id}/nodes` — List run nodes
- `GET /runs/{run_id}/outputs/{output_id}` — Get run output
- `POST /runs/{run_id}/mark` — Mark run annotation
- `GET /runs/{run_id}/flags` — List run flags
- `GET /runs/{run_id}/audits` — List audit remarks for a run

### SIP Trunks

- `GET /sip-trunks/` — List SIP trunks
- `POST /sip-trunks/` — Create a SIP trunk
- `GET /sip-trunks/options` — Get SIP trunk options
- `POST /sip-trunks/bulk` — Create multiple SIP trunks
- `GET /sip-trunks/{id}` — Get a SIP trunk
- `PUT /sip-trunks/{id}` — Update a SIP trunk
- `DELETE /sip-trunks/{id}` — Delete a SIP trunk

### Sessions

- `GET /sessions/` — List sessions by caller ID
- `GET /sessions/{session_id}/stream` — Stream session messages (SSE)
- `GET /sessions/{session_id}` — Get session
- `GET /sessions/{session_id}/messages` — List session messages

### Signals

- `GET /signals/keys` — List signal keys for the org
- `POST /signals/keys` — Add a custom signal key to node
- `DELETE /signals/keys` — Delete a custom signal key from node
- `POST /signals/` — Publish an immediate signal
- `POST /signals/scheduled-signals` — Schedule a delayed signal
- `PATCH /signals/scheduled-signals/{scheduled_signal_id}` — Patch a scheduled signal
- `DELETE /signals/scheduled-signals/{scheduled_signal_id}` — Delete a scheduled signal

### Test Suites

- `GET /test-suites/`
- `POST /test-suites/`
- `GET /test-suites/candidates`
- `GET /test-suites/{suite_id}`
- `PATCH /test-suites/{suite_id}`
- `DELETE /test-suites/{suite_id}`
- `GET /test-suites/{suite_id}/members`
- `PATCH /test-suites/{suite_id}/members`
- `POST /test-suites/{suite_id}/generate`
- `POST /test-suites/{suite_id}/run`
- `GET /test-suites/{suite_id}/runs`
- `GET /test-suites/runs/{run_id}`
- `POST /test-suites/runs/{run_id}/cancel`

### Twin

- `GET /twin/schema` — Get Twin database schema
- `POST /twin/tables` — Create a Twin table
- `GET /twin/tables/{tableName}` — Get Twin table data
- `DELETE /twin/tables/{tableName}` — Drop a Twin table
- `POST /twin/tables/{tableName}/rows` — Insert a row into a Twin table
- `PATCH /twin/tables/{tableName}/rows` — Update a row in a Twin table
- `DELETE /twin/tables/{tableName}/rows` — Delete rows from a Twin table
- `POST /twin/sql` — Execute SQL on Twin database
- `POST /twin/dump` — Create a Twin workflow dump table
- `DELETE /twin/dump/{tableName}` — Delete a Twin workflow dump

### Use Cases

- `GET /use-cases/` — [Legacy] List use cases

### Versions

- `GET /versions/{version_id}/` — Get a version with nodes summary
- `PATCH /versions/{version_id}/` — Update a version
- `POST /versions/{version_id}/fork` — Fork a version
- `POST /versions/{version_id}/publish` — Publish a version
- `POST /versions/{version_id}/lock` — Lock a version
- `POST /versions/{version_id}/unlock` — Unlock a version
- `POST /versions/{version_id}/unpublish` — Unpublish a version
- `GET /versions/{version_id}/nodes` — List version nodes
- `POST /versions/{version_id}/nodes` — Add nodes to a version
- `GET /versions/{version_id}/nodes/{node_id}` — Get a single node
- `PUT /versions/{version_id}/nodes/{node_id}` — Update a node
- `DELETE /versions/{version_id}/nodes/{node_id}` — Delete a node
- `GET /versions/{version_id}/nodes/{node_id}/available-vars` — List available variables for a node
- `GET /versions/{version_id}/nodes/{node_id}/config-schema` — Get config schema for a node
- `PUT /versions/{version_id}/nodes/{node_id}/custom-output` — Set custom node output
- `POST /versions/{version_id}/nodes/{node_id}/test` — Test a single node
- `POST /versions/{version_id}/test-all` — Test all nodes in a version
- `POST /versions/{version_id}/tools/{tool_id}/tool-call-result/inspect` — Inspect a tool's Tool Call Result
- `POST /versions/{version_id}/tools/{tool_id}/tool-call-result/sync` — Sync a tool's Tool Call Result
- `POST /versions/{version_id}/tools/{tool_id}/tool-call-result/generate` — Generate a tool's Tool Call Result
- `PUT /versions/{version_id}/tools/{tool_id}/tool-call-result/visibility` — Set Tool Call Result visibility
- `GET /versions/{version_id}/prompt-issues` — List prompt issues

### Voice

- `GET /voices/` — List available voices
- `POST /voice/tokens/` — Create a voice call token

### Workflow Folders

- `GET /workflow-folders/` — List workflow folders
- `POST /workflow-folders/` — Create a workflow folder
- `GET /workflow-folders/{folder_id}` — Get a workflow folder
- `PUT /workflow-folders/{folder_id}` — Update a workflow folder
- `DELETE /workflow-folders/{folder_id}` — Delete a workflow folder

### Workflow Variables

- `GET /workflows/{workflow_id}/variables` — List workflow variables
- `POST /workflows/{workflow_id}/variables` — Create a workflow variable
- `PATCH /workflows/{workflow_id}/variables/{variable_id}` — Update a workflow variable
- `DELETE /workflows/{workflow_id}/variables/{variable_id}` — Delete a workflow variable

### Workflows

- `GET /workflows/` — List workflows
- `POST /workflows/` — Create a workflow
- `GET /workflows/{workflow_id}` — Get a workflow
- `PATCH /workflows/{workflow_id}` — Update a workflow
- `DELETE /workflows/{workflow_id}` — Delete a workflow
- `GET /workflows/{workflow_id}/versions` — List workflow versions
- `GET /workflows/templates` — List workflow templates
- `POST /workflows/{workflow_id}/duplicate` — Duplicate a workflow
- `POST /workflows/{workflow_id}/publish` — Publish a workflow
- `POST /workflows/{workflow_id}/unpublish` — Unpublish a workflow
- `GET /workflows/{workflow_id}/runs` — List workflow runs
- `POST /workflows/{workflow_id}/runs` — Trigger a workflow run
- `GET /workflows/{workflow_id}/sessions` — List workflow sessions
- `POST /workflows/{workflow_id}/cancel-runs` — Cancel active workflow runs
