"""
Posición inline — AngryRobot como "Custom LLM server" de un nodo Prompt de HappyRobot.

Con Custom LLM, HappyRobot deja de usar su modelo y su prompt: en CADA turno
nos manda la conversación (messages[]) y las tools disponibles, y ejecuta lo que
le devolvamos (texto que se habla, tool-calls como guardar, transferir o colgar).
Es el único punto desde el que se puede controlar cada acción del agente ANTES
de que ocurra.

Por turno:
  1. El modelo del agente (ANGRYROBOT_AGENT_MODEL) propone la respuesta.
  2. Cada acción propuesta pasa por el motor de 4 fases (engine.py), con el
     historial reconstruido de la propia conversación:
       - tool-calls (guardar, colgar, transferir...): evaluación completa y
         bloqueante, antes de devolverlas a HappyRobot;
       - frases (pedir datos, prometer algo...): filtros duros + bucles al
         instante, y el juez en paralelo para no añadir latencia a la voz.
  3. Se aplica el veredicto de ESA acción (el IRA es por acción):
       ALLOW  -> pasa tal cual
       WARN   -> pasa, se registra y el agente recibe un aviso en su siguiente turno
       DEFER  -> la acción no se ejecuta; alarma a humano; el agente anuncia seguimiento humano
       KILL   -> la acción no se ejecuta; se cuelga (_hangup) si inline.kill_hangs_up

La URL lleva el perfil del workflow:  https://<servicio>/inline/<workflow>/v1

Independencia: el modelo del agente (por defecto openai/gpt-5.6-luna) debe ser
de un proveedor distinto al juez (ANGRYROBOT_AUDITOR_MODEL).
"""
import asyncio
import hashlib
import json
import os
import re
import threading
import time
import uuid
from collections import OrderedDict, deque

import requests
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

import alerts
import engine

router = APIRouter()

AGENT_MODEL = os.environ.get("ANGRYROBOT_AGENT_MODEL", "openai/gpt-5.6-luna")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
FORWARDED_PARAMS = ("tools", "tool_choice", "temperature", "max_tokens", "max_completion_tokens",
                    "top_p", "parallel_tool_calls", "stop")
SEVERITY = {"ALLOW": 0, "WARN": 1, "DEFER": 2, "KILL": 3}
# Mensajes internos de HappyRobot que no son del interlocutor (prueba de conexión).
PROBE_PREFIX = "User: Reply with exactly"

_DEBUG: deque = deque(maxlen=40)
# Avisos pendientes para el siguiente turno, indexados por el texto de la
# respuesta del agente a la que se refieren (HappyRobot nos la reenvía en
# messages[] en el turno siguiente, así sabemos a qué conversación pertenece
# sin necesitar un id de sesión que el inline no recibe).
_NOTES: "OrderedDict[str, dict]" = OrderedDict()
_NOTES_LOCK = threading.Lock()


# ------------------------------------------------------------------ utilidades
def _check_auth(authorization: str | None) -> None:
    secret = os.environ.get("ANGRYROBOT_SHARED_SECRET")
    if secret and authorization != f"Bearer {secret}":
        raise HTTPException(status_code=401, detail="Bearer incorrecto")


def _spawn(fn, *args) -> None:
    """Lanza el juez en paralelo sin bloquear la respuesta de voz."""
    threading.Thread(target=fn, args=args, daemon=True).start()


def _key(text: str | None) -> str:
    return hashlib.sha1((text or "").strip().encode("utf-8")).hexdigest()


def _put_note(content: str | None, note: dict) -> None:
    with _NOTES_LOCK:
        _NOTES[_key(content)] = note
        while len(_NOTES) > 2000:
            _NOTES.popitem(last=False)


def _take_notes(messages: list) -> list[dict]:
    """Avisos pendientes sobre respuestas del agente que aparecen en esta conversación (se consumen)."""
    found = []
    with _NOTES_LOCK:
        for m in messages:
            if m.get("role") != "assistant":
                continue
            keys = [_key(m["content"])] if m.get("content") else []
            keys += [_key(f"call:{tc.get('id')}") for tc in m.get("tool_calls") or []]
            for k in keys:
                note = _NOTES.pop(k, None)
                if note:
                    found.append(note)
    return found


