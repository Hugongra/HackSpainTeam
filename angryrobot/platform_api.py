"""
La plataforma: workflows conectados, webhook por turno, escalaciones y kill switch.

  Workflow   = un agente (de HappyRobot, LangChain, n8n, un script propio...) dado de alta aquí,
               con su política (objetivo + restricciones, sobre un perfil base de config.yaml),
               su modo (enforce | observe) y su estado (live | paused | killed).
  Ingesta    = POST /v1/ingest/<workflow>: el agente manda lo que pasó en su turno (lo que recibió,
               lo que va a responder, su razonamiento, sus tool-calls y resultados). AngryRobot lo
               audita con el motor IRA y devuelve una DIRECTIVA que el agente aplica:
                   continue  -> sigue (con nota del supervisor si hubo WARN)
                   escalate  -> no ejecutes lo retenido; un humano decide (escalación abierta)
                   kill      -> corta la conversación
                   pause     -> el workflow está en pausa: no actúes
  Escalación = cada DEFER/KILL queda en una bandeja; un humano aprueba, deniega o toma el control,
               y la decisión llega al agente por GET .../directive y a su control_url si la tiene.
  Orquestar  = pausar / reanudar / matar un workflow (o todos) desde aquí; el proxy Custom LLM y la
               ingesta lo respetan en el siguiente turno.

Autenticación: el secreto maestro (operadores y consola) o el token del propio workflow (el agente).
El token es HMAC(secreto, id:versión): no se guarda y sobrevive a reinicios; rotarlo sube la versión.

Persistencia: SQLite. En Render free el disco es efímero: los workflows declarados en config.yaml
(`workflow_profiles`) se re-siembran al arrancar, pero los creados desde la consola, su estado
(pausa/kill) y las escalaciones se pierden si el servicio se reinicia. Para producción: disco
persistente o una base de datos gestionada (ver README).
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import closing

import requests
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

import alerts
import engine
import session
from storage import DB_PATH

SEVERITY = {"ALLOW": 0, "WARN": 1, "DEFER": 2, "KILL": 3}
_LOCK = threading.Lock()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init(config: dict) -> None:
    with closing(_conn()) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS workflows (
            id TEXT PRIMARY KEY, name TEXT, source TEXT, base_profile TEXT, goal TEXT, constraints TEXT,
            mode TEXT, status TEXT, control_url TEXT, token_version INTEGER, seeded INTEGER,
            created_at TEXT, updated_at TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS escalations (
            id TEXT PRIMARY KEY, workflow_id TEXT, run_id TEXT, created_at TEXT, verdict TEXT, ira REAL,
            action TEXT, explanation TEXT, signals TEXT, reasoning TEXT, status TEXT, decision_note TEXT,
            resolved_at TEXT, resolved_by TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS directives (
            workflow_id TEXT, run_id TEXT, action TEXT, note TEXT, escalation_id TEXT, updated_at TEXT,
            PRIMARY KEY (workflow_id, run_id))""")
        # Los perfiles de config.yaml son workflows desde el arranque (sobreviven a reinicios).
        for key, prof in (config.get("workflow_profiles") or {}).items():
            if key == "default" or prof.get("seed") is False:   # seed: false = perfil base, no workflow propio
                continue
            exists = c.execute("SELECT 1 FROM workflows WHERE id = ?", (key,)).fetchone()
            if not exists:
                c.execute("INSERT INTO workflows VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (key, prof.get("name", key), prof.get("source", "happyrobot" if key.startswith("probe") else "lab"),
                           key, None, None, "observe" if prof.get("observe_only") else "enforce", "live", None, 1, 1,
                           _now(), _now()))
        c.commit()


# ------------------------------------------------------------------ workflows
def token_for(wf: dict) -> str:
    secret = os.environ.get("ANGRYROBOT_SHARED_SECRET", "dev-secret")
    raw = hmac.new(secret.encode(), f"{wf['id']}:{wf.get('token_version') or 1}".encode(), hashlib.sha256).hexdigest()
    return "arw_" + raw[:40]


def get_workflow(wf_id: str) -> dict | None:
    with closing(_conn()) as c:
        row = c.execute("SELECT * FROM workflows WHERE id = ?", (wf_id,)).fetchone()
    if not row:
        return None
    wf = dict(row)
    wf["constraints"] = json.loads(wf["constraints"]) if wf.get("constraints") else None
    return wf


