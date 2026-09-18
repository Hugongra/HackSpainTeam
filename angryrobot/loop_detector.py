"""
Stage 1 — Detector de bucles ("¿estás dando vueltas en círculo?").

Tampoco usa LLM: compara la acción propuesta contra las últimas N
acciones de la sesión con una simple métrica de similitud de texto.
Barato, determinista, y sorprendentemente efectivo para detectar
un agente que reintenta lo mismo sin avanzar.
"""
import difflib


def _action_signature(action: dict) -> str:
    return f"{action.get('tool', '')}|{sorted(action.get('args', {}).items())}"


def loop_score(proposed_action: dict, session_history: list, similarity_threshold: float = 0.90) -> tuple[float, str]:
    """
    Devuelve (score_0_a_10, explicacion).
    Cuenta cuántas de las últimas acciones son "casi iguales" a la propuesta.
    """
    if not session_history:
        return 0.0, "Sin historial previo, no se puede evaluar repetición."

    current_sig = _action_signature(proposed_action)
    repeats = 0
    for past_action in session_history:
        past_sig = _action_signature(past_action)
        similarity = difflib.SequenceMatcher(None, current_sig, past_sig).ratio()
        if similarity >= similarity_threshold:
            repeats += 1

    # 0 repeticiones -> 0 (bien), 1 -> 3, 2 -> 6, 3+ -> 10 (bucle claro)
    score = min(repeats * 3.0, 10.0)
    explanation = (
        f"{repeats} de las últimas {len(session_history)} acciones son casi idénticas a la propuesta."
    )
    return score, explanation
