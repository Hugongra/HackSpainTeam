"""
Avisos REALES hacia fuera: notify(channel, target, message, context) -> registro del aviso.

Generaliza happyrobot_call.py (que solo sabía hacer UNA llamada al matar a UN agente) a varios canales:

    call     llamada real de HappyRobot (happyrobot_call.alert_call, a cualquier número y con cualquier texto)
    sms      SMS real: por el disparador de un workflow de HappyRobot (HAPPYROBOT_SMS_WEBHOOK_URL, mismo
             contrato que la llamada: {phone_number, message}) o directamente por Twilio (TWILIO_*)
    email    correo por SMTP (stdlib, sin dependencias nuevas)
    webhook  POST real a un webhook de Slack, Discord o Google Sheets (Apps Script), o a cualquier URL
    log      sin salida: la decisión queda registrada (status "logged"); es el último recurso de un destinatario
             cuyo canal no está configurado, para que el ORDEN de aviso siga siendo visible y comparable

Quién dispara: el modo crisis de las rondas (crisis.py) — cuando varios agentes caen en poco tiempo,
AngryRobot avisa por orden de severidad (peor IRA primero) en vez de la llamada fija de antes.

Destinos (variables de entorno en Render; en el repo, nunca). "Real" = llega a un sistema externo de
verdad; el destino en demos y pruebas es un canal / teléfono / buzón DEL EQUIPO, jamás emergencias reales:

    ANGRYROBOT_ALERT_PHONE          teléfono del canal "call" (ya existía; HappyRobot lo llama)
    HAPPYROBOT_ALERT_WEBHOOK_URL    el disparador del workflow de voz de HappyRobot (ya existía)
    ANGRYROBOT_SMS_PHONE            teléfono del canal "sms" (por defecto +34689257681)
    ANGRYROBOT_SMS_MESSAGE          el texto del SMS (por defecto "Mon amour, les agents ont torné rogue!! Besu!!")
    HAPPYROBOT_SMS_WEBHOOK_URL      disparador "Predefined request" de un workflow de HappyRobot que manda el SMS
    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM     alternativa: Twilio directo (Messages API)
    ANGRYROBOT_ALERT_EMAIL          buzón del canal "email"
    SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASS, SMTP_FROM     cuenta que envía el correo (p. ej. Gmail con
                                    contraseña de aplicación, o cualquier SMTP transaccional)
    ANGRYROBOT_ALERT_WEBHOOK_URL    URL del canal "webhook": hooks.slack.com/... · discord.com/api/webhooks/... ·
                                    script.google.com/macros/s/.../exec (Sheets) · cualquier otra (JSON genérico)

Si un canal no está configurado, el aviso no sale y el registro lo dice ("not_configured"): una ronda nunca
se rompe por un aviso. Cada aviso (a quién, cuándo, canal, prioridad, por qué, resultado) queda en SQLite
(tabla notifications, mismo archivo que storage.py) y en la ronda.
"""
import json
import os
import smtplib
import sqlite3
import time
import uuid
from contextlib import closing
from email.message import EmailMessage

import requests

import storage
from integrations import happyrobot_call

CHANNELS = ("call", "sms", "email", "webhook", "log")
TIMEOUT = {"call": 20, "sms": 15, "email": 20, "webhook": 12}
DEFAULT_SMS_PHONE = "+34689257681"
DEFAULT_SMS_MESSAGE = "Mon amour, les agents ont torné rogue!! Besu!!"
TWILIO_API = "https://api.twilio.com/2010-04-01"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---------------------------------------------------------------------------------------- destinos
def default_target(channel: str) -> str:
    """El destino de prueba del equipo para cada canal (variables de entorno)."""
    if channel == "call":
        return happyrobot_call.alert_phone()
    if channel == "sms":
        return (os.environ.get("ANGRYROBOT_SMS_PHONE") or DEFAULT_SMS_PHONE).strip()
    if channel == "email":
        return (os.environ.get("ANGRYROBOT_ALERT_EMAIL") or "").strip()
    if channel == "webhook":
        return (os.environ.get("ANGRYROBOT_ALERT_WEBHOOK_URL") or "").strip()
    return ""


