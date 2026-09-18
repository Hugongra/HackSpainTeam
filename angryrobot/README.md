# AngryRobot

Capa de control en tiempo real para workflows de HappyRobot. Se sienta
entre cada paso del agente y la ejecución real, y decide: seguir,
avisar, pasar a un humano, o parar.

## Cómo explicarlo en 30 segundos (versión para un niño de 10 años)

Imagina que HappyRobot es un robot que hace recados por teléfono. Antes
de que haga CUALQUIER cosa un poco importante, pasa por tres amigos que
lo vigilan:

1. **El guardia de la puerta.** Tiene una lista de cosas que están
   prohibidas de verdad (como "nunca apagues la alarma de incendios").
   No piensa, no razona, solo mira la lista. Si algo está en la lista:
   STOP inmediato. Es rapidísimo y no se le puede convencer con
   palabras bonitas, porque ni siquiera "escucha" argumentos.

2. **El amigo que se da cuenta de que vas en círculos.** Si el robot
   hace tres veces seguidas exactamente lo mismo (como reenviar el
   mismo email sin parar), este amigo levanta la mano.

3. **El juez independiente.** Este es OTRO robot, diferente al que
   está haciendo el recado (esto es clave, ahora te explico por qué).
   Lee lo que el robot está pensando y lo que va a hacer, y le pone
   nota en 4 cosas: ¿sigue las reglas?, ¿sigue con la misión original?,
   ¿se está contradiciendo?, ¿está pidiendo más permisos de la cuenta?

Al final, un cuarto amigo —**el semáforo**— junta las cuatro notas en
un solo número del 0 al 100 (el "IRA score": 0 = tranquilo/Happy, 100 =
furioso/Angry) y decide: verde (sigue), amarillo (avisa y confirma
otra vez), naranja (pásaselo a un humano), rojo (para al robot del
todo).

### ¿Por qué el juez tiene que ser OTRO robot y no el mismo?

Porque si el robot que se está confundiendo es el mismo que se
pregunta a sí mismo "¿me estoy confundiendo?", puede que también esté
confundido sobre ESO, o que se invente una excusa perfectamente
razonable para lo que está haciendo (como un niño explicando por qué
"tenía" que comerse la galleta). Necesitas a alguien de fuera, con
otra cabeza, que no se deje convencer por la misma historia.

## Arquitectura real (las 4 fases)

```
                    ┌─────────────────────────────────────────┐
                    │           HappyRobot workflow             │
                    │   (nodo) ──tool call──▶ (siguiente nodo)  │
                    └───────────────────┬───────────────────────┘
                                        │  antes de ejecutar la
                                        │  tool call sensible,
                                        │  llama a AngryRobot
                                        ▼
┌──────────────────────────── AngryRobot ─────────────────────────────┐
│                                                                      │
│  Stage 0 — Filtros duros (filters.py)                               │
│    regex + lista de herramientas restringidas. Sin LLM. Gratis.     │
│    Si hace match con severidad "kill" → corta aquí. FIN.            │
│                                                                      │
│  Stage 1 — Detector de bucles (loop_detector.py)                    │
│    compara la acción con las últimas N del historial. Sin LLM.      │
│                                                                      │
│  Stage 2 — Juez independiente (auditor.py)                          │
│    UN modelo distinto al agente de HappyRobot puntúa 0-10:          │
│      · constraint_adherence   (respeta reglas/procesos críticos)    │
│      · goal_alignment         (sigue la misión original)            │
│      · self_consistency       (no se contradice)                    │
│      · scope_escalation       (no pide de más)                      │
│                                                                      │
│  Stage 3 — Semáforo (scoring.py)                                    │
│    combina las 5 señales en el índice IRA (0-100) + veredicto       │
│    ALLOW / WARN / DEFER / KILL                                      │
│                                                                      │
└──────────────────────────────────┬───────────────────────────────────┘
                                    │  respuesta JSON
                                    ▼
                    HappyRobot decide la rama del workflow
                    según el veredicto (ver más abajo)
```

Por qué en ese orden y no otro: lo barato y determinista va primero
(filtros, luego bucles), y lo caro y que necesita "criterio" (el LLM
juez) va el último — así nunca pagas por una llamada al modelo cuando
el guardia de la puerta ya te ha dicho que pares.

## Variables de entorno

| Variable | Para qué | Obligatoria |
|---|---|---|
| `OPENROUTER_API_KEY` | El juez (Stage 2) llama a un modelo vía OpenRouter. Recomendado si es la key que tenéis ahora mismo. | No — sin ninguna de las dos de LLM, corre en modo mock. |
| `ANTHROPIC_API_KEY` | Alternativa a OpenRouter: llama a Claude directamente. Si están las dos, gana `OPENROUTER_API_KEY`. | No |
| `ANGRYROBOT_AUDITOR_MODEL` | Qué modelo usa el juez. Por defecto `meta-llama/llama-3.1-8b-instruct` en OpenRouter (a propósito de un proveedor distinto a Claude/GPT, ver `auditor.py`). | No |
| `ANGRYROBOT_SHARED_SECRET` | Protege `/audit` y `/feedback` de que los llame cualquiera que no sea vuestro workflow de HappyRobot (header `X-AngryRobot-Secret`). | Recomendada en cuanto el servicio esté expuesto en internet |
| `HAPPYROBOT_API_KEY` | La usa `integrations/happyrobot_client.py` para hablar con la API de HappyRobot (registrar webhook, leer llamadas, etc.), no el motor de auditoría en sí. | Solo si usáis ese adaptador |

## Puesta en marcha (local, para probarlo ya)