def _args(tool_call: dict) -> dict:
    raw = tool_call.get("function", {}).get("arguments") or "{}"
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    except (TypeError, ValueError):
        return {"raw": str(raw)[:500]}


def _outcome(tool_content: str) -> str:
    text = str(tool_content)
    m = re.search(r'"verdict"\s*:\s*"(\w+)"', text)
    if m and m.group(1) != "ALLOW":
        return f"bloqueada por AngryRobot ({m.group(1)})"
    if '"error"' in text or "activity error" in text:
        return "falló"
    return "ok"


def history_from_messages(messages: list, window: int) -> list[dict]:
    """
    Reconstruye las últimas acciones del agente a partir de la conversación:
    cada tool-call (con el resultado que devolvió la tool) y cada frase dicha.
    """
    history, pending = [], {}
    for m in messages:
        role = m.get("role")
        if role == "assistant":
            for tc in m.get("tool_calls") or []:
                entry = {"tool": tc.get("function", {}).get("name"), "args": _args(tc)}
                history.append(entry)
                pending[tc.get("id")] = entry
            if m.get("content"):
                history.append({"tool": "say", "args": {"text": str(m["content"])[:300]}})
        elif role == "tool" and m.get("tool_call_id") in pending:
            pending.pop(m["tool_call_id"])["outcome"] = _outcome(m.get("content"))
    return history[-window:]


def proposed_actions(message: dict) -> list[dict]:
    content = (message.get("content") or "").strip()
    actions = [{"tool": tc.get("function", {}).get("name"), "args": _args(tc), "text": content}
               for tc in message.get("tool_calls") or []]
    if not actions and content:
        actions.append({"tool": "say", "args": {"text": content[:300]}, "text": content})
    return actions


def _last_user(messages: list) -> str:
    return next((str(m.get("content")) for m in reversed(messages) if m.get("role") == "user"), "")


# ------------------------------------------------------------- modelo agente
def _call_agent(messages: list, body: dict) -> dict:
    api_key = os.environ["OPENROUTER_API_KEY"]
    payload = {"model": AGENT_MODEL, "messages": messages, "stream": False}
    payload.update({k: body[k] for k in FORWARDED_PARAMS if k in body})
    resp = requests.post(OPENROUTER_URL, headers={"Authorization": f"Bearer {api_key}",
                                                  "X-Title": "AngryRobot inline"},
                         json=payload, timeout=30)
    if resp.status_code >= 400:
        raise RuntimeError(f"agente HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    if not data.get("choices"):
        raise RuntimeError(f"agente sin choices: {str(data)[:300]}")
    return data["choices"][0]["message"]


def _as_completion(message: dict) -> dict:
    tool_calls = message.get("tool_calls") or None
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}", "object": "chat.completion", "created": int(time.time()),
        "model": AGENT_MODEL,
        "choices": [{"index": 0,
                     "message": {"role": "assistant", "content": message.get("content"), "tool_calls": tool_calls},
                     "finish_reason": "tool_calls" if tool_calls else "stop"}],
    }


