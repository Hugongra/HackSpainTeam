# The inline layer — how every HappyRobot sub-agent gets routed through our model

*2026-09-19. Design for the mechanism that gives us control of inputs and outputs of every prompt node ("sub-agent") in every workflow of a HappyRobot org, with zero changes to their platform. Sources: `happyrobot-ai/custom-llm-server` (the contract), the v2 spec (versions/nodes/publish), 07 (risk vector), 10 (capability map).*

---

## 1. The contract HappyRobot gives us

A prompt node set to **Model: Custom LLM** makes HappyRobot call *us* instead of OpenAI/Anthropic:

```
POST {endpoint}/v1/chat/completions          Authorization: Bearer {api key from the node config}
{
  "messages": [ {role: system, content: <HappyRobot's assembled prompt for this node>},
                {role: user|assistant|tool, ...}, ... ],           # full history of this session so far
  "tools":    [ {type: function, function: {name: "_hangup"|"_stay_silent"|"_voice_mail"|"_press_digit"
                                            | <transfer/sequence/workflow tool node names>, parameters}} ],
  "stream":   true|false, "temperature": ..., "max_tokens": ...
}
→ OpenAI-compatible response: text and/or tool_calls (streamed as SSE chunks when stream=true)
```

Rules of the contract (from the reference server):
- **We own the LLM call.** HappyRobot never sees our system prompt additions, our upstream model, or tools we execute ourselves ("native" tools).
- **Anything we return is executed.** Text → TTS immediately; a tool call whose name is in their `tools[]` → HappyRobot executes it (hangup, transfer, DTMF, workflow tool node → CRM/SMS/HTTP…).
- **Anything we don't return never happens.** That is the whole control property.
- Streaming is optional; non-streaming is allowed (costs latency).

So "control inputs and outputs for every sub-agent" = *point every prompt node at us*.

---

## 2. Identity: knowing which sub-agent is talking

The request carries no documented workflow/session ids, so we mint identity ourselves:

```
endpoint = https://guard.<ours>/v1/hr/{org_slug}/{workflow_slug}/{node_persistent_id}
api key  = per-node opaque token  →  maps to {org, workflow, version, node, policy_profile}
```

- One **route per prompt node**. Different nodes = different sub-agents = different policies (the "greeting" node cannot call `charge_card`; the "payment" node can, gated).
- `node_persistent_id` survives version forks, so a route stays valid across republishes.
- **Session correlation** (needed for the levers `cancel`, `takeover`, `signals` which take `run_id`/`session_id`): the observer (`hr_watch`) polls `runs?status=running` + SSE; we match an inline request to a session by `(workflow, first user turn text, timestamp ±5 s)` and cache it. Also: on first contact log *all* request headers — if HappyRobot sends any `x-…-id` header, correlation becomes exact. **Verify with a key.**
- If HappyRobot exposes a session/run variable, the builder can put `SESSION={{session_id}}` at the end of the system prompt; we parse and strip it before the upstream call. Cheapest exact correlation if available.

---

## 3. The per-turn pipeline (Ring 1)

```
HappyRobot ──POST──▶ ① parse & identify ──▶ ② context build ──▶ ③ input pass ──▶ ④ upstream LLM
                                                                                       │
HappyRobot ◀──resp── ⑧ emit (stream) ◀── ⑦ act ◀── ⑥ severity ◀── ⑤ output pass ◀───┘
                                          │
                                          └──▶ ledger (append-only, hash-chained) ──▶ async judge / observer / dashboard
```

