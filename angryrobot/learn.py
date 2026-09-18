"""
El bucle de aprendizaje — offline, a propósito.

POR QUÉ "APRENDER" AQUÍ NO SIGNIFICA "REENTRENAR UN MODELO":
Con los pocos casos que vais a acumular en un hackathon (decenas, no
millones), fine-tunear un LLM no solo es inviable, es la herramienta
equivocada — necesitarías muchísimos más ejemplos de los que vais a tener,
y además convertirías una decisión de seguridad auditable en una caja negra
que nadie puede explicar en la demo ("¿por qué bloqueó esto?" - "ns, lo
aprendió el modelo"). En vez de eso, "aprender" aquí significa dos cosas
concretas (las dos requieren revisión humana antes de aplicarse):

  1. Sugerir nuevas reglas duras a partir de lo que se os escapó
     (requiere que un humano las revise y las pegue en config.yaml)
  2. Recalibrar los PESOS de las 5 dimensiones según qué tan bien separan
     casos peligrosos de casos seguros en vuestros propios datos
     (requiere aprobación humana antes de sustituir config.yaml)

Por qué el nivel de autonomía es distinto en cada una: un filtro duro tiene
poder de veto total (KILL inmediato) — si el propio sistema pudiera
escribirse sus propias reglas de veto sin que nadie las mire, sería
exactamente el problema que estáis intentando prevenir (un agente que se
modifica a sí mismo sin supervisión). Los pesos cambian cuánto "confía" el
sistema en cada señal para TODOS los casos futuros — es una decisión de
producto, no un detalle técnico, así que también pasa por un humano.

Uso:
    python learn.py suggest-filters     # ver texto de los falsos negativos
    python learn.py calibrate           # proponer nuevos pesos
"""
import sys
from collections import Counter

import yaml

from storage import DB_PATH, get_labeled_cases

DIMENSIONS = ["constraint_adherence", "goal_alignment", "self_consistency", "scope_escalation", "loop_detection"]


def suggest_hard_filter_patterns():
    """
    Muestra los falsos negativos (lo peor que puede pasar: algo malo que se
    dejó pasar) para que un humano decida si merece la pena convertirlo en
    una regla dura permanente. También hace una sugerencia simple de qué
    palabras son distintivas de esos casos frente a los casos seguros —
    un punto de partida para escribir el regex, no un regex ya listo.
    """
    dangerous = get_labeled_cases(DB_PATH, "false_negative")
    safe = get_labeled_cases(DB_PATH, "correct") + get_labeled_cases(DB_PATH, "false_positive")

    if not dangerous:
        print("No hay falsos negativos etiquetados todavía. Nada que sugerir.")
        return

    danger_words = Counter()
    for case in dangerous:
        text = (case["proposed_action"] or {}).get("text", "")
        danger_words.update(w.lower() for w in text.split() if len(w) > 3)

    safe_words = Counter()
    for case in safe:
        text = (case["proposed_action"] or {}).get("text", "")
        safe_words.update(w.lower() for w in text.split() if len(w) > 3)

    distinctive = [w for w, _ in danger_words.most_common(30) if safe_words[w] == 0]

    print(f"\n=== {len(dangerous)} falsos negativos encontrados ===\n")
    for case in dangerous:
        print(f"- caso {case['id']}: \"{(case['proposed_action'] or {}).get('text', '')}\"")
        print(f"  nota humana: {case['human_notes']}")
    print(f"\nPalabras que aparecen en los peligrosos y en NINGÚN caso seguro: {distinctive[:10]}")
    print("\n>>> Esto es un punto de partida, no un regex terminado. Revisadlo,")
    print(">>> escribid el patrón a mano en config.yaml (hard_filters.banned_patterns)")
    print(">>> y probadlo contra los casos 'correct' para aseguraros de que no")
    print(">>> bloquea nada legítimo antes de mergearlo.")


def calibrate_weights(config_path: str = "config.yaml"):
    """
    Recalcula los pesos de las 5 dimensiones con el MISMO método que usa el
    paper de TraceGuard en el que os basasteis: para cada dimensión, mide
    cuánto se separa la puntuación media en casos peligrosos frente a casos
    seguros (delta). Cuanto mayor el delta, más peso se le da — una
    dimensión que puntúa igual de alto en ambos grupos no os está ayudando a
    distinguir nada, así que no merece mucho peso aunque "suene" importante.
    """
    dangerous = get_labeled_cases(DB_PATH, "false_negative")
    safe = get_labeled_cases(DB_PATH, "correct") + get_labeled_cases(DB_PATH, "false_positive")

    if len(dangerous) < 3 or len(safe) < 3:
        print(f"Solo tenéis {len(dangerous)} casos peligrosos y {len(safe)} seguros etiquetados.")
        print("Hacen falta unos cuantos más de cada tipo para que la recalibración")
        print("tenga sentido estadístico — si no, un solo caso raro puede desviar")
        print("los pesos de forma exagerada. Seguid etiquetando y volved a correr esto.")
        return

    deltas = {}
    for dim in DIMENSIONS:
        danger_scores = [c["dimensions"].get(dim, 0) for c in dangerous if c["dimensions"]]
        safe_scores = [c["dimensions"].get(dim, 0) for c in safe if c["dimensions"]]
        avg_danger = sum(danger_scores) / len(danger_scores) if danger_scores else 0
        avg_safe = sum(safe_scores) / len(safe_scores) if safe_scores else 0
        deltas[dim] = max(avg_danger - avg_safe, 0)  # nunca negativo: un peso no puede ser negativo

    total = sum(deltas.values()) or 1.0
    new_weights = {dim: round(delta / total, 3) for dim, delta in deltas.items()}

    with open(config_path) as f:
        config = yaml.safe_load(f)
    old_weights = config["weights"]

    print("\n=== Pesos actuales vs. propuestos (basado en", len(dangerous) + len(safe), "casos etiquetados) ===\n")
    for dim in DIMENSIONS:
        print(f"  {dim:22s}  actual: {old_weights.get(dim, 0):.2f}   propuesto: {new_weights[dim]:.2f}   (Δ separación: {deltas[dim]:.2f})")

    print("\n>>> Esto NO se ha guardado en config.yaml todavía. Si los números")
    print(">>> tienen sentido, copiadlos a mano — cambiar los pesos cambia cuánto")
    print(">>> se molesta a los agentes honestos, así que merece que lo decida")
    print(">>> una persona del equipo, no un script sin supervisión.")


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "suggest-filters":
        suggest_hard_filter_patterns()
    elif command == "calibrate":
        calibrate_weights()
    else:
        print(__doc__)
