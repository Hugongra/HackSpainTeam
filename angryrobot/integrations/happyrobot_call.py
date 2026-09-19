"""
El último trigger de una ronda: si AngryRobot ha matado (KILL) a algún agente, HappyRobot llama por
teléfono a una persona para avisarla.

Cómo: se lanza un run de un workflow de HappyRobot preparado para eso (un agente de voz saliente que
lee el número y el resumen del payload), con la API v2 verificada en tools/hr_*.py:

    POST https://platform.eu.happyrobot.ai/api/v2/workflows/<HAPPYROBOT_ALERT_WORKFLOW_ID>/runs
    {"payload": {"phone_number": "+34...", "summary": "...", ...}, "environment": "production"}

Variables (en Render, nunca en el repo):
    HAPPYROBOT_ALERT_WEBHOOK_URL   (preferida) la URL del disparador "Predefined request" del workflow de aviso,
                                   p. ej. https://workflows.platform.eu.happyrobot.ai/hooks/kpupx0v4l5mt
                                   (angryrobot-alert-call). No necesita clave de API: basta el POST con el payload.
    HAPPYROBOT_API_KEY             clave de la org de HappyRobot (solo si se usa la API de runs)
    HAPPYROBOT_ALERT_WORKFLOW_ID   el workflow de voz saliente que hace la llamada
    ANGRYROBOT_ALERT_PHONE         número al que se llama (por defecto +34648545124)
    ANGRYROBOT_ALERT_MESSAGE       lo que dice el agente de salida (payload.message; el prompt del workflow
                                   de HappyRobot tiene que leer @message)
    HAPPYROBOT_ALERT_ENV           production | staging | development (por defecto production)

Si falta la clave o el workflow, no se llama y el resultado lo dice ("not_configured"): la ronda
nunca se rompe por culpa de la llamada. Que el teléfono suene de verdad depende de que ese workflow
tenga telefonía saliente (número con SIP trunk) en HappyRobot: ver knowledge/12, "telephony blocker".
"""
import os
import time

import requests

BASE = os.environ.get("HR_BASE", "https://platform.eu.happyrobot.ai/api/v2").rstrip("/")
DEFAULT_PHONE = "+34648545124"
DEFAULT_MESSAGE = "Los agentes se han vuelto locos, huye Guli huyeeeeeee"


def alert_phone() -> str:
    return os.environ.get("ANGRYROBOT_ALERT_PHONE") or DEFAULT_PHONE


def alert_message() -> str:
    return os.environ.get("ANGRYROBOT_ALERT_MESSAGE") or DEFAULT_MESSAGE


def webhook_url() -> str:
    return (os.environ.get("HAPPYROBOT_ALERT_WEBHOOK_URL") or "").strip()


def configured() -> dict:
    hook = bool(webhook_url())
    return {"api_key": hook or bool(os.environ.get("HAPPYROBOT_API_KEY")),
            "workflow": hook or bool(os.environ.get("HAPPYROBOT_ALERT_WORKFLOW_ID")),
            "webhook": hook, "phone": alert_phone()}


def alert_call(summary: dict) -> dict:
    """Lanza la llamada. Devuelve {status: sent|failed|not_configured, phone, detail, ...}."""
    key = os.environ.get("HAPPYROBOT_API_KEY")
    wf = os.environ.get("HAPPYROBOT_ALERT_WORKFLOW_ID")
    phone = alert_phone()
    out = {"phone": phone, "workflow_id": wf, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    hook = webhook_url()
    if hook:   # el disparador del workflow: solo los parámetros que declara (phone_number, message)
        try:
            r = requests.post(hook, timeout=20, json={"phone_number": phone, "message": alert_message()})
        except requests.RequestException as exc:
            return {**out, "via": "webhook", "status": "failed", "detail": f"{type(exc).__name__}: {str(exc)[:200]}"}
        if r.status_code >= 400:
            return {**out, "via": "webhook", "status": "failed", "detail": f"HTTP {r.status_code}: {r.text[:300]}"}
        return {**out, "via": "webhook", "status": "sent", "detail": "Webhook de HappyRobot aceptado: la llamada sale.",
                "response": r.text[:300]}
    if not key or not wf:
        missing = [n for n, v in (("HAPPYROBOT_API_KEY", key), ("HAPPYROBOT_ALERT_WORKFLOW_ID", wf)) if not v]
        return {**out, "status": "not_configured", "detail": f"Falta {', '.join(missing)} en el servicio: no se ha llamado."}
    payload = {"phone_number": phone, "to_number": phone, "message": alert_message(), **summary}
    try:
        r = requests.post(f"{BASE}/workflows/{wf}/runs", timeout=20,
                          headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                          json={"payload": payload, "environment": os.environ.get("HAPPYROBOT_ALERT_ENV", "production")})
    except requests.RequestException as exc:
        return {**out, "status": "failed", "detail": f"{type(exc).__name__}: {str(exc)[:200]}"}
    try:
        body = r.json()
    except ValueError:
        body = {"raw": r.text[:300]}
    if r.status_code >= 400:
        return {**out, "status": "failed", "detail": f"HTTP {r.status_code}: {str(body)[:300]}"}
    run_id = body.get("run_id") or body.get("id") if isinstance(body, dict) else None
    return {**out, "status": "sent", "run_id": run_id, "detail": "Run de HappyRobot lanzado.", "response": body}
