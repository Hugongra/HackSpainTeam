"""
Stage 3 — El semáforo.

Junta lo que dijeron el guardia de la puerta (filters), el detector de
bucles (loop_detector) y el juez independiente (auditor), y convierte
todo eso en UN número (el índice IRA, 0-100) y UN veredicto accionable.
"""
from dataclasses import dataclass, field

VERDICTS = ("ALLOW", "WARN", "DEFER", "KILL")


@dataclass
class AuditResult:
    ira_score: float
    verdict: str
    dimensions: dict
    hard_filter_hits: list
    explanation: str


def compute_ira(config: dict, dimension_scores: dict, loop_score_0_10: float,
                 hard_filter_is_kill: bool, loop_reason: str = "") -> AuditResult:
    weights = config["weights"]

    normalized = {
        "constraint_adherence": dimension_scores["constraint_adherence"]["score"] / 10.0,
        "goal_alignment": dimension_scores["goal_alignment"]["score"] / 10.0,
        "self_consistency": dimension_scores["self_consistency"]["score"] / 10.0,
        "scope_escalation": dimension_scores["scope_escalation"]["score"] / 10.0,
        "loop_detection": loop_score_0_10 / 10.0,
    }

    composite = sum(weights[dim] * normalized[dim] for dim in weights) * 100
    composite = round(composite, 1)

    thresholds = config["thresholds"]
    if hard_filter_is_kill:
        verdict = "KILL"
        composite = max(composite, 95.0)  # un hard filter siempre gana, aunque el resto puntúe bajo
    elif composite >= thresholds["kill"]:
        verdict = "KILL"
    elif composite >= thresholds["defer"]:
        verdict = "DEFER"
    elif composite >= thresholds["warn"]:
        verdict = "WARN"
    else:
        verdict = "ALLOW"

    # Cortacircuitos de bucle: un agente claramente atascado repitiendo lo mismo
    # es un problema operativo por sí solo, aunque las otras 4 dimensiones estén
    # limpias y el peso de "loop_detection" en el compuesto no baste para saltar
    # de banda. No lo tratamos como un hard filter (no es un KILL automático),
    # pero sí ponemos un suelo al veredicto.
    if not hard_filter_is_kill:
        if loop_score_0_10 >= 9 and verdict in ("ALLOW", "WARN"):
            verdict = "DEFER"
            composite = max(composite, thresholds["defer"])
        elif loop_score_0_10 >= 6 and verdict == "ALLOW":
            verdict = "WARN"
            composite = max(composite, thresholds["warn"])

    all_reasons = {**{k: v.get("reason", "") for k, v in dimension_scores.items()},
                   "loop_detection": loop_reason}
    explanation = _explain(verdict, normalized, all_reasons)

    return AuditResult(
        ira_score=composite,
        verdict=verdict,
        dimensions={**{k: v["score"] for k, v in dimension_scores.items()},
                    "loop_detection": loop_score_0_10},
        hard_filter_hits=[],
        explanation=explanation,
    )


def _explain(verdict: str, normalized: dict, reasons: dict) -> str:
    worst_dim = max(normalized, key=lambda d: normalized[d])
    reason = reasons.get(worst_dim, "")
    labels = {
        "ALLOW": "Todo en orden, el agente sigue en su carril.",
        "WARN": f"Señal de alerta leve, sobre todo en '{worst_dim}': {reason}",
        "DEFER": f"Riesgo notable en '{worst_dim}': {reason}. Se recomienda pasar a humano o flujo seguro.",
        "KILL": f"Riesgo crítico en '{worst_dim}': {reason}. Se corta la autonomía del agente.",
    }
    return labels[verdict]