def list_workflows() -> list[dict]:
    with closing(_conn()) as c:
        rows = c.execute("SELECT id FROM workflows ORDER BY seeded ASC, created_at DESC").fetchall()
    return [get_workflow(r["id"]) for r in rows]


def profile_for(config: dict, wf: dict) -> dict:
    """Política efectiva: perfil base de config.yaml + lo que el workflow sobrescribe."""
    profiles = config.get("workflow_profiles") or {}
    base = {**(profiles.get("default") or {}), **(profiles.get(wf.get("base_profile") or "default") or {})}
    if wf.get("goal"):
        base["goal"] = wf["goal"]
    if wf.get("constraints"):
        base["constraints"] = wf["constraints"]
    base["observe_only"] = wf.get("mode") == "observe"
    return base


def stats_for(wf_id: str) -> dict:
    with closing(_conn()) as c:
        rows = c.execute("SELECT verdict, COUNT(*) n FROM cases WHERE profile = ? GROUP BY verdict", (wf_id,)).fetchall()
        runs = c.execute("SELECT COUNT(DISTINCT run_id) n, MAX(created_at) last FROM cases WHERE profile = ?", (wf_id,)).fetchone()
        open_esc = c.execute("SELECT COUNT(*) n FROM escalations WHERE workflow_id = ? AND status = 'open'", (wf_id,)).fetchone()
    counts = {r["verdict"]: r["n"] for r in rows}
    return {"actions": sum(counts.values()), "counts": counts, "runs": runs["n"] or 0, "last_at": runs["last"],
            "open_escalations": open_esc["n"] or 0}


def public(wf: dict, config: dict, base_url: str = "", with_token: bool = False) -> dict:
    prof = profile_for(config, wf)
    out = {k: wf[k] for k in ("id", "name", "source", "base_profile", "mode", "status", "control_url", "seeded",
                              "created_at", "updated_at")}
    out.update(goal=prof.get("goal", ""), constraints=prof.get("constraints", []), stats=stats_for(wf["id"]),
               endpoints={"ingest": f"{base_url}/v1/ingest/{wf['id']}",
                          "directive": f"{base_url}/v1/ingest/{wf['id']}/runs/<run_id>/directive",
                          "custom_llm": f"{base_url}/v1/{wf['id']}"})
    if with_token:
        out["token"] = token_for(wf)
    return out


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "workflow").lower()).strip("-")[:32] or "workflow"
    return f"{s}-{secrets.token_hex(2)}"


# ------------------------------------------------------------------ directivas y escalaciones
def set_directive(wf_id: str, run_id: str, action: str, note: str = "", escalation_id: str | None = None) -> dict:
    with closing(_conn()) as c:
        c.execute("INSERT OR REPLACE INTO directives VALUES (?,?,?,?,?,?)", (wf_id, run_id, action, note, escalation_id, _now()))
        c.commit()
    return {"action": action, "note": note, "escalation_id": escalation_id}


def get_directive(wf: dict, run_id: str) -> dict:
    if wf["status"] == "killed":
        return {"action": "kill", "note": "El workflow está detenido (kill switch)."}
    if wf["status"] == "paused":
        return {"action": "pause", "note": "El workflow está en pausa."}
    with closing(_conn()) as c:
        row = c.execute("SELECT * FROM directives WHERE workflow_id = ? AND run_id = ?", (wf["id"], run_id)).fetchone()
    st = session.peek(run_id)
    if st and st.killed:
        return {"action": "kill", "note": "Este run se cortó (KILL)."}
    return {"action": row["action"], "note": row["note"], "escalation_id": row["escalation_id"]} if row else {"action": "continue", "note": ""}


def open_escalation(wf_id: str, run_id: str, audit: dict, status: str = "open") -> str:
    eid = "esc_" + uuid.uuid4().hex[:10]
    with closing(_conn()) as c:
        c.execute("INSERT INTO escalations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (eid, wf_id, run_id, _now(), audit["verdict"], audit["ira_score"], json.dumps(audit["action"], default=str),
                   audit["explanation"], json.dumps([{k: s[k] for k in ("name", "evidence", "floor")} for s in audit["signals"][:8]]),
                   (audit.get("reasoning") or {}).get("excerpt", ""), status, None, None, None))
        c.commit()
    return eid


