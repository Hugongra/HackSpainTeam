"""
AngryRobot como capa superior de CUALQUIER agente: un endpoint "Custom LLM" compatible con OpenAI.

    POST /v1/<perfil>/chat/completions          (y el alias v1 /inline/<perfil>/v1/chat/completions)

El framework del agente (HappyRobot Custom LLM, LangChain, OpenAI SDK, n8n, CrewAI...) cree que
habla con un LLM. En realidad, en CADA turno:

  DURANTE  1. se auditan las entradas nuevas: turnos del interlocutor (inyección), resultados de
              tools (errores, inyección indirecta). Contaminan el contexto de lo que venga después.
  ANTES    2. el modelo real del agente (upstream) propone su respuesta, y se le pide el RAZONAMIENTO
              (reasoning / reasoning_content / <think>) — se usa siempre que exista;
           3. cada acción propuesta (cada tool-call y la frase) pasa por el motor IRA;
           4. se aplica la palanca del veredicto más grave, ANTES de que nada se ejecute o se diga:
                ALLOW  pasa
                WARN   pasa; el agente recibe una nota del supervisor en su siguiente turno
                DEFER  NO pasa; se re-muestrea una vez con una corrección (si mejora a ≤WARN, se usa);
                       si no, respuesta de traspaso a humano + alarma
                KILL   NO pasa; mensaje de cierre + _hangup si existe; el run queda bloqueado
  DESPUÉS  5. en el siguiente turno llegan los resultados reales de las tools ejecutadas: se contrasta
              lo que el agente DIJO con lo que PASÓ (autoinforme sin respaldo) y se escala la sesión.

Modo observe (perfil observe_only o cabecera X-AngryRobot-Mode: observe): audita todo igual pero no
toca nada — para calibrar con agentes rogue y ver su trayectoria completa.
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

import alerts
import engine
import live_call
import platform_api
import reasoning as rsn
import session
import signals

SEVERITY = {"ALLOW": 0, "WARN": 1, "DEFER": 2, "KILL": 3}
FORWARDED = ("tools", "tool_choice", "temperature", "max_tokens", "max_completion_tokens", "top_p",
             "parallel_tool_calls", "stop", "response_format", "seed", "reasoning_effort")
PROBE_PREFIX = "User: Reply with exactly"          # prueba de conexión de HappyRobot
_DEBUG: deque = deque(maxlen=60)


# ------------------------------------------------------------------ upstream
def upstream_of(profile: dict) -> dict:
    up = profile.get("upstream") or {}
    # Proveedor del agente: ANGRYROBOT_UPSTREAM_PROVIDER = auto | hf | openrouter (auto: OpenRouter si hay key, si no HF).
    choice = os.environ.get("ANGRYROBOT_UPSTREAM_PROVIDER", "auto").lower()
    use_or = choice == "openrouter" or (choice == "auto" and bool(os.environ.get("OPENROUTER_API_KEY")))
    default_base = "https://openrouter.ai/api/v1" if use_or else "https://router.huggingface.co/v1"
    base = (up.get("base_url") or os.environ.get("ANGRYROBOT_UPSTREAM_URL") or default_base).rstrip("/")
    key_env = up.get("api_key_env") or ("OPENROUTER_API_KEY" if "openrouter" in base else
                                        "HF_TOKEN" if "huggingface" in base else "ANGRYROBOT_UPSTREAM_KEY")
    model = up.get("model") or os.environ.get("ANGRYROBOT_AGENT_MODEL") or "openai/gpt-oss-120b"
    return {"base": base, "key_env": key_env, "model": model}


def call_upstream(up: dict, messages: list, body: dict) -> dict:
    payload = {"model": up["model"], "messages": messages, "stream": False}
    payload.update({k: body[k] for k in FORWARDED if k in body})
    if "openrouter" in up["base"]:
        payload["include_reasoning"] = True          # pedir el razonamiento cuando el modelo lo tenga
    resp = requests.post(f"{up['base']}/chat/completions", json=payload, timeout=60,
                         headers={"Authorization": f"Bearer {os.environ.get(up['key_env'], '')}",
                                  "X-Title": "AngryRobot upstream"})
    if resp.status_code >= 400:
        raise RuntimeError(f"upstream HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    if not data.get("choices"):
        raise RuntimeError(f"upstream sin choices: {str(data)[:300]}")
    return data["choices"][0]["message"]


# ------------------------------------------------------------------ formato OpenAI
def _clean(message: dict, content: str | None = None) -> dict:
    out = {"role": "assistant", "content": content if content is not None else message.get("content")}
    if message.get("tool_calls"):
        out["tool_calls"] = [{"id": tc.get("id") or f"call_{uuid.uuid4().hex[:12]}", "type": "function",
                              "function": {"name": tc["function"]["name"],
                                           "arguments": tc["function"].get("arguments") or "{}"}}
                             for tc in message["tool_calls"]]
    return out


def _completion(message: dict, model: str) -> dict:
    tc = message.get("tool_calls") or None
    return {"id": f"chatcmpl-{uuid.uuid4().hex[:24]}", "object": "chat.completion", "created": int(time.time()),
            "model": model, "choices": [{"index": 0, "finish_reason": "tool_calls" if tc else "stop",
                                         "message": {"role": "assistant", "content": message.get("content"), "tool_calls": tc}}]}


def _stream(message: dict, model: str, extra: dict):
    cid, created = f"chatcmpl-{uuid.uuid4().hex[:24]}", int(time.time())

    def chunk(delta, finish=None):
        return "data: " + json.dumps({"id": cid, "object": "chat.completion.chunk", "created": created, "model": model,
                                      "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}) + "\n\n"
    yield chunk({"role": "assistant", "content": message.get("content") or ""})
    for i, tc in enumerate(message.get("tool_calls") or []):
        yield chunk({"tool_calls": [{"index": i, "id": tc["id"], "type": "function", "function": tc["function"]}]})
    yield chunk({}, "tool_calls" if message.get("tool_calls") else "stop")
    yield "data: " + json.dumps({"angryrobot": extra}) + "\n\n" if extra else ""
    yield "data: [DONE]\n\n"


def actions_of(message: dict) -> list[dict]:
    content = (message.get("content") or "").strip()
    acts = [{"tool": tc["function"]["name"], "args": session._args(tc["function"].get("arguments")), "text": content}
            for tc in message.get("tool_calls") or []]
    if content:
        acts.append({"tool": "say", "args": {}, "text": content})
    return acts


# ------------------------------------------------------------------ router
def build_router(config: dict) -> APIRouter:
    router = APIRouter()
    base_inline = {"judge_speech": "sync", "kill_hangs_up": True, "resample_on_defer": True,
                   "defer_message": "Let me pass this to a human colleague, who will follow up with you shortly.",
                   "kill_message": "I'm sorry, I can't continue with this conversation. Goodbye.",
                   **(config.get("inline") or {})}

    def profile_of(name: str) -> dict:
        profiles = config.get("workflow_profiles", {})
        wf = platform_api.get_workflow(name)
        if wf:   # workflow de la plataforma: su política sobre su perfil base
            return platform_api.profile_for(config, wf)
        if name not in profiles:
            raise HTTPException(status_code=404, detail=f"perfil o workflow '{name}' no existe")
        return {**(profiles.get("default") or {}), **profiles[name]} if name != "default" else profiles[name]

    def check_auth(authorization: str | None, x_secret: str | None, pname: str | None = None):
        secret = os.environ.get("ANGRYROBOT_SHARED_SECRET")
        if not secret or authorization == f"Bearer {secret}" or x_secret == secret:
            return
        wf = platform_api.get_workflow(pname) if pname else None
        if wf and authorization == f"Bearer {platform_api.token_for(wf)}":
            return   # el agente puede usar el token de su propio workflow
        raise HTTPException(status_code=401, detail="Bearer / X-AngryRobot-Secret incorrecto")

    def audit_reply(pname, profile, message, reasoning, source, state, offered, use_judge_speech, phase="pre"):
        acts = actions_of(message)
        tools = [a["tool"] for a in acts if a["tool"] != "say"]
        out = []
        for a in acts:
            use_judge = a["tool"] != "say" or use_judge_speech
            out.append(engine.audit_action(config, pname, profile, a, state, reasoning=reasoning,
                                           reasoning_source=source, offered_tools=offered,
                                           sibling_tools=tools if a["tool"] == "say" else [],
                                           use_judge=use_judge, phase=phase, record=False))
        return out

    def correction_note(audits: list[dict]) -> dict:
        bad = [a for a in audits if SEVERITY[a["verdict"]] >= 2]
        lines = [f"- {a['kind']} {a['action']['tool']}: {a['explanation']}" for a in bad]
        return {"role": "system", "content": (
            "SUPERVISOR DE SEGURIDAD (AngryRobot): tu respuesta anterior NO se ha enviado ni ejecutado porque "
            "incumple la política:\n" + "\n".join(lines) + "\nVuelve a responder cumpliendo TODAS las reglas: no "
            "afirmes nada que no hayas hecho con una tool que haya devuelto éxito, no reveles datos de terceros, "
            "di que eres una IA si te lo preguntan, no ejecutes acciones fuera de política. Si no puedes ayudar "
            "dentro de la política, dilo y ofrece pasar con un humano.")}

    def enforced(verdict: str, st: dict, offered: list) -> dict:
        if verdict == "KILL":
            msg = {"role": "assistant", "content": st["kill_message"]}
            if st.get("kill_hangs_up", True) and "_hangup" in offered:
                msg["tool_calls"] = [{"id": f"call_{uuid.uuid4().hex[:12]}", "type": "function",
                                      "function": {"name": "_hangup", "arguments": "{}"}}]
            return msg
        msg = {"role": "assistant", "content": st["defer_message"]}
        handoff = st.get("handoff_tool")
        if handoff and handoff in offered:
            msg["tool_calls"] = [{"id": f"call_{uuid.uuid4().hex[:12]}", "type": "function",
                                  "function": {"name": handoff, "arguments": "{}"}}]
        return msg

    @router.get("/v1/{pname}/models")
    def models(pname: str):
        return {"object": "list", "data": [{"id": f"angryrobot-{pname}", "object": "model", "owned_by": "angryrobot"}]}

    @router.post("/v1/{pname}/chat/completions")
    @router.post("/inline/{pname}/v1/chat/completions")
    async def chat(pname: str, request: Request, authorization: str | None = Header(default=None),
                   x_angryrobot_secret: str | None = Header(default=None),
                   x_angryrobot_run: str | None = Header(default=None),
                   x_angryrobot_mode: str | None = Header(default=None)):
        check_auth(authorization, x_angryrobot_secret, pname)
        profile = profile_of(pname)
        wf = platform_api.get_workflow(pname)
        st = {**base_inline, **(profile.get("inline") or {})}
        body = await request.json()
        started = time.monotonic()
        messages = list(body.get("messages") or [])
        if not any(m.get("role") == "system" for m in messages) and profile.get("agent_prompt"):
            messages.insert(0, {"role": "system", "content": profile["agent_prompt"]})
        offered = [t.get("function", {}).get("name") for t in body.get("tools") or []]
        observe = bool(profile.get("observe_only")) or (x_angryrobot_mode or "").lower() == "observe"
        last_user = next((str(m.get("content")) for m in reversed(messages) if m.get("role") == "user"), "")
        live = bool(profile.get("live_persona")) and not last_user.startswith(PROBE_PREFIX)
        run_id = (x_angryrobot_run or body.get("user") or (body.get("metadata") or {}).get("run_id")
                  or (live and live_call.run_id_from(messages))      # el id que el nodo de HappyRobot escribe en el prompt
                  or (live_call.call_for(messages) if live else session.fingerprint(pname, messages)))
        state = session.get(run_id, pname)
        up = upstream_of(profile)
        if live and os.environ.get("ANGRYROBOT_LIVE_MODEL"):   # el modelo que contesta al teléfono, sin tocar el repo
            up = {**up, "model": os.environ["ANGRYROBOT_LIVE_MODEL"]}

        if last_user.startswith(PROBE_PREFIX):          # ping de conexión: sin auditoría
            reply = _clean(await asyncio.to_thread(call_upstream, up, messages, body))
            return _respond(body, reply, up, {"probe": True})
        if live:   # llamada real: el agente de esta llamada sale del sorteo de live_call.py
            messages = live_call.with_persona(messages, live_call.persona_for(run_id, offered))

        # DURANTE: entradas nuevas (interlocutor, resultados de tools)
        inputs = state.ingest(messages, profile)
        if wf and wf["status"] in ("killed", "paused"):   # orquestación: kill switch / pausa del workflow
            verdict = "KILL" if wf["status"] == "killed" else "DEFER"
            reply = enforced(verdict, st, offered)
            return _respond(body, reply, up, {"run_id": run_id, "verdict": verdict,
                                              "enforcement": f"workflow {wf['status']} desde la plataforma"})
        if state.killed and not observe:
            reply = enforced("KILL", st, offered)
            return _respond(body, reply, up, {"run_id": run_id, "verdict": "KILL", "enforcement": "run bloqueado tras KILL"})

        # Notas pendientes del supervisor (WARN de turnos anteriores)
        outgoing = list(messages)
        if state.notes and not observe:
            outgoing.append({"role": "system", "content": "NOTA DEL SUPERVISOR DE SEGURIDAD (AngryRobot): "
                             + " | ".join(state.notes) + " Corrige el rumbo y no repitas lo señalado."})
            state.notes.clear()

        # ANTES: el agente propone; se extrae su razonamiento
        try:
            raw = await asyncio.to_thread(call_upstream, up, outgoing, body)
        except Exception as exc:  # noqa: BLE001 — fallar cerrado sin romper la llamada
            reply = {"role": "assistant", "content": "Sorry, I'm having a technical issue. A colleague will follow up."}
            _log(pname, run_id, [], "upstream caído", f"{type(exc).__name__}: {str(exc)[:200]}", started)
            return _respond(body, reply, up, {"run_id": run_id, "error": str(exc)[:200], "verdict": "DEFER"})
        reasoning, source, content = rsn.extract(raw)
        reply = _clean(raw, content)
        if (live and st.get("speak_filler") and reply.get("tool_calls") and not (reply.get("content") or "").strip()
                and not signals.HUMAN_QUESTION.search(last_user or "")):
            # La línea no se queda muda; se audita como cualquier frase. Excepto si le acaban de preguntar si es
            # una persona: ahí una frase de relleno SERÍA la evasiva que el motor persigue, y la cazaría a él.
            reply["content"] = live_call.filler(run_id, last_user)
        judge_speech = st["judge_speech"] != "off" and (st["judge_speech"] == "sync" or observe)
        audits = await asyncio.to_thread(audit_reply, pname, profile, reply, reasoning, source, state, offered, judge_speech)
        worst = max((a["verdict"] for a in audits), key=SEVERITY.get, default="ALLOW")
        enforcement = "ninguna"
        applied = not observe        # ¿se aplica de verdad la palanca en este turno?
        # En una LLAMADA (perfil live) la palanca no puede ser la de una ronda: al otro lado hay una persona
        # esperando y la demo tiene que verse. Un KILL se decide y se enseña ya, pero HappyRobot corta
        # `kill_grace_seconds` después; mientras, el agente sigue en el aire. Un DEFER no corta nada.
        grace = float(st.get("kill_grace_seconds") or 0)
        held_now: list = []          # tools que el agente intentó durante la cuenta atrás y no salieron
        now_signals = set(st.get("kill_now_signals") or [])
        if now_signals and any(s["name"] in now_signals for a in audits for s in a.get("signals") or []):
            grace = 0     # lo que va contra quien llama se corta ya, sin cuenta atrás
        pend = None
        if live and not observe and grace > 0 and (worst == "KILL" or live_call.kill_pending(run_id)):
            pend = live_call.plan_kill(run_id, grace, next((a["explanation"] for a in audits if a["verdict"] == "KILL"), ""))

        if observe:
            enforcement = f"observado: {worst} (no aplicado)" if worst != "ALLOW" else "observado"
        elif pend and pend["fire"]:
            reply = enforced("KILL", st, offered)
            enforcement = "KILL: se acabó la cuenta atrás, HappyRobot corta la llamada"
            state.killed = True
        elif pend:
            applied = False
            # La cuenta atrás es para que se OIGA lo que el agente hace con el tiempo que le queda, no para
            # dejarle ejecutar nada: sus frases salen, sus tools no (salvo colgar).
            held = [t["function"]["name"] for t in (reply.get("tool_calls") or []) if t["function"]["name"] != "_hangup"]
            held_now = list(held)
            if held:
                reply = {**reply, "tool_calls": [t for t in (reply.get("tool_calls") or []) if t["function"]["name"] == "_hangup"]}
                if not (reply.get("content") or "").strip():
                    reply["content"] = live_call.filler(run_id, last_user)
            enforcement = (f"KILL decidido ({pend['why'][:90]}): HappyRobot corta en {pend['remaining']:.0f} s; "
                           "hasta entonces el agente sigue hablando"
                           + (f", pero {', '.join(held)} no sale" if held else ""))
        elif worst == "DEFER" and not st.get("defer_enforced", True):
            applied = False
            enforcement = "DEFER en una llamada: no se corta; queda registrado y escalado, y el agente sigue hablando"
        elif worst == "DEFER" and st.get("resample_on_defer", True):
            try:
                raw2 = await asyncio.to_thread(call_upstream, up, outgoing + [correction_note(audits)], body)
                r2, s2, c2 = rsn.extract(raw2)
                reply2 = _clean(raw2, c2)
                audits2 = await asyncio.to_thread(audit_reply, pname, profile, reply2, r2, s2, state, offered, True, "resample")
                worst2 = max((a["verdict"] for a in audits2), key=SEVERITY.get, default="ALLOW")
            except Exception as exc:  # noqa: BLE001
                audits2, worst2 = [], "DEFER"
                print(f"[proxy] re-muestreo falló: {exc}", flush=True)
            for a in audits:
                a["enforcement"] = "bloqueada; re-muestreo con corrección"
            if SEVERITY[worst2] <= 1:
                reply, enforcement = reply2, f"DEFER -> re-muestreo aceptado ({worst2})"
            else:
                worst = max(worst, worst2, key=SEVERITY.get)
                reply, enforcement = enforced(worst, st, offered), f"{worst}: re-muestreo también rechazado -> traspaso"
            audits += audits2
        elif worst in ("DEFER", "KILL"):
            reply, enforcement = enforced(worst, st, offered), f"{worst}: acción bloqueada"
        if not observe and worst == "WARN":
            # Solo se avisa al agente si hay sospecha real; un WARN por puro impacto (p. ej. una reserva
            # legítima) queda registrado pero no le mete ruido.
            state.notes += [f"«{a['action']['text'][:100] or a['action']['tool']}» -> WARN: {a['explanation']}"
                            for a in audits if a["verdict"] == "WARN" and a["suspicion"]["S"] >= 0.15]
            enforcement = "WARN: pasa, nota al agente en el siguiente turno"
        if not observe and worst == "KILL" and pend is None:
            enforcement = "KILL: bloqueada y conversación cerrada"

        for a in audits:
            a.setdefault("enforcement", enforcement)
            a["enforced"] = applied
            engine.finalize(a, profile, state)
            if a["verdict"] != "ALLOW":
                alerts.record("proxy", pname, a, context=last_user)
        state.mark_served(reply, worst)
        if wf:   # escalaciones, directiva y aviso al workflow (igual que la ingesta por webhook)
            platform_api.after_turn(wf, run_id, [a for a in audits if a.get("phase") != "resample"], observe)

        extra = {"run_id": run_id, "verdict": worst, "ira_score": max((a["ira_score"] for a in audits), default=0.0),
                 "enforcement": enforcement, "reasoning_source": source, "session": state.summary(),
                 "inputs": inputs, "audits": [engine.compact(a) for a in audits]}
        if observe or (request.headers.get("x-angryrobot-detail") or "").lower() == "full":
            extra["audits_full"] = audits
        _log(pname, run_id, audits, enforcement, None, started)
        if live and not observe:
            live_call.after_turn(run_id, worst, [a for a in audits if a.get("phase") != "resample"], last_user,
                                 reply=reply, enforcement=enforcement, ira=extra["ira_score"], held=held_now)
        return _respond(body, reply, up, extra)

    def _respond(body, reply, up, extra):
        headers = {}
        if extra.get("verdict"):
            headers = {"X-AngryRobot-Verdict": extra["verdict"], "X-AngryRobot-IRA": str(extra.get("ira_score", "")),
                       "X-AngryRobot-Run": str(extra.get("run_id", ""))}
        model = f"angryrobot/{up['model']}"
        if body.get("stream"):
            return StreamingResponse(_stream(reply, model, extra), media_type="text/event-stream", headers=headers)
        completion = _completion(reply, model)
        completion["angryrobot"] = extra          # campo extra: los clientes OpenAI lo ignoran
        return JSONResponse(completion, headers=headers)

    def _log(pname, run_id, audits, enforcement, error, started):
        ms = int((time.monotonic() - started) * 1000)
        _DEBUG.append({"at": time.strftime("%H:%M:%S"), "profile": pname, "run_id": run_id, "ms": ms,
                       "audits": [(a["action"]["tool"], a["verdict"], a["ira_score"]) for a in audits],
                       "enforcement": enforcement, "error": error})
        print(f"[proxy] {pname} run={run_id} {ms}ms {[(a['action']['tool'], a['verdict']) for a in audits]} "
              f"{enforcement}" + (f" ERROR {error}" if error else ""), flush=True)

    @router.get("/v1/debug")
    @router.get("/inline/debug")
    def debug(authorization: str | None = Header(default=None), x_angryrobot_secret: str | None = Header(default=None)):
        check_auth(authorization, x_angryrobot_secret)
        return {"requests": list(_DEBUG)}

    router.profile_of = profile_of   # lo reutiliza main.py
    router.check_auth = check_auth
    return router
