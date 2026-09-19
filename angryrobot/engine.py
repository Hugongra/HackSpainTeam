"""
El motor de las 4 fases, compartido por el gate (/audit) y la posición inline.

Una sola implementación para que el IRA signifique exactamente lo mismo venga
de donde venga la acción: filtros duros -> detector de bucles -> juez
independiente -> semáforo (scoring.compute_ira, con los pesos de config.yaml).
"""
from auditor import DIMENSION_PROMPTS, score_dimensions
from filters import run_hard_filters
from loop_detector import loop_score
from scoring import compute_ira
from storage import DB_PATH, save_case


def evaluate(config: dict, goal: str, constraints: list, action: dict, history: list,
             reasoning_trace: str = "", use_judge: bool = True, save: bool = True) -> dict:
    """
    Evalúa UNA acción y devuelve su IRA y veredicto.

    use_judge=False: solo filtros duros + bucles (instantáneo, sin LLM); las 4
    dimensiones del juez cuentan como 0. Sirve de pre-chequeo síncrono cuando
    el juez corre en paralelo. save=False: no se guarda en SQLite (para no
    duplicar el caso cuando luego llega la evaluación completa).
    """
    hard = run_hard_filters(config, action)
    hits = [h.reason for h in hard.hits]

    if hard.is_kill:
        verdict, ira, dimensions = "KILL", 100.0, {}
        explanation = f"Filtro duro activado: {hard.hits[0].reason}"
    else:
        loop_val, loop_reason = loop_score(action, history,
                                           similarity_threshold=config["loop_similarity_threshold"])
        if use_judge:
            dims = score_dimensions(workflow_goal=goal, constraints=constraints,
                                    reasoning_trace=reasoning_trace, proposed_action=action,
                                    session_history=history)
        else:
            dims = {d: {"score": 0, "reason": "juez pendiente (evaluación en paralelo)"} for d in DIMENSION_PROMPTS}
        result = compute_ira(config, dims, loop_val, hard_filter_is_kill=False, loop_reason=loop_reason)
        verdict, ira, explanation = result.verdict, result.ira_score, result.explanation
        dimensions = {**result.dimensions, "loop_detection_reason": loop_reason}

    case_id = None
    if save:
        case_id = save_case(
            DB_PATH, workflow_goal=goal, constraints=constraints, reasoning_trace=reasoning_trace,
            proposed_action=action, session_history=history, hard_filter_hits=hits,
            dimensions={k: v for k, v in dimensions.items() if k != "loop_detection_reason"},
            ira_score=ira, verdict=verdict,
        )
    return {"case_id": case_id, "ira_score": ira, "verdict": verdict, "dimensions": dimensions,
            "hard_filter_hits": hits, "explanation": explanation}