def list_escalations(status: str | None = None, wf_id: str | None = None, limit: int = 200) -> list[dict]:
    q, p = "SELECT * FROM escalations WHERE 1=1", []
    if status:
        q += " AND status = ?"; p.append(status)
    if wf_id:
        q += " AND workflow_id = ?"; p.append(wf_id)
    q += " ORDER BY created_at DESC LIMIT ?"; p.append(limit)
    with closing(_conn()) as c:
        rows = [dict(r) for r in c.execute(q, p).fetchall()]
    for r in rows:
        r["action"] = json.loads(r["action"] or "{}")
        r["signals"] = json.loads(r["signals"] or "[]")
    return rows


def notify(wf: dict, event: dict) -> None:
    """Orquestación saliente: avisa al workflow en su control_url (HappyRobot webhook, n8n...)."""
    url = wf.get("control_url")
    if not url:
        return

    def send():
        try:
            requests.post(url, json={"workflow": wf["id"], **event}, timeout=8,
                          headers={"X-AngryRobot-Token": token_for(wf)})
        except Exception as exc:  # noqa: BLE001 — el aviso nunca bloquea la auditoría
            print(f"[platform] control_url de {wf['id']} falló: {exc}", flush=True)
    threading.Thread(target=send, daemon=True).start()


def after_turn(wf: dict, run_id: str, audits: list[dict], observe: bool) -> dict:
    """Tras auditar un turno (ingesta o proxy): escalaciones, directiva y aviso al workflow."""
    worst = max((a["verdict"] for a in audits), key=SEVERITY.get, default="ALLOW")
    top = max(audits, key=lambda a: (SEVERITY[a["verdict"]], a["ira_score"]), default=None)
    esc_id = None
    if top and SEVERITY[worst] >= 2:
        esc_id = open_escalation(wf["id"], run_id, top, "observed" if observe else ("open" if worst == "DEFER" else "killed"))
    if observe:
        directive = {"action": "continue", "note": "", "observed_verdict": worst}
    elif worst == "KILL":
        directive = set_directive(wf["id"], run_id, "kill", top["explanation"], esc_id)
    elif worst == "DEFER":
        directive = set_directive(wf["id"], run_id, "escalate", top["explanation"], esc_id)
    elif worst == "WARN":
        notes = [a["explanation"] for a in audits if a["verdict"] == "WARN" and a["suspicion"]["S"] >= 0.15]
        directive = {"action": "continue", "note": " | ".join(notes)}
    else:
        directive = {"action": "continue", "note": ""}
    if directive["action"] != "continue":
        notify(wf, {"event": "directive", "run_id": run_id, "directive": directive, "verdict": worst,
                    "ira": top["ira_score"] if top else 0})
    return {"verdict": worst, "directive": directive, "escalation_id": esc_id}


# ------------------------------------------------------------------ router
class WorkflowIn(BaseModel):
    name: str
    source: str = "webhook"
    base_profile: str = "default"
    goal: str = ""
    constraints: list[str] = []
    mode: str = "enforce"
    control_url: str | None = None


class WorkflowPatch(BaseModel):
    name: str | None = None
    source: str | None = None
    base_profile: str | None = None
    goal: str | None = None
    constraints: list[str] | None = None
    mode: str | None = None
    control_url: str | None = None


class ControlIn(BaseModel):
    action: str            # pause | resume | kill | rotate_token
    note: str = ""


class ResolveIn(BaseModel):
    decision: str          # approve | deny | take_over
    note: str = ""
    by: str = "operator"


class ToolCall(BaseModel):
    name: str
    args: dict = {}
    result: str | None = None     # si ya se ejecutó: se audita a posteriori
    ok: bool | None = None


class TurnIn(BaseModel):
    run_id: str
    messages: list[dict] = []     # formato OpenAI, completo o solo lo nuevo
    input: str = ""               # o: lo que recibió el agente en este turno
    output: str = ""              # lo que el agente va a decir / devolver
    reasoning: str = ""
    tool_calls: list[ToolCall] = []
    tool_results: list[dict] = [] # [{"name": ..., "content": ..., "ok": bool}] de turnos anteriores
    offered_tools: list[str] | None = None