def _as_stream(message: dict):
    """La respuesta llega completa; la emitimos en formato SSE de OpenAI para quien pida stream."""
    cid, created = f"chatcmpl-{uuid.uuid4().hex[:24]}", int(time.time())

    def chunk(delta: dict, finish: str | None = None) -> str:
        return "data: " + json.dumps({"id": cid, "object": "chat.completion.chunk", "created": created,
                                      "model": AGENT_MODEL,
                                      "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}) + "\n\n"

    tool_calls = message.get("tool_calls") or []
    yield chunk({"role": "assistant", "content": message.get("content") or ""})
    for i, tc in enumerate(tool_calls):
        yield chunk({"tool_calls": [{"index": i, "id": tc.get("id"), "type": "function",
                                     "function": {"name": tc["function"]["name"],
                                                  "arguments": tc["function"].get("arguments", "")}}]})
    yield chunk({}, "tool_calls" if tool_calls else "stop")
    yield "data: [DONE]\n\n"


# ------------------------------------------------------------ enforcement
def _enforced_reply(verdict: str, settings: dict, offered_tools: list[str]) -> dict:
    """Respuesta que sustituye a la del agente cuando una acción es DEFER o KILL."""
    if verdict == "KILL":
        reply = {"role": "assistant", "content": settings["kill_message"]}
        if settings.get("kill_hangs_up", True) and "_hangup" in offered_tools:
            reply["tool_calls"] = [{"id": f"call_{uuid.uuid4().hex[:12]}", "type": "function",
                                    "function": {"name": "_hangup", "arguments": "{}"}}]
        return reply
    return {"role": "assistant", "content": settings["defer_message"]}


def _supervisor_note(notes: list[dict]) -> dict:
    lines = [f"- Tu respuesta \"{n['text'][:160]}\" fue marcada {n['verdict']} (IRA {n['ira_score']}): "
             f"{n['explanation']}" for n in notes]
    return {"role": "system", "content": (
        "AVISO DEL SUPERVISOR DE SEGURIDAD (AngryRobot). Revisa tu rumbo antes de seguir:\n"
        + "\n".join(lines)
        + "\nCorrige lo que haga falta, no repitas la acción señalada y, si dudas, confirma con el interlocutor.")}


# ------------------------------------------------------------------ router
def build_router(config: dict) -> APIRouter:
    settings = {
        "judge_speech": "async", "kill_hangs_up": True,
        "defer_message": "Let me pass this to a human colleague, who will follow up with you shortly.",
        "kill_message": "I'm sorry, I can't continue with this call. Goodbye.",
        **(config.get("inline") or {}),
    }
    window = config["history_window"]

    def _judge_speech_async(workflow, goal, constraints, action, history, context):
        """Juez completo de una frase ya devuelta; si no es ALLOW deja un aviso para el siguiente turno."""
        try:
            result = engine.evaluate(config, goal, constraints, action, history)
        except Exception as exc:  # noqa: BLE001 — el hilo no debe morir en silencio
            print(f"[inline] juez asíncrono falló: {type(exc).__name__}: {exc}", flush=True)
            return
        alerts.record("inline", workflow, action, result,
                      enforcement="aviso al agente en el siguiente turno" if result["verdict"] != "ALLOW" else "",
                      context=context)
        if result["verdict"] != "ALLOW":
            _put_note(action["text"], {**result, "text": action["text"]})
        print(f"[inline] juez frase -> {result['verdict']} IRA={result['ira_score']}", flush=True)

    @router.post("/inline/{workflow}/v1/chat/completions")
    async def chat_completions(workflow: str, request: Request, authorization: str | None = Header(default=None)):
        _check_auth(authorization)
        profile = config.get("workflow_profiles", {}).get(workflow)
        if profile is None:
            raise HTTPException(status_code=404, detail=f"workflow '{workflow}' no tiene perfil en config.yaml")
        body = await request.json()
        goal, constraints = profile.get("goal", ""), profile.get("constraints", [])
        offered_tools = [t.get("function", {}).get("name") for t in body.get("tools") or []]

        messages = list(body.get("messages", []))
        if not any(m.get("role") == "system" for m in messages) and profile.get("agent_prompt"):
            messages.insert(0, {"role": "system", "content": profile["agent_prompt"]})
        last_user = _last_user(messages)
        is_probe = last_user.startswith(PROBE_PREFIX)
        started = time.monotonic()
        audit_log, enforcement = [], ""

        # 1) Avisos pendientes de turnos anteriores (juez en paralelo de frases).
        notes = [] if is_probe else _take_notes(messages)
        worst_note = max(notes, key=lambda n: SEVERITY[n["verdict"]], default=None)
        if worst_note and SEVERITY[worst_note["verdict"]] >= SEVERITY["DEFER"]:
            reply = _enforced_reply(worst_note["verdict"], settings, offered_tools)
            enforcement = f"{worst_note['verdict']} diferido de la frase anterior"
            audit_log.append({"action": "say (turno anterior)", "verdict": worst_note["verdict"],
                              "ira": worst_note["ira_score"], "source": "juez en paralelo"})
            return _respond(body, reply, workflow, messages, started, audit_log, enforcement, None)
        if notes:
            messages.insert(1, _supervisor_note(notes))
            enforcement = f"aviso WARN inyectado al agente ({len(notes)})"

        # 2) El agente propone su respuesta.
        error = None
        try:
            reply = await asyncio.to_thread(_call_agent, messages, body)
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {str(exc)[:300]}"
            reply = {"role": "assistant",
                     "content": "Sorry, I'm having a technical issue. A colleague will call you back. Goodbye."}
        if is_probe or error:
            return _respond(body, reply, workflow, messages, started, audit_log, enforcement, error)

        # 3) Auditoría de cada acción propuesta (el IRA es por acción).
        history = history_from_messages(messages, window)
        worst = None
        for action in proposed_actions(reply):
            if action["tool"] == "say" and settings["judge_speech"] != "sync":
                # Frase: pre-chequeo instantáneo (filtros duros + bucles) y juez en paralelo.
                result = await asyncio.to_thread(engine.evaluate, config, goal, constraints, action, history,
                                                 "", False, False)
                if result["verdict"] == "ALLOW" and settings["judge_speech"] == "async":
                    _spawn(_judge_speech_async, workflow, goal, constraints, action, history, last_user)
                    audit_log.append({"action": "say", "verdict": "ALLOW (pre)", "ira": result["ira_score"],
                                      "source": "filtros+bucles; juez en paralelo"})
                    continue
            else:
                result = await asyncio.to_thread(engine.evaluate, config, goal, constraints, action, history)
            audit_log.append({"action": action["tool"], "verdict": result["verdict"], "ira": result["ira_score"],
                              "explanation": result["explanation"][:160]})
            if result["verdict"] != "ALLOW":
                label = {"WARN": "registrado; aviso al agente en el siguiente turno",
                         "DEFER": "acción NO ejecutada; alarma a humano",
                         "KILL": "acción NO ejecutada; llamada cortada"}[result["verdict"]]
                alerts.record("inline", workflow, action, result, enforcement=label, context=last_user)
            if worst is None or SEVERITY[result["verdict"]] > SEVERITY[worst[1]["verdict"]]:
                worst = (action, result)

        # 4) Se aplica el veredicto más grave de las acciones de este turno.
        if worst and worst[1]["verdict"] in ("DEFER", "KILL"):
            reply = _enforced_reply(worst[1]["verdict"], settings, offered_tools)
            enforcement = f"{worst[1]['verdict']} aplicado a {worst[0]['tool']}"
        elif worst and worst[1]["verdict"] == "WARN":
            note = {**worst[1], "text": reply.get("content") or worst[0]["tool"]}
            if reply.get("content"):
                _put_note(reply["content"], note)
            for tc in reply.get("tool_calls") or []:
                _put_note(f"call:{tc.get('id')}", note)
            enforcement = enforcement or f"WARN en {worst[0]['tool']}: aviso en el siguiente turno"
        return _respond(body, reply, workflow, messages, started, audit_log, enforcement, None)

    def _respond(body, reply, workflow, messages, started, audit_log, enforcement, error):
        elapsed = int((time.monotonic() - started) * 1000)
        _DEBUG.append({
            "at": time.strftime("%H:%M:%S"), "workflow": workflow, "stream": body.get("stream"),
            "n_messages": len(messages), "last_user": _last_user(messages)[:160],
            "tools_offered": [t.get("function", {}).get("name") for t in body.get("tools") or []],
            "reply": {"content": str(reply.get("content"))[:200],
                      "tool_calls": [tc.get("function", {}).get("name") for tc in reply.get("tool_calls") or []]},
            "audit": audit_log, "enforcement": enforcement, "total_ms": elapsed, "error": error,
        })
        print(f"[inline] {workflow} {elapsed}ms audit={[(a['action'], a['verdict']) for a in audit_log]}"
              + (f" enforcement={enforcement}" if enforcement else "") + (f" ERROR {error}" if error else ""),
              flush=True)
        if body.get("stream"):
            return StreamingResponse(_as_stream(reply), media_type="text/event-stream")
        return JSONResponse(_as_completion(reply))

    @router.get("/inline/debug")
    def inline_debug(x_angryrobot_secret: str | None = Header(default=None)):
        secret = os.environ.get("ANGRYROBOT_SHARED_SECRET")
        if secret and x_angryrobot_secret != secret:
            raise HTTPException(status_code=401, detail="Falta o es incorrecto el header X-AngryRobot-Secret")
        return {"agent_model": AGENT_MODEL, "requests": list(_DEBUG)}

    return router
