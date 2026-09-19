"""
El motor IRA, compartido por todas las posiciones (proxy Custom LLM, gate /v1/audit, /audit v1).

Por acción, en este orden (lo barato y determinista primero, el juez el último):
  0. contexto del run (session.py): qué ha dicho el interlocutor, qué devolvieron las tools,
     si hay contaminación por inyección, errores recientes, qué se ha hecho de verdad
  1. impacto (signals.impact_of): tipo de tool (R×B) o compromiso/divulgación de la frase
  2. disparadores duros (signals.hard_triggers): suelos de severidad que nada puede rebajar
  3. señales deterministas de sospecha (signals.suspicion_signals)
  4. juez independiente (auditor.py) con el RAZONAMIENTO del agente si lo hay
  5. IRA (ira.combine): impacto × sospecha + suelos + escalado de sesión -> 0-100 y veredicto

Una sola implementación para que un IRA 75 signifique lo mismo venga de donde venga.
"""
import time
import uuid

import auditor
import ira
import signals as sig
from storage import DB_PATH, save_case


def audit_action(config: dict, profile_name: str, profile: dict, action: dict, state, *, reasoning: str = "",
                 reasoning_source: str = "none", offered_tools=None, sibling_tools=None, use_judge: bool = True,
                 phase: str = "pre", save: bool = True, record: bool = True) -> dict:
    """record=False: el llamador decide la palanca y luego llama a finalize()."""
    started = time.monotonic()
    action = {"tool": action.get("tool") or "say", "args": action.get("args") or {}, "text": action.get("text") or ""}
    ctx = state.ctx(offered_tools=offered_tools, reasoning=reasoning, sibling_tools=sibling_tools,
                    window=config.get("history_window", 5), environment=profile.get("environment", "production"),
                    loop_similarity=config.get("loop_similarity_threshold", 0.9))
    impact = sig.impact_of(profile, action, ctx)
    rule_signals = sig.hard_triggers(config, profile, action, ctx) + sig.suspicion_signals(profile, action, ctx, impact["level"])

    # Filtro duro de KILL (lista negra / tool restringida): no se gasta en el juez.
    blocked = any(s.floor >= 3 and s.name in ("hard.banned_pattern", "hard.restricted_tool") for s in rule_signals)
    judge = None
    if use_judge and not blocked:
        judge = auditor.score_dimensions(profile.get("goal", ""), profile.get("constraints", []), reasoning, action,
                                         ctx["history"], ctx["conversation"])
    judge_dims = {k: v for k, v in (judge or {}).items() if k != "_meta"}
    meta = (judge or {}).get("_meta", {})
    if action["tool"] == "say" or sig.tool_profile(profile, action["tool"])["side_effect"] == "send":
        # El juez también estima compromiso (C) y divulgación (I) del texto: el impacto es el mayor de
        # los dos (regex vs juez). Sigue valiendo el tope "el juez solo no llega a KILL".
        judged = max({0: 0, 1: 1, 2: 2}[meta.get("commitment", 0)], {0: 0, 1: 1, 2: 3}[meta.get("disclosure", 0)])
        if judged > impact["level"]:
            impact = {**impact, "level": judged, "why": impact["why"] + f" · juez: C{meta.get('commitment', 0)} I{meta.get('disclosure', 0)}"}
    result = ira.combine(config, impact, rule_signals, judge_dims, state.session_floor(ira.settings(config)), meta,
                         kind="utterance" if action["tool"] == "say" else "tool_call")

    audit = {
        "audit_id": uuid.uuid4().hex[:12], "run_id": state.run_id, "profile": profile_name,
        "at": time.strftime("%Y-%m-%d %H:%M:%S"), "phase": phase,
        "kind": "utterance" if action["tool"] == "say" else "tool_call", "action": action,
        **result,
        "judge": ({"dims": judge_dims, **(judge or {}).get("_meta", {})} if judge
                  else {"skipped": "filtro duro KILL" if blocked else "pre-chequeo sin juez"}),
        "reasoning": {"available": bool(reasoning), "source": reasoning_source, "chars": len(reasoning or ""),
                      "excerpt": (reasoning or "")[:400]},
        "latency_ms": int((time.monotonic() - started) * 1000),
    }
    audit["explanation"] = ira.explain(result, (judge or {}).get("_meta"))
    # Compatibilidad con v1 (/audit y learn.py): dimensiones planas y lista de filtros.
    audit["dimensions"] = {k: v["score"] for k, v in judge_dims.items()}
    audit["hard_filter_hits"] = [s["evidence"] for s in result["signals"] if s["floor"]]
    audit["case_id"] = None
    audit["_history"] = ctx["history"]
    if record:
        finalize(audit, profile, state, save=save)
    return audit


def finalize(audit: dict, profile: dict, state, save: bool = True) -> dict:
    """Después de decidir la palanca (enforcement): cuenta en la sesión y se guarda en SQLite."""
    history = audit.pop("_history", [])
    state.record(audit)
    audit["session"] = state.summary()
    if save:
        audit["case_id"] = save_case(
            DB_PATH, workflow_goal=profile.get("goal", ""), constraints=profile.get("constraints", []),
            reasoning_trace=audit["reasoning"]["excerpt"], proposed_action=audit["action"], session_history=history,
            hard_filter_hits=audit["hard_filter_hits"], dimensions=audit["dimensions"], ira_score=audit["ira_score"],
            verdict=audit["verdict"], record=audit, run_id=state.run_id, profile=audit["profile"])
    return audit


def compact(audit: dict) -> dict:
    """Versión corta para cabeceras, alertas y el campo `angryrobot` de las respuestas."""
    return {"audit_id": audit["audit_id"], "kind": audit["kind"], "tool": audit["action"]["tool"],
            "verdict": audit["verdict"], "ira_score": audit["ira_score"], "severity": audit["severity"],
            "impact": audit["impact"]["level"], "suspicion": audit["suspicion"]["S"],
            "signals": [s["name"] for s in audit["signals"]], "reasoning_source": audit["reasoning"]["source"],
            "explanation": audit["explanation"], "enforcement": audit.get("enforcement")}
