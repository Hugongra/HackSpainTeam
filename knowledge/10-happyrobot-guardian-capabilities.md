# Building the guardian *above* HappyRobot — what their API gives us, need by need

*2026-09-19. Source: the public v2 OpenAPI spec (179 paths), `happyrobot-ai/custom-llm-server`, and the team notebook (19 Sep). Companion to 01 (API/action surface), 06 (framework v0), 07 (risk vector).*

**Thesis (from the notebook):** *AngryRobots — the anger-management layer for your agents.* An agentic layer above HappyRobot that (1) monitors what goes into and comes out of the models, (2) computes a **rogue index** per action/session/agent, (3) can shut a conversation down, and (4) investigates the potential impact of what the agent did. Below is everything HappyRobot exposes for each of those, with the honest gaps.

---

## 0. The three positions we can occupy

| Position | Mechanism | Sees | Can act before it happens? | Latency |
|---|---|---|---|---|
| **Inline** | Prompt node → *Model: Custom LLM* → our OpenAI-compatible endpoint | full message history + every tool schema (`_hangup`, `_stay_silent`, `_voice_mail`, `_press_digit`, transfers, sequences, workflow tool nodes) each turn; we return the utterance and the tool calls | **Yes** — nothing is spoken or executed unless we return it | ~100 ms budget |
| **Live observer** | SSE `GET /sessions/{id}/stream`; realtime JWT channels (`runs_firehose`, `run_detail`, `conversations_org`); LiveKit subscribe-only observer via `POST /voice/tokens/ {session_id, should_takeover:false}` | messages as they land (`role, content, tool_calls, is_interrupted, is_filler, turn_index`); `run_detail` events `new_message`, `new_node_output`, `new_session`; raw audio | No — but can intervene within seconds | 1–3 s |
| **Post-hoc auditor** | REST over runs/nodes/outputs/sessions/messages/audits/flags/issues/contacts; Twin SQL; recordings | everything, including per-node **inputs** and full output payloads | No | minutes → days |

The **Custom LLM position is what makes a "layer above" possible without touching HappyRobot's code.** It is configured per prompt node in their builder (Model: Custom LLM, Endpoint URL, API key) — no platform changes, no vendor cooperation needed beyond an org that lets us edit a workflow.

---

## 1. Monitor model INPUTS

| What flows into the model | Where we see it | Notes |
|---|---|---|
| System prompt (`prompt_md`), initial message, model choice | `GET /versions/{id}/nodes/{node_id}` (prompt node: `prompt_md`, `initial_message`, `model` as TemplatedValue) | Version-diffable: `GET /workflows/{id}/versions` + node dumps → detect prompt changes on a live version (config-change trigger) |
| Conversation history per turn | Inline: the `messages[]` HappyRobot POSTs to us. Observer: SSE / `GET /sessions/{id}/messages` | Inline sees exactly what the model sees; observer sees what was persisted |
| Tool schemas offered to the model | Inline: `tools[]` in the request. Static: tool nodes on the version (`function.parameters[].binding: agent|fixed`) | `binding: agent` params are the LLM-controlled attack surface |
| Trigger payload / run variables | `POST /workflows/{id}/runs` body (what an external system injected); `GET /runs/{id}/outputs/{output_id}` → `input{}` per node; `GET /versions/{id}/nodes/{id}/available-vars` | Per-node `input{}` is the closest thing to "what the model was given" for non-prompt nodes |
| Caller context | `session.user_number`, `sip_code`, `languages`; `GET /contacts/resolve?identifier=` → `contact_summary`, `extracted_attributes`, `memories` | Lets us tell "caller's own data" from "someone else's data" (disclosure check) |
| Injection surface | Inline: the latest `user` message. Observer: `role: user` messages | User-turn classifier runs here |
| Knowledge base contents | `GET /knowledge-bases/{kb}/files` | For "did it quote something it shouldn't" — file list only, not chunk-level |

**Gap:** we cannot see the STT layer (audio → text) except as its output; `is_filler`/`is_interrupted` and the `transcriber` flag type are the only transcription-quality signals.

---

## 2. Monitor model OUTPUTS