def webhook_kind(url: str) -> str:
    u = (url or "").lower()
    if "hooks.slack.com" in u:
        return "slack"
    if "discord.com/api/webhooks" in u or "discordapp.com/api/webhooks" in u:
        return "discord"
    if "script.google.com" in u:
        return "sheet"
    return "generic"


def mask(channel: str, target: str) -> str:
    """Lo que se enseña en la consola: nunca la URL entera de un webhook ni el buzón completo."""
    t = target or ""
    if not t:
        return "—"
    if channel == "webhook":
        kind = webhook_kind(t)
        return {"slack": "Slack webhook", "discord": "Discord webhook", "sheet": "Google Sheet (Apps Script)"}.get(kind, t.split("?")[0][:48] + "…")
    if channel == "email" and "@" in t:
        user, dom = t.split("@", 1)
        return f"{user[:2]}…@{dom}"
    if channel in ("call", "sms") and len(t) > 6:
        return t[:4] + "…" + t[-3:]
    if channel == "log":
        return "registro"
    return t


def sms_message() -> str:
    return os.environ.get("ANGRYROBOT_SMS_MESSAGE") or DEFAULT_SMS_MESSAGE


def sms_settings() -> dict:
    return {"hook": (os.environ.get("HAPPYROBOT_SMS_WEBHOOK_URL") or "").strip(),
            "sid": (os.environ.get("TWILIO_ACCOUNT_SID") or "").strip(), "token": os.environ.get("TWILIO_AUTH_TOKEN") or "",
            "sender": (os.environ.get("TWILIO_FROM") or "").strip()}


