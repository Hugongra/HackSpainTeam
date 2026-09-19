# HappyRobot all-layers watcher — research notes

*Researched 2026-09-18 for the HackSpain HappyRobot track. Source of truth is the public OpenAPI spec
(`platform.happyrobot.ai/api/v2/docs/json`, saved as [`happyrobot-api-v2.openapi.json`](happyrobot-api-v2.openapi.json));
the docs site is access-code gated so everything below is from the spec + HappyRobot's public GitHub repos.*

## Access model

| | |
|---|---|
| Base URL | `https://platform.happyrobot.ai/api/v2` (EU: `platform.eu.happyrobot.ai`) |
| Auth | `Authorization: Bearer <API key>` — opaque, **org-scoped**. `GET /api-key/describe` returns org + key metadata. |
| Scope | Every endpoint derives `org_id` from the key. A watcher sees *all layers of its own org*, never other tenants. |
| Surface | 179 paths / ~205 ops. Runtime data plane + builder plane + testing/audit plane + Twin (SQL) plane. |
| Legacy | `v1` and `/runs/?use_case_id=` + `/use-cases/` are deprecated; "use case" == "workflow". |

## The object tree a watcher can walk

```
Org
└─ Workflow (id, slug, latest_version{is_live, environment, workflow_version 2|3})
   ├─ Version ─ Node[] (type: prompt | tool | condition | path | loop | loop_break | loop_end | cron | module-change)
   ├─ Run (status, execution_environment, annotation, input/output_tokens, is_e2e_test, data{})
   │  ├─ RunNode[] + edges[] (execution order, conditional_expr, per-node status/error)
   │  │  └─ Output (full payload: input{}, data{}, tokens incl. cached, session_id, chat_session_id, event_id)
   │  ├─ Session[] (type, status, duration, user_number, call_connected_at, sip_code/reason,
   │  │  │          failure_reason, llm_model, stt_model, tts_model, voice_id, languages[])
   │  │  └─ Message[] (role, content, tool_calls, artifacts, is_filler, is_interrupted, turn_index)
   │  ├─ Recording[] (signed URL per session)
   │  ├─ AuditRemark[] (northstar_name, grade passed|failed|n/a, correction, message_ids[])
   │  ├─ Flag[] (type, priority, correction, correction_reason)
   │  └─ Credits (L1→L2→L3 component taxonomy, total_credits)
   ├─ Issue[] (metric_key/value/threshold, source manual|auto, status)
   ├─ Audit stats (pass_rate_24h, average_run_score) · Node errors (grouped by node × error)
   └─ Northstars / Custom evals / Adversarial tests & suites / E2E scenarios / Test suites
Contact (type, value, contact_summary, extracted_attributes, tags, interactions_count)
└─ Interaction[] (channel, tags, interaction_summary, extracted_attributes) · Memory[] (content)
Twin DB — arbitrary SQL over org tables; `POST /twin/dump` auto-materialises every run variable of a workflow
Signals — pub/sub keys (org.* / usecase.* / session.*) that can target *active* sessions
```

## Transports — how a watcher actually receives data

| # | Transport | Layer | Status | Notes |
|---|---|---|---|---|
| 1 | **Poll REST** | everything | ✅ confirmed | Consistent page/cursor pagination; `GET /workflows/{id}/runs?sort=desc&status=running`. This is the backbone. |
| 2 | **SSE** `GET /sessions/{id}/stream?backfillLimit=N` | messages, live | ✅ route confirmed (401 unauth) | Emits `message` events until the session ends. One stream per session. |
| 3 | **Realtime JWT** `POST /realtime/tokens` | runs firehose, run detail, org conversations, adversarial tests | ⚠️ endpoint confirmed, **WS host unknown** | Channels: `runs_firehose`, `run_detail`, `conversations_org`, `conversation_group`, `adversarial_test`. No route under `/api/v2/realtime*` or obvious subdomains — probably a third-party realtime provider. Decode the JWT claims (`tools/hr_watch.py realtime …` does this) or watch the app's network tab. |
| 4 | **LiveKit audio observer** `POST /voice/tokens/ {session_id, should_takeover:false}` | live audio + LiveKit data/transcription events | ✅ confirmed | Returns `{url, token, room_name, run_id}`. "Hidden, subscribe-only observer, AI agent stays active." `pip install livekit` works. `should_takeover:true` = human takeover. |
| 5 | **Push webhook from the workflow** | whatever the workflow chooses to POST | ✅ (workflow-side) | Add an HTTP-request node (end-of-call etc.) pointing at `tools/hr_watch.py listen` (expose via ngrok/cloudflared). Old python SDK shows the classic shape: `{type: start|end, call{id, metadata{from,to}, extraction, classification}, content{recording | messages, tools}}`. |
| 6 | **Twin SQL** | bulk / historical | ✅ confirmed | `POST /twin/dump {workflowId, tableName}` then `POST /twin/sql`. Capped rows/bytes; `truncated` flag. |
| 7 | **Signals** `POST /signals/` | *into* live sessions | ✅ confirmed | Not observation — but a watcher that *reacts* (e.g. inject a hint into an active call) uses this. |

## What a watcher can compute from this