| What comes out | Where we see it | Notes |
|---|---|---|
| Proposed utterance (before TTS) | **Inline only** — the completion we are about to return | Rewrite / resample / replace with `_stay_silent` |
| Proposed tool calls (before execution) | **Inline only** — `tool_calls` in our completion | Drop, hold, modify args, or substitute `_hangup`/transfer |
| Spoken utterances (after TTS) | SSE stream; `messages[]` with `role: assistant`, `is_interrupted` (barge-in truncated) | Observer path; what the caller actually heard |
| Executed tool calls + results | `messages[].tool_calls`; `GET /runs/{id}/nodes` (per-node `status`, `error`) → `GET /runs/{id}/outputs/{output_id}` (`data{}`, `input{}`, tokens) | Ground truth for "did it really do it" → self-report mismatch |
| Graph actions (Tier 2 nodes: CRM writes, SMS, email…) | `run nodes` + `outputs`; edges with `conditional_expr` | Not LLM-chosen, but consume LLM-extracted variables |
| Node errors, retries | `GET /workflows/{id}/audits/node-errors`; run node `error` | The "error → improvise" trigger |
| Cost / tokens | run `input_tokens/output_tokens`; `GET /billing/usage/runs/{id}` (L1→L3 credits) | Runaway signal |
| Recording | `GET /runs/{id}/recordings` (signed URLs) | Evidence for investigations |
| HappyRobot's own quality verdicts | `GET /runs/{id}/audits` (northstar `grade: passed/failed`), `/runs/{id}/flags`, `/workflows/{id}/issues` (with `metric_key/value/threshold`), `/audits/stats` | Free second opinion; also our calibration ground truth |

---

## 3. SHUT DOWN a conversation / an agent (the levers)

| Lever | Call | Scope | Reversible? | Notes |
|---|---|---|---|---|
| Rewrite / silence this turn | Inline: return edited text or `_stay_silent` | turn | — | Only position that prevents speech |
| Hold a tool | Inline: don't return the tool call; return a hold line | turn | yes | Approval flow with TTL |
| Steer the live session | `POST /signals/ {keys:["session.<id>"], payload}` | session | yes | Requires the workflow to have a signal-listening branch (e.g. inject supervisor note) |
| Human takeover | `POST /voice/tokens/ {session_id, should_takeover:true}` | session | — | Human joins the LiveKit room and takes the call; `false` = silent listen |
| End the call gracefully | Inline: return `_hangup` after a closing line; or transfer tool | session | no | |
| Kill the run | `POST /runs/{run_id}/cancel` | run | no | Hard stop, no goodbye |
| Kill every active run of the agent | `POST /workflows/{id}/cancel-runs {unpublish_workflow: true}` | workflow | unpublish is reversible | **One call = kill switch + take the agent offline** |
| Take the agent offline / roll back | `POST /versions/{id}/unpublish`, `POST /versions/{id}/publish` (previous good), `POST /workflows/{id}/unpublish` | workflow | yes | Version rollback is our "revert to last known good" |
| Detach telephony | `POST /phone-numbers/remove-from-workflow` | number | yes | Nuclear: callers get nothing |
| Freeze a caller | `POST /workflows/{id}/variables` (block-list) + prompt/condition reading it; `contacts.has_blocked_workflows` exists natively | contact | yes | Per-contact containment |
| Revoke a tool's credentials | `PUT /integrations/{id}/credentials/{credId}` | integration | yes | Cuts a Tier 2 action at the source |

**Gap:** no "pause" primitive — a run is running, cancelled, or done. Pause = hold at the inline layer, or takeover.

---

## 4. INVESTIGATE potential impact of an action

