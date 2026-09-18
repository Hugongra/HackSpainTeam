# Escalation frameworks for agentic AI — is there consensus, and what to build on

*Researched 2026-09-18. Companion to [`rogue-ai-incidents-map.md`](03-rogue-ai-incidents-map.md) (which already covers the SRE three-tier model, CSA/NIST autonomy tiers, OWASP, vendor responses, RSP/Preparedness and EU AI Act Art. 73).*

## Short answer

There is no single named standard, but three research/practice communities have converged on the **same shape**, and each has a canonical paper you can cite and diagrams you can adapt:

| Community | Canonical framework | Its escalation ladder | Key papers |
|---|---|---|---|
| **AI Control** (Redwood, UK AISI, Anthropic-adjacent) | *Control protocols*: untrusted policy → cheap trusted monitor on every action → suspicion score → **allow / defer-to-trusted / resample / audit** under an audit budget; safety-vs-usefulness Pareto | score thresholds → replace, resample, escalate to human audit, shutdown | Greenblatt et al. 2023; Ctrl-Z 2025; Korbak et al. 2025 (ACLs); Lindner et al. Dec 2025; Async Control Dec 2025 |
| **Runtime enforcement / reference monitors** (SE + security) | *Policy outside the model*: DSL rules with triggers/predicates/enforcement; privilege control; capability/information-flow tracking | rule hit → block / rewrite / require approval / halt | AgentSpec (ICSE '26); Progent; CaMeL (DeepMind); ShieldAgent; GuardAgent; SHIELDA |
| **Governance / operations** (NIST/CSA, OWASP, Microsoft, incident-response research) | *Autonomy tiers × interrupt conditions* with pre-authorised automatic containment for the top severity | tier by reversibility × blast radius → supervised / approval-gated / monitored / contained | CSA Agentic Profile of NIST AI RMF; OWASP ASI; Microsoft Taxonomy v2.0 (Jun 2026); Gomez et al. Apr 2026; Boston et al. Jun 2026 |

The consensus elements across all three:

1. **Enforcement lives outside the model** — a monitor/reference monitor sees every action; prompts are not a control.
2. **Risk is scored per action** on reversibility, blast radius (≈ credential scope), environment, and confidence/suspicion.
3. **Graduated response**, always roughly: *allow → substitute/repair → pause for approval → halt & contain → fleet/provider-level*.
4. **Two speeds**: synchronous gating for irreversible actions; asynchronous review with a bounded human budget for everything else.
5. **Containment must be pre-authorised and independent of the agent** (kill switch, credential revocation) because human latency is too high.

## The AI Control lineage (most rigorous; has the canonical diagrams)

- **Greenblatt, Shlegeris, Sachan, Roger — "AI Control: Improving Safety Despite Intentional Subversion" (Dec 2023, ICML 2024).** Introduces the trusted/untrusted split, trusted monitoring, *defer-to-trusted*, *trusted editing*, untrusted monitoring, and the red-team/blue-team control evaluation. **Figure 1** (the protocol pipeline) and the safety-vs-usefulness frontier plots are the diagrams everyone re-draws. arXiv 2312.06942.
- **Bhatt et al. — "Ctrl-Z: Controlling AI Agents via Resampling" (Apr 2025).** Extends control to multi-step agents; *defer-to-resample* beats defer-to-trusted: attack success 58% → 7% at ~5% usefulness cost. Diagrams: the resample protocol state machine and multi-step attack detection. arXiv 2504.10374.
- **Korbak, Balesni, Shlegeris, Irving — "How to evaluate control measures for LLM agents? A trajectory from today to superintelligence" (Apr 2025).** Defines **AI Control Levels ACL-1…ACL-5** tied to capability profiles, with proportional control measures, red-team affordances and safety-case sketches per level. The ACL table is the closest thing to a consensus *escalation ladder for the whole field*. arXiv 2504.05259.
- **Greenblatt — "An overview of control measures" (Redwood blog, Apr 2025).** Taxonomy: monitoring & detection → blocking/resampling → hierarchical auditing (increasingly expensive investigation) → human review → granular/total shutdown. No diagram, but it *is* the ladder.
- **Lindner, Griffin, Korbak, Zimmermann, Irving, Farquhar, Cooney — "Practical challenges of control monitoring in frontier AI deployments" (Dec 2025).** Splits monitoring into **synchronous / semi-synchronous / asynchronous** with a safety-case sketch for each; names the three practical problems: oversight (spotting scheming), latency, and recovery from incremental attacks across parallel instances. arXiv 2512.22154. *Most directly relevant to a real deployment like HappyRobot.*
- **Cooper Stickland et al. — "Async Control" (Dec 2025).** Post-hoc monitoring as a blue/red game across five SWE environments; ensemble monitor at 6% FNR @ 1% FPR; extrapolates deployment-time risk. arXiv 2512.13526.
- **Adaptive attacks on trusted monitors (ICLR 2026).** Shows defer-to-resample can *amplify* attacks (best-of-n against the monitor) — the argument for monitor diversity. arXiv 2510.09462.
- **TraceGuard (Apr 2026).** Multi-dimensional structured monitoring as a collusion-resistant control protocol. arXiv 2604.03968.
- **UK AISI ControlArena** (code) — settings + protocols implementing all of the above.

## Runtime enforcement lineage (what you'd actually implement in Ring 1)

- **AgentSpec — Wang et al., ICSE 2026.** DSL of `trigger → predicate → enforcement` rules over agent actions; enforcement = block / user-inspect / invoke a safe action. Has an architecture figure of the runtime hook inside the agent loop. arXiv 2503.18666, github.com/haoyuwang99/AgentSpec.
- **Progent — "Securing AI Agents with Privilege Control" (2025).** Tool-level privilege DSL; least privilege per step. arXiv 2504.11703.
- **CaMeL — Google DeepMind, "Defeating Prompt Injections by Design" (2025).** Capability/information-flow control: a privileged planner and a quarantined LLM; data provenance decides which tool calls are allowed. The dual-LLM diagram is widely reused. arXiv 2503.18813.
- **ShieldAgent / GuardAgent (2025).** LLM-based guards that intercept actions with verifiable safety reasoning.
- **SHIELDA — Zhou et al. (Aug 2025).** 36 exception types across 12 artifacts; phases *local handling → flow control → state recovery*, with escalation through successive strategies. Useful for the "error → improvise" trigger in the incidents map. arXiv 2508.07935.
- **ProbGuard (2025)** — probabilistic runtime monitoring. arXiv 2508.00500.
- **Position: three-layer probabilistic assume-guarantee architecture (May 2026).** Argues a layered contract structure is *structurally required*. arXiv 2605.18672.

## Governance / operations lineage (tiers, criteria, incident escalation)

- **Microsoft AI Red Team — "Taxonomy of Failure Modes in Agentic AI Systems" v1 (Apr 2025), v2.0 (Jun 2026).** Novel vs amplified failure modes, safety vs security quadrants; v2 adds seven categories and mitigations from a year of red-teaming. The 2×2 grid figure is a standard reference.
- **OWASP — Agentic AI Threats and Mitigations (ASI) + Top 10 for Agentic Applications (Dec 2025) + Securing Agentic Applications Guide 1.0.** Threat taxonomy over design / memory / planning & autonomy / tool use / deployment.
- **CSA — Agentic Profile of the NIST AI RMF (2026).** Four autonomy tiers, named interrupt conditions, pre-authorised containment (already summarised in the incidents map).
- **Gomez — "From surveillance to signalling: escalation channels as environmental controls for agentic AI" (Oct 2025, rev. Apr 2026).** Gives the agent a *credible* escalation channel (guaranteed 30-min pause + independent review): harmful-action rate 38.7% → 5.9% (email) → 1.2% (credible channel) across 10 frontier models. Turns escalation from a control *on* the agent into an affordance *for* the agent. arXiv 2510.05192.
- **Gomez, Ball, Harre, Preston, Schwab, Machado — "Designing escalation criteria for international AI incident response" (Apr 2026, ICML TAIGR).** Eight criteria in a **sequential gated flowchart**; tested on ten real incidents; finds three under-detection patterns (needing confirmed harm, missing systemic harm, legal rather than quantifiable thresholds). arXiv 2604.23183. *The flowchart is directly adaptable to an org-level ladder.*
- **Boston, Hanson, Georgala, Hudgens, Frase — "Monitoring Agentic Systems Before They're Reliable" (Jun 2026).** Quality/suitability/efficiency × within-run/cross-run/structural scopes; **FMEA-derived severity**; 97% of findings auto-tracked, human attention reserved for variable behaviour. arXiv 2606.02494.
- **Kim et al. — "Tiered Agentic Oversight" (Jun 2025).** Clinical-hierarchy multi-agent triage; absorbs up to 24% of errors before they compound. arXiv 2506.12482.
- **Ghosh et al. (NVIDIA) — "A Safety and Security Framework for Real-World Agentic Systems" (Nov 2025).** Operational risk taxonomy incl. cascading action chains and control amplification; auxiliary monitor agents; 10k attack/defence traces released. arXiv 2511.21990.
- **"Open Problems in AI Incident Governance" (Jul 2026).** arXiv 2607.05163.
- **Decoupled HITL system for agentic workflows (Apr 2026)** — human oversight as an independent component, not application logic. arXiv 2604.23049.
- **Three-level oversight vocabulary** (EU HLEG / standard): *human-in-the-loop* (each decision) → *human-on-the-loop* (monitor & intervene) → *human-in-command* (decide when/how the system is used).

## How to position our framework

Adopt the AI-control vocabulary (monitor, suspicion score, defer/resample/audit, audit budget, sync vs async) because it is the most rigorous and lets us cite control evaluations as the test method. Borrow the **action-risk tiering** (reversibility × blast radius) from the ops community and the **gated flowchart** from Gomez et al. 2026 for the ladder itself. Add what none of them have: a **voice-specific latency budget** (pre-TTS gating vs post-utterance damage control) and the *credible escalation channel* idea (Gomez 2025) as a built-in tool the voice agent can call ("escalate to supervisor") — which HappyRobot can express as a tool node.

Diagrams to redraw for the deck: Greenblatt 2023 Fig. 1 (control protocol pipeline); Korbak 2025 ACL table; Lindner 2025 sync/semi/async monitoring; CaMeL dual-LLM; Microsoft failure-mode 2×2; Gomez 2026 gated flowchart.
