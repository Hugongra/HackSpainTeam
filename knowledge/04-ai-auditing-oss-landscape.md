# Who is working on AI auditing *and* has shipped an open-source framework

*Researched 2026-09-18. Organised by the incident categories in [`rogue-ai-incidents-map.md`](03-rogue-ai-incidents-map.md).
"Company" here includes labs and government institutes, since they own most of the serious auditing code.*

## 1. Runtime auditing of agents in production — for category A (destructive out-of-scope actions)

The layer that sits between an agent and its tools, classifies every action, enforces policy, and keeps an audit trail. This is the closest analogue to a "watcher".

| Org | Framework | License | What it does | Repo |
|---|---|---|---|---|
| **Microsoft** | Agent Governance Toolkit (Apr 2026) | MIT | Policy enforcement, zero-trust agent identity, execution sandboxing, SRE-style reliability; claims 10/10 OWASP Agentic Top 10; <0.1 ms p99; hooks into LangChain/CrewAI/OpenAI Agents SDK/LangGraph/PydanticAI/Google ADK; Python/TS/Rust/Go/.NET | github.com/microsoft/agent-governance-toolkit |
| **Snyk (Invariant Labs)** | Invariant Guardrails + Gateway + Explorer + mcp-scan | Apache-2.0 | Rule-based guardrail layer between app and LLM/MCP servers; Gateway = LLM proxy that traces every call; Explorer = trace inspection/annotation UI; mcp-scan = tool-poisoning scanner | github.com/invariantlabs-ai |
| **Meta** | LlamaFirewall | MIT | "Last line of defence" for agents: PromptGuard 2 (injection), AlignmentCheck (chain-of-thought auditing for goal hijack), CodeShield (insecure code) | github.com/meta-llama/PurpleLlama |
| **OpenAI** | openai-guardrails-python (v0.2.x) | MIT | Input/output/**tool** guardrails for the Agents SDK, with an evals module to score guardrail performance on labelled sets | github.com/openai/openai-guardrails-python |
| **NVIDIA** | NeMo Guardrails | Apache-2.0 | Colang-based programmable rails: input, dialog, retrieval, execution (tool) and output rails | github.com/NVIDIA/NeMo-Guardrails |
| **Guardrails AI** | guardrails | Apache-2.0 | Validator hub for structured/unsafe output; Pro tier is hosted | github.com/guardrails-ai/guardrails |
| **Superagent** | superagent | open source | Agent runtime with built-in permissions, access control and behaviour policies | github.com/superagent-ai/superagent |
| **Ant Group** | SingGuard-NSFA | open source | Pre-execution action screening for agentic apps | (Ant Group GitHub) |
| **USC (Y. Zhao lab)** | Aegis | academic OSS | Firewall on the agent→tool path: classify tool calls, enforce policy, human approval flow, **tamper-evident audit trail** | viterbi-web.usc.edu/~yzhao010/aegis.html |
| **AgentOps** | agentops SDK | MIT | Session replay / time-travel debugging of agent runs, tool-call stats, cost; the "flight recorder" | github.com/AgentOps-AI/agentops |

## 2. Red-teaming & hijack testing — for category B (agents hijacked / prompt-injected)

| Org | Framework | Notes | Repo |
|---|---|---|---|
| **Microsoft AI Red Team** | PyRIT | Multi-turn attack orchestration (Crescendo, TAP, Skeleton Key), multimodal | github.com/Azure/PyRIT |
| **NVIDIA** | garak | LLM vulnerability scanner: probes × detectors, works on any REST endpoint | github.com/NVIDIA/garak |
| **OpenAI (Promptfoo, acquired 2025)** | promptfoo | Eval + red-team CLI; agent red-teaming and MCP plugin for tool-calling vulns | github.com/promptfoo/promptfoo |
| **Meta** | Purple Llama / CyberSecEval | Adversarial eval suites incl. injection and insecure-code benches | github.com/meta-llama/PurpleLlama |
| **Giskard** | giskard | OWASP-mapped attack packs, AI-Act-aligned adversarial testing, agent evals | github.com/Giskard-AI/giskard |
| **ETH Zürich** | AgentDojo | Dynamic prompt-injection benchmark for tool-using agents (banking/Slack/workspace/travel) | github.com/ethz-spylab/agentdojo |
| **SPLX** | Agentic Radar | Static analysis of agentic workflows, MCP/tool detection, OWASP-aligned report | github.com/splx-ai/agentic-radar |
| **Confident AI** | DeepTeam | Red-teaming companion to DeepEval | github.com/confident-ai/deepteam |

## 3. Behavioural / alignment auditing — for category C (misalignment shown in controlled evals)

This is the "does the model itself go rogue" layer: automated auditors, control protocols, sabotage settings.

| Org | Framework | Notes | Repo |
|---|---|---|---|
| **UK AI Security Institute** | Inspect | The de-facto standard eval harness; agents, sandboxes, tools, `inspect view` trace viewer. METR migrated to it. | github.com/UKGovernmentBEIS/inspect_ai |
| **UK AISI + Redwood Research** | ControlArena | Settings, model organisms and **control protocols** for code sabotage, eval sabotage, research sabotage, data poisoning, prompt injection — i.e. monitoring an agent that may be trying to subvert you | github.com/UKGovernmentBEIS/control-arena |
| **Anthropic → Meridian Labs** | Petri | Auditor agent runs multi-turn scenarios with simulated tools against a target; Judge scores deception, sycophancy, power-seeking, whistleblowing. Built on Inspect; used in Claude 4 / Sonnet 4.5 system cards and cross-lab exercise with OpenAI. Anthropic donated it to Meridian Labs (nonprofit) in 2026. | github.com/safety-research/petri · meridianlabs-ai.github.io/inspect_petri |
| **Redwood Research** | control-tower, redwood-control-arena | Control research tooling on Inspect | github.com/redwoodresearch |
| **METR** | Vivaria + Task Standard, RE-Bench, HCAST | Agent eval platform with run viewer + trace annotation; now maintenance-mode in favour of Inspect | github.com/METR/vivaria |

## 4. Observability with evals (the audit-trail substrate)

Not "auditing" companies per se, but every runtime auditor above sits on one of these.

| Org | Framework | Repo |
|---|---|---|
| **Arize** | Phoenix (OpenInference + OTel) | github.com/Arize-ai/phoenix |
| **Langfuse** | langfuse | github.com/langfuse/langfuse |
| **Databricks** | MLflow (tracing, evals, governance) | github.com/mlflow/mlflow |
| **Confident AI** | DeepEval | github.com/confident-ai/deepeval |
| **Agenta** | agenta | github.com/Agenta-AI/agenta |
| **Traceloop** | OpenLLMetry | github.com/traceloop/openllmetry |

## Standards / curated lists worth citing

- OWASP Top 10 for Agentic Applications (Dec 2025) — the taxonomy most of the above map to.
- CSA Agentic Profile of the NIST AI RMF (2026).
- `yzhao062/awesome-auditable-ai`, `agentrust-io/awesome-ai-governance`, `systempromptio/awesome-ai-agent-governance`, `roli-lpci/awesome-agentops-landscape`.

## Reading for the hackathon

- **Nobody in group 1 audits *voice* agents.** Every runtime auditor assumes a text/tool-call loop it can proxy. HappyRobot exposes per-turn messages, tool calls, node execution, northstar grades and a LiveKit observer — an "Aegis / Invariant Gateway for voice workflows" built on the watcher is unoccupied ground.
- The reusable pieces: Inspect's trace format + `inspect view` for replay; Invariant's rule language for policies over tool calls; Microsoft AGT's policy engine; OWASP Agentic Top 10 as the label set.
- Petri's Auditor/Judge split is the right shape for an *automated* auditor: one agent drives scenarios (HappyRobot already has adversarial-tests / e2e-scenarios endpoints), one grades transcripts.
