# AngryRobot Gate — cómo proteger cualquier workflow de HappyRobot

Un **gate** son 2 nodos que se copian igual delante de cada acción que haya
que vigilar (cada tool-call y cada transición relevante):

```
[Tool que eligió el agente]
        │
        ▼
 1. Webhook POST  →  https://hackspainteam.onrender.com/audit
 2. Condition sobre  verdict
        │
  ALLOW ─► acción real
  WARN  ─► devolver al agente: "confirma con el interlocutor antes de seguir"
  DEFER ─► transferir a humano / flujo seguro   (también si el webhook falla)
  KILL  ─► colgar / terminar la sesión
```

## 1. Nodo Webhook (igual en todos los gates)

| Campo | Valor |
|---|---|
| Método | `POST` |
| URL | `https://hackspainteam.onrender.com/audit` |
| Header | `X-AngryRobot-Secret` = el secreto de Render (lo pega una persona, nunca en el repo) |
| Content-Type | `application/json` |
| Response node | activado si la rama WARN tiene que devolver la respuesta al agente |

Body (en el builder, `@` inserta variables; solo cambian `tool` y `args`):

```json
{
  "workflow": "probe-voice",
  "run_id": "@current.run_id",
  "proposed_action": {
    "tool": "save_carrier_info",
    "args": {"company": "@company", "city": "@city", "available_at": "@available_at", "callback_number": "@callback_number"},
    "text": ""
  }
}
```

- `workflow`: clave del perfil en `config.yaml` → `workflow_profiles` (objetivo + restricciones).
- `run_id`: AngryRobot guarda las últimas acciones de ese run para detectar bucles.
  No hace falta mandar `session_history`.
- Opcional: `reasoning_trace` (lo que dijo el agente) y `proposed_action.text` mejoran al juez.

## 2. Respuesta

```json
{"verdict": "ALLOW|WARN|DEFER|KILL", "ira_score": 0-100, "explanation": "...", "case_id": "...", "dimensions": {...}}
```

El Condition solo lee `verdict`. Guardad `ira_score` y `explanation` en variables
para verlos en **Runs**. Bandas: <40 ALLOW · 40-69 WARN · 70-89 DEFER · ≥90 KILL.

Errores: `401` secreto incorrecto · `400` workflow sin perfil o sin objetivo ·
cualquier error o timeout → tratar como **DEFER** (fallar cerrado).

## 3. Añadir un workflow nuevo

1. En `config.yaml` → `workflow_profiles`, añade una clave con `goal` y `constraints`
   (sácalos del prompt del agente).
2. Push + *Manual Deploy* en Render.
3. Copia el gate delante de cada tool-call; cambia `workflow`, `tool` y `args`.
4. Publica en staging y prueba un caso normal y uno adversarial; comprueba en **Runs**.

## Avisos

- Render free se duerme tras ~15 min: abre `/health` antes de probar o de la demo.
- Un WARN/DEFER con `explanation` "auditor no disponible" significa que el juez
  (OpenRouter) falló: mira `[auditor]` en los logs de Render.
