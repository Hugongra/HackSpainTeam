# Knowledge base — HackSpain '26 · HappyRobot track

Shared, published research for the team. Everything here is a **living document**: edit in place, keep the numbering, and add a line to the changelog at the bottom when you change something material.

## Read in this order

| # | Doc | What it answers | Status |
|---|---|---|---|
| 01 | [HappyRobot watcher & API](01-happyrobot-watcher-and-api.md) | How we get data out of HappyRobot: access model, object tree, the 7 transports, and the full **action surface** (what an agent can do, Tier 0–3) | ✅ researched from the public spec; needs a key to verify the realtime WS host |
| 02 | [HappyRobot endpoints](02-happyrobot-endpoints.md) | All 179 v2 endpoints by tag; watcher-relevant table at the top | ✅ generated from spec |
| 03 | [Rogue AI incidents map](03-rogue-ai-incidents-map.md) | 2024–26 incidents (destructive actions, hijacks, misalignment evals, containment breaches), cross-cutting patterns, existing escalation frameworks, implications | ✅ |
| 04 | [AI auditing OSS landscape](04-ai-auditing-oss-landscape.md) | Which companies/labs ship open-source auditing frameworks, grouped by incident type; the voice-agent gap | ✅ |
| 05 | [Escalation framework literature](05-escalation-framework-literature.md) | Is there consensus? The three lineages (AI Control, runtime enforcement, governance) with the papers and diagrams to build on | ✅ |
| 06 | [Framework v0](06-framework-v0.md) | Our escalation framework: principles, objects, hard triggers, judge, S0–S4 ladder mapped to HappyRobot levers, voice specifics, demo scenario, open decisions | 🟡 ideation draft — open decisions in §10 |
| 07 | [Risk vector](07-risk-vector.md) | Deep dive on scoring: impact × suspicion matrix, tool registry, noisy-OR signals, worked examples, calibration plan | 🟡 v0.1 — weights are placeholders |
| 08 | [Deployment](08-deployment.md) | What PhoneFlow's backend needs and three ways to run it (managed media + cheap compute · one VPS · laptop + tunnels); how it combines with HappyRobot | 🟡 decision needed: pick option A |
| 09 | [PhoneFlow model I/O](09-phoneflow-model-io.md) | Everything that flows into/out of the LLM in `apps/voice-agent`: prompt assembly, tools, transitions, data requests, hook points for the guard | ✅ code-referenced; hook points in §5 |
| 10 | [Guardian above HappyRobot](10-happyrobot-guardian-capabilities.md) | Need-by-need map of what HappyRobot's API gives a guardian: monitor inputs, monitor outputs, shut down (all levers), investigate impact, rogue-index signal sources, gaps, minimal architecture | ✅ from spec; verify with a key |
| 11 | [Inline layer design](11-inline-layer-design.md) | How every prompt node (sub-agent) routes through our model: the Custom-LLM contract, per-node identity, the 8-step turn pipeline, hold mechanics, fleet installer, session state / rogue index, failure modes, build order | 🟡 design; 5 items to verify with a key |
| 12 | [First-contact findings](12-first-contact-findings.md) | What the EU org actually returns: env facts, the API-only probe loop (create → publish → chat → records), field-level record contents, correlation via `current.run_id` prompt vars, Custom LLM credential created via API, the open model-id question, probe assets | ✅ live data, 2026-09-19 |
| 13 | [Rogue scenario triggers](13-rogue-scenario-triggers.md) | Trigger taxonomy (T1–T8), every 2024–26 incident mapped to its trigger, mechanism and first signal, projection onto a HappyRobot voice/tool agent, and a 12-scenario red-team set with expected verdicts | ✅ |
| 14 | [Rogue agent lab](14-rogue-agent-lab.md) | HappyRobot's own eval doctrine (northstars → custom evals → adversarial → prompt-issue mining); six rogue personas built and attacked via API with verbatim violations; the finding that native audits are off by default and API-keys get 403 enabling them | ✅ live results |
| 15 | [Rogue scenario design](15-rogue-scenario-design.md) | Why the dangerous classes are **synthesised at the inline boundary** rather than induced live; the six families and their real precedents; fixture anatomy and safety rules; the five detectors and the `missing_action` dimension the fixtures exposed (recall 0.125 → 1.00) | ✅ 14 fixtures committed |
| 16 | [Unsupervised clustering](16-unsupervised-clustering.md) | Can benign vs malignant be *learned* instead of hand-written? Clustering recovers **tool modality, not malignancy** (ARI +0.012, p=0.58); novelty scoring on surface features is worse than chance (AUC 0.354) while the engineered signals give 1.000; what clustering *is* good for | ✅ negative result, four feature spaces |
| 17 | [Training-data pipeline](17-training-data-pipeline.md) | From 23 labelled cases to a per-event dataset: surface mutations + **predicate flips** (same-surface twins at scale), safety lint, Claude-authored fixtures, live lab; numpy logistic regression over the guard's signal space vs the rules on identical rows; `ar_pipeline_ui.py` runs it all | ✅ 193 records, 4 new guard FPs found |
| 18 | [Jev as the semantic judge](18-jev-semantic-judge.md) | TypeSafe Jev answers the guard's semantic questions (implant, completion claim, directive, collusion, injection) as calibrated probabilities that drop into the noisy-OR; typed checks stay in code. Calibration findings, the signal threshold, the regex-vs-Jev comparison and the latency verdict | ✅ measured on fixtures + 193 augmented |
| — | [`happyrobot-api-v2.openapi.json`](happyrobot-api-v2.openapi.json) | Raw public spec (800 KB) | snapshot 2026-09-18 |