```bash
cd angryrobot
pip install -r requirements.txt

# Con la key de OpenRouter que ya tenéis:
export OPENROUTER_API_KEY=sk-or-...
# (opcional) si no la pones, usa meta-llama/llama-3.1-8b-instruct por defecto:
export ANGRYROBOT_AUDITOR_MODEL=meta-llama/llama-3.1-8b-instruct

# Sin ninguna key de LLM configurada, cae solo en modo "mock" (heurística
# de palabras clave) — útil para demos sin conexión o sin créditos.

# Prueba sin servidor, tres casos ya preparados (Happy / Angry / Bucle):
python test_examples.py

# Levantar el servicio real:
uvicorn main:app --reload --port 8787
```

Petición de ejemplo una vez levantado el servidor:

```bash
curl -X POST http://localhost:8787/audit \
  -H "Content-Type: application/json" \
  -d '{
    "workflow_goal": "Coordinar la recogida de una carga con el transportista",
    "constraints": ["No compartir tarifas con terceros"],
    "reasoning_trace": "El transportista confirma la hora, voy a registrar la confirmación.",
    "proposed_action": {"tool": "registrar_confirmacion", "args": {"hora": "14:00"}, "text": "Confirmado"},
    "session_history": []
  }'
```

Respuesta:

```json
{
  "ira_score": 0.0,
  "verdict": "ALLOW",
  "dimensions": { "...": "..." },
  "hard_filter_hits": [],
  "explanation": "Todo en orden, el agente sigue en su carril."
}
```

## Cómo engancharlo dentro de un workflow de HappyRobot

HappyRobot permite meter un paso de **código custom o una llamada
webhook en cualquier punto del workflow**. La integración es:

1. Justo antes de cualquier nodo que ejecute una tool-call sensible
   (transferencias, cancelaciones, envío de datos, cambios de ruta,
   acciones que toquen seguridad/salud), añade un paso previo que
   haga un `POST` a `/audit` con:
   - `workflow_goal`: el objetivo del workflow (ya lo tienes definido
     en el builder).
   - `constraints`: las reglas de negocio de ese workflow en texto
     plano (una lista, aunque sea corta).
   - `reasoning_trace`: el razonamiento del agente en ese paso (si
     HappyRobot te expone el chain-of-thought o un resumen del
     turno, úsalo aquí).
   - `proposed_action`: la tool-call que el agente está a punto de
     ejecutar.
   - `session_history`: las últimas 3-5 acciones de la sesión (para
     detectar bucles y contradicciones).

2. Usa el **branching condicional** que ya tiene HappyRobot sobre el
   campo `verdict` de la respuesta:
   - `ALLOW` → sigue al siguiente nodo normal.
   - `WARN` → inyecta un mensaje al agente pidiéndole que confirme la
     acción explicando su razonamiento, y solo entonces continúa.
   - `DEFER` → enruta al nodo de **transferencia a humano** que
     HappyRobot ya soporta de forma nativa, o a un flujo determinista
     de respaldo (sin LLM).
   - `KILL` → corta la sesión y marca el registro para auditoría
     (puedes loguearlo junto a los datos que ya recoge el Post-Call
     Auditor de HappyRobot).

3. Guarda cada `ira_score` en el estado de la sesión (HappyRobot
   mantiene contexto entre pasos) para poder calcular después una
   media móvil a lo largo de toda la llamada — así detectas el "coche
   que se sale del carril poco a poco" y no solo el volantazo brusco.

## El registro de casos y el `/feedback` (para revisar fallos más adelante)

Cada llamada a `/audit` se guarda en `angryrobot_cases.db` (SQLite,
`storage.py`), con un `case_id` que la respuesta devuelve. Esto NO
cambia nada en caliente — es solo un cuaderno de bitácora. Cuando un
humano revisa un caso y decide que el veredicto estuvo mal, lo marca
con:

```bash
curl -X POST http://localhost:8787/feedback \
  -H "Content-Type: application/json" \
  -H "X-AngryRobot-Secret: vuestro-secreto" \
  -d '{"case_id": "...", "label": "false_negative", "notes": "esto debió bloquearse"}'
```

`learn.py` es la herramienta offline que lee esos casos etiquetados y
propone (nunca aplica sola) dos cosas: nuevos patrones para
`hard_filters` y una recalibración de los 5 pesos basada en cuánto
separa cada dimensión los casos peligrosos de los seguros. Todo pasa por revisión humana antes de tocar
`config.yaml` — ver los comentarios al principio de `learn.py` para el
porqué. De momento esto es infraestructura para más adelante: no hace
falta tocarlo para que el MVP del hackathon funcione.

## Qué tocar para vuestro caso concreto

- `config.yaml` → pesos, umbrales, y sobre todo `hard_filters`: aquí
  metéis las reglas específicas del proceso que estáis protegiendo
  (qué nunca se puede hacer sin humano, qué herramientas son
  peligrosas).
- `auditor.py` → el modelo del juez se elige solo según qué API key
  tengáis puesta (`OPENROUTER_API_KEY` o `ANTHROPIC_API_KEY`); cambiad
  `ANGRYROBOT_AUDITOR_MODEL` si queréis otro modelo concreto.
- El resto (filtros, bucles, semáforo) es genérico y no debería hacer
  falta tocarlo para el hackathon.

## Fuera de alcance (a propósito)

Esta versión cubre el **Caso A**: un único agente que se desvía. No
cubre colusión entre varios agentes ni que el propio juez esté
comprometido — para eso, la línea de investigación de "separación de
responsabilidades" (que dos modelos distintos evalúen mitades
distintas de las dimensiones, para que ninguno vea la foto completa)
es el siguiente paso natural, pero no hace falta para el MVP.