- **Structure diff**: version/node graph changes over time (who edited the prompt, when it went live).
- **Execution trace per run**: node order + edges + per-node tokens/errors → flame-graph style view of a call.
- **Conversation quality**: transcript + `is_interrupted`/`is_filler` + tool calls + northstar grades + flags → per-call scorecard.
- **Telephony health**: `sip_code`, `failure_reason`, `call_connected_at` vs `timestamp` (ring time), duration distribution.
- **Model mix**: llm/stt/tts/voice per session; token + credit cost per run (`/billing/usage/runs/{id}`).
- **Cross-run memory**: contact summaries, extracted attributes, memories — what the agent "knows" about a caller.
- **Live**: SSE per session for text; LiveKit observer for audio; realtime firehose (once host is known) for run lifecycle.

## Gaps / things to verify with a real key

1. Realtime WS host + message format for `runs_firehose` (decode JWT, or capture from app.happyrobot.ai).
2. Exact SSE event JSON (assumed = Message object).
3. Whether `GET /versions/{id}/nodes` needs a published version (watcher tries live/published first).
4. Rate limits — none documented in the spec (only the SIP-trunk "1 per 10 min" note). Poll at ≥10 s.
5. `data_retention_days` on workflows — outputs may have `data_deleted: true` for old runs.

## Tooling in this repo

- [`tools/hr_watch.py`](../tools/hr_watch.py) — stdlib-only watcher: `whoami`, `map`, `poll`, `stream`, `realtime`, `listen`, `sql`, `get`. Mirrors every layer into `hr_watch.sqlite` + `hr_watch.jsonl` with new/changed detection.
- [`happyrobot-endpoints.md`](02-happyrobot-endpoints.md) — all 179 endpoints grouped by tag.
- Use `/usr/bin/python3` on this Mac (PlatformIO's `python3` on PATH has no CA bundle).

## Action surface — what a HappyRobot agent can actually *do*

Sources: v2 spec node schemas, `happyrobot-ai/custom-llm-server`, happyrobot.ai integrations page, technical-overview blog.

### Tier 0 — in-call controls (built-in tools, sent to the LLM as functions)
`_hangup`, `_stay_silent`, `_voice_mail` (leave message / voicemail detection), `_press_digit` (DTMF/IVR navigation), plus **call transfer** and **sequences** exposed as workflow tool nodes attached to the prompt node. Voice-only.

### Tier 1 — tool nodes attached to the prompt node (LLM-invoked, mid-conversation)
`type: tool` with a `function` {description, parameters[{name, required, binding: agent|fixed}], message: ai|fixed|none, hold_music}. Backed by:
- an **API call** (HTTP request to any endpoint — "anything with an HTTP endpoint")
- an **MCP tool** (`is_mcp`, `mcp_server_credential_id`, `mcp_tool_name`) — org registers MCP servers via `POST /mcp/`, tools are auto-discovered
- **send a message** (SMS/WhatsApp/email/Slack/Teams via the integration layer)
- **custom code**
- **transfer** (warm/cold to a human or number)
- **knowledge-base lookup** (RAG over uploaded files)
`binding: fixed` means the arg is set by the builder, `agent` means the LLM fills it — the latter is the attack surface.

### Tier 2 — action nodes in the workflow graph (deterministic, not LLM-chosen, run before/after/around the conversation)
`type: action` with an `event_id` from the integrations catalogue (`GET /integrations/?include_events=true`; event.type 1 = action, 0 = trigger). Catalogue: **200+ providers** — named: Salesforce, HubSpot, ServiceNow, Zendesk, MongoDB, Redis, Slack, Microsoft Teams, Gmail/Outlook email, Google Sheets, Google Maps, Snowflake, Twilio/Telnyx SMS, WhatsApp Business, DAT, Truckop, Highway, Transport Pro; plus **delegated categories** (CRM, HRIS, ATS… e.g. HubSpot, Workday) routed through a Merge-style unified layer (`_merge_provider_slug`); plus webhooks, and **browser automation** for systems without APIs. Read (contacts, tickets, inventory, order status) and write (log outcomes, update deal stages, create cases, write to DBs).
Control flow: `condition`, `path`, `loop` (`execute_in_parallel`, `do_child_run` — spawns child runs), `loop_break`, `module-change`, `cron`.

### Tier 3 — org/platform-level actions (via API, could be reached by a rogue *builder* agent or MCP)
Trigger runs (`POST /workflows/{id}/runs`), create/publish versions & nodes, purchase/attach phone numbers & SIP trunks, add org members, create integrations credentials, create/drop Twin tables and run SQL, publish signals into live sessions, upload knowledge-base files, run test suites. This is the "builder surface" (~150 ops) — HappyRobot's own MCP servers (`mcp:full`) expose it to AI agents.

### Channels an agent lives on
Voice (inbound/outbound, SIP/WebRTC, BYO carrier), SMS, WhatsApp, Email, web chat (`chatbot-agent`), plus `webhook` / `schedule` triggers. Workflow templates: `voice-agent`, `inbound-voice-agent`, `whatsapp-agent`, `sms-agent`, `email-agent`, `chatbot-agent`.

### Implication for the guard
- Tier 0+1 are the only actions the *LLM chooses* → these pass through the Custom-LLM proxy (Ring 1) and are fully interceptable.
- Tier 2 actions are deterministic graph steps but consume LLM-extracted variables → guard the *variables* (bounds/validation) and, for HTTP actions, point the URL at our forwarding proxy.
- Tier 3 is the blast radius if an agent holds an org API key or MCP `mcp:full` token → scope keys, never give a voice agent's tools org-level access.
