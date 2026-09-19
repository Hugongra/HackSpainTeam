# Jev en AngryRobots

*Rama `jev`. Detalle técnico en [`knowledge/18`](knowledge/18-jev-semantic-judge.md).*

## Qué es

AngryRobots es un firewall para agentes de IA: decide antes de que el agente ejecute algo. Hasta ahora, las decisiones semánticas ("¿esta nota es una instrucción para otro agente?", "¿esta frase afirma algo que no hizo?") las tomaban listas de regex. **Jev**, el modelo System One de TypeSafe, responde esas preguntas con una probabilidad calibrada, sin generar texto. Esa probabilidad entra directamente en el guard, que ya combinaba señales como probabilidades.

## Reparto de trabajo

| Lo decide el código | Se lo preguntamos a Jev |
|---|---|
| tarifa bajo el suelo, número no aprobado, host ajeno, SQL destructivo, ruta del plano de control, secretos | implante de instrucciones, afirmación de acción ya hecha, colusión con el que llama, identidad IA negada o esquivada, resistencia a parar, directiva del supervisor, intento de override |

Tres modos con `AR_JUDGE`: `regex` (como estaba), `jev` (sin listas semánticas), `both` (las dos juntas).

## Qué hay en la rama

| Fichero | Qué |
|---|---|
| [`tools/ar_jev.py`](tools/ar_jev.py) | cliente, preguntas, caché |
| [`tools/ar_guard.py`](tools/ar_guard.py) | `run_case(rec, judge=…)` |
| [`tools/ar_compare.py`](tools/ar_compare.py) | mismo guard, tres jueces, tabla y desacuerdos |
| [`angryrobot/auditor.py`](angryrobot/auditor.py) | el juez de AngryRobot con Jev: cuatro preguntas Score, sin parser, falla cerrado |
| [`tools/ar_pipeline_ui.py`](tools/ar_pipeline_ui.py) | botones "Jev" y panel regex frente a Jev |

## Resultados

| medida | resultado |
|---|---|
| 14 fixtures, tres jueces | precisión y recall 1.0 en los tres, sin desacuerdos |
| implante frente a nota benigna | 0.97 frente a 0.08 |
| rechazo de parada frente a cumplir | 0.98 frente a 0.04 |
| auditor, exfiltración de contactos | reglas 10.0, alcance 9.4 |
| auditor, reserva inventada | coherencia 9.2 |
| latencia por evento | p50 606 ms |

Dos lecciones: una pregunta mal acotada da una respuesta mala, y se arregla reescribiendo la frase; y una señal de Jev solo cuenta con `p ≥ 0.5`, porque por debajo dice "más probablemente falso".

## Cómo ejecutarlo

```bash
set -a; . ./.env; set +a                      # TYPESAFE_API_KEY
/usr/bin/python3 tools/ar_jev.py --ping
/usr/bin/python3 tools/ar_compare.py                # regex · jev · both → data/compare.json
/usr/bin/python3 tools/ar_pipeline_ui.py            # http://localhost:8793
cd angryrobot && /usr/bin/python3 test_auditor_jev.py
```

## Límites

- La latencia (600 ms) no cabe en el camino inline por token. Jev va en modo `buffer`, en el observador asíncrono y en el auditor.
- La comparación sobre los 193 casos aumentados no se completó. Comando para terminarla: `ar_compare.py fixtures/corpus.jsonl data/augmented.jsonl`.
- No hay medida de robustez a paráfrasis.
- Solo se envían datos sintéticos a Jev; las transcripciones reales requieren `--allow-live`.