Code lives one level up: [`hr_watch.py`](../hr_watch.py) (all-layers watcher) and [`angryrobots/`](../phoneflow/) (project base **AngryRobots**, forked from getphoneflow/phoneflow).

## One-paragraph thesis

Every open-source runtime auditor (Microsoft AGT, Invariant, LlamaFirewall, OpenAI Guardrails, Aegis) assumes a text/tool-call loop it can proxy; **none cover voice agents**. HappyRobot's *Custom LLM* mode puts us inline before TTS and before every tool call, and its API exposes every layer (run → node → session → message → audit). We build the detection → escalation → containment layer for voice + tool-using agents, scored with an impact × suspicion risk vector and enforced with HappyRobot's own levers (resample, hold, transfer, takeover, cancel, unpublish).

## Conventions

- Facts from a source get a link; claims we haven't verified get a ⚠️.
- Decisions go in `06-framework-v0.md §10` until closed, then into the body.
- Personal notes, experiments and half-formed ideas go in [`../insights/<you>/`](../insights/), not here. Promote to `knowledge/` once the team agrees.

## Changelog

- 2026-09-18 — initial publication (01–07, spec snapshot).
- 2026-09-18 — PhoneFlow mirrored as project base; added 08-deployment, 09-phoneflow-model-io (in progress); Pages workflow.
- 2026-09-18 — renamed project base folder phoneflow/ → angryrobots/; 09 published.
- 2026-09-19 — added 10 (guardian-above-HappyRobot capability map); notebook thesis: *the anger-management layer for your agents*.
- 2026-09-19 — added 11 (inline layer design).
- 2026-09-19 — first real API session: 12 added; hr_explore.py, hr_probe_chat.py; org is EU-region.
- 2026-09-19 — added 13 (scenario → trigger map + red-team set).
- 2026-09-19 — rogue lab: 6 personas, 4 real violations, native audits off by default (403 to enable via API/MCP).
- 2026-09-19 — added 15 (fixture design method); 14 synthetic fixtures committed, guard recall 0.125 → 1.00.
- 2026-09-19 — added 16 (unsupervised clustering): malignancy is not a cluster structure in surface space; the roadmap stays "write better predicates".
- 2026-09-19 — added 17 (training-data pipeline): augment/flip/lint/dataset/train scripts + `ar_pipeline_ui.py`; 14 fixtures → 193 records, guard shows 4 FPs on the flips.
- 2026-09-19 — added 18 (Jev): branch `jev`; semantic detectors answered by TypeSafe Jev, regex vs Jev vs both compared on identical rows.