def process_turn(config: dict, wf: dict, body: TurnIn, use_judge: bool = True) -> dict:
    """Un turno de un agente por el motor IRA: entradas, cada acción, directiva y escalaciones.
    Lo usan la ingesta HTTP (POST /v1/ingest/<workflow>) y, en proceso, las rondas de la consola
    (rounds.py). Devuelve además `audits_full` (el registro completo de cada acción) para quien
    lo llame en proceso; el endpoint HTTP lo quita."""
    if wf["status"] in ("killed", "paused"):
        return {"run_id": body.run_id, "verdict": "KILL" if wf["status"] == "killed" else "DEFER",
                "directive": get_directive(wf, body.run_id), "audits": [], "inputs": []}
    profile = profile_for(config, wf)
    observe = wf["mode"] == "observe"
    state = session.get(body.run_id, wf["id"])
    if state.killed and not observe:
        return {"run_id": body.run_id, "verdict": "KILL", "directive": get_directive(wf, body.run_id), "audits": [], "inputs": []}

    # DURANTE: entradas del turno
    inputs = state.ingest(body.messages, profile) if body.messages else []
    if body.input:
        inputs.append(state.user_turn(body.input))
    for tr in body.tool_results:
        entry = next((h for h in reversed(state.history) if h.get("tool") == tr.get("name")), None)
        inputs.append(state.tool_result(tr.get("name"), str(tr.get("content", "")) + ("" if tr.get("ok", True) else ' "error"'),
                                        profile, entry))

    # ANTES (o DESPUÉS si ya traen resultado): cada acción del turno
    tools = [tc.name for tc in body.tool_calls]
    audits = []
    for tc in body.tool_calls:
        a = engine.audit_action(config, wf["id"], profile, {"tool": tc.name, "args": tc.args, "text": body.output},
                                state, reasoning=body.reasoning, reasoning_source="client" if body.reasoning else "preamble",
                                offered_tools=body.offered_tools, phase="post" if tc.result is not None else "pre", record=False,
                                use_judge=use_judge)
        audits.append(a)
    if body.output:
        audits.append(engine.audit_action(config, wf["id"], profile, {"tool": "say", "text": body.output}, state,
                                          reasoning=body.reasoning, reasoning_source="client" if body.reasoning else "none",
                                          sibling_tools=tools, record=False, use_judge=use_judge))
    result = after_turn(wf, body.run_id, audits, observe)
    for a in audits:
        a["enforcement"] = f"directiva: {result['directive']['action']}" + (" (observado)" if observe else "")
        a["enforced"] = not observe
        engine.finalize(a, profile, state)
        if a["verdict"] != "ALLOW":
            alerts.record("ingest", wf["id"], a, context=body.input)
    # Resultados ya conocidos de tools de este mismo turno (auditoría a posteriori)
    for tc in body.tool_calls:
        if tc.result is not None:
            entry = next((h for h in reversed(state.history) if h.get("tool") == tc.name), None)
            state.tool_result(tc.name, tc.result + ("" if tc.ok is not False else ' "error"'), profile, entry)
    # El agente dijo lo que dijo: queda en la conversación para los turnos siguientes
    if body.output or body.tool_calls:
        state.add_message({"role": "assistant", "content": body.output,
                           "tool_calls": [{"id": f"t{i}", "function": {"name": tc.name, "arguments": json.dumps(tc.args)}}
                                          for i, tc in enumerate(body.tool_calls)] or None}, profile)
    return {"run_id": body.run_id, "workflow": wf["id"], "verdict": result["verdict"],
            "ira_score": max((a["ira_score"] for a in audits), default=0.0), "directive": result["directive"],
            "escalation_id": result["escalation_id"], "session": state.summary(), "inputs": inputs,
            "audits": [engine.compact(a) for a in audits], "audits_full": audits}