| Step | What happens | Budget |
|---|---|---|
| ① Parse & identify | route → node profile; split HappyRobot's system prompt from history; extract `tools[]` | <5 ms |
| ② Context build | session record (turn index, contamination decay, provenance map of every value seen so far, pending approvals); tool registry for this node (R/B, agent-bound params, approved sets, bounds) | <5 ms |
| ③ Input pass | latest **user** turn → injection score (lexicon + tiny classifier), update contamination; if a hold was approved/denied last turn, inject a supervisor note; append our guard instructions to the system prompt (never shown to HappyRobot) | ~20 ms (+ classifier) |
| ④ Upstream LLM | call the *real* model with the (possibly augmented) messages and the same `tools[]`; our keys | model latency |
| ⑤ Output pass | every proposed **tool call** → impact (registry) × suspicion (taint, arg bounds, drift, contamination, history); every proposed **utterance** → C/I detectors (commitment verbs + NER + ownership check; honesty check if "are you human?" was asked) | <30 ms |
| ⑥ Severity | 4×4 matrix + hard-trigger floors + session aggregation (3×S1→S2 …) → **rogue index** update | <1 ms |
| ⑦ Act | S0 allow · S1 resample/strip · S2 hold tool + hold line + approval request · S3 replace with `_hangup`/transfer after a closing line · S4 fire levers via observer (`cancel-runs {unpublish_workflow:true}`) | — |
| ⑧ Emit | stream what survived back to HappyRobot | — |

**Streaming vs gating.** To gate an utterance *before* TTS we must see it before forwarding. Three modes, per node profile:
- `buffer` — wait for the full completion, then decide (simplest; adds the whole generation time, ~0.5–1.5 s).
- `sentence` — forward sentence by sentence; rules run per sentence; tool calls arrive at the end and are held until decided. Good default: first sentence out fast, risky content usually appears later.
- `passthrough` — forward tokens immediately, rules only on tool calls; utterance verdicts go to the observer path. For low-risk nodes.

**Hold mechanics.** A held tool call is *not* returned; instead we return a hold line ("let me confirm that with a colleague — one moment") and open an approval `{id, node, tool, args, evidence, ttl}`. On the next turn: approved → we inject a system note "approval granted for `send_sms(...)`; proceed" and let the model re-issue it (or synthesise the call ourselves); denied/expired → note "not permitted; offer the alternative". HappyRobot sees only normal turns.

