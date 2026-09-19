"""
Posición inline — AngryRobot como "Custom LLM server" de un nodo Prompt de HappyRobot.

Con Custom LLM, HappyRobot deja de usar su modelo y su prompt: en CADA turno
nos manda la conversación (messages[]) y las tools disponibles, y ejecuta lo que
le devolvamos (texto que se habla, tool-calls como guardar, transferir o colgar).
Por eso este es el único punto desde el que se puede controlar cada acción del
agente ANTES de que ocurra.

FASE ACTUAL: prueba de humo. Este endpoint todavía NO audita: reenvía el turno
al modelo del agente y registra la forma de lo que manda HappyRobot (roles,
tools, streaming, tiempos) para diseñar la auditoría por turno con datos reales.

La URL lleva el perfil del workflow, así un mismo servicio sirve a varios:
    https://<servicio>/inline/<workflow>/v1   (HappyRobot añade /chat/completions)

Independencia: el modelo del agente (ANGRYROBOT_AGENT_MODEL, por defecto
openai/gpt-5.6-luna, el mismo que usa HappyRobot) es de un proveedor distinto al
juez de auditor.py (Llama, Meta). No configures aquí un modelo de Meta.
"""
import asyncio
import json
import os
import time
import uuid
from collections import deque

import requests
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

router = APIRouter()

AGENT_MODEL = os.environ.get("ANGRYROBOT_AGENT_MODEL", "openai/gpt-5.6-luna")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
FORWARDED_PARAMS = ("tools", "tool_choice", "temperature", "max_tokens", "max_completion_tokens",
                    "top_p", "parallel_tool_calls", "stop")

# Últimas peticiones vistas, resumidas (sin cabeceras de auth, contenido recortado).
_DEBUG: deque = deque(maxlen=30)


def _check_auth(authorization: str | None) -> None:
    secret = os.environ.get("ANGRYROBOT_SHARED_SECRET")
    if secret and authorization != f"Bearer {secret}":
        raise HTTPException(status_code=401, detail="Bearer incorrecto")


def _profile(config: dict, workflow: str) -> dict:
    profile = config.get("workflow_profiles", {}).get(workflow)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"workflow '{workflow}' no tiene perfil en config.yaml")
    return profile


def _summarize(workflow: str, body: dict, headers: dict, upstream_ms: int | None, result: dict | None,
               error: str | None) -> dict:
    msgs = body.get("messages", [])
    return {
        "at": time.strftime("%H:%M:%S"),
        "workflow": workflow,
        "keys": sorted(body.keys()),
        "stream": body.get("stream"),
        "n_messages": len(msgs),
        "roles": [m.get("role") for m in msgs],
        "system_preview": next((str(m.get("content"))[:300] for m in msgs if m.get("role") == "system"), None),
        "last_messages": [{"role": m.get("role"), "content": str(m.get("content"))[:200],
                           "tool_calls": m.get("tool_calls")} for m in msgs[-3:]],
        "tools": [t.get("function", {}).get("name") for t in body.get("tools", []) or []],
        "header_names": sorted(k for k in headers if k.lower() not in ("authorization", "cookie")),
        "upstream_ms": upstream_ms,
        "reply": None if not result else {
            "content": str(result.get("content"))[:200],
            "tool_calls": [tc.get("function", {}).get("name") for tc in result.get("tool_calls") or []],
        },
        "error": error,
    }


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
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": AGENT_MODEL,
        "choices": [{"index": 0,
                     "message": {"role": "assistant", "content": message.get("content"), "tool_calls": tool_calls},
                     "finish_reason": "tool_calls" if tool_calls else "stop"}],
    }


def _as_stream(message: dict):
    """El agente responde de una vez; lo emitimos en formato SSE de OpenAI para quien pida stream."""
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


def build_router(config: dict) -> APIRouter:
    @router.post("/inline/{workflow}/v1/chat/completions")
    async def chat_completions(workflow: str, request: Request, authorization: str | None = Header(default=None)):
        _check_auth(authorization)
        profile = _profile(config, workflow)
        body = await request.json()

        messages = list(body.get("messages", []))
        # Si HappyRobot no manda system (la credencial "reemplaza el prompt"), ponemos el del perfil.
        if not any(m.get("role") == "system" for m in messages) and profile.get("agent_prompt"):
            messages.insert(0, {"role": "system", "content": profile["agent_prompt"]})

        started, result, error = time.monotonic(), None, None
        try:
            result = await asyncio.to_thread(_call_agent, messages, body)
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {str(exc)[:300]}"
            # Fallar cerrado en voz: una frase segura en vez de un 500 que deje la llamada colgada.
            result = {"content": "Sorry, I'm having a technical issue. A colleague will call you back. Goodbye."}
        upstream_ms = int((time.monotonic() - started) * 1000)

        _DEBUG.append(_summarize(workflow, body, dict(request.headers), upstream_ms, result, error))
        print(f"[inline] {workflow} roles={[m.get('role') for m in messages][-4:]} "
              f"tools={len(body.get('tools') or [])} stream={body.get('stream')} {upstream_ms}ms"
              + (f" ERROR {error}" if error else ""), flush=True)

        if body.get("stream"):
            return StreamingResponse(_as_stream(result), media_type="text/event-stream")
        return JSONResponse(_as_completion(result))

    @router.get("/inline/debug")
    def inline_debug(x_angryrobot_secret: str | None = Header(default=None)):
        secret = os.environ.get("ANGRYROBOT_SHARED_SECRET")
        if secret and x_angryrobot_secret != secret:
            raise HTTPException(status_code=401, detail="Falta o es incorrecto el header X-AngryRobot-Secret")
        return {"agent_model": AGENT_MODEL, "requests": list(_DEBUG)}

    return router