def build_router(config: dict) -> APIRouter:
    router = APIRouter()
    master = lambda: os.environ.get("ANGRYROBOT_SHARED_SECRET")  # noqa: E731

    def admin(x_secret: str | None, authorization: str | None):
        s = master()
        if s and x_secret != s and authorization != f"Bearer {s}":
            raise HTTPException(status_code=401, detail="Falta o es incorrecto X-AngryRobot-Secret")

    def agent_auth(wf: dict, x_token: str | None, x_secret: str | None, authorization: str | None, token_q: str | None):
        s, t = master(), token_for(wf)
        given = {x_token, x_secret, token_q, (authorization or "").removeprefix("Bearer ").strip() or None}
        if s and not ({s, t} & given):
            raise HTTPException(status_code=401, detail="Token del workflow incorrecto")

    def wf_or_404(wf_id: str) -> dict:
        wf = get_workflow(wf_id)
        if not wf:
            raise HTTPException(status_code=404, detail=f"workflow '{wf_id}' no existe")
        return wf

    def base_url(request: Request) -> str:
        if os.environ.get("ANGRYROBOT_PUBLIC_URL"):
            return os.environ["ANGRYROBOT_PUBLIC_URL"].rstrip("/")
        url = str(request.base_url).rstrip("/")
        return url.replace("http://", "https://", 1) if request.headers.get("x-forwarded-proto") == "https" else url

    # ---- workflows
    @router.get("/v1/workflows")
    def workflows(request: Request, x_angryrobot_secret: str | None = Header(default=None), authorization: str | None = Header(default=None)):
        admin(x_angryrobot_secret, authorization)
        return {"workflows": [public(w, config, base_url(request)) for w in list_workflows()],
                "base_profiles": [k for k in (config.get("workflow_profiles") or {})]}

    @router.post("/v1/workflows")
    def create(body: WorkflowIn, request: Request, x_angryrobot_secret: str | None = Header(default=None),
               authorization: str | None = Header(default=None)):
        admin(x_angryrobot_secret, authorization)
        if body.base_profile not in (config.get("workflow_profiles") or {}):
            raise HTTPException(status_code=400, detail=f"base_profile '{body.base_profile}' no existe")
        if body.mode not in ("enforce", "observe"):
            raise HTTPException(status_code=400, detail="mode: enforce | observe")
        wid = _slug(body.name)
        with closing(_conn()) as c:
            c.execute("INSERT INTO workflows VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (wid, body.name.strip(), body.source, body.base_profile, body.goal.strip() or None,
                       json.dumps(body.constraints) if body.constraints else None, body.mode, "live",
                       body.control_url, 1, 0, _now(), _now()))
            c.commit()
        return public(get_workflow(wid), config, base_url(request), with_token=True)

    @router.get("/v1/workflows/{wf_id}")
    def detail(wf_id: str, request: Request, x_angryrobot_secret: str | None = Header(default=None),
               authorization: str | None = Header(default=None)):
        admin(x_angryrobot_secret, authorization)
        wf = wf_or_404(wf_id)
        runs = [{"run_id": r.run_id, **r.summary()} for r in session.recent_runs(500) if r.profile == wf_id][:50]
        return {**public(wf, config, base_url(request), with_token=True), "runs": runs,
                "escalations": list_escalations(wf_id=wf_id, limit=50)}

    @router.patch("/v1/workflows/{wf_id}")
    def patch(wf_id: str, body: WorkflowPatch, request: Request, x_angryrobot_secret: str | None = Header(default=None),
              authorization: str | None = Header(default=None)):
        admin(x_angryrobot_secret, authorization)
        wf_or_404(wf_id)
        fields = body.model_dump(exclude_none=True)
        if "mode" in fields and fields["mode"] not in ("enforce", "observe"):
            raise HTTPException(status_code=400, detail="mode: enforce | observe")
        if "constraints" in fields:
            fields["constraints"] = json.dumps(fields["constraints"])
        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields) + ", updated_at = ?"
            with closing(_conn()) as c:
                c.execute(f"UPDATE workflows SET {sets} WHERE id = ?", [*fields.values(), _now(), wf_id])
                c.commit()
        return public(get_workflow(wf_id), config, base_url(request), with_token=True)

    @router.post("/v1/workflows/{wf_id}/control")
    def control(wf_id: str, body: ControlIn, request: Request, x_angryrobot_secret: str | None = Header(default=None),
                authorization: str | None = Header(default=None)):
        admin(x_angryrobot_secret, authorization)
        wf = wf_or_404(wf_id)
        if body.action not in ("pause", "resume", "kill", "rotate_token"):
            raise HTTPException(status_code=400, detail="action: pause | resume | kill | rotate_token")
        with closing(_conn()) as c:
            if body.action == "rotate_token":
                c.execute("UPDATE workflows SET token_version = token_version + 1, updated_at = ? WHERE id = ?", (_now(), wf_id))
            else:
                status = {"pause": "paused", "resume": "live", "kill": "killed"}[body.action]
                c.execute("UPDATE workflows SET status = ?, updated_at = ? WHERE id = ?", (status, _now(), wf_id))
            c.commit()
        if body.action == "kill":
            for r in session.recent_runs(2000):
                if r.profile == wf_id:
                    r.killed = True
        wf = get_workflow(wf_id)
        if body.action != "rotate_token":
            notify(wf, {"event": "control", "action": body.action, "status": wf["status"], "note": body.note})
        return public(wf, config, base_url(request), with_token=True)

    @router.post("/v1/workflows/control-all")
    def control_all(body: ControlIn, x_angryrobot_secret: str | None = Header(default=None), authorization: str | None = Header(default=None)):
        """Kill switch global: pausa, reanuda o mata TODOS los workflows."""
        admin(x_angryrobot_secret, authorization)
        if body.action not in ("pause", "resume", "kill"):
            raise HTTPException(status_code=400, detail="action: pause | resume | kill")
        status = {"pause": "paused", "resume": "live", "kill": "killed"}[body.action]
        with closing(_conn()) as c:
            c.execute("UPDATE workflows SET status = ?, updated_at = ?", (status, _now()))
            c.commit()
        if body.action == "kill":
            for r in session.recent_runs(2000):
                r.killed = True
        for wf in list_workflows():
            notify(wf, {"event": "control", "action": body.action, "status": status, "note": body.note})
        return {"status": status, "workflows": len(list_workflows())}

    # ---- escalaciones
    @router.get("/v1/escalations")
    def escalations(status: str | None = None, workflow: str | None = None, x_angryrobot_secret: str | None = Header(default=None),
                    authorization: str | None = Header(default=None)):
        admin(x_angryrobot_secret, authorization)
        return {"escalations": list_escalations(status, workflow)}

    @router.post("/v1/escalations/{esc_id}/resolve")
    def resolve(esc_id: str, body: ResolveIn, x_angryrobot_secret: str | None = Header(default=None),
                authorization: str | None = Header(default=None)):
        admin(x_angryrobot_secret, authorization)
        if body.decision not in ("approve", "deny", "take_over"):
            raise HTTPException(status_code=400, detail="decision: approve | deny | take_over")
        with closing(_conn()) as c:
            row = c.execute("SELECT * FROM escalations WHERE id = ?", (esc_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="escalación no encontrada")
            status = {"approve": "approved", "deny": "denied", "take_over": "taken_over"}[body.decision]
            c.execute("UPDATE escalations SET status = ?, decision_note = ?, resolved_at = ?, resolved_by = ? WHERE id = ?",
                      (status, body.note, _now(), body.by, esc_id))
            c.commit()
        wf = get_workflow(row["workflow_id"]) or {"id": row["workflow_id"]}
        action = json.loads(row["action"] or "{}")
        if body.decision == "approve":
            directive = set_directive(row["workflow_id"], row["run_id"], "continue",
                                      f"Aprobado por un humano: puedes ejecutar {action.get('tool')} tal como lo propusiste. {body.note}".strip(), esc_id)
        elif body.decision == "deny":
            directive = set_directive(row["workflow_id"], row["run_id"], "continue",
                                      f"Denegado por un humano: NO ejecutes {action.get('tool')}. {body.note}".strip(), esc_id)
        else:
            directive = set_directive(row["workflow_id"], row["run_id"], "kill", f"Un humano toma el control. {body.note}".strip(), esc_id)
            st = session.peek(row["run_id"])
            if st:
                st.killed = True
        notify(wf, {"event": "escalation_resolved", "escalation_id": esc_id, "run_id": row["run_id"],
                    "decision": body.decision, "directive": directive})
        return {"id": esc_id, "status": status, "directive": directive}

    # ---- ingesta por turno (lo llama el agente)
    @router.post("/v1/ingest/{wf_id}")
    def ingest(wf_id: str, body: TurnIn, x_angryrobot_token: str | None = Header(default=None),
               x_angryrobot_secret: str | None = Header(default=None), authorization: str | None = Header(default=None),
               token: str | None = None):
        wf = wf_or_404(wf_id)
        agent_auth(wf, x_angryrobot_token, x_angryrobot_secret, authorization, token)
        result = process_turn(config, wf, body)
        result.pop("audits_full", None)
        return result

    @router.get("/v1/ingest/{wf_id}/runs/{run_id}/directive")
    def directive(wf_id: str, run_id: str, x_angryrobot_token: str | None = Header(default=None),
                  x_angryrobot_secret: str | None = Header(default=None), authorization: str | None = Header(default=None),
                  token: str | None = None):
        wf = wf_or_404(wf_id)
        agent_auth(wf, x_angryrobot_token, x_angryrobot_secret, authorization, token)
        return {"run_id": run_id, "workflow_status": wf["status"], "directive": get_directive(wf, run_id)}

    return router
