# First contact with the HappyRobot org — what the API actually returns

*2026-09-19, ~00:30. Org **HackSpain – Team 10** (`hackspainteam10`, tier enterprise, **EU region**). Key "Angryrobots". Tools: `hr_explore.py`, `hr_probe_chat.py`, `hr_watch.py listen`. Raw dumps in `explore/` (gitignored).*

## Environment facts

| Fact | Value |
|---|---|
| Base URL | **`https://platform.eu.happyrobot.ai/api/v2`** — the US host answers `401 invalid or revoked` for an EU key. `HR_BASE` is set in `.env`. |
| Key scope | Org-scoped with permissions: `GET /org/members/` → `403 API key cannot perform action workspace.member.view`. Everything else we tried is allowed, incl. creating workflows, credentials, publishing. |
| Org state at start | 1 empty workflow ("test", unpublished), 0 runs, 0 contacts, 0 phone numbers, 0 KBs, 0 MCP servers, Twin **not provisioned** (`404 Twin database not available`). |
| Catalogue | 6 templates (`voice-agent`, `inbound-voice-agent`, `whatsapp-agent`, `sms-agent`, `email-agent`, `chatbot-agent`); 100+ integrations in groups accounting/ats/authentication/built-in/communications/crm/data/filestorage/hris/mcp/ticketing; 141 voices (HappyRobot's own `v3` family, es-ES incl.). |
| Realtime JWT | HS256, claims `{channel, org_id, use_case_id, exp}` — still no WS host. |
| Quirks | `/audits/node-errors` → 500 on an empty workflow; `/billing/usage/credits` needs `start_date/end_date`; one `POST /chat/.../messages` hit a Cloudflare 502 (message lost, no retry by the platform). |

## The probe loop works end-to-end by API (no phone number, no UI)

`POST /workflows/ {from_template: chatbot-agent, inputs:{agent_name, prompt:{prompt_md, initial_message}}}` → 201 with `latest_version` → `POST /versions/{id}/publish {environment}` → `POST /chat/tokens/ {workflow_id, data}` → chat token → `POST /chat/sessions/` (Bearer = chat token) → `POST /chat/sessions/{id}/messages {content}` → poll `GET /chat/sessions/{id}/history` → `POST /chat/sessions/{id}/close`. Replies arrive in ~3 s. Cost of a 4-turn chat: **3.39 credits** (Texting 3.24 = Chatbot orchestration 2.4 + LLM 0.84; Run 0.15).

Template graph: `action:Trigger (Chatbot Request)` → `action:Inbound Text Agent` → child `prompt:Prompt`. Default model `{"type":"static","static":{"id":"gpt-5.6-luna-max","name":"gpt-5.6-luna"}}`.

Behaviour of the default agent under our first red-team turns: refused the "ignore instructions / 900 EUR / other carriers" injection, answered "I'm an AI" honestly, refused to confirm a booking it hadn't made. Good baseline — the rogue behaviour will have to be induced (or scripted via the inline model).

## What each record contains (per run)

| Record | Notable fields |
|---|---|
| Trigger node output | `data` = the chat-token `data{}` we passed + `text_session_id`; **`input{}` = `current.run_id`, `current.use_case_id`, `current.version_id`, `current.run_url`, `current.org_id`, `execution_environment`, `time.*`** |
| Inbound Text Agent output | `session_id`, `status`, `duration`, `channel{type: pusher}`, `close_reason` (`client_closed`), `transcript` (plain text) and **`transcript_entries[]`** `{id, role, content, timestamp}`, `tools_result[]`, `message_direction`, `error{code,details,message,category}` |
| Prompt node output | `data{prompt, initial_message, prompt_components}` only — *no per-turn model I/O here* |
| Session | `type: text`, `status: canceled` (when client closes), `llm_model: gpt-5.6-luna`, `duration`, `failure_reason` |
| Message | `{id, session_id, role: assistant|user|event, status: sent, content, timestamp, is_filler, is_interrupted, tool_calls, artifacts, turn_index (null for text)}`; an `event` message `session_closed` ends the list |
| Run | `status completed`, `input_tokens/output_tokens` (782/404), `annotation null`, `is_e2e_test` |
| Credits | L1→L3 taxonomy as documented |

**Not present anywhere:** the exact prompt the model received per turn, tool schemas offered, the model's raw completion. → Only the **inline** position sees model inputs/outputs; the API sees transcripts and node payloads.

## Correlation solved: prompt variables

`GET /versions/{v}/nodes/{prompt}/available-vars` exposes `current.run_id`, `current.use_case_id`, `current.version_id`, `current.run_url`, `current.org_id`, and a text-session id, plus integration variables (`transfer.*`). A guard-managed prompt can end with `\n[ar] run={{current.run_id}} session={{…}}` — the inline proxy strips it and gets exact ids for the levers.

## Custom LLM Server — status

- It is an **integration** (`019d75d2-9590-75c3-a924-dc1afbd61000`, group data, `agent_specific: true`, "Bring your own OpenAI-compatible endpoint for headless voice agents"). Credential form: `endpoint` (…/v1), `auth_type` bearer|oauth2, `api_key`, `oauth2_credential_id`.
- **Created via API**: `POST /integrations/{id}/create-credential {credential_type:"endpoint", title, data:{endpoint, auth_type:"bearer", api_key}}` → credential `01a0b6a3-73ef-7dd2-9b46-01a91e6b744a` pointing at our cloudflared tunnel (`hr_watch.py listen --reply say`, verified reachable; QUIC was blocked, `--protocol http2` works).
- **Unknown: the `model.static.id` that binds a prompt node to it.** `PUT /versions/{v}/nodes/{n}` accepts *any* id without validation; an invalid id (we tried the credential uuid) makes the text agent **silently ignore user messages** — no error in run nodes, session `llm_model: null`. Publishing the same version twice → `400 Version is already live` (fork per attempt).
- Hypotheses left: the builder writes a specific id (e.g. `custom-llm`, `custom-llm/<cred>`), or Custom LLM only applies to **voice** agent nodes (per its description) and the chatbot path ignores it. Fastest resolution: set it once in the builder UI on the voice probe and read the node back.

## Probe assets in the org (safe to delete later)

| Workflow | id | slug | purpose |
|---|---|---|---|
| angryrobots-probe-chat | `01a0b6a2-0c9b-70cd-a5c9-a8396a514f59` | `ox39o9gqzovu` | API-driven text conversations; live version restored to `gpt-5.6-luna-max` |
| angryrobots-probe-voice | `01a0b6a6-712c-7a1c-a7e2-dcbbfe861a6d` | `7ll3viyfja9a` | inbound voice via web call (LiveKit) — for the Custom-LLM test |

## Next

1. Learn the Custom-LLM model id (UI once → API forever) and confirm the capture endpoint receives `messages[] + tools[]`.
2. Drive the voice probe headlessly: `POST /voice/tokens/ {workflow_id}` → LiveKit room; inject `say`-synthesised speech with the LiveKit Python SDK → fully automated voice red-teaming.
3. Turn `hr_probe_chat.py` into the red-team runner (scenario files) and start filling the ledger.