| Question | How we answer it |
|---|---|
| What did the agent actually *do* in this call? | `GET /runs/{id}/nodes` (ordered node executions + `edges[]` with `conditional_expr`) → `outputs/{output_id}` for each (full `data{}` and `input{}`) → `messages[].tool_calls` |
| Did it *say* it did something it didn't? | Assistant messages with completion claims vs. successful tool outputs of the matching class (self-report mismatch) |
| What did it commit to? | Assistant messages (rates/dates/guarantees) → commitments ledger; `contacts/{id}/memories` (what HappyRobot itself remembered) |
| Whose data did it touch? | `contacts/resolve` → ownership check on every identifier in assistant text; `interactions` / `extracted_attributes` |
| What downstream systems were written? | Tier 2 action nodes in `run nodes` with their integration `event_id` (`GET /integrations/?include_events=true` → provider/category) |
| How much did it cost / how long did it run? | `billing/usage/runs/{id}`, session `duration`, run `completed_at - timestamp` |
| Has this caller / pattern appeared before? | `GET /sessions/?caller_id=`; `contacts/{id}/interactions`; Twin SQL over `POST /twin/dump` tables (every run variable materialised) |
| Is it one run or the whole version? | `GET /workflows/{id}/runs?status=&start_date=` across runs; `audits/stats`, `audits/node-errors`, `issues` per version |
| Evidence pack for humans | recordings (signed URL), transcript (`messages`), node trace, HappyRobot audit remarks, our ledger |
| Write findings back | `POST /runs/{id}/mark {annotation: incorrect|critical, correction}` (creates an issue), `POST /messages/{id}/flags {type: transcriber|message|tool_call|run|interruption, priority, correction}`, `PATCH /issues/{id}` | Verdicts appear inside HappyRobot's own UI |

**Native accelerator:** workflow `settings.audit_conditions` (conditions over run variables, `audit_sampling_bps`) lets us make HappyRobot itself audit 100 % of runs where our variables mark them risky — e.g. set a `rogue_index` variable via a tool/extract step and condition audits on it.

---

## 5. Where the rogue index gets its signals (mapping to 07-risk-vector)

| Signal | HappyRobot source |
|---|---|
| Impact: tool R/B | version tool nodes (`function`, `is_mcp`), integration category |
| Impact: environment | `run.execution_environment` |
| Impact: commitment / disclosure | assistant messages (inline or SSE) + `contacts/resolve` for ownership |
| Suspicion: drift | `run nodes` errors + edges; `audits/node-errors` |
| Suspicion: injection | user messages |
| Suspicion: taint | inline request: where an arg value first appeared in `messages[]` vs. fixed binding / tool result |
| Suspicion: arg anomaly | Twin dump distributions per variable |
| Suspicion: judge | our LLM over the message window |
| Suspicion: behaviour | session `duration`, `turn_index`, retries, credits vs. per-workflow baselines |
| Suspicion: history | `sessions?caller_id`, contact tags, our ledger |
| Verifiability | tool outputs present for the claim? |
| Calibration truth | northstar `grade`, flags, issues |

---

## 6. Honest gaps and how we cover them

1. **No pause / no pre-execution hook outside the prompt node.** Tier 2 graph actions execute as configured. Cover: point their HTTP nodes at our forwarding proxy; validate the extracted variables inline before they're set.
2. **Realtime WS host undocumented.** Cover: SSE per session + polling `runs?status=running` (works with just a key); decode the JWT once we have one.
3. **Docs gated.** Cover: the public spec is complete; `custom-llm-server` documents the inline contract.
4. **Inline only sees the prompt node's tools.** Cover: Tier 2 actions via post-hoc + proxy.
5. **Latency of the observer path.** Cover: the inline layer handles anything irreversible; the observer handles patterns.
6. **Access risk (key, Custom LLM permission, tool nodes).** Test in the first 20 minutes with a key: `whoami` → `map` → set Custom LLM on one prompt node → attach one `send_sms`/HTTP tool.

---

## 7. Minimal architecture

```
        HappyRobot org (their telephony, STT, TTS, workflows)
        │  prompt node → Model: Custom LLM ──────────────┐
        │  SSE /sessions/{id}/stream, REST, LiveKit obs   │
        ▼                                                 ▼
  ┌───────────────┐   events    ┌──────────────────┐   completions
  │  Observer     │ ──────────▶ │  Rogue engine    │ ◀────────────── Inline proxy (custom-llm-server fork)
  │ (hr_watch)    │             │  risk vector →   │ ──────────────▶ allow / rewrite / hold / _hangup
  └───────────────┘             │  rogue index →   │
                                │  S0–S4 ladder    │ ──▶ levers: signals, takeover, cancel, cancel-runs+unpublish, mark/flag
                                └──────────────────┘
                                          │ ledger (hash-chained) + evidence packs
                                          ▼
                                 Dashboard (AngryRobots UI shell): live calls, rogue index timeline, hold approvals, kill switch
```