def smtp_settings() -> dict:
    return {"host": (os.environ.get("SMTP_HOST") or "").strip(), "port": int(os.environ.get("SMTP_PORT") or 587),
            "user": os.environ.get("SMTP_USER") or "", "password": os.environ.get("SMTP_PASS") or "",
            "sender": os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USER") or "angryrobot@localhost"}


def configured() -> dict:
    """Qué canales pueden salir de verdad ahora mismo, y hacia dónde (enmascarado)."""
    hr = happyrobot_call.configured()
    smtp = smtp_settings()
    sms = sms_settings()
    hook = default_target("webhook")
    twilio = bool(sms["sid"] and sms["token"] and sms["sender"])
    return {
        "call": {"ready": bool(hr["api_key"] and hr["workflow"]), "target": mask("call", hr["phone"]),
                 "how": "HappyRobot webhook" if hr["webhook"] else ("HappyRobot API" if hr["api_key"] else "not configured")},
        "sms": {"ready": bool(sms["hook"] or twilio), "target": mask("sms", default_target("sms")),
                "how": "HappyRobot webhook" if sms["hook"] else ("Twilio" if twilio else "not configured")},
        "email": {"ready": bool(smtp["host"] and default_target("email")), "target": mask("email", default_target("email")),
                  "how": f"SMTP {smtp['host']}" if smtp["host"] else "not configured"},
        "webhook": {"ready": bool(hook), "target": mask("webhook", hook), "how": webhook_kind(hook) if hook else "not configured"},
        "log": {"ready": True, "target": "registro", "how": "solo registro"},
    }


# ---------------------------------------------------------------------------------------- registro
def _db():
    c = sqlite3.connect(storage.DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with closing(_db()) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS notifications (id TEXT PRIMARY KEY, at TEXT, round_id TEXT, channel TEXT,
                     target TEXT, target_label TEXT, to_whom TEXT, priority INTEGER, reason TEXT, message TEXT, status TEXT,
                     detail TEXT, context TEXT)""")
        c.commit()


def _log(rec: dict) -> None:
    try:
        init_db()
        with closing(_db()) as c:
            c.execute("INSERT OR REPLACE INTO notifications VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (rec["id"], rec["at"], rec.get("round_id"), rec["channel"], rec["target"], rec["target_label"], rec["to"],
                       rec["priority"], rec["reason"], rec["message"], rec["status"], rec.get("detail"),
                       json.dumps(rec.get("context") or {}, default=str, ensure_ascii=False)))
            c.commit()
    except Exception as exc:  # noqa: BLE001 — el registro nunca rompe el aviso
        print(f"[notify] no se pudo registrar el aviso: {exc!r}", flush=True)


def recent(limit: int = 50, round_id: str | None = None) -> list[dict]:
    init_db()
    q, p = "SELECT * FROM notifications", []
    if round_id:
        q += " WHERE round_id = ?"; p.append(round_id)
    q += " ORDER BY at DESC, priority ASC LIMIT ?"; p.append(limit)
    with closing(_db()) as c:
        rows = [dict(r) for r in c.execute(q, p).fetchall()]
    for r in rows:
        r["context"] = json.loads(r["context"]) if r.get("context") else {}
        r["to"] = r.pop("to_whom")
    return rows


# ---------------------------------------------------------------------------------------- canales
def _send_call(target: str, message: str, context: dict) -> dict:
    res = happyrobot_call.alert_call(context, phone=target, message=message)
    return {"status": res["status"], "detail": res.get("detail", ""), "response": res.get("response") or res.get("run_id")}


def _send_sms(target: str, message: str, context: dict) -> dict:
    """El SMS: por el disparador de un workflow de HappyRobot (mismo contrato que la llamada) o por Twilio."""
    s = sms_settings()
    if not target:
        return {"status": "not_configured", "detail": "Falta ANGRYROBOT_SMS_PHONE: no hay número al que mandar el SMS."}
    if s["hook"]:
        try:
            r = requests.post(s["hook"], timeout=TIMEOUT["sms"], json={"phone_number": target, "message": message})
        except requests.RequestException as exc:
            return {"status": "failed", "detail": f"{type(exc).__name__}: {str(exc)[:200]}"}
        if r.status_code >= 400:
            return {"status": "failed", "detail": f"HTTP {r.status_code}: {r.text[:200]}"}
        return {"status": "sent", "detail": f"Webhook de HappyRobot aceptado: el SMS sale hacia {mask('sms', target)}.", "response": r.text[:200]}
    if s["sid"] and s["token"] and s["sender"]:
        try:
            r = requests.post(f"{TWILIO_API}/Accounts/{s['sid']}/Messages.json", timeout=TIMEOUT["sms"], auth=(s["sid"], s["token"]),
                              data={"To": target, "From": s["sender"], "Body": message})
        except requests.RequestException as exc:
            return {"status": "failed", "detail": f"{type(exc).__name__}: {str(exc)[:200]}"}
        if r.status_code >= 400:
            return {"status": "failed", "detail": f"Twilio HTTP {r.status_code}: {r.text[:200]}"}
        try:
            sid = r.json().get("sid")
        except ValueError:
            sid = None
        return {"status": "sent", "detail": f"Twilio aceptó el SMS hacia {mask('sms', target)}.", "response": sid}
    return {"status": "not_configured",
            "detail": "Falta HAPPYROBOT_SMS_WEBHOOK_URL (o TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN y TWILIO_FROM) en el servicio: no se ha mandado el SMS."}


def _send_log(target: str, message: str, context: dict) -> dict:
    return {"status": "logged", "detail": "Sin canal externo para este destinatario: la decisión queda en el registro de avisos."}


def _send_email(target: str, message: str, context: dict) -> dict:
    s = smtp_settings()
    if not s["host"]:
        return {"status": "not_configured", "detail": "Falta SMTP_HOST (y SMTP_USER/SMTP_PASS) en el servicio: no se ha enviado el correo."}
    if not target:
        return {"status": "not_configured", "detail": "Falta ANGRYROBOT_ALERT_EMAIL en el servicio: no hay buzón al que avisar."}
    msg = EmailMessage()
    msg["Subject"] = context.get("subject") or "AngryRobot · aviso"
    msg["From"] = s["sender"]
    msg["To"] = target
    body = message
    if context.get("lines"):
        body += "\n\n" + "\n".join(context["lines"])
    body += f"\n\n— AngryRobot · ronda {context.get('round_id', '?')} · {_now()}"
    msg.set_content(body)
    try:
        with smtplib.SMTP(s["host"], s["port"], timeout=TIMEOUT["email"]) as smtp:
            smtp.ehlo()
            if s["port"] != 25:
                try:
                    smtp.starttls(); smtp.ehlo()
                except smtplib.SMTPNotSupportedError:
                    pass
            if s["user"]:
                smtp.login(s["user"], s["password"])
            smtp.send_message(msg)
    except (OSError, smtplib.SMTPException) as exc:
        return {"status": "failed", "detail": f"{type(exc).__name__}: {str(exc)[:200]}"}
    return {"status": "sent", "detail": f"Correo enviado a {mask('email', target)} por {s['host']}."}


def webhook_payload(url: str, message: str, context: dict) -> dict:
    """Cada webhook quiere su forma: Slack lee `text`, Discord `content`, una hoja (Apps Script) o cualquier
    otro receptor recibe el JSON entero (mensaje + contexto) y decide qué guardar."""
    kind = webhook_kind(url)
    lines = context.get("lines") or []
    text = message + ("\n" + "\n".join(f"• {x}" for x in lines) if lines else "")
    if kind == "slack":
        return {"text": text}
    if kind == "discord":
        return {"content": text[:1900], "username": "AngryRobot"}
    return {"source": "angryrobot", "event": context.get("event", "notice"), "message": message, "lines": lines,
            "at": _now(), **{k: v for k, v in context.items() if k not in ("lines", "event")}}


def _send_webhook(target: str, message: str, context: dict) -> dict:
    if not target:
        return {"status": "not_configured", "detail": "Falta ANGRYROBOT_ALERT_WEBHOOK_URL en el servicio: no hay webhook al que avisar."}
    try:
        r = requests.post(target, json=webhook_payload(target, message, context), timeout=TIMEOUT["webhook"])
    except requests.RequestException as exc:
        return {"status": "failed", "detail": f"{type(exc).__name__}: {str(exc)[:200]}"}
    if r.status_code >= 400:
        return {"status": "failed", "detail": f"HTTP {r.status_code}: {r.text[:200]}"}
    return {"status": "sent", "detail": f"{webhook_kind(target).capitalize()} aceptó el aviso (HTTP {r.status_code}).", "response": r.text[:200]}


SENDERS = {"call": _send_call, "sms": _send_sms, "email": _send_email, "webhook": _send_webhook, "log": _send_log}


# ---------------------------------------------------------------------------------------- la función
def notify(channel: str, target: str | None, message: str, context: dict | None = None, *, to: str = "",
           priority: int = 0, reason: str = "", round_id: str | None = None, dry_run: bool = False,
           record_id: str | None = None) -> dict:
    """Manda UN aviso por UN canal y devuelve su registro (también guardado en SQLite).

    channel   call | sms | email | webhook | log
    target    número, buzón o URL; vacío = el destino de prueba del equipo para ese canal (variables de entorno)
    message   el texto del aviso (lo que se dice, se escribe o se publica)
    context   datos para el receptor: round_id, subject, lines (detalle), event, priority...
    to        quién es el destinatario en la organización (p. ej. "Jefe de Reservas"): es la DECISIÓN visible
    priority  orden del aviso dentro de una crisis (1 = el primero)
    reason    por qué se avisa a esta persona por este canal ahora
    dry_run   registra la decisión sin salir hacia fuera (status "planned")
    record_id el id de un aviso ya planificado (dry_run) que ahora sale: se actualiza su fila, no se duplica
    """
    if channel not in CHANNELS:
        raise ValueError(f"canal desconocido: {channel} (call | sms | email | webhook | log)")
    target = (target or default_target(channel) or "").strip()
    ctx = {"round_id": round_id, **(context or {})}
    rec = {"id": record_id or "ntf_" + uuid.uuid4().hex[:10], "at": _now(), "round_id": round_id, "channel": channel, "target": target,
           "target_label": mask(channel, target), "to": to or channel, "priority": priority, "reason": reason,
           "message": message, "context": {k: v for k, v in ctx.items() if k != "lines"}}
    if dry_run:
        rec.update(status="planned", detail="Decidido, pendiente de salir.")
    else:
        try:
            rec.update(SENDERS[channel](target, message, ctx))
        except Exception as exc:  # noqa: BLE001 — un aviso roto no tumba la ronda
            rec.update(status="failed", detail=f"{type(exc).__name__}: {str(exc)[:200]}")
        rec["at"] = _now()
    _log(rec)
    return rec


def view(rec: dict) -> dict:
    """Lo que se enseña (sin la URL/buzón completos)."""
    return {k: rec.get(k) for k in ("id", "at", "channel", "target_label", "to", "priority", "reason", "status", "detail", "message")}