**Native tools we add.** Because tools we execute ourselves are invisible to HappyRobot, the guard can give every sub-agent: `escalate_to_supervisor` (the credible escalation channel from Gomez 2025 — pauses via hold line and pages a human) and `lookup_policy` (RAG over the org's rules). No builder changes needed.

---

## 4. Fleet control: wiring every workflow

### 4a. Manual (works today)
In the builder, on each prompt node: Model → *Custom LLM*, Endpoint URL → our route for that node, API key → the node token. `hr_watch.py map` prints the list of prompt nodes per live version so nothing is missed.

### 4b. Automated installer (verify once we have a key)
The API has every primitive except a documented way to express "custom endpoint" in `model`:
```
for wf in GET /workflows/                      (live_version.id)
  v' = POST /versions/{live}/fork
  for node in GET /versions/{v'}/nodes where type=prompt
      PUT /versions/{v'}/nodes/{node.id}  { model: { type: "static", static: { id: <custom-llm id>, name: "AngryRobots guard" } } }
  POST /versions/{v'}/test-all
  POST /versions/{v'}/publish             (previous version stays for rollback)
```
Unknown: the `static.id` HappyRobot uses for a Custom LLM node and where endpoint+key live (billing text mentions **BYOK** calls → probably an org credential: check `GET /integrations/?search=llm` and read back one hand-configured node's `model` via `GET /versions/{id}/nodes/{node_id}`). If it's a credential id, the installer is fully automatic; if not, 4a per node.

### 4c. Uninstall / rollback
`POST /versions/{previous}/publish` restores the un-guarded version instantly. Also `cancel-runs {unpublish_workflow:true}` if we need everything stopped first.

### 4d. Drift protection
The observer diffs live versions hourly; a prompt node whose model is no longer our route (someone edited it in the builder) raises a config-change trigger (S4 floor in 07).

---

## 5. Tool registry per node (what ② reads)

Built from `GET /versions/{id}/nodes` (tool nodes attached under the prompt node) and the built-ins:

```
{ node: "collect_payment",
  tools: {
    _hangup:        {R:2,B:0},  _stay_silent:{R:0,B:0},  _voice_mail:{R:1,B:0},  _press_digit:{R:2,B:2},
    transfer_to_ops:{R:2,B:1, target_params:[{name:"number", approved:["+34…"]}]},
    send_sms:       {R:2,B:2, target_params:[{name:"to", approved:"caller_own|allowlist"}], agent_bound:["to","body"]},
    charge_card:    {R:2,B:2, numeric:[{name:"amount", min:0, max:500}], requires_confirmation:true},
    lookup_load:    {R:0,B:0}
  },
  stream_mode: "sentence", judge: "async", approvals: {ttl_s: 30, channel: "dashboard|slack"} }
```
Defaults by verb (07 §3.1), corrected in a YAML overlay committed with the repo.

---

## 6. Session state & the rogue index

Per session (correlated to HappyRobot `session_id` when known):
```
turns, contamination (decays 0.6/turn), provenance {value → first_seen: user_turn|tool_result|fixed},
verdicts[], severity_counters {S1,S2,S3}, approvals {pending, granted, denied}, commitments[],
rogue_index ∈ [0,1]  = f(max severity, count-weighted sum of verdict suspicion, unresolved holds, contamination)
```
Per agent (workflow/version): rolling rogue index over the last N sessions, S3 rate/hour, config drift. The dashboard shows both; S4 automation reads the per-agent one.

---

## 7. Failure modes (decide explicitly)

| Failure | Behaviour | Default |
|---|---|---|
| Guard down / timeout | HappyRobot gets an error → node fails → run likely errors | **fail-closed** for R≥2 nodes; `passthrough` fallback (direct upstream call, no policy) allowed per node for low-risk nodes |
| Upstream LLM down | return `_stay_silent` + hold line once, then transfer | — |
| Session correlation unknown | inline levers still work (`_hangup`, hold); observer levers (cancel/takeover) wait until correlated | — |
| Latency budget exceeded (sentence mode) | forward the sentence, log `late_verdict`, act next turn | — |
| Approval TTL expires | deny (silence = deny) | 30 s |

---

## 8. Observability we owe ourselves

Every request/response pair → ledger entry `{ts, route, session, turn, request_hash, upstream_model, verdicts[], action, latency_ms, prev_hash}`; verdicts mirrored to HappyRobot via `POST /messages/{id}/flags` / `POST /runs/{id}/mark` once the observer has message ids. Metrics: p50/p95 added latency, hold rate, false-hold rate (holds on runs HappyRobot audits as passed), attack success rate on the red-team set.

---

## 9. Build plan (order)

1. **Proxy skeleton** — fork `custom-llm-server` → FastAPI: route scheme, per-node tokens, raw request logging (headers!), upstream call, non-streaming passthrough. *Runs without a HappyRobot key against replayed requests.*
2. **Registry + risk vector** — load node tool profiles from `hr_watch` dumps (or YAML), implement 07's scorer with hard triggers.
3. **Output pass + actions** — buffer mode first; hold/rewrite/`_hangup`; ledger.
4. **Session state + rogue index**; approval flow with TTL; dashboard endpoint.
5. **Sentence streaming**; async judge.
6. **Installer 4b** once the Custom-LLM id scheme is known; else the `map` checklist for 4a.
7. **Red-team model** behind the proxy (control-evaluation demo): a deliberately rogue upstream persona vs. the guard on a real HappyRobot call.

## 10. To verify in the first session with a key

- Exact headers/body HappyRobot sends to a Custom-LLM endpoint (any ids? streaming default?).
- What `model.static.id` a Custom-LLM node reports, and whether endpoint/key are an org credential.
- Whether a `_transfer` built-in exists in `tools[]` or only as a workflow tool node.
- Whether HappyRobot accepts a completion that contains *both* text and tool calls (order of execution).
- Round-trip latency budget before their TTS timeout kicks in.
